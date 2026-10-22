import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { postOutcomes, OUTCOME_METRICS } from "../lib/post-outcomes.js"
import { draftIdentity, fingerprint, invalidateText, textHash } from "../lib/draft-revisions.js"

const now = Date.parse("2026-10-22T12:00:00Z")
const text = "Invented retained sentence."
const hash = textHash(text)
const makeSample = (changes = {}) => ({ schema_version: 1, tweet_id: "123", source: "x_api.public_metrics",
  sampled_at: "2026-10-21T12:00:00Z", posted_at: "2026-10-20T12:00:00Z",
  post_time_basis: "x_api.created_at", post_time_status: "recorded", post_age_seconds: 86400,
  published_revision_status: "recorded", published_text_sha256: hash, counts: { likes: 0, impressions: 12 }, ...changes })
const fixture = samples => ({ drafts: [{ id: "fixture", status: "posted", tweet_id: "123", text }],
  publish_ledger: { fixture: { phase: "confirmed", tweet_id: "123", text, text_sha256: hash } },
  tweet_metrics: { "123": { samples: samples || { first: makeSample() } } } })
const project = state => postOutcomes(state, { now })
const first = state => project(state).posts[0]

test("exact receipt and real sample identify published text; zero differs from unknown", () => {
  const result = first(fixture())
  assert.equal(result.text, text); assert.equal(result.published_text_sha256, hash)
  assert.equal(result.revision_status, "recorded")
  assert.equal(result.observations[0].post_age_seconds, 86400)
  assert.deepEqual(result.observations[0].counts, { likes: 0, retweets: null, replies: null, quotes: null, impressions: 12, bookmarks: null })
})

test("draft edits and mutable angles cannot rewrite publication; matching historical text can recover it", () => {
  const state = fixture()
  state.drafts[0].status = "pending"; state.drafts[0].text = "Later edit"
  state.drafts[0].review_context = { two_bot: { angle_chosen: "untrusted_current_angle" } }
  assert.equal(first(state).text, text)
  delete state.publish_ledger.fixture.text
  assert.equal(first(state).text, null)
  state.drafts[0].revision_history = [{ text, review_context: { two_bot: { angle_chosen: "old_unbound_angle" } } }]
  assert.equal(first(state).text, text)
  assert.doesNotMatch(JSON.stringify(project(state)), /angle|human_edit|Later edit/)
})

test("a pending draft or memory alone cannot establish a receipt; an orphan receipt can", () => {
  assert.equal(project({ drafts: [{ status: "pending", tweet_id: "123", text }], publish_ledger: {}, memory: { shipped_tweets: [{ tweet_id: "123" }] } }).posts.length, 0)
  const state = fixture(); state.drafts = []
  assert.equal(first(state).text, text)
  state.publish_ledger.fixture.phase = "not_sent"
  assert.equal(project(state).posts.length, 0)
})

test("missing fingerprints and conflicting fingerprint/body evidence remain explicit", () => {
  const state = fixture({ first: makeSample({ published_revision_status: "unknown", published_text_sha256: null }) })
  delete state.publish_ledger.fixture.text_sha256
  assert.equal(first(state).revision_status, "unknown"); assert.equal(first(state).text, null)
  state.publish_ledger.fixture.text_sha256 = "a".repeat(64)
  assert.equal(first(state).revision_status, "conflict"); assert.equal(first(state).text, null)
})

test("nested conflicting receipts are retained without choosing a text or looping", () => {
  const state = fixture()
  state.publish_ledger.fixture.attempt_conflicts = [{ tweet_id: "123", text_sha256: "b".repeat(64) }, { tweet_id: "456" }]
  state.publish_ledger.fixture.attempt_conflicts.push(state.publish_ledger.fixture)
  assert.equal(first(state).revision_status, "conflict")
  assert.deepEqual(project(state).posts.map(p => p.tweet_id), ["123", "456"])
})

test("all distinct same-time payloads survive permutation; exact duplicate payloads appear once", () => {
  const a = makeSample(), b = makeSample({ counts: { likes: 4 } })
  const left = fixture({ a, b, duplicate: structuredClone(a) }), right = fixture({ b, a })
  assert.deepEqual(project(left), project(right))
  assert.equal(first(left).observations.length, 2)
  assert.ok(first(left).observations.every(o => o.conflict))
})

