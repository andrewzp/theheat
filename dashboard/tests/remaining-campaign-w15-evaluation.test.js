// W15 dashboard consumers with invented fixtures only: revision feedback, coverage match evidence,
// supplied metrics reaching the outcome projection, and review-only correction candidates.
import test from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { draftIdentity, textHash } from "../lib/draft-revisions.js"
import { feedbackRecord, readPostFeedback, revisionFeedbackInput, revisionFeedbackSummary, revisionTarget, savePostFeedback } from "../lib/post-feedback.js"
import { postOutcomes } from "../lib/post-outcomes.js"
import { buildWeeklyReview } from "../lib/weekly-review.js"
import PostOutcomeHistory from "../app/components/PostOutcomeHistory.js"
import { CoverageAssessment } from "../app/components/CoverageEvidence.js"
import { RevisionFeedbackForm } from "../app/components/PostFeedback.js"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const id = "6f1c2a4e-9b7d-4e21-8a3c-5d6e7f809a1b"
const posted = { id:"synthetic-post", event_id:"synthetic-event", type:"heat_record", status:"posted", publish_outcome:"confirmed",
  tweet_id:"1900000000000000001", text:"Invented: Fictionville reached 49.1C.", content_revision:1, posted_at:"2026-10-10T19:00:00.000Z",
  created_at:"2026-10-10T18:00:00.000Z", review_context:{ source:"invented fixture only" } }
const pending = { id:"synthetic-draft", event_id:"synthetic-pending", type:"heat_record", status:"pending", text:"Invented pending copy.",
  content_revision:2, created_at:"2026-10-11T08:00:00.000Z", review_context:{ source:"invented fixture only" } }
function state() {
  const receipt = { ...draftIdentity(posted), text:posted.text, tweet_id:posted.tweet_id, phase:"confirmed", intent_id:"10a97d68-2e51-4998-92ed-f830863f7218" }
  return { drafts:[structuredClone(posted), structuredClone(pending)], publish_ledger:{ [posted.event_id]:receipt } }
}

test("revision feedback binds one exact revision, requires a tag and refuses a graphic without one", () => {
  const s = state()
  const draftTarget = revisionTarget(s.drafts[1], s), postTarget = revisionTarget(s.drafts[0], s)
  assert.equal(draftTarget.tweet_id, null); assert.equal(draftTarget.graphic_sha256, null)
  assert.equal(postTarget.tweet_id, posted.tweet_id); assert.equal(postTarget.content_revision, 1)
  const input = { request_id:id, target:draftTarget, subject:"copy", tags:["concise", "incorrect"], note:"" }
  assert.deepEqual(revisionFeedbackInput(input), input)
  for (const bad of [{ ...input, tags:[] }, { ...input, tags:["rude"] }, { ...input, subject:"graphic" }, { ...input, tags:["concise", "concise"] }])
    assert.throws(() => revisionFeedbackInput(bad), /invalid_feedback/)
  const record = { ...input, schema_version:2, kind:"dashboard_revision_feedback", category:"human_feedback", received_at:"2026-10-12T00:00:00.000Z" }
  assert.deepEqual(feedbackRecord(record), record)
  assert.deepEqual(revisionFeedbackSummary([]), { status:"none_recorded", records:0, subjects:{ copy:0, graphic:0 },
    tags:{ concise:0, useful:0, confusing:0, incorrect:0 }, category:"human_feedback" })
})

