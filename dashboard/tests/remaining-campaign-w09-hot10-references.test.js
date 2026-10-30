/** W09.1 operator quote references for a qualified Hot10 bulletin (invented catalogue rows).
 * Python builds the bundle and envelope; JS must agree byte-for-byte, offer each ranked row
 * as one exact element, show it readably in the real editor component, and name the exact
 * saved fact when references are unavailable. Python runs with sockets trapped.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { OperatorClaimReferences } from "../app/components/OperatorClaimReferences.js"
import { fingerprint, invalidateText, projectDraft } from "../lib/draft-revisions.js"
import { buildOperatorClaimReferences, readOperatorClaimReferences } from "../lib/operator-claim-references.js"
import { factValueText, operatorReferencesForDisplay, referenceChoices, resolveReference, retainedClaimFacts,
  sameFactValue, unavailableFactReason } from "../lib/operator-claim-reference-input.js"

const root = fileURLToPath(new URL("../..", import.meta.url))  // repository root, independent of cwd
const code = `
import json,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.editorial.operator_claim_references import build_operator_claim_references
from tests.gist_hazard_helpers import saved_state
draft=saved_state('hot10')['drafts'][0]
bundle=draft['review_context']['two_bot']['bundle']
ranking=[i for i,f in enumerate(bundle['current_facts']) if f['label']=='ranking'][0]
text=draft['text']
items=[{'claim':{'start':0,'end':8,'text':text[:8]},'sources':[{'pointer':'/current_facts/0'},{'pointer':'/current_facts/%d/value/3'%ranking}]}]
print(json.dumps(dict(raw_draft=json.dumps(draft,ensure_ascii=False),ranking=ranking,items=items,
  envelope=build_operator_claim_references(text,bundle,items))))
`
const value = (() => {
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", code], { cwd: root, encoding: "utf8", timeout: 60000,
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented", LC_ALL: "C", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
})()
const draft = () => JSON.parse(value.raw_draft)

test("Python and JS build the same ranked-row envelope; any row change or reorder invalidates it", () => {
  const d = draft(), bundle = d.review_context.two_bot.bundle
  const built = buildOperatorClaimReferences(d.text, bundle, value.items)
  assert.equal(fingerprint(built), fingerprint(value.envelope))
  assert.deepEqual(readOperatorClaimReferences(d.text, bundle, value.envelope), built)
  const changed = structuredClone(bundle)
  changed.current_facts[value.ranking].value[3].forecast_high_c += 0.1
  assert.equal(readOperatorClaimReferences(d.text, changed, value.envelope), null)
  const reordered = structuredClone(bundle), rows = reordered.current_facts[value.ranking].value;
  [rows[2], rows[3]] = [rows[3], rows[2]]
  assert.equal(readOperatorClaimReferences(d.text, reordered, value.envelope), null)
})

test("the picker offers each of the ten ranked rows once, never the whole list or the empty rank-change list", () => {
  const bundle = draft().review_context.two_bot.bundle, facts = retainedClaimFacts(bundle)
  const choices = referenceChoices(facts)
  const rows = choices.filter(row => row.pointer.startsWith(`/current_facts/${value.ranking}/`))
  assert.equal(rows.length, 10)
  assert.deepEqual(rows[0].fact, { label: "ranking[0]", value: facts[value.ranking].value[0], unit: null })
  const changes = facts.findIndex(fact => fact.label === "rank_changes")
  assert.deepEqual(facts[changes].value, [])
  assert.equal(choices.some(row => row.pointer.startsWith(`/current_facts/${changes}`)), false)
  for (const pointer of [`/current_facts/${value.ranking}`, `/current_facts/${value.ranking}/value/10`, `/current_facts/${changes}/value/0`])
    assert.throws(() => resolveReference(facts, pointer))
  assert.match(factValueText(facts[value.ranking].value[0]), /^rank 1 · city .+ · departure c /)
  assert.equal(sameFactValue(facts[value.ranking].value[0], structuredClone(facts[value.ranking].value[0])), true)
  assert.equal(sameFactValue(facts[value.ranking].value[0], { ...facts[value.ranking].value[0], rank: 2 }), false)
})

test("a saved row reference survives the real edit path and reads back in the editor; editing the text clears it", () => {
  const d = draft()
  invalidateText(d, d.text, value.items)
  const projected = projectDraft(d)
  assert.equal(projected.operator_claim_reference_view.status, "saved")
  assert.equal(operatorReferencesForDisplay(projected).status, "saved")
  const html = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft: projected }))
  assert.match(html, /Saved for this exact text and source snapshot/)
  assert.match(html, /ranking\[3\]: rank 4 · city /)
  assert.doesNotMatch(html, /\[object Object\]/)
  const edited = structuredClone(d)
  invalidateText(edited, `${d.text} Updated.`)
  assert.equal(Object.hasOwn(edited.review_context, "operator_claim_references"), false)
  assert.equal(projectDraft(edited).operator_claim_reference_view.status, "missing")
})

test("when facts cannot be referenced the editor names the exact saved fact instead of a generic refusal", () => {
  const d = draft()
  d.review_context.two_bot.bundle.current_facts[value.ranking].value[0] = { rank: 1, nested: { city: "Invented" } }
  assert.throws(() => retainedClaimFacts(d.review_context.two_bot.bundle))
  assert.match(unavailableFactReason(d.review_context.two_bot.bundle), /“ranking” has entries that are not plain values or flat rows/)
  const html = renderToStaticMarkup(React.createElement(OperatorClaimReferences, { draft: projectDraft(d), editing: true, onChange: () => {} }))
  assert.match(html, /Saved source facts are unavailable; refresh before linking a quote\. Saved fact “ranking” has entries/)
  assert.doesNotMatch(html, /Use selected quote/)
})
