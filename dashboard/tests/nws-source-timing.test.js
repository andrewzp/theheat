import test from "node:test"
import assert from "node:assert/strict"
import { nwsSourceTiming } from "../lib/nws-source-timing.js"
import { draftReviewControls } from "../lib/draft-review-ui.js"
import { draftIdentity } from "../lib/draft-revisions.js"
import { nwsDraft } from "./fixtures/nws-warning-evidence.js"

const at = value => Date.parse(value)
const saved = d => d.review_context.two_bot.bundle.raw_signal_dump.source_evidence
const props = d => saved(d).feature.properties
const NOW = at("2026-01-01T01:00:00Z")

test("saved timing is not a live-current pass and never changes source or decision identity", () => {
  const draft = nwsDraft(), before = structuredClone(draft), identity = draftIdentity(draft)
  const timing = nwsSourceTiming(draft, NOW)
  assert.deepEqual(timing, { status: "saved_window", blocked: false, cutoff: "2026-01-01T06:00:00.000Z" })
  assert.deepEqual(draft, before)
  assert.deepEqual(draftIdentity(draft), identity)
  assert.equal(draftReviewControls({ ...draft, review_status: "needs_revalidation" }, NOW).canReview, true)
})

for (const [label, change] of [
  ["expired", d => { props(d).expires = "2026-01-01T00:59:59Z" }],
  ["earlier ends", d => { props(d).ends = "2026-01-01T01:00:00Z" }],
  ["future sent", d => { props(d).sent = "2026-01-01T01:00:00.000001Z" }],
  ["future effective", d => { props(d).effective = "2026-01-01T01:01:00Z" }],
  ["future capture", d => { saved(d).captured_at = "2026-01-01T01:00:00.000001Z" }],
  ["old capture", d => { saved(d).captured_at = "2025-12-31T18:00:00Z" }],
  ["naive date", d => { props(d).sent = "2026-01-01T00:00:00" }],
  ["invalid calendar date", d => { props(d).sent = "2026-02-30T00:00:00Z" }],
  ["invalid hour", d => { props(d).sent = "2026-01-01T24:00:00Z" }],
  ["invalid minute", d => { props(d).expires = "2026-01-01T06:61:00Z" }],
  ["invalid offset", d => { props(d).sent = "2026-01-01T00:00:00+24:00" }],
  ["invalid optional end", d => { props(d).ends = "not a timestamp" }],
  ["invalid optional onset", d => { props(d).onset = "not a timestamp" }],
  ["empty interval", d => { props(d).effective = props(d).expires }],
  ["onset beyond end", d => { props(d).onset = "2026-01-01T07:00:00Z" }],
  ["missing evidence", d => { delete d.review_context.two_bot.bundle.raw_signal_dump.source_evidence }],
  ["mismatched identity", d => { d.event_id += ".other" }],
]) test(`known NWS ${label} holds review/approval/scheduling, never editing`, () => {
  const draft = nwsDraft(); change(draft)
  // Caller/persisted presentation fields cannot claim the source is ready.
  draft.source_timing = { blocked: false, status: "current" }
  Object.assign(draft, { review_status: "passed", review_kind: "model", automatic_publication: { enabled: true } })
  const source = nwsSourceTiming(draft, NOW), controls = draftReviewControls(draft, NOW)
  assert.equal(source.blocked, true)
  assert.ok(controls.sourceHold)
  assert.equal(controls.canReview, false)
  assert.equal(controls.canApprove, false)
  assert.equal(controls.canSchedule, false)
  assert.equal(controls.canEdit, true)
})

test("six-hour issuance and capture deadlines hold at cutoff; offsets and sub-ms starts cannot extend them", () => {
  const draft = nwsDraft()
  props(draft).expires = "2026-01-01T08:00:00Z"
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T05:59:59.999Z")).blocked, false)
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T06:00:00Z")).blocked, true)
  props(draft).sent = "2026-01-01T10:00:00.000999+10:00"
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T00:00:00Z")).blocked, true)
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T06:00:00Z")).blocked, true)
  saved(draft).captured_at = "2025-12-31T23:00:00.999999Z"
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T05:00:00.998Z")).blocked, false)
  assert.equal(nwsSourceTiming(draft, at("2026-01-01T05:00:00.999Z")).blocked, true)
})

test("a future wind onset within the warning interval allows preparation review", () => {
  const draft = nwsDraft(); props(draft).onset = "2026-01-01T03:00:00Z"
  assert.equal(nwsSourceTiming(draft, NOW).blocked, false)
  props(draft).sent = "2025-12-31T19:00:00-05:00"
  assert.equal(nwsSourceTiming(draft, NOW).blocked, false)
})

test("unsupported families are untouched; a known NWS identity cannot hide missing evidence", () => {
  assert.deepEqual(nwsSourceTiming({ type: "hot10", source_timing: { blocked: true } }, NOW), { status: "not_applicable", blocked: false })
  assert.equal(nwsSourceTiming({ review_context: { two_bot: { bundle: { event_id: "nws_missing" } } } }, NOW).blocked, true)
  assert.equal(nwsSourceTiming(nwsDraft(), NaN).blocked, true)
})