test("revision feedback saves through the existing archive and reads back per revision; a changed draft refuses", async () => {
  Object.assign(process.env, { GIST_ID:"fixture_state", THEHEAT_FEEDBACK_GIST_ID:"fixture_feedback", GITHUB_TOKEN:"fixture_token" })
  const s = state(), archive = {}, original = globalThis.fetch
  globalThis.fetch = async (url, options = {}) => {
    if (url === "https://api.github.com/gists/fixture_state") return Response.json({ public:true, files:{ "state.json":{ content:JSON.stringify(s) } } })
    assert.equal(url, "https://api.github.com/gists/fixture_feedback")
    if (options.method === "PATCH") { Object.assign(archive, JSON.parse(options.body).files); return Response.json({}) }
    return Response.json({ public:false, files:archive })
  }
  try {
    const input = { request_id:id, target:revisionTarget(s.drafts[1], s), subject:"copy", tags:["useful"], note:"Invented note." }
    const saved = await savePostFeedback(input)
    assert.equal(saved.record.kind, "dashboard_revision_feedback"); assert.equal(saved.already_saved, false)
    const read = await readPostFeedback()
    const row = read.revisions.find(r => r.target.draft_id === "synthetic-draft")
    assert.equal(row.summary.status, "recorded"); assert.equal(row.summary.tags.useful, 1)
    assert.equal(read.revisions.find(r => r.target.draft_id === "synthetic-post").summary.status, "none_recorded")
    assert.equal(read.posts[0].ratings.length, 0, "revision tags never become punch/clarity/economy ratings")
    s.drafts[1].text = "Invented edited copy."
    await assert.rejects(savePostFeedback({ ...input, request_id:"7f1c2a4e-9b7d-4e21-8a3c-5d6e7f809a1b" }), /post_changed/)
  } finally { globalThis.fetch = original }
})

test("weekly review keeps revision feedback separate from opinions and never counts it as invalid", () => {
  const s = state()
  const record = { request_id:id, target:revisionTarget(s.drafts[0], s), subject:"copy", tags:["confusing"], note:"",
    schema_version:2, kind:"dashboard_revision_feedback", category:"human_feedback", received_at:"2026-10-12T00:00:00.000Z" }
  const report = buildWeeklyReview({ state:s, feedbackRecords:[record], asOf:"2026-10-14T00:00:00.000Z" })
  assert.equal(report.revision_feedback.status, "recorded"); assert.equal(report.revision_feedback.tags.confusing, 1)
  assert.equal(report.exclusions.invalid_opinions, 0)
})

test("the form offers tags only; nothing is pre-selected and the graphic choice needs a graphic", () => {
  const s = state()
  const revision = { target:revisionTarget(s.drafts[1], s), feedback:[], summary:revisionFeedbackSummary([]) }
  const html = renderToStaticMarkup(React.createElement(RevisionFeedbackForm, { revision, busy:false, blocked:false, onSave:() => {} }))
  assert.match(html, /no feedback yet/); assert.match(html, /Looks incorrect/)
  assert.doesNotMatch(html, /checked=""[^>]*type="checkbox"|type="checkbox"[^>]*checked=""/)
  assert.match(html, /value="graphic" disabled=""|disabled=""[^>]*value="graphic"/)
  assert.match(html, /disabled=""[^>]*>Save feedback|type="submit" class="btn" disabled=""/)
})

// The campaign's credential-free PATH can resolve an older system python3; prefer the repository's
// locked SDK interpreter when this checkout sits beside it (local worktrees), else the PATH python3 (CI).
const SDK_PYTHON = path.resolve(ROOT, "../../environments/sdk-locked/bin/python")
const PYTHON = process.env.THEHEAT_TEST_PYTHON || (existsSync(SDK_PYTHON) ? SDK_PYTHON : "python3")
function python(args) {
  const env = { PATH:process.env.PATH, LC_ALL:"C", TZ:"UTC", PYTHONDONTWRITEBYTECODE:"1" }
  return execFileSync(PYTHON, [path.join(ROOT, "scripts/theheat_evaluation.py"), ...args], { cwd:ROOT, env, encoding:"utf8" })
}

test("fresh-process metrics intake appends a sample that the outcome view reads with post age", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "w15-metrics-"))
  const s = state()
  s.publish_ledger[posted.event_id].text_sha256 = textHash(posted.text)
  writeFileSync(path.join(dir, "state.json"), JSON.stringify(s))
  writeFileSync(path.join(dir, "response.json"), JSON.stringify({ data:[{ id:posted.tweet_id, created_at:"2026-10-10T19:00:00.000Z",
    public_metrics:{ like_count:4, retweet_count:1, reply_count:0, quote_count:0 } }] }))
  python(["metrics-intake", "--state", path.join(dir, "state.json"), "--response", path.join(dir, "response.json"),
    "--captured-at", "2026-10-11T19:00:00Z", "--ids", posted.tweet_id, "--output", path.join(dir, "out.json")])
  const out = JSON.parse(readFileSync(path.join(dir, "out.json"), "utf8"))
  assert.equal(out.report.appended, 1)
  const outcome = postOutcomes(out.state, { now:Date.parse("2026-10-20T00:00:00Z") }).posts[0]
  assert.equal(outcome.observations[0].post_age_seconds, 86400); assert.equal(outcome.observations[0].counts.impressions, null)
  assert.equal(outcome.feedback.status, "not_loaded"); assert.ok(!outcome.evidence_needed.includes("metric_observation"))
})