test("chronological history preserves a later lower count without clipping or inferring a delta", () => {
  const state = fixture({ newer: makeSample({ sampled_at: "2026-10-22T00:00:00Z", post_age_seconds: 129600, counts: { likes: 2 } }),
    older: makeSample({ counts: { likes: 5 } }) })
  assert.deepEqual(first(state).observations.map(o => o.counts.likes), [5, 2])
  assert.deepEqual(first(state).observations.map(o => o.post_age_seconds), [86400, 129600])
  assert.ok(first(state).observations.every(o => !o.conflict))
})

test("source microseconds and equivalent timezones remain exact rather than merged into one millisecond", () => {
  const state = fixture({ a: makeSample({ sampled_at: "2026-10-21T13:00:00.000001+01:00", post_age_seconds: 86400.000001 }),
    b: makeSample({ sampled_at: "2026-10-21T12:00:00.000002Z", post_age_seconds: 86400.000002 }) })
  assert.deepEqual(first(state).observations.map(o => o.post_age_seconds), [86400.000001, 86400.000002])
  assert.ok(first(state).observations.every(o => !o.conflict))
})

for (const date of ["2026-02-31T00:00:00Z", "2026-10-23T00:00:00Z", "2026-10-21T00:00:00", "bad", "0000-01-01T00:00:00Z"]) {
  test(`invalid/future/unzoned collection time stays unknown: ${date}`, () => {
    const row = first(fixture({ a: makeSample({ sampled_at: date }) })).observations[0]
    assert.equal(row.collected_at, null); assert.equal(row.post_age_seconds, null)
  })
}

test("receipt proxy, absent creation time and conflicting stored age cannot become real post age", () => {
  for (const changes of [{ posted_at: null }, { post_time_basis: "receipt.confirmed_at" }, { post_time_status: "unknown" }, { post_age_seconds: 1 }, { posted_at: "2026-10-22T00:00:00Z" }]) {
    const row = first(fixture({ a: makeSample({ receipt_age_seconds: 86400, ...changes }) })).observations[0]
    assert.equal(row.post_age_seconds, null)
  }
  assert.equal(first(fixture({ a: makeSample({ post_age_seconds: 1 }) })).observations[0].age_status, "conflict")
})

test("legacy flat rows remain legacy; no samples or platform times are invented", () => {
  const state = fixture(); state.tweet_metrics["123"] = { at: "2026-10-21T12:00:00Z", likes: 3 }
  let rows = first(state).observations
  assert.equal(rows.length, 1); assert.equal(rows[0].kind, "legacy"); assert.equal(rows[0].post_age_seconds, null)
  state.tweet_metrics["123"] = { samples: { a: makeSample() }, legacy_rows: { a: { at: "2026-10-20T13:00:00Z", likes: 1 } } }
  rows = first(state).observations
  assert.deepEqual(rows.map(o => o.kind), ["legacy", "sample"])
})

test("malformed or mismatched source identity withholds values without dropping the observation", () => {
  for (const raw of [null, { schema_version: 1 }, makeSample({ tweet_id: "456" }), makeSample({ source: "invented_other_source" })]) {
    const row = first(fixture({ a: raw })).observations[0]
    assert.equal(row.association, "unusable"); assert.ok(Object.values(row.counts).every(v => v === null))
  }
})

test("bad individual counts cannot hide valid zero or other recorded fields", () => {
  for (const value of [true, "1", -1, 0.5, Infinity, NaN, 2 ** 53]) {
    const row = first(fixture({ a: makeSample({ counts: { likes: value, replies: 0 } }) })).observations[0]
    assert.equal(row.counts.likes, null); assert.equal(row.counts.replies, 0)
  }
})

test("large retained histories are not silently truncated and projection never mutates input", () => {
  const state = fixture(Object.fromEntries(Array.from({ length: 1100 }, (_, i) => [String(i), makeSample({ counts: { likes: i } })])))
  const before = structuredClone(state)
  assert.equal(first(state).observations.length, 1100)
  assert.deepEqual(project(state), project(state)); assert.deepEqual(state, before)
  assert.deepEqual(OUTCOME_METRICS, ["likes", "retweets", "replies", "quotes", "impressions", "bookmarks"])
})

