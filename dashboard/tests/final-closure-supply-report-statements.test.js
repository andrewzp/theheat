// A6: the editor shows each report statement the brief and checks used, with its
// exact quote, attribution, source date, language/translation decision and source
// revision. The draft fixture is produced by src/editorial/report_supply.py
// (tests/final_closure/test_supply_report_statements.py asserts it).
import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ReportStatementEvidence } from "../app/components/ReportStatementEvidence.js"
import { reportStatementsForDisplay } from "../lib/report-statement-evidence.js"

const fixture = JSON.parse(readFileSync(new URL("../../tests/final_closure/fixtures/supply_report_statements.json", import.meta.url)))
const render = draft => renderToStaticMarkup(React.createElement(ReportStatementEvidence, { draft }))
const clone = value => JSON.parse(JSON.stringify(value))

test("the editor shows quote, attribution, date, translation decision and source revision", () => {
  const view = reportStatementsForDisplay(fixture.draft)
  assert.equal(view.status, "present")
  assert.deepEqual(view.statements.map(row => row.claim_id), ["c1", "c2"])
  const html = render(fixture.draft)
  assert.match(html, /“120 households were evacuated” — Ficta Civil Protection/)
  assert.match(html, /“Las carreteras siguen cerradas” — Ficta municipality/)
  assert.match(html, /Reviewed translation: Roads remain closed/)
  assert.match(html, /Human-reviewed \(editor-note-invented-7\)/)
  assert.match(html, /2026-10-28/)
  assert.match(html, /retained text 073bd1493d68…/)
  assert.match(html, /never independent confirmation/)
  assert.match(html, /The writer reported citing a report statement/)
})

test("an altered or partial statement is unreadable, never partially shown", () => {
  const changed = clone(fixture.draft)
  changed.review_context.two_bot.bundle.human_impact[0].value = "200 households were evacuated"
  assert.equal(reportStatementsForDisplay(changed).status, "unreadable")
  const diverged = clone(fixture.draft)
  diverged.review_context.two_bot.human_impact = diverged.review_context.two_bot.human_impact.slice(1)
  assert.equal(reportStatementsForDisplay(diverged).status, "unreadable")
  const unreviewed = clone(fixture.draft)
  for (const rows of [unreviewed.review_context.two_bot.bundle.human_impact, unreviewed.review_context.two_bot.human_impact]) {
    rows[1].translation.state = "translation_unreviewed"
  }
  assert.equal(reportStatementsForDisplay(unreviewed).status, "unreadable")
  assert.match(render(changed), /do not rely on them/)
  assert.equal(render({ review_context: {} }), "")
})
