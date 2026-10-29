import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { OperatorClaimReferences } from "../app/components/OperatorClaimReferences.js"
import { buildOperatorClaimReferences, projectOperatorClaimReferences, readOperatorClaimReferences } from "../lib/operator-claim-references.js"
import { operatorReferencesForDisplay, quoteFromSelection } from "../lib/operator-claim-reference-input.js"
import { draftIdentity } from "../lib/draft-revisions.js"

const fixture = JSON.parse(readFileSync(new URL("../../tests/fixtures/operator_claim_references.json", import.meta.url)))
const build = (items = fixture.items, text = fixture.text, bundle = fixture.bundle) => buildOperatorClaimReferences(text, bundle, items)
function projected() {
  const draft = { id: "invented-reference", event_id: fixture.bundle.event_id, type: fixture.bundle.signal_kind, text: fixture.text, content_revision: 1,
    review_context: { source: "Invented fixture", two_bot: { bundle: fixture.bundle }, operator_claim_references: fixture.saved } }
  draft.revision_identity = draftIdentity(draft)
  draft.operator_claim_reference_view = projectOperatorClaimReferences(draft)
  return draft
}

test("paired Unicode fixture round-trips exact server hashes and leaves inputs unchanged", () => {
  const before = structuredClone(fixture), result = build()
  assert.deepEqual(result, fixture.saved)
  assert.deepEqual(readOperatorClaimReferences(fixture.text, fixture.bundle, result), result)
  result.items[0].claim.text = "Changed return"
  assert.deepEqual(fixture, before)
})

test("exact bounded source pointers exclude traversal, URLs, ambiguous indexes and supplied digests", () => {
  for (const pointer of ["/current_facts/00", "/current_facts/-1", "/current_facts/1.0", "/current_facts/64", "/current_facts/0/value", "/current_facts/0~1", "https://invalid.example/", "__proto__", "/current_facts/999999999999"]) {
    const items = structuredClone(fixture.items); items[0].sources[0].pointer = pointer
    assert.throws(() => build(items))
  }
  for (const change of [i => i[0].claim.start = true, i => i[0].claim.end = Number.MAX_SAFE_INTEGER + 1,
    i => i[0].claim.text = "different", i => i[0].claim.end = i[0].claim.start,
    i => i[0].claim.text_sha256 = "a".repeat(64), i => i[0].sources[0].value_sha256 = "a".repeat(64),
    i => i[0].sources = [], i => i[0].sources.push(structuredClone(i[0].sources[0])), i => i.push(structuredClone(i[0])),
    i => i[0].origin = "verified", i => delete i[0]]) {
    const items = structuredClone(fixture.items); change(items)
    const before = structuredClone(items)
    assert.throws(() => build(items)); assert.deepEqual(items, before)
  }
})

test("stale or malformed retained metadata is unavailable as a whole", () => {
  for (const change of [v => v.text_sha256 = "f".repeat(64), v => v.bundle_sha256 = "f".repeat(64),
    v => v.items[0].sources[0].value_sha256 = "f".repeat(64), v => v.schema_version = true,
    v => v.items = [], v => v.items[0].sources[0].extra = "untrusted"]) {
    const value = structuredClone(fixture.saved); change(value)
    assert.equal(readOperatorClaimReferences(fixture.text, fixture.bundle, value), null)
  }
  for (const change of [b => b.current_facts[0].unit = "other unit", b => b.where = "Other invented place"]) {
    const bundle = structuredClone(fixture.bundle); change(bundle)
    assert.equal(readOperatorClaimReferences(fixture.text, bundle, fixture.saved), null)
  }
  assert.equal(readOperatorClaimReferences(fixture.text + ".", fixture.bundle, fixture.saved), null)
  for (const value of [undefined, null, [], {}]) assert.equal(readOperatorClaimReferences(fixture.text, fixture.bundle, value), null)
})

