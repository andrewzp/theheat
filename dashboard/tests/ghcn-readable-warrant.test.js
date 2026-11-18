import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GhcnReadableWarrant } from "../app/components/GhcnReadableWarrant.js"
import { readableGHCNWarrantForDisplay } from "../lib/ghcn-readable-warrant.js"
import { temperaturePreviewSourceStatus } from "../lib/graphic-preview.js"
import { readableDraft } from "./helpers/ghcn-readable.js"

test("complete retained rows and absence groups display without mutating authority", () => {
  const draft = readableDraft(), before = structuredClone(draft)
  const display = readableGHCNWarrantForDisplay(draft)
  assert.equal(display.status, "saved")
  assert.equal(display.rows.length, 2)
  assert.equal(display.columns.length, 9)
  assert.deepEqual(display.rows[0].slice(5), [null, null, null, null])
  display.rows[0][4] = 999
  assert.deepEqual(draft, before)
  assert.equal(temperaturePreviewSourceStatus(draft), "ghcn") // Affordance, never scientific certification.
})

test("archive disclosure is collapsed, read-only and names its source and absence semantics", () => {
  const html = renderToStaticMarkup(React.createElement(GhcnReadableWarrant, { draft: readableDraft() }))
  assert.match(html, /<details/)
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/)
  assert.match(html, /Saved GHCN archive/)
  assert.match(html, /not a live source check/)
  assert.match(html, /never zero/)
  assert.match(html, /references this same complete baseline/)
  assert.match(html, /temperature_2m_max:previous_c/)
  assert.match(html, /tabindex="0"/)
  assert.match(html, /scope="col"/)
  assert.match(html, /scope="row"/)
  assert.match(html, /—/)
  assert.doesNotMatch(html, /<button|<input|<form|<script|<a\b/)
})

for (const fault of ["schema", "duplicate", "bad_day", "partial", "all_null", "bool_count", "string_value", "extra_column", "mixed_maps", "alias_path", "oversize", "nonfinite"]) {
  test(`malformed retained display is unavailable: ${fault}`, () => {
    const draft = readableDraft(), wire = draft.review_context.two_bot.bundle
    const baseline = wire.raw_signal_dump.evidence.baseline, table = baseline.calendar_table
    if (fault === "schema") baseline.schema_version += "-unknown"
    else if (fault === "duplicate") table.rows.push([...table.rows[0]])
    else if (fault === "bad_day") table.rows[0][0] = "02-30"
    else if (fault === "partial") table.rows[0][1] = null
    else if (fault === "all_null") table.rows[0].fill(null, 1)
    else if (fault === "bool_count") table.rows[0][1] = true
    else if (fault === "string_value") table.rows[0][4] = "28"
    else if (fault === "extra_column") table.columns.push("unknown")
    else if (fault === "mixed_maps") baseline.variables.temperature_2m_max.calendar_years = {}
    else if (fault === "alias_path") wire.historical_context.baseline.same_document_baseline = "https://example.invalid"
    else if (fault === "oversize") wire.where = "x".repeat(40000)
    else table.rows[0][4] = Infinity
    assert.equal(readableGHCNWarrantForDisplay(draft).status, "unavailable")
    assert.equal(temperaturePreviewSourceStatus(draft), "unsupported")
    const html = renderToStaticMarkup(React.createElement(GhcnReadableWarrant, { draft }))
    assert.match(html, /unavailable or uses an unsupported format/)
    assert.doesNotMatch(html, /<table/)
  })
}

test("unrelated and original full inputs add no archive disclosure", () => {
  assert.equal(renderToStaticMarkup(React.createElement(GhcnReadableWarrant, { draft: {} })), "")
  const draft = readableDraft(), baseline = draft.review_context.two_bot.bundle.raw_signal_dump.evidence.baseline
  delete baseline.wire_profile; delete baseline.calendar_table; baseline.schema_version = 2
  draft.review_context.two_bot.bundle.historical_context.baseline = {}
  assert.equal(readableGHCNWarrantForDisplay(draft).status, "absent")
})
