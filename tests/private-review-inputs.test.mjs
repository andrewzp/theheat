// Bounded bridge to the EXISTING weekly/outcome readers; INVENTED snapshot only.
// Run explicitly: node --test tests/private-review-inputs.test.mjs
import { test } from "node:test"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { chmodSync, mkdtempSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { draftIdentity } from "../dashboard/lib/draft-revisions.js"
import { buildWeeklyReview } from "../dashboard/lib/weekly-review.js"

const script = new URL("../scripts/private_review_inputs.mjs", import.meta.url).pathname
const asOf = "2026-10-18T12:00:00.000Z"
const privateText = "PRIVATE INVENTED SENTENCE: a storm closes the ferry."

function state() {
  const d = { id: "invented-draft", event_id: "invented-event", type: "storm", status: "posted", publish_outcome: "confirmed",
    tweet_id: "1234567890", text: privateText, content_revision: 1, manual_override: false,
    posted_at: "2026-10-17T12:00:00.000Z",
    review_context: { two_bot: { bundle: { event_id: "invented-event", signal_kind: "storm", note: "PRIVATE BUNDLE NOTE" } } } }
  return { drafts: [d], publish_ledger: { [d.event_id]: { ...draftIdentity(d), text: d.text, tweet_id: d.tweet_id,
    phase: "confirmed", intent_id: "10a97d68-2e51-4998-92ed-f830863f7218" } },
  tweet_metrics: { "1234567890": { samples: { a: { schema_version: 1, tweet_id: "1234567890", source: "x_api.public_metrics",
    sampled_at: "2026-10-18T00:00:00Z", posted_at: "2026-10-17T12:00:00Z", post_time_basis: "x_api.created_at",
    post_time_status: "recorded", post_age_seconds: 43200, counts: { likes: 2 } } } } } }
}

function privateDir() {
  const dir = realpathSync(mkdtempSync(join(realpathSync(tmpdir()), "theheat-review-inputs-")))
  chmodSync(dir, 0o700)
  return dir
}

function file(dir, name, value, mode = 0o600) {
  const path = join(dir, name)
  writeFileSync(path, typeof value === "string" ? value : JSON.stringify(value))
  chmodSync(path, mode)
  return path
}

const run = (args) => spawnSync(process.execPath, [script, ...args], { encoding: "utf8", env: { PATH: "/usr/bin:/bin" } })

test("existing readers run unchanged and stdout stays content-free", () => {
  const dir = privateDir(), input = file(dir, "state.json", state())
  const first = run(["--state", input, "--as-of", asOf])
  assert.equal(first.status, 0, first.stderr)
  const value = JSON.parse(first.stdout)
  assert.equal(value.schema, "theheat.private-review-inputs/v1")
  assert.deepEqual(value.weekly, buildWeeklyReview({ state: state(), feedbackRecords: null, asOf }))
  assert.equal(value.feedback_supplied, false)
  assert.equal(value.outcomes.posts[0].text_available, true)
  assert.ok(!("text" in value.outcomes.posts[0]))
  assert.equal(value.outcomes.posts[0].publication_context.status, "recorded")
  for (const secret of [privateText, "PRIVATE BUNDLE NOTE"]) assert.ok(!first.stdout.includes(secret))
  assert.equal(run(["--state", input, "--as-of", asOf]).stdout, first.stdout) // Fixed inputs reproduce bytes.
  const feedback = file(dir, "feedback.json", { records: [] })
  const withFeedback = JSON.parse(run(["--state", input, "--feedback", feedback, "--as-of", asOf]).stdout)
  assert.equal(withFeedback.weekly.editorial_feedback.records_in_window, 0) // Supplied zero, not missing.
})

test("only explicit absolute owner-only regular files and an aware clock are read", () => {
  const dir = privateDir(), input = file(dir, "state.json", state())
  const loose = file(dir, "loose.json", state(), 0o644)
  const link = join(dir, "link.json")
  symlinkSync(input, link)
  for (const args of [["--state", "state.json", "--as-of", asOf], ["--state", loose, "--as-of", asOf],
    ["--state", link, "--as-of", asOf], ["--state", input], ["--state", input, "--as-of", "2026-10-18T12:00:00"],
    ["--state", input, "--as-of", asOf, "--output", dir], ["--state", input, "--state", input, "--as-of", asOf],
    ["--state", file(dir, "dupe.json", '{"drafts":[],"drafts":[]}'), "--as-of", asOf],
    ["--state", input, "--feedback", file(dir, "bad-feedback.json", { records: [], extra: 1 }), "--as-of", asOf]]) {
    const result = run(args)
    assert.equal(result.status, 2, JSON.stringify(args))
    assert.equal(result.stdout, "")
    assert.ok(!result.stderr.includes(dir))
  }
})

test("the bridge cannot fetch, write files or spawn processes", () => {
  const source = readFileSync(script, "utf8")
  for (const forbidden of [/\bfetch\s*\(/, /node:http/, /node:https/, /node:net/, /writeFile/, /child_process/,
    /\beval\s*\(/, /new Function/, /\bimport\s*\(/]) assert.doesNotMatch(source, forbidden, String(forbidden))
})

test("malformed conflicting and unavailable passive contexts never expose raw payloads", () => {
  const dir = privateDir()
  for (const [name, raw] of [["malformed", { x: { text: "PRIVATE RAW BODY", notes: "PRIVATE RAW NOTES" } }],
    ["conflicting", { x: { text: "PRIVATE RAW BODY" }, y: { source: "PRIVATE SOURCE CONTEXT" } }],
    ["unavailable", ["PRIVATE UNAVAILABLE ARRAY BODY"]]]) {
    const input = state()
    input.publish_ledger["invented-event"].publication_observations = raw
    const result = run(["--state", file(dir, `${name}.json`, input), "--as-of", asOf])
    assert.equal(result.status, 0, result.stderr)
    const writer = JSON.parse(result.stdout).outcomes.posts[0].writer_context
    assert.notEqual(writer.status, "recorded")
    assert.ok(writer.variants.length > 0)
    for (const value of [privateText, "PRIVATE RAW BODY", "PRIVATE RAW NOTES", "PRIVATE SOURCE CONTEXT",
      "PRIVATE UNAVAILABLE ARRAY BODY", "raw_data", '"payload"']) assert.ok(!result.stdout.includes(value), value)
    assert.equal(result.stderr, "")
  }
})

test("unknown metrics age and draft-only inventory remain distinct from known zero", () => {
  const dir = privateDir(), input = state()
  const sample = input.tweet_metrics["1234567890"].samples.a
  sample.counts = { likes: true, retweets: 0, impressions: "99" }
  delete sample.post_age_seconds
  const result = run(["--state", file(dir, "unknown.json", input), "--as-of", asOf])
  assert.equal(result.status, 0, result.stderr)
  const observed = JSON.parse(result.stdout).outcomes.posts[0].observations[0]
  assert.equal(observed.counts.likes, null)
  assert.equal(observed.counts.impressions, null)
  assert.equal(observed.counts.retweets, 0)
  assert.equal(observed.post_age_seconds, null)
  assert.equal(observed.age_status, "conflict")
  input.publish_ledger = {}
  const draftOnly = JSON.parse(run(["--state", file(dir, "draft-only.json", input), "--as-of", asOf]).stdout)
  assert.equal(draftOnly.outcomes.posts[0].revision_status, "unknown")
  assert.equal(draftOnly.outcomes.posts[0].qualified_weekly_receipt, false)
  assert.equal(draftOnly.weekly.delivery.count, 0)
  const looseParent = privateDir()
  chmodSync(looseParent, 0o755)
  assert.equal(run(["--state", file(looseParent, "input.json", input), "--as-of", asOf]).status, 2)
})