test("codepoint limits and selected-fact/metadata limits reject excess without truncation", () => {
  const text = "x".repeat(280), bundle = { current_facts: Array.from({ length: 64 }, (_, n) => ({ label: "invented", value: n })) }
  const item = { claim: { start: 0, end: 280, text }, sources: bundle.current_facts.map((_, n) => ({ pointer: `/current_facts/${n}` })) }
  assert.equal(build([item], text, bundle).items[0].sources.length, 64)
  const items = Array.from({ length: 32 }, (_, n) => ({ claim: { start: n, end: n + 1, text: "x" }, sources: [{ pointer: "/current_facts/0" }] }))
  assert.equal(build(items, text, bundle).items.length, 32)
  assert.throws(() => build([...items, { ...items[0], claim: { start: 32, end: 33, text: "x" } }], text, bundle), /32/)
  assert.throws(() => build([item, items[1]], text, bundle), /64/)
  const oversized = Array.from({ length: 32 }, (_, n) => ({ claim: { start: n, end: 280, text: "🌡".repeat(280 - n) }, sources: [{ pointer: "/current_facts/0" }, { pointer: "/current_facts/1" }] }))
  assert.throws(() => build(oversized, "🌡".repeat(280), bundle), /16 KiB/)
  assert.throws(() => build([item], text + "x", bundle))
  assert.equal(build([], text, null), null)
  for (const facts of [null, [null], [{ label: "x", value: {} }], [{ label: "x", value: Infinity }], Array(2), Array.from({ length: 65 }, () => ({ label: "x", value: 1 })), [{ label: "\ud800", value: 1 }]])
    assert.throws(() => build(fixture.items, fixture.text, { current_facts: facts }))
})

test("DOM UTF-16 quote selection preserves emoji, combining marks and repeated quotes exactly", () => {
  const text = "🌡 e\u0301 🌡 e\u0301"
  assert.deepEqual(quoteFromSelection(text, 6, 11), { start: 5, end: 9, text: "🌡 e\u0301" })
  assert.throws(() => quoteFromSelection(text, 1, 2), /complete quote/)
  for (const bounds of [[0, 0], [-1, 2], [0, 99]]) assert.throws(() => quoteFromSelection(text, ...bounds))
})

test("display is identity-bound, validates facts again, and never upgrades references to review", () => {
  const draft = projected(), before = structuredClone(draft)
  assert.equal(operatorReferencesForDisplay(draft).status, "saved")
  assert.deepEqual(draft, before)
  for (const change of [d => d.revision_identity.content_revision++, d => d.operator_claim_reference_view.items[0].sources[0].fact.value = {},
    d => d.text = "changed", d => d.operator_claim_reference_view.items[0].sources[0].pointer = "__proto__"]) {
    const changed = structuredClone(draft); change(changed)
    assert.deepEqual(operatorReferencesForDisplay(changed), { status: "unavailable", items: [] })
  }
  const stale = structuredClone(draft); stale.review_context.two_bot.bundle.current_facts[0].value = 99
  assert.equal(projectOperatorClaimReferences(stale).status, "unavailable")
  const conflict = structuredClone(draft); conflict.revision_conflicts = [{}]
  assert.equal(projectOperatorClaimReferences(conflict).status, "unavailable")
  const malformed = structuredClone(draft); malformed.revision_identity = {}; malformed.operator_claim_reference_view.identity = {}
  assert.equal(operatorReferencesForDisplay(malformed).status, "unavailable")
})

test("component presents honest saved facts and accessible edit controls without link execution", () => {
  const draft = projected()
  const html = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft }))
  for (const phrase of ["Operator-selected source references", "do not establish scientific support", "Saved source label: Invented fixture", "Saved source type: Unknown", "Source scope: Unknown", "Not supplied", "false", "&lt;img"])
    assert.ok(html.includes(phrase), phrase)
  assert.ok(!html.includes("<img") && !html.includes("href="))
  const editing = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft, editing: true, items: fixture.items, onChange() {} }))
  for (const phrase of ["Saved references are hidden while editing", "Use selected quote", "Change reference 1", "Remove reference 1", "readOnly", "Select a quote from the current draft"])
    assert.ok(editing.includes(phrase), phrase)
  assert.ok(!editing.includes("Saved for this exact text"))
})

test("explicit retained source type, spatial scope and valid times are displayed without inventing an issue time", () => {
  const draft = projected()
  draft.review_context.two_bot.bundle = structuredClone(draft.review_context.two_bot.bundle)
  draft.review_context.two_bot.bundle.evidence = { evidence_type: "forecast", spatial_scope: "model_grid_point", issued_at: null,
    valid_start: "2032-01-02T00:00:00Z", valid_end: "2032-01-03T00:00:00Z" }
  draft.review_context.operator_claim_references = buildOperatorClaimReferences(draft.text, draft.review_context.two_bot.bundle, fixture.items)
  draft.revision_identity = draftIdentity(draft)
  draft.operator_claim_reference_view = projectOperatorClaimReferences(draft)
  const html = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft }))
  for (const value of ["Saved source type: forecast", "Source scope: model_grid_point", "Issue time: Unknown", "2032-01-02T00:00:00Z"])
    assert.ok(html.includes(value), value)
})
