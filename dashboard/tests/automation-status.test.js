import test from "node:test"
import assert from "node:assert/strict"

import {
  FAILING_CONCLUSIONS,
  dotColorForWorkflow,
  failingWorkflows,
  dotColorForSelfHeal,
} from "../lib/automation-status.js"

const NOW = Date.parse("2026-06-17T16:00:00Z")

test("FAILING_CONCLUSIONS covers the three red states", () => {
  assert.ok(FAILING_CONCLUSIONS.has("failure"))
  assert.ok(FAILING_CONCLUSIONS.has("timed_out"))
  assert.ok(FAILING_CONCLUSIONS.has("startup_failure"))
  assert.ok(!FAILING_CONCLUSIONS.has("success"))
  assert.ok(!FAILING_CONCLUSIONS.has("cancelled"))
})

test("a failed run is RED, not yellow (the regression that hid 5 red days)", () => {
  assert.equal(
    dotColorForWorkflow({ state: "active", last_run_conclusion: "failure" }),
    "red",
  )
})

test("timed_out and startup_failure are RED", () => {
  assert.equal(dotColorForWorkflow({ state: "active", last_run_conclusion: "timed_out" }), "red")
  assert.equal(
    dotColorForWorkflow({ state: "active", last_run_conclusion: "startup_failure" }),
    "red",
  )
})

test("a successful run is green", () => {
  assert.equal(
    dotColorForWorkflow({ state: "active", last_run_conclusion: "success" }),
    "green",
  )
})

test("a fetch error is RED", () => {
  assert.equal(dotColorForWorkflow({ error: "boom" }), "red")
})

test("manually disabled is gray", () => {
  assert.equal(dotColorForWorkflow({ state: "disabled_manually" }), "gray")
})

test("a cancelled run on an active workflow is not red", () => {
  assert.notEqual(
    dotColorForWorkflow({ state: "active", last_run_conclusion: "cancelled" }),
    "red",
  )
})

test("missing workflow is gray", () => {
  assert.equal(dotColorForWorkflow(null), "gray")
})

test("failingWorkflows returns only the red ones", () => {
  const status = {
    workflows: [
      { name: "theheat-bot", state: "active", last_run_conclusion: "success" },
      { name: "voice-regression", state: "active", last_run_conclusion: "failure" },
      { name: "refresh-thresholds", state: "active", last_run_conclusion: "success" },
      { name: "source-health-sentinel", error: "GH down" },
    ],
  }
  const failing = failingWorkflows(status).map((w) => w.name)
  assert.deepEqual(failing, ["voice-regression", "source-health-sentinel"])
})

test("failingWorkflows is empty when all green", () => {
  const status = {
    workflows: [
      { name: "theheat-bot", state: "active", last_run_conclusion: "success" },
      { name: "voice-regression", state: "active", last_run_conclusion: "success" },
    ],
  }
  assert.deepEqual(failingWorkflows(status), [])
})

test("failingWorkflows tolerates missing status", () => {
  assert.deepEqual(failingWorkflows(null), [])
  assert.deepEqual(failingWorkflows({}), [])
})

test("self-heal dot: a stale heartbeat is RED (the dead watcher is loud)", () => {
  const beacon = { run_at: "2026-06-15T00:00:00Z", outcome: "ok" } // ~64h stale
  assert.equal(dotColorForSelfHeal(beacon, NOW), "red")
})

test("self-heal dot: a fresh ok heartbeat is green", () => {
  const beacon = { run_at: "2026-06-17T12:00:00Z", outcome: "ok" } // 4h fresh
  assert.equal(dotColorForSelfHeal(beacon, NOW), "green")
})

test("self-heal dot: a fresh error heartbeat is yellow", () => {
  const beacon = { run_at: "2026-06-17T12:00:00Z", outcome: "error" }
  assert.equal(dotColorForSelfHeal(beacon, NOW), "yellow")
})

test("self-heal dot: a missing beacon is gray (not configured yet, no rollout noise)", () => {
  assert.equal(dotColorForSelfHeal(null, NOW), "gray")
  assert.equal(dotColorForSelfHeal({}, NOW), "gray")
})