test("unavailable state, known empty receipts and empty/unreadable metric rows remain distinct", () => {
  assert.equal(project(null).status, "unknown")
  assert.equal(project({ drafts: [], publish_ledger: { corrupt: null } }).status, "unknown")
  assert.equal(project({ drafts: [], publish_ledger: {} }).status, "no_retained_receipts")
  const state = fixture(); delete state.tweet_metrics
  assert.equal(first(state).history_status, "not_retained")
  state.tweet_metrics = { "123": { samples: [] } }
  assert.equal(first(state).history_status, "unreadable_or_empty")
  assert.throws(() => postOutcomes(state, { now: NaN }), /valid clock/)
})

const publicationFixture = () => JSON.parse(readFileSync(new URL("../../tests/fixtures/post_outcome_publication_context.json", import.meta.url), "utf8"))
const context = state => first(state).publication_context

test("actual Python publication fixture joins full receipt identity to type and source without leaking unbound data", () => {
  const state = publicationFixture(), before = structuredClone(state), draft = state.drafts[0]
  assert.deepEqual(context(state), { status: "recorded", type: "monthly_high", source: {
    event_id: draft.event_id, signal_kind: "monthly_high", bundle_sha256: fingerprint(draft.review_context.two_bot.bundle),
  } })
  assert.deepEqual(draftIdentity(draft), Object.fromEntries(["content_revision", "text_sha256", "evidence_sha256"].map(key => [key, state.publish_ledger[draft.event_id][key]])))
  assert.doesNotMatch(JSON.stringify(project(state)), /unbound_writer_angle|manual_override|selected_candidate_rank|DO_NOT_DISPLAY_FULL_SOURCE/)
  assert.deepEqual(state, before)
})

test("unchanged receipt cannot certify mutable angle, variant, manual flag, reviewer or actor", () => {
  const state = publicationFixture(), expected = project(state), identity = draftIdentity(state.drafts[0])
  Object.assign(state.drafts[0], { manual_override: false, selected_candidate_rank: 99, actor: "invented_unbound_actor", source_brief_id: "invented_unbound_brief" })
  state.drafts[0].review_binding = { kind: "human", actor: "invented_unbound_reviewer" }
  state.drafts[0].review_context.two_bot.angle_chosen = "new_unbound_angle"
  assert.deepEqual(draftIdentity(state.drafts[0]), identity)
  assert.deepEqual(project(state), expected)
})

for (const change of [
  draft => { draft.type = "monthly_low" },
  draft => { draft.review_context.two_bot.bundle.raw_signal_dump.source_product = "changed" },
  draft => { draft.event_id = "different-event" },
  draft => { draft.content_revision++ },
  draft => { draft.text += " Later edit." },
]) test(`full identity is recomputed instead of trusting same text or copied hashes: ${change}`, () => {
  const state = publicationFixture(), originalText = first(state).text
  change(state.drafts[0])
  const receipt = state.publish_ledger["invented-outcome-event"]
  Object.assign(state.drafts[0], { text_sha256: receipt.text_sha256, evidence_sha256: receipt.evidence_sha256 })
  // Declared identity fields do not replace recomputation of the actual inputs.
  assert.equal(context(state).status, "unknown")
  assert.equal(first(state).text, originalText)
})

test("complete historical snapshot recovers original context; partial edit history never borrows today's fields", () => {
  const state = publicationFixture(), original = structuredClone(state.drafts[0]), expected = context(state)
  invalidateText(state.drafts[0], "A later invented revision.")
  assert.equal(context(state).status, "unknown")
  assert.equal(first(state).text, original.text)
  state.drafts[0].revision_history.push(original)
  state.drafts[0].type = "monthly_low"
  state.drafts[0].event_id = "later-unrelated-event"
  assert.deepEqual(context(state), expected)
})

