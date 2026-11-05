import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure } from "../app/components/GraphicPreview.js"
import { riverPreviewSourceStatus } from "../lib/graphic-preview.js"

function draft() {
  return {
    id: "invented-river", type: "river_flood", status: "pending", text: "Invented attributed forecast.",
    revision_identity: { content_revision: 0, decision_revision: 0,
      text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64) },
    review_context: { nwps_point_capture: { schema_version: 1, artifact_sha256: "c".repeat(64),
      capture_sha256: "d".repeat(64), bundle_sha256: "e".repeat(64) },
    two_bot: { bundle: { signal_kind: "river_flood", raw_signal_dump: { nwps_index_hint: { gaugelid: "FAKF1" } } } } },
  }
}

test("a saved river capture offers its read-only preview without attachment controls", () => {
  const value = draft()
  assert.equal(riverPreviewSourceStatus(value), "retained")
  const html = renderToStaticMarkup(React.createElement(GraphicPreview, { draft: value }))
  assert.match(html, /Preview graphic/)
  assert.match(html, /river forecast chart/)
  assert.doesNotMatch(html, /Attach graphic|Review text and graphic|retained-input-/)
})

test("missing river capture is actionable and an ordinary gauge is not reinterpreted as NWPS", () => {
  const value = draft()
  delete value.review_context.nwps_point_capture
  assert.equal(riverPreviewSourceStatus(value), "missing")
  const html = renderToStaticMarkup(React.createElement(GraphicPreview, { draft: value }))
  assert.match(html, /river forecast packet was not saved/)
  assert.doesNotMatch(html, /<button/)
  delete value.review_context.two_bot.bundle.raw_signal_dump.nwps_index_hint
  assert.equal(riverPreviewSourceStatus(value), "unsupported")
  assert.equal(renderToStaticMarkup(React.createElement(GraphicPreview, { draft: value })), "")
})

test("editing a river draft hides the old preview action", () => {
  const html = renderToStaticMarkup(React.createElement(GraphicPreview, { draft: draft(), editing: true }))
  assert.match(html, /Save or cancel your text edit/)
  assert.doesNotMatch(html, /Preview graphic/)
})

test("river figure labels the issued forecast and point count without assuming an acquisition timestamp", () => {
  const html = renderToStaticMarkup(React.createElement(GraphicPreviewFigure, {
    value: { schema_version: 2, source: "NOAA/NWS National Water Prediction Service",
      title: "Invented river-stage forecast", alt_text: "Three forecast points in feet.",
      width: 1200, height: 1500, scope: "Crossing time is uncertain.",
      source_context: { kind: "nwps_forecast_points", gauge: "FAKF1", unit: "ft",
        issued_at: "2026-07-01T14:00:00+00:00", first_major_at: "2026-07-02T18:00:00+00:00",
        checked_at: "2026-07-01T16:00:00+00:00", point_count: 3 } }, url: "blob:invented",
  }))
  assert.match(html, /Gauge FAKF1/)
  assert.match(html, /forecast issued 2026-07-01T14:00:00\+00:00/)
  assert.match(html, /3 supplied points in feet/)
  assert.match(html, /Source checked 2026-07-01T16:00:00\+00:00/)
  assert.match(html, /currentness requires a new source check/)
  assert.match(html, /Crossing time is uncertain/)
})
