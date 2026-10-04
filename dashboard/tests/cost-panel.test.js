import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { CostPanel, formatRecordedAmount, formatTokenRange } from "../app/components/CostPanel.js"
const render = props => renderToStaticMarkup(React.createElement(CostPanel, props))

test("missing costs render unavailable rather than a zero bill or enforced cap", () => {
  const output = render({})
  assert.match(output, /Actual bill unavailable/)
  assert.match(output, /Monthly usage evidence unavailable/)
  assert.match(output, /No valid observation dates/)
  assert.doesNotMatch(output, /\$0\.00|0 responses|progressbar|meter/)
  assert.match(output, /<details/)
  assert.match(output, /<summary>Cost coverage and missing charges/)
  assert.match(render({loading: true}), /Loading cost evidence/)
  assert.match(render({stale: true}), /Refresh failed · cost evidence unavailable/)
  assert.doesNotMatch(render({stale: true}), /showing the last loaded/)
})

test("range rounds outwards and preserves positive values below a cent", () => {
  assert.equal(formatTokenRange({min: "0.091409960", max: "0.103850930"}), "$0.09–$0.11")
  assert.equal(formatTokenRange({min: "0.000000030", max: "0.000000030"}), "$0.00000003")
  assert.equal(formatTokenRange({min: "0.000000001", max: "0.010000001"}), "$0.000000001–$0.02")
  assert.equal(formatTokenRange({min: "0.000000000", max: "0.000000000"}), "$0.00")
  assert.equal(formatTokenRange({min: "9600000.000140800", max: "9600000.000140800"}), "$9,600,000.0001408")
  for (const value of [null, {}, {min: "PRIVATE", max: "NaN"}, {min: "1.000000000", max: "0.000000000"}]) assert.equal(formatTokenRange(value), "Unavailable")
  assert.equal(formatRecordedAmount(0.00000003), "<$0.01")
  assert.equal(formatRecordedAmount(null), "Unavailable")
})

test("fresh pricing date is distinct from old usage; incomplete evidence and stale refresh are explicit", () => {
  const evidence = {recorded: {status: "inconsistent", month: "2026-10", priced_subtotal_usd: null}, scenario: {
    pricing_date: "2026-10-02", observation_period: {first: "2026-09-01T00:00:00.000Z", last: "2026-09-02T00:00:00.000Z"},
    token_subtotal_usd: {min: "0.001000000", max: "0.002000000"}, tokens: {prompt: 100, candidate: 20, thought: 300},
    truncated: true, invalid: true, eligible_records: 2, excluded_records: 3}}
  const markup = render({evidence, stale: true})
  for (const text of [/Refresh failed/, /Conflicting usage records/, /2026-10 month to date/, /snapshot: 2026-10-02/,
    /Observed: 2026-09-01 00:00 UTC to 2026-09-02 00:00 UTC/, /window is truncated/, /Invalid evidence/, /Eligible thinking tokens/, /Do not add it/, /does not bound account charges/]) assert.match(markup, text)
})

test("main page requests the named scenario through its existing dashboard fetch", () => {
  const source = readFileSync(new URL("../app/page.js", import.meta.url), "utf8")
  assert.match(source, /cost_scenario=\$\{encodeURIComponent\(COST_SCENARIO.scenario\)\}/)
  assert.match(source, /costEvidence: payload.costEvidence/)
  assert.match(source, /<CostPanel evidence=\{data\?\.costEvidence\} stale=\{Boolean\(refreshError\)\}/)
  assert.doesNotMatch(source, /fetch\(["']\/api\/usage/)
})
