// Final closure C2/C3: the joint-review panel compares the text's measured values with
// the graphic's own description. Advisory only; invented copy and descriptions.
import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { textGraphicAgreement } from "../lib/text-graphic-agreement.js"
import { MediaControls, TextGraphicAgreement } from "../app/components/GraphicPreview.js"

const PM25 = "Model forecast for Sample City, 2026-10-30 (Asia/Example). Hourly PM2.5: 00:00 88.1 µg/m³; 01:00 91.4 µg/m³. 24-hour mean 89.6 µg/m³."

test("values stated in the graphic description agree at the text's own precision", () => {
  const result = textGraphicAgreement("Sample City's PM2.5 is forecast to average 90 µg/m³ Friday.", PM25)
  assert.deepEqual(result, { status: "compared", unmatched: [], compared: 1 })
})

test("a value the graphic never states is named, including derived departures", () => {
  const result = textGraphicAgreement("Sample City's PM2.5 is forecast to average 95 µg/m³, 1,800 µg/m³ of dust and 8°C warmer.", PM25)
  assert.deepEqual(result.unmatched, ["95 µg/m³", "1,800 µg/m³", "8°C"])
})

test("Fahrenheit copy is compared with Celsius descriptions; years and times are not values", () => {
  const description = "Observed daily maximum 39.9 °C at station ZZ000000001 on 2026-06-25; comparator 39.1 °C."
  assert.deepEqual(textGraphicAgreement("Sample Town reached 103.8°F, beating its 2020 mark at 3 p.m.", description).unmatched, [])
  assert.equal(textGraphicAgreement("No measured values here.", description).status, "no_measured_values")
  assert.equal(textGraphicAgreement("47°C", "").status, "not_comparable")
})

test("the review panel shows the comparison and keeps the human review decisive", () => {
  const sha = "c".repeat(64)
  const draft = { id: "invented", status: "pending", text: "Sample City's PM2.5 is forecast to average 95 µg/m³ Friday.",
    media_attachment_sha256: sha, editorial_policy: { policy_sha256: "d".repeat(64) }, revision_identity: {} }
  const preview = { status: "ready", value: { schema_version: 4, media_descriptor_sha256: sha, delivery_text: PM25 } }
  const html = renderToStaticMarkup(React.createElement(MediaControls, { draft, preview, reviewConfirmed: false,
    onConfirm: () => {}, onAction: () => {} }))
  assert.match(html, /data-status="unmatched"/)
  assert.match(html, /Not stated in the graphic description: 95 µg\/m³/)
  assert.match(html, /Record joint review/)  // Still the human's decision; nothing is blocked or approved here.
  const published = renderToStaticMarkup(React.createElement(TextGraphicAgreement, { text: draft.text, value: { schema_version: 5 } }))
  assert.match(published, /Software does not read a published image/)
})
