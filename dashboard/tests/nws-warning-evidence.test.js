import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { nwsWarningForDisplay } from "../lib/nws-warning-evidence.js"
import { NwsWarningEvidence } from "../app/components/NwsWarningEvidence.js"
import { draftIdentity } from "../lib/draft-revisions.js"
import { nwsDraft } from "./fixtures/nws-warning-evidence.js"

const render = draft => renderToStaticMarkup(React.createElement(NwsWarningEvidence, { draft }))
const envelope = draft => draft.review_context.two_bot.bundle.raw_signal_dump.source_evidence

test("expired source is visibly held with original evidence retained; saved-window status never claims live currentness", () => {
  const draft = nwsDraft(), before = structuredClone(draft)
  const held = renderToStaticMarkup(React.createElement(NwsWarningEvidence, { draft, now: Date.parse("2026-01-01T06:00:00Z") }))
  assert.ok(held.includes("Source update needed"))
  assert.ok(held.includes("Review and approval are held"))
  assert.ok(held.includes('role="status"'))
  assert.ok(held.includes("TAIL: Dangerous winds are possible tonight"))
  assert.ok(held.includes("Saved review window ends (UTC)"))
  const within = renderToStaticMarkup(React.createElement(NwsWarningEvidence, { draft, now: Date.parse("2026-01-01T01:00:00Z") }))
  assert.ok(!within.includes("Source update needed"))
  assert.ok(within.includes("may have changed since capture"))
  assert.deepEqual(draft, before)
})

test("actual component shows the complete retained warning beyond compact facts and its instructions", () => {
  const draft = nwsDraft(), saved = envelope(draft), html = render(draft)
  assert.ok(saved.feature.properties.description.length > 800)
  for (const value of ["Warning saved with this draft", "Invented Pelican Island", "NWS Test Office", "Typhoon Warning",
    "Alert", saved.feature.properties.sent, saved.captured_at, saved.feature.properties.effective,
    saved.feature.properties.expires, "TAIL: Dangerous winds are possible tonight", saved.feature.properties.instruction,
    "does not establish observed harm", "may have changed since capture", "does not authenticate", "before posting"])
    assert.ok(html.includes(value), value)
  assert.equal((html.match(/<details/g) || []).length, 1)
  assert.equal((html.match(/href=/g) || []).length, 1)
  assert.ok(html.includes('rel="noreferrer noopener"'))
  assert.ok(!html.includes("<button") && !html.includes("<input"))
})

test("presentation leaves revision, all input and review/approval bindings unchanged", () => {
  const draft = nwsDraft()
  draft.review_binding = { kind: "invented" }; draft.approval_binding = { mode: "invented" }
  const before = structuredClone(draft), identity = draftIdentity(draft)
  render(draft); nwsWarningForDisplay(draft)
  assert.deepEqual(draft, before); assert.deepEqual(draftIdentity(draft), identity)
})

test("escaped source content cannot introduce HTML or an arbitrary hyperlink", () => {
  const draft = nwsDraft(), props = envelope(draft).feature.properties
  props.description = '<script>alert("invented")</script> https://invalid.example/'
  props.instruction = '<img src=x onerror="alert(1)">'
  const html = render(draft)
  assert.ok(html.includes("&lt;script&gt;") && html.includes("&lt;img"))
  assert.ok(!html.includes("<script") && !html.includes("<img"))
  assert.ok(!html.includes('href="https://invalid.example/"'))
  assert.ok(html.includes('href="https://api.weather.gov/alerts/urn:oid:'))
})

for (const change of [
  d => { envelope(d).source_alert_id = "javascript:alert(1)" },
  d => { envelope(d).source_url = "https://invalid.example/alerts/active" },
  d => { envelope(d).feature.id = "https://invalid.example/" },
  d => { envelope(d).feature.properties.id += ".other" },
  d => { d.event_id += ".other" },
  d => { d.review_context.two_bot.bundle.event_id += ".other" },
  d => { d.review_context.two_bot.bundle.raw_signal_dump.event_id += ".other" },
  d => { envelope(d).feature.properties.description = "x".repeat(65537) },
  d => { envelope(d).feature.properties.instruction = { invented: "not text" } },
  d => { delete envelope(d).feature.properties.sent },
  d => { envelope(d).feature.properties.description = "Malformed \ud800 text" },
  d => { d.event_id = { toString: {} } },
]) test("malformed or mismatched saved NWS input is honestly unavailable: " + String(change), () => {
  const draft = nwsDraft(); change(draft)
  assert.equal(nwsWarningForDisplay(draft).status, "unreadable")
  const html = render(draft)
  assert.ok(html.includes("cannot be displayed")); assert.ok(!html.includes("href="))
})

test("missing input and unsupported families remain distinct; absent instructions are explicit", () => {
  const draft = nwsDraft(); delete draft.review_context.two_bot.bundle.raw_signal_dump.source_evidence
  assert.ok(render(draft).includes("was not saved"))
  assert.equal(render({ type: "air_quality_hazard" }), "")
  const absent = nwsDraft(); envelope(absent).feature.properties.instruction = null
  assert.ok(render(absent).includes("No separate instructions were supplied"))
})