test("outcome view links feedback and review-only corrections, and names missing evidence", () => {
  const s = state()
  s.publish_ledger[posted.event_id].text_sha256 = textHash(posted.text)
  const feedbackRecords = [{ kind:"dashboard_revision_feedback", target:{ tweet_id:posted.tweet_id }, tags:["incorrect"] }]
  const correctionReport = { candidates:[{ tweet_id:posted.tweet_id, claim:"49.1C", kind:"value", uncertainty:"Invented: provisional QC.",
    source_evidence:{ retrieved_at:"2026-10-18T00:00:00Z", statement:"Invented table shows 48.7C." }, automatic_correction:false, deletion:false }], incomplete:[] }
  const outcomes = postOutcomes(s, { now:Date.parse("2026-10-20T00:00:00Z"), feedbackRecords, correctionReport })
  const post = outcomes.posts[0]
  assert.equal(post.feedback.revision_tags.incorrect, 1); assert.equal(post.corrections.status, "candidates")
  assert.ok(post.evidence_needed.includes("metric_observation"))
  const html = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes }))
  assert.match(html, /Correction candidates for your review \(nothing is corrected or deleted automatically\)/)
  assert.match(html, /Still needed to know more: [^<]*a metric observation/)
  const none = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes:postOutcomes(s, { now:Date.parse("2026-10-20T00:00:00Z"), feedbackRecords:[] }) }))
  assert.match(none, /No feedback recorded for this post\. That is not a negative score\./)
})

test("fresh-process reference intake and production matching reach the actual coverage view", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "w15-coverage-"))
  const sha = "a".repeat(64)
  const ev = (event_id, extra = {}) => ({ event_id, origin:"reference", kind:"physical_event_candidate", source_class:"observed",
    hazards:[{ label:"Heat record", evidence_sha256:sha }], regions:[{ label:"Fictionville", evidence_sha256:sha }],
    event_start:"2026-10-10T00:00:00Z", event_end:"2026-10-11T00:00:00Z", issued_at:null, published_at:null, first_available_at:null,
    label_source:"invented reviewer table", ...extra })
  writeFileSync(path.join(dir, "intake.json"), JSON.stringify({ schema:"theheat.reference-intake/v1", set_id:"fixture-w15-node", created_at:"2026-10-20T12:00:00Z",
    selection:{ scope_label:"Invented", method:"invented_fixture", independent_of_bot_output:false, protocol_document_sha256:"c".repeat(64) },
    comparison_window:{ start:null, end:null }, events:[ev("ref-found"), ev("ref-wrong-place", { regions:[{ label:"Nowhereland", evidence_sha256:sha }] })] }))
  const s = state(); s.drafts[0].city = "Fictionville"
  writeFileSync(path.join(dir, "state.json"), JSON.stringify(s))
  python(["reference-intake", "--input", path.join(dir, "intake.json"), "--retained-at", "2026-10-20T12:00:00Z", "--output", path.join(dir, "record.json")])
  python(["match-coverage", "--record", path.join(dir, "record.json"), "--state", path.join(dir, "state.json"), "--cutoff", "2026-10-20T12:00:00Z",
    "--evaluated-at", "2026-10-20T13:00:00Z", "--policy-sha256", "f".repeat(64), "--invented-fixture", "--output", path.join(dir, "assessment.json")])
  const assessment = JSON.parse(readFileSync(path.join(dir, "assessment.json"), "utf8"))
  assert.equal(assessment.metrics.event_recall, null)
  const html = renderToStaticMarkup(React.createElement(CoverageAssessment, { assessment }))
  assert.match(html, /Matched production records/)
  assert.match(html, /No match; the closest records differ as shown/)
  assert.match(html, /place differs/)
  assert.match(html, /Draft saved/)
  assert.match(html, /invented fixture/)
})

