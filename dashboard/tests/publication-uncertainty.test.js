import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { hasUnresolvedPublish } from "../lib/draft-revisions.js"
import { mergePublishLedger } from "../lib/state-store.js"

const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/publication_uncertainty_contract.json", import.meta.url)))
const draft = { id: "draft", event_id: "event", text: "Current reviewed text.", status: "pending" }

function malformedSubtrees(row) {
  if (!row || typeof row !== "object" || Array.isArray(row)) return [row]
  const conflicts = Object.hasOwn(row, "attempt_conflicts") ? row.attempt_conflicts : []
  if (!Array.isArray(conflicts) || conflicts.some((child) => !child || typeof child !== "object" || Array.isArray(child))) return [row]
  return conflicts.flatMap(malformedSubtrees)
}

function containsValue(value, target) {
  try { assert.deepEqual(value, target); return true } catch { /* Keep looking through nested evidence. */ }
  return Boolean(value && typeof value === "object" && Object.values(value).some((child) => containsValue(child, target)))
}

for (const example of cases) {
  test(`shared uncertainty gate: ${example.name}`, () => {
    for (const outcome of [undefined, "not_sent", "confirmed", "unknown"]) {
      const record = { ...draft, ...(outcome ? { publish_outcome: outcome } : {}) }
      const state = { publish_ledger: Object.hasOwn(example, "row") ? { event: example.row } : {} }
      const original = structuredClone([record, state])
      assert.equal(hasUnresolvedPublish(record, state), example.unresolved || outcome === "unknown")
      assert.deepEqual([record, state], original)
    }
  })
  if (!example.malformed) continue
  test(`merge preserves opaque uncertainty: ${example.name}`, () => {
    const bad = { event: example.row }, original = structuredClone(bad)
    for (const incoming of [{}, { event: { phase: "not_sent" } }, { event: { phase: "confirmed", tweet_id: "receipt", text: draft.text } }]) {
      const forward = mergePublishLedger(bad, incoming)
      assert.deepEqual(mergePublishLedger(incoming, bad), forward)
      assert.equal(hasUnresolvedPublish(draft, { publish_ledger: forward }), true)
      for (const payload of malformedSubtrees(example.row)) assert.equal(containsValue(forward.event, payload), true)
      assert.deepEqual(mergePublishLedger(forward, bad), forward)
      assert.deepEqual(mergePublishLedger(forward, forward), forward)
    }
    assert.deepEqual(bad, original)
    const known = { event: { phase: "not_sent" } }
    assert.deepEqual(mergePublishLedger(mergePublishLedger(known, bad), bad), mergePublishLedger(known, mergePublishLedger(bad, bad)))
  })
}

test("unidentified nested unknown attempts cannot be absorbed by not-sent evidence", () => {
  const row = cases.find((example) => example.name === "unknown nested attempt").row
  const ledger = mergePublishLedger({ event: row }, { event: { phase: "not_sent" } })
  assert.equal(hasUnresolvedPublish(draft, { publish_ledger: ledger }), true)
  assert.equal(containsValue(ledger, { phase: "unknown" }), true)
  assert.deepEqual(mergePublishLedger(ledger, { event: row }), ledger)
})

test("container marker cannot hide other retained attempt fields", () => {
  const row = { preserved_evidence_only: true, attempt_conflicts: [], phase: "unknown", text: "Original evidence" }
  const merged = mergePublishLedger({ event: row }, {})
  assert.equal(merged.event.phase, "unknown")
  assert.equal(merged.event.text, row.text)
})
