// Final closure B2: the editor's advisory copy notes mirror the Python generation
// gate on shared invented vectors, and copy-gate kills reach the existing check
// consumers. Invented text only; no network, model, Gist or X access.
import assert from "node:assert/strict"
import test from "node:test"
import fs from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { COPY_GATES_VERSION, COPY_MESSAGES, copyNotes, sentences } from "../lib/copy-gates.js"
import { CopyNotes } from "../app/components/CopyNotes.js"
import { selectionTrace } from "../lib/selection-trace.js"
import { buildWeeklyReview } from "../lib/weekly-review.js"
import { sourceOutcome } from "../lib/live-content-status.js"

const vectors = JSON.parse(fs.readFileSync(new URL("../../tests/fixtures/copy_gate_vectors.json", import.meta.url), "utf8"))
const pythonSource = fs.readFileSync(new URL("../../src/two_bot/copy_gates.py", import.meta.url), "utf8")

test("every shared invented vector yields exactly the Python gate's codes", () => {
  assert.ok(vectors.vectors.length >= 15)
  for (const vector of vectors.vectors) {
    assert.deepEqual(copyNotes(vector.text).map(note => note.code), vector.codes, vector.id)
  }
})

test("version and messages stay identical to the Python module", () => {
  assert.ok(pythonSource.includes(`COPY_GATES_VERSION = "${COPY_GATES_VERSION}"`))
  for (const [code, message] of Object.entries(COPY_MESSAGES)) {
    assert.ok(pythonSource.includes(`"${code}": "${message}"`), code)
  }
})

test("abbreviations, decimals, units and an appended source URL are not sentence ends", () => {
  assert.equal(sentences("Sample City in the U.S. hit 47°C on Oct. 30 at 3 p.m. local time.").length, 1)
  assert.equal(sentences("Port Example hit 47°C. That is 8°C above normal.").length, 2)
  assert.equal(sentences("About 4.5 mm fell in Sample Basin.\nhttps://example.org/a").length, 1)
})

test("the editor note names the rule, escapes the excerpt and never claims a check passed", () => {
  const sterile = renderToStaticMarkup(React.createElement(CopyNotes, {
    id: "copy", text: "A model forecast puts <b>Port Example</b> at 47°C Thursday, a stark reminder of how fast it warms." }))
  assert.match(sterile, /data-code="source_led_opener"/)
  assert.match(sterile, /data-code="generic_explanatory_ending"/)
  assert.match(sterile, /Generation rule/)
  assert.ok(!sterile.includes("<b>") && sterile.includes("advice only; checks still decide"))
  const clean = renderToStaticMarkup(React.createElement(CopyNotes, {
    id: "copy", text: "Port Example is forecast to reach 47°C Thursday, 8°C above its July normal.", live: true }))
  assert.match(clean, /No copy notes\. This is not a factual or editorial check\./)
  assert.match(clean, /aria-live="polite"/)
})

test("danger wording is only advisory in the bundle-blind editor", () => {
  const notes = copyNotes("Port Example faces dangerously hot air on Thursday.")
  assert.deepEqual(notes.map(n => [n.code, n.blocking]), [["danger_wording_needs_source", false]])
})

test("a recorded copy-gate kill is a failed check in the trace, weekly review and source outcome", () => {
  const ts = "2026-10-13T10:00:00.000Z"
  const state = { drafts: [], suppressions: [{ ts, event_id: "invented-event", source: "invented_source", stage: "copy_gate",
    reason: "source_led_opener: 'A model forecast puts'" }], run_history: [] }
  const trace = selectionTrace(state)
  const row = trace.events.find(r => r.event_id === "invented-event")
  assert.equal(row.outcome, "failed_checks")
  const report = buildWeeklyReview({ state, asOf: "2026-10-14T00:00:00.000Z" })
  assert.equal(report.evidence.stage_failures.counts.copy_gate, 1)
  assert.equal(report.evidence.stage_failures.other_holds, 0)
  assert.equal(sourceOutcome({ source: "invented_source", status: "success" }, state.suppressions).state, "writer_or_check_rejection")
})