test("a feedback save from a page opened at 127.0.0.1 is same-origin; another origin or a missing Origin is refused", async () => {
  Object.assign(process.env, { NODE_ENV:"production", DASHBOARD_USERNAME:"editor", DASHBOARD_PASSWORD:"invented-test-only",
    THEHEAT_STATE_BACKEND:"gist", THEHEAT_DB_PATH:"" })
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  const { POST } = await import("../app/api/post-feedback/route.js")
  const auth = `Basic ${Buffer.from("editor:invented-test-only").toString("base64")}`
  const send = headers => POST(new Request("http://localhost:3000/api/post-feedback", { method:"POST",
    headers:{ authorization:auth, "content-type":"text/plain", ...headers }, body:"x" }))
  const loopback = await send({ origin:"http://127.0.0.1:3000", host:"127.0.0.1:3000", "sec-fetch-site":"same-origin" })
  assert.equal((await loopback.json()).code, "invalid_feedback", "origin accepted; the body is then refused as invalid")
  for (const headers of [{ origin:"https://elsewhere.example", host:"localhost:3000" }, { host:"localhost:3000" }])
    assert.equal((await (await send(headers)).json()).code, headers.origin ? "cross_origin_mutation_refused" : "feedback_origin_refused")
})


test("the feedback read returns published outcomes with that feedback joined, from the same two reads", async () => {
  Object.assign(process.env, { GIST_ID:"fixture_state", THEHEAT_FEEDBACK_GIST_ID:"fixture_feedback", GITHUB_TOKEN:"fixture_token" })
  const s = state(), original = globalThis.fetch, calls = []
  s.publish_ledger[posted.event_id].text_sha256 = textHash(posted.text)
  const target = revisionTarget(s.drafts[0], s)
  const record = { request_id:id, target, subject:"copy", tags:["useful"], note:"", schema_version:2,
    kind:"dashboard_revision_feedback", category:"human_feedback", received_at:"2026-10-12T00:00:00.000Z" }
  globalThis.fetch = async url => { calls.push(url)
    return url.endsWith("fixture_state") ? Response.json({ public:true, files:{ "state.json":{ content:JSON.stringify(s) } } })
      : Response.json({ public:false, files:{ [`editorial-feedback-${id}.json`]:{ content:JSON.stringify(record) } } }) }
  try {
    const read = await readPostFeedback()
    const post = read.outcomes.posts.find(p => p.tweet_id === posted.tweet_id)
    assert.equal(post.feedback.status, "recorded"); assert.equal(post.feedback.revision_tags.useful, 1)
    assert.equal(calls.length, 2, "no extra state or archive read")
    const html = renderToStaticMarkup(React.createElement(PostOutcomeHistory, { outcomes:read.outcomes }))
    assert.match(html, /Your feedback: 0 rating\(s\); tags useful 1\./)
  } finally { globalThis.fetch = original }
})

test("weekly review lists supplied correction candidates for review only and never applies them", async () => {
  const { weeklyReviewMarkdown } = await import("../lib/weekly-review.js")
  const s = state()
  const correctionReport = { candidates:[{ tweet_id:posted.tweet_id, claim:"49.1C", kind:"value", automatic_correction:false, deletion:false },
    { tweet_id:posted.tweet_id, claim:"x", kind:"place", automatic_correction:true, deletion:false }], incomplete:[{ needed:["source_statement"] }] }
  const report = buildWeeklyReview({ state:s, asOf:"2026-10-14T00:00:00.000Z", correctionReport })
  assert.deepEqual(report.corrections, { status:"supplied", review_only:true, candidates:1, posts:[posted.tweet_id], kinds:["value"], incomplete:1 })
  assert.match(weeklyReviewMarkdown(report), /Correction candidates for editor review \(none applied\): 1 across 1 post\(s\); 1 supplied/)
  assert.equal(buildWeeklyReview({ state:s, asOf:"2026-10-14T00:00:00.000Z" }).corrections.status, "not_supplied")
})
