/** Real canonical invented AWC input through the ordinary projection and component. */
import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ClaimEvidence } from "../app/components/ClaimEvidence.js"
import { claimEvidenceForDisplay } from "../lib/saved-claim-evidence.js"
import { initializeRevision, projectDraft } from "./helpers/review-policy.js"
import { pythonJSON } from "./helpers/gist-hazard-harness.js"

const originals = new Map()
function draft(variant = "default") {
  if (!originals.has(variant)) originals.set(variant, pythonJSON(`
import json,sys
from pytest import MonkeyPatch
from src.data import awc_observed
from tests.test_awc_observed import NOW, install, reports
from tests.gist_hazard_helpers import saved_state
value=json.load(sys.stdin)
with MonkeyPatch.context() as m:
    if value['variant']=='zero':
        rows=reports();rows[0][0]='TAAA 151200Z 00/M25';rows[0][5]='0'
        rows[1][0]='TBBB 151200Z 65/20';rows[1][5]='65';install(m,rows=rows)
    else: install(m)
    b=awc_observed.build_bundle(awc_observed.nominate(now=NOW),now=NOW).to_dict()
    print(json.dumps(saved_state('awc',bundle=b)['drafts'][0],ensure_ascii=False))
`, { variant }))
  return initializeRevision(structuredClone(originals.get(variant)))
}
const source = d => claimEvidenceForDisplay(projectDraft(d)).source
const pointFacts = d => d.review_context.two_bot.bundle.current_facts.find(x => x.label === "observed_airports").value
const rawPoints = d => d.review_context.two_bot.bundle.raw_signal_dump.evidence.points

test("canonical airport source facts become bounded scalar display rows without changing authority", () => {
  const d = draft(), before = structuredClone(d), view = source(d)
  assert.equal(view.status, "saved")
  for (const point of pointFacts(d)) {
    assert.ok(view.facts.some(f => String(f.value).includes(point.airport)))
    assert.ok(view.facts.some(f => String(f.value).includes(point.station_id)))
    assert.ok(view.facts.some(f => String(f.value).includes(point.country)))
    assert.ok(view.facts.some(f => f.value === point.temperature_c && f.unit === "°C"))
    assert.ok(view.facts.some(f => f.value === point.valid_time))
  }
  assert.ok(view.facts.every(f => f.value === null || ["string", "number", "boolean"].includes(typeof f.value)))
  assert.deepEqual(d, before)
  const html = renderToStaticMarkup(React.createElement(ClaimEvidence, { draft: projectDraft(d) }))
  assert.ok(html.includes("Saved source facts") && html.includes("Norway") && html.includes("Chile"))
  assert.ok(!html.includes("source facts are incomplete"))
  assert.ok(html.includes("not per-claim citations or a new source check"))
  assert.ok(!html.includes("<input") && !html.includes("<form"))
})

test("zero and exact observation time are retained, without inferring model claims", () => {
  const d = draft("zero"), view = source(d)
  assert.equal(view.status, "saved")
  assert.ok(view.facts.some(f => f.value === 0 && f.unit === "°C"))
  assert.equal(view.when, d.review_context.two_bot.bundle.when)
  assert.equal(claimEvidenceForDisplay(projectDraft(d)).claims.status, "missing")
  assert.equal(claimEvidenceForDisplay(projectDraft(d), { editing: true }).claims.status, "editing")
})

test("incomplete, conflicting and unsupported airport fact shapes remain unreadable without partial display", () => {
  const cases = [
    d => { d.type = "fire" },
    d => { d.review_context.two_bot.bundle.event_id = "wrong" },
    d => { pointFacts(d).pop() },
    d => { pointFacts(d).push(structuredClone(pointFacts(d)[0])) },
    d => { pointFacts(d)[0].country = "Other country" },
    d => { pointFacts(d)[1].valid_time = "2026-11-15T11:00:00Z" },
    d => { pointFacts(d)[0].temperature_c = true; rawPoints(d)[0].temperature_c = true },
    d => { pointFacts(d)[0].airport = "x".repeat(2049); rawPoints(d)[0].airport = "x".repeat(2049) },
    d => { pointFacts(d)[0].unexpected = {}; rawPoints(d)[0].unexpected = {} },
    d => { delete d.review_context.two_bot.bundle.raw_signal_dump.evidence },
    d => { d.review_context.two_bot.bundle.raw_signal_dump.report_schema = "other-product" },
    d => { pointFacts(d)[1] = null },
    d => { pointFacts(d)[0].station_id = rawPoints(d)[0].station_id = ["TAAA"] },
    d => { pointFacts(d)[0].country_code = rawPoints(d)[0].country_code = ["NO"] },
    d => { pointFacts(d)[0].valid_time = rawPoints(d)[0].valid_time = "2026-11-31T12:00:00Z" },
    d => { d.review_context.two_bot.bundle.current_facts.push({ label: "extra", value: 1 }) },
    d => { d.review_context.two_bot.bundle.current_facts[1].value = "13:00 UTC" },
    d => { d.review_context.two_bot.bundle.current_facts[2].value = "16 Nov" },
  ]
  for (const change of cases) {
    const d = draft(); change(d)
    const result = source(d)
    assert.equal(result.status, "unreadable", String(change))
    assert.deepEqual(result.facts, [])
  }
})


test("invalid nested generic facts stay invalid and the airport projection remains inert text", () => {
  const d = draft(), b = d.review_context.two_bot.bundle
  b.signal_kind = d.type = "temperature"
  assert.equal(source(d).status, "unreadable")
  const zero = draft("zero"), projected = projectDraft(zero)
  projected.claim_evidence.source.facts[0].value = '<img src=x onerror="invalid()">'
  const html = renderToStaticMarkup(React.createElement(ClaimEvidence, { draft: projected }))
  assert.ok(html.includes("&lt;img") && !html.includes("<img"))
  assert.ok(!html.includes("href="))
  assert.equal(projected.review_status, "needs_revalidation")
})
