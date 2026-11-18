import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ClaimEvidence } from "../app/components/ClaimEvidence.js"
import { projectDraft } from "../lib/draft-revisions.js"
import { claimEvidenceForDisplay } from "../lib/saved-claim-evidence.js"

const aliases = [
  ["all_time_high", "open_meteo_archive_high"],
  ["all_time_low", "open_meteo_archive_low"],
  ["record", "calendar_record"],
  ["record_low", "calendar_record_low"],
]
function draft(type, kind) {
  return { id: "invented-source-kind", event_id: "invented-event", type,
    content_revision: 1, status: "pending", text: "Invented station observation.",
    review_context: { two_bot: { bundle: { event_id: "invented-event", signal_kind: kind,
      where: "Invented station", when: "2032-01-02",
      current_facts: [{ label: "observed_temperature", value: 41.2, unit: "°C" },
        { label: "missing_interval", value: null }] } } } }
}

for (const [legacy, kind] of aliases) {
  test(`actual projection and component display saved facts for ${legacy}/${kind} without authority`, () => {
    const input = draft(legacy, kind), before = structuredClone(input)
    const projected = projectDraft(input), shown = claimEvidenceForDisplay(projected)
    assert.equal(shown.source.status, "saved")
    assert.deepEqual(shown.source.facts, [{ label: "observed_temperature", value: 41.2, unit: "°C" },
      { label: "missing_interval", value: null, unit: null }])
    assert.equal(shown.claims.status, "missing")
    assert.equal(projected.review_status, "policy_unverified")
    assert.equal(projected.review_binding, undefined)
    assert.equal(projected.approval_binding, undefined)
    const html = renderToStaticMarkup(React.createElement(ClaimEvidence, { draft: projected }))
    assert.match(html, /Saved source facts/)
    assert.match(html, /41\.2 °C/)
    assert.doesNotMatch(html, /incomplete, inconsistent or too large/)
    assert.deepEqual(input, before)
  })
  test(`the reverse ${kind}/${legacy} does not acquire an undocumented alias`, () => {
    assert.equal(claimEvidenceForDisplay(projectDraft(draft(kind, legacy))).source.status, "unreadable")
  })
}

for (const [type, kind] of [["all_time_high", "open_meteo_archive_low"],
  ["record", "calendar_record_low"], ["all_time_high_extra", "open_meteo_archive_high"],
  ["constructor", "open_meteo_archive_high"]]) {
  test(`mismatched source identity ${type}/${kind} stays unavailable`, () => {
    assert.equal(claimEvidenceForDisplay(projectDraft(draft(type, kind))).source.status, "unreadable")
  })
}

test("an accepted kind alias cannot bypass event identity or scalar-fact bounds", () => {
  const cases = []
  let value = draft(...aliases[0]); value.review_context.two_bot.bundle.event_id = "other"; cases.push(value)
  value = draft(...aliases[0]); value.review_context.two_bot.bundle.current_facts[0].value = { nested: 41.2 }; cases.push(value)
  value = draft(...aliases[0]); value.review_context.two_bot.bundle.current_facts[0].value = "x".repeat(2049); cases.push(value)
  value = draft(...aliases[0]); value.review_context.two_bot.bundle.current_facts = Array.from({ length: 65 }, () => ({ label: "value", value: 1 })); cases.push(value)
  for (const input of cases) {
    const before = structuredClone(input)
    assert.equal(claimEvidenceForDisplay(projectDraft(input)).source.status, "unreadable")
    assert.deepEqual(input, before)
  }
})

test("existing exact-kind source facts retain their display behavior", () => {
  assert.equal(claimEvidenceForDisplay(projectDraft(draft("monthly_high", "monthly_high"))).source.status, "saved")
})
