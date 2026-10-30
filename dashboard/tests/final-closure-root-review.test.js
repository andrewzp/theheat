import test from "node:test"
import assert from "node:assert/strict"
import { textGraphicAgreement } from "../lib/text-graphic-agreement.js"
import { copyNotes } from "../lib/copy-gates.js"
import { codeRevisionEvidence } from "../lib/runtime-inventory.js"
import { gpmAccessHealth } from "../lib/source-access.js"
import { readFileSync } from "node:fs"

for (const [text, description] of [
  ["30°C", "Temperature 19°C on 2026-10-30."],
  ["100 km/h", "Rainfall 100 mm; wind 20 km/h."],
  ["86°F", "Rainfall 30 mm; temperature 19°C."],
  ["−25.5°C", "Temperature 25.5°C on 2026-10-30."],
]) test(`graphic comparison preserves dimensions and signs: ${text}`, () => {
  assert.deepEqual(textGraphicAgreement(text, description).unmatched, [text])
})

test("substantive diagnostic language receives advice rather than a false filler rejection", () => {
  assert.equal(copyNotes("Sample Bay reached 31°C, a sign of coral bleaching confirmed in the survey.")
    .some(note => note.code === "generic_explanatory_ending" && note.blocking), false)
})

test("a newer uninstrumented bot run does not inherit an old matching revision", () => {
  const sha = "a".repeat(40)
  const result = codeRevisionEvidence({ run_history: [
    { id: "old", started_at: "2026-10-30T10:00:00Z", runtime_inventory: {
      schema_version: 1, captured_at: "2026-10-30T10:00:00Z", git_sha: sha } },
    { id: "new", started_at: "2026-10-30T11:00:00Z" },
  ] }, { deployment: { git_sha: sha }, now: Date.parse("2026-10-30T12:00:00Z") })
  assert.equal(result.status, "unknown")
  assert.equal(result.deployed_revision_pipeline_run.status, "observed")
})

for (const flag of [false, null]) test(`Sources does not advertise unenforced backoff: ${flag}`, () => {
  const fixture = JSON.parse(readFileSync(new URL("../../tests/final_closure/fixtures/supply_gpm_access.json", import.meta.url)))
  const item = fixture.cases.refused_backoff
  const latest = item.state.run_history.toSorted((a, b) => b.started_at.localeCompare(a.started_at))[0]
  latest.runtime_inventory = { schema_version: 1, captured_at: latest.started_at,
    flags: { earthdata_refusal_backoff_enabled: flag } }
  const result = gpmAccessHealth(item.state, { asOf: item.as_of })
  assert.notEqual(result.stage, "refused_backoff")
  assert.equal(result.backoff, null)
  assert.doesNotMatch(result.public_text, /retried only after/)
})
