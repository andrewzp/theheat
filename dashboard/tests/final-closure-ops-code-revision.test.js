import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { codeRevisionEvidence } from "../lib/runtime-inventory.js"
import { ProductHealthPanel } from "../app/components/ProductHealthPanel.js"

const DEPLOYED = "a".repeat(40)
const OLDER = "b".repeat(40)
const NOW = Date.parse("2026-11-02T12:00:00Z")
const run = (id, at, gitSha, extra = {}) => ({
  id, started_at: at, ...extra,
  runtime_inventory: { schema_version: 1, captured_at: at, git_sha: gitSha, mode: "alerts", flags: {} },
})

test("deployed code differing from the last bot report is never presented as a run on the deployed code", () => {
  const state = { run_history: [run("r2", "2026-11-02T10:00:00Z", OLDER), run("r1", "2026-11-01T10:00:00Z", OLDER)] }
  const evidence = codeRevisionEvidence(state, { deployment: { git_sha: DEPLOYED }, now: NOW })
  assert.equal(evidence.status, "differs")
  assert.equal(evidence.dashboard_git_sha, DEPLOYED)
  assert.equal(evidence.last_report.git_sha, OLDER)
  assert.deepEqual(evidence.deployed_revision_pipeline_run, { status: "not_observed", at: null, run_id: null })
  assert.match(evidence.reason, /does not show that the bot has run the deployed code/)
})

test("a configuration-only report on the deployed code matches without establishing a pipeline run", () => {
  const state = { run_history: [run("config-1-1", "2026-11-02T11:00:00Z", DEPLOYED, { configuration_only: true })] }
  const evidence = codeRevisionEvidence(state, { deployment: { git_sha: DEPLOYED }, now: NOW })
  assert.equal(evidence.status, "matches")
  assert.equal(evidence.last_report.kind, "configuration_only")
  assert.equal(evidence.deployed_revision_pipeline_run.status, "not_observed")
  assert.match(evidence.reason, /no retained pipeline run on it is recorded/)
})

test("an older pipeline run on the deployed code is found even after a newer configuration report", () => {
  const state = { run_history: [
    run("config-9-1", "2026-11-02T11:00:00Z", DEPLOYED, { configuration_only: true }),
    run("r5", "2026-11-02T09:00:00Z", DEPLOYED),
  ] }
  const evidence = codeRevisionEvidence(state, { deployment: { git_sha: DEPLOYED.toUpperCase() }, now: NOW })
  assert.equal(evidence.status, "matches")
  assert.deepEqual(evidence.deployed_revision_pipeline_run, { status: "observed", at: "2026-11-02T09:00:00.000Z", run_id: "r5" })
})

test("missing, malformed, future or inverted evidence stays unknown rather than borrowing another revision", () => {
  assert.equal(codeRevisionEvidence({}, { deployment: { git_sha: DEPLOYED }, now: NOW }).status, "unknown")
  assert.equal(codeRevisionEvidence({ run_history: [run("r", "2026-11-02T10:00:00Z", OLDER)] }, { deployment: null, now: NOW }).status, "unknown")
  const future = codeRevisionEvidence({ run_history: [run("r", "2026-11-03T10:00:00Z", DEPLOYED)] }, { deployment: { git_sha: DEPLOYED }, now: NOW })
  assert.equal(future.status, "unknown")
  assert.equal(future.last_report, null)
  const inverted = { run_history: [{ id: "r", started_at: "2026-11-02T10:00:00Z",
    runtime_inventory: { schema_version: 1, captured_at: "2026-11-02T09:00:00Z", git_sha: DEPLOYED } }] }
  assert.equal(codeRevisionEvidence(inverted, { deployment: { git_sha: DEPLOYED }, now: NOW }).status, "unknown")
  const noSha = codeRevisionEvidence({ run_history: [run("r", "2026-11-02T10:00:00Z", "not-a-sha")] }, { deployment: { git_sha: DEPLOYED }, now: NOW })
  assert.equal(noSha.status, "unknown")
  assert.equal(noSha.deployed_revision_pipeline_run.status, "not_observed")
})

test("panel shows the revision comparison and never equates an empty queue with worldwide coverage", () => {
  const health = { milestones: {}, queue: { waiting_count: 0, unresolved_publish_count: 0 }, writer: {}, metrics: {} }
  const codeRevision = codeRevisionEvidence({ run_history: [run("r", "2026-11-02T10:00:00Z", OLDER)] }, { deployment: { git_sha: DEPLOYED }, now: NOW })
  const markup = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health, config: { status: "recorded" }, codeRevision }))
  assert.match(markup, /data-code-revision="differs"/)
  assert.match(markup, /Code revision · differs/)
  assert.match(markup, /empty queue does not show that nothing worth covering happened worldwide/)
  const absent = renderToStaticMarkup(React.createElement(ProductHealthPanel, { health, config: { status: "recorded" } }))
  assert.doesNotMatch(absent, /Code revision/)
})
