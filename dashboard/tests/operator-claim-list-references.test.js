/** Exact list-element source references are byte-identical between Python and JS (invented PM2.5). */
import assert from "node:assert/strict"
import test from "node:test"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { fingerprint } from "../lib/draft-revisions.js"
import { buildOperatorClaimReferences, readOperatorClaimReferences } from "../lib/operator-claim-references.js"
import { referenceChoices, resolveReference, retainedClaimFacts } from "../lib/operator-claim-reference-input.js"

const root = path.resolve(process.cwd(), "..")
const code = `
import json,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.editorial.operator_claim_references import build_operator_claim_references
from tests.gist_hazard_helpers import pm25_bundle
bundle=pm25_bundle()
text='Invented forecast near the model grid point 27.75N.'
grid=[i for i,f in enumerate(bundle['current_facts']) if isinstance(f['value'],list)][0]
items=[{'claim':{'start':0,'end':8,'text':text[:8]},'sources':[{'pointer':'/current_facts/0'},{'pointer':'/current_facts/%d/value/0'%grid}]}]
print(json.dumps(dict(raw_bundle=json.dumps(bundle),text=text,grid=grid,items=items,
  envelope=build_operator_claim_references(text,bundle,items))))
`
const value = (() => {
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", code], { cwd: root, encoding: "utf8", timeout: 60000,
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented", LC_ALL: "C", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
})()

test("Python and JS build the same element-reference envelope and both read it back", () => {
  const bundle = JSON.parse(value.raw_bundle)
  const built = buildOperatorClaimReferences(value.text, bundle, value.items)
  assert.equal(fingerprint(built), fingerprint(value.envelope))
  assert.deepEqual(readOperatorClaimReferences(value.text, bundle, value.envelope), built)
  const changed = structuredClone(bundle)
  changed.current_facts[value.grid].value[0] += 0.25
  assert.equal(readOperatorClaimReferences(value.text, changed, value.envelope), null)
})

test("the picker offers each list element separately and never the whole list as a scalar", () => {
  const bundle = JSON.parse(value.raw_bundle), facts = retainedClaimFacts(bundle)
  const choices = referenceChoices(facts), grid = value.grid
  assert.equal(choices.filter(row => row.pointer.startsWith(`/current_facts/${grid}`)).length, facts[grid].value.length)
  assert.equal(choices.some(row => row.pointer === `/current_facts/${grid}`), false)
  assert.deepEqual(resolveReference(facts, `/current_facts/${grid}/value/1`).view,
    { label: `${facts[grid].label}[1]`, value: facts[grid].value[1], unit: facts[grid].unit ?? null })
  for (const pointer of [`/current_facts/${grid}`, `/current_facts/${grid}/value/9`, "/current_facts/0/value/0", "/current_facts/01"])
    assert.throws(() => resolveReference(facts, pointer))
})