test("distinct receipt source identities conflict even when text is identical; exact duplicates are order independent", () => {
  const state = publicationFixture(), receipt = state.publish_ledger["invented-outcome-event"], expected = project(state)
  receipt.attempt_conflicts = [structuredClone(receipt)]
  assert.deepEqual(project(state), expected)
  const changed = structuredClone(state.drafts[0])
  changed.review_context.two_bot.bundle.current_facts = [{ label: "different source fact", value: 1 }]
  state.drafts[0].revision_history = [changed]
  receipt.attempt_conflicts.push({ ...receipt, ...draftIdentity(changed), attempt_conflicts: [] })
  assert.equal(first(state).revision_status, "recorded", "text identity remains independent")
  assert.deepEqual(context(state), { status: "conflict", type: null, source: null })
  const reordered = structuredClone(state); reordered.publish_ledger["invented-outcome-event"].attempt_conflicts.reverse()
  assert.deepEqual(project(reordered), project(state))
})

test("shared/cyclic receipt objects cannot make context depend on ledger order", () => {
  const state = publicationFixture(), receipt = state.publish_ledger["invented-outcome-event"]
  receipt.attempt_conflicts = [receipt]
  state.publish_ledger.other = receipt
  const reverse = { ...state, publish_ledger: Object.fromEntries(Object.entries(state.publish_ledger).reverse()) }
  assert.equal(context(state).status, "conflict")
  assert.deepEqual(project(state), project(reverse))
})

for (const change of [
  receipt => { delete receipt.evidence_sha256 }, receipt => { delete receipt.intent_id },
  receipt => { receipt.content_revision = true }, receipt => { receipt.content_revision = 0 },
  receipt => { receipt.evidence_sha256 = "malformed" }, receipt => { receipt.attempt_conflicts = {} },
  receipt => { receipt.phase = "submitted" }, receipt => { receipt.phase = "unknown" },
  receipt => { receipt.phase = "not_sent" }, receipt => { delete receipt.phase },
]) test(`legacy, malformed and unconfirmed receipts cannot mint context: ${change}`, () => {
  const state = publicationFixture(); change(state.publish_ledger["invented-outcome-event"])
  assert.deepEqual(context(state), { status: "unknown", type: null, source: null })
})

test("orphan receipt, incomplete snapshots, conflicts and malformed Unicode withhold metadata without losing history", () => {
  for (const change of [
    state => { state.drafts = [] }, state => { delete state.drafts[0].id },
    state => { delete state.drafts[0].type }, state => { state.drafts[0].type = "\ud800" },
    state => { state.drafts[0].revision_conflicts = [{}] },
  ]) {
    const state = publicationFixture(); change(state)
    assert.equal(context(state).status, "unknown"); assert.equal(first(state).observations.length, 1)
  }
  const state = publicationFixture(); state.publish_ledger["invented-outcome-event"].text += " wrong body"
  assert.equal(context(state).status, "conflict")
})

test("context does not alter schema1/legacy metric ages and its output cannot mutate the retained source", () => {
  const state = publicationFixture(), before = structuredClone(state), output = project(state)
  output.posts[0].publication_context.source.event_id = "output-only-edit"
  assert.deepEqual(state, before)
  const retained = context(state), originalContext = structuredClone(retained)
  state.drafts[0].review_context.two_bot.bundle.raw_signal_dump.description = "later input mutation"
  assert.deepEqual(retained, originalContext)
  assert.equal(context(state).status, "unknown")
  state.drafts[0] = before.drafts[0]
  state.tweet_metrics["123"] = { at: "2026-10-21T12:00:00Z", likes: 0 }
  assert.equal(context(state).status, "recorded")
  assert.equal(first(state).observations[0].kind, "legacy")
  assert.equal(first(state).observations[0].counts.likes, 0)
  assert.equal(first(state).observations[0].post_age_seconds, null)
})

test("a verified type does not manufacture missing or mismatched source-bundle identity", () => {
  for (const bundle of [null, {}, { event_id: "another event", signal_kind: "monthly_high" }]) {
    const state = publicationFixture()
    state.drafts[0].review_context.two_bot.bundle = bundle
    Object.assign(state.publish_ledger["invented-outcome-event"], draftIdentity(state.drafts[0]))
    assert.deepEqual(context(state), { status: "recorded", type: "monthly_high", source: null })
  }
})
