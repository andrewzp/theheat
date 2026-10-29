import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { OperatorClaimReferences } from "../app/components/OperatorClaimReferences.js"
import { draftIdentity, initializeRevision, invalidateText, projectDraft } from "../lib/draft-revisions.js"
import { projectOperatorClaimReferences } from "../lib/operator-claim-references.js"
import { operatorClaimKindMatches } from "../lib/operator-claim-reference-input.js"

const fixture = JSON.parse(readFileSync(new URL("../../tests/fixtures/operator_claim_references.json", import.meta.url)))
// Browser contract fixtures. The corresponding Python regression obtains each
// of these six kinds from the actual intern over invented GHCN source bytes.
const variants = [
  ["all_time_high", "open_meteo_archive_high"], ["all_time_low", "open_meteo_archive_low"],
  ["monthly_high", "monthly_high"], ["monthly_low", "monthly_low"],
  ["record", "calendar_record"], ["record_low", "calendar_record_low"],
]
function draft(legacy, kind) {
  const bundle = { ...structuredClone(fixture.bundle), signal_kind: kind }
  return initializeRevision({ id: "invented-kind-alias", event_id: bundle.event_id, type: legacy, text: fixture.text, status: "pending",
    review_context: { source: "Invented fixture", two_bot: { bundle } } })
}
for (const [legacy, kind] of variants) {
  test(`documented GHCN kind pair ${legacy}/${kind} can edit, project and select facts`, () => {
    const d = draft(legacy, kind), before = draftIdentity(d), bundle = structuredClone(d.review_context.two_bot.bundle)
    invalidateText(d, d.text, fixture.items)
    assert.equal(d.content_revision, before.content_revision + 1)
    assert.deepEqual(d.review_context.two_bot.bundle, bundle)
    const projected = projectDraft(d)
    assert.equal(projected.operator_claim_reference_view.status, "saved")
    const html = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft: projected, editing: true, items: fixture.items, onChange() {} }))
    assert.ok(html.includes("Use selected quote"))
    assert.ok(!html.includes("source snapshot does not match"))
    const badHash = structuredClone(d)
    badHash.review_context.operator_claim_references.text_sha256 = "f".repeat(64)
    assert.equal(projectOperatorClaimReferences(badHash).status, "unavailable")
    const badSource = structuredClone(d)
    badSource.review_context.two_bot.bundle.current_facts[0].value = 901
    assert.equal(projectOperatorClaimReferences(badSource).status, "unavailable")
    for (const change of [x => x.type = "unrelated_temperature_kind", x => x.event_id = "other-event",
      x => x.review_context.two_bot.bundle.signal_kind = "other_source_kind"]) {
      const changed = structuredClone(d); change(changed)
      assert.equal(projectOperatorClaimReferences(changed).status, "unavailable")
      const old = structuredClone(changed)
      assert.throws(() => invalidateText(changed, changed.text, fixture.items), /snapshot does not match/)
      assert.deepEqual(changed, old)
      const refused = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft: changed, editing: true, items: fixture.items, onChange() {} }))
      assert.ok(!refused.includes("Use selected quote"))
      assert.ok(refused.includes("source snapshot does not match"))
    }
  })
}

test("kind aliases are directional exact and never coerced", () => {
  for (const [saved, bundle, expected] of [
    ["temperature", "temperature", true], ["record", "record", true],
    ["open_meteo_archive_high", "all_time_high", false], ["calendar_record", "record", false],
    ["record_low", "calendar_record", false], ["all_time_high", "open_meteo_archive_low", false],
    ["monthly_high", "open_meteo_archive_high", false], ["ALL_TIME_HIGH", "open_meteo_archive_high", false],
    [null, null, false], ["", "", false], [true, true, false], [[], [], false],
  ]) assert.equal(operatorClaimKindMatches(saved, bundle), expected)
})
