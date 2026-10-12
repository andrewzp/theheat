import test from "node:test"
import assert from "node:assert/strict"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ReportsForReview, { ReportDetail, reportCommand } from "../app/components/ReportsForReview.js"

test("actual report component opens evidence review without promising a draft", () => {
  const html = renderToStaticMarkup(createElement(ReportsForReview, { readOnly: true }))
  assert.match(html, /Reports needing evidence/)
  assert.match(html, /for="report-choice"/)
  assert.match(html, /aria-live="polite"/)
  assert.match(html, /Open evidence/)
  assert.doesNotMatch(html, /Request draft/)
})

test("report command is exact references only and cannot carry claims or verdicts", () => {
  const report = { lineage_id: "fixture:report", report_sha256: "a".repeat(64), expected_policy_sha256: "b".repeat(64),
    episode_reference: null, facts: "untrusted", human_reviewed: true, cost: 0 }
  const body = reportCommand(report, new Date("2026-10-11T12:00:00Z"))
  assert.equal(body.action, "open_report_evidence")
  assert.deepEqual(body.targets, [])
  assert.deepEqual(Object.keys(body.payload).sort(), ["episode_reference", "expected_policy_sha256", "lineage_id", "report_sha256"])
  assert.equal(body.expires_at, "2026-10-11T13:00:00.000Z")
})

test("source wording is escaped, translation remains unreviewed and unknown time stays unknown", () => {
  const report = { claims: [{ claim_id: "claim1", summary: "Invented report", kind: "forecast", attribution: "Invented agency",
    original_language: "pt", excerpts: [{ text: '<script>fetch("https://invalid.test")</script>' }],
    translation: { text: "Invented interpretation", status: "unreviewed" }, times: {}, holds: ["translation_review_pending"] }] }
  const html = renderToStaticMarkup(createElement(ReportDetail, { report }))
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /Translation \(unreviewed\)/)
  assert.match(html, /Unknown/)
  assert.match(html, /<details><summary>Original source wording/)
})
