import test from "node:test"
import assert from "node:assert/strict"
import { buildRuntimeConfig, dashboardDeployment, summarizeSourceAttempts } from "../lib/runtime-inventory.js"

const now = Date.parse("2026-09-09T03:00:00Z")
function run(at = "2026-09-09T02:00:00Z") {
  return { run_id: "run1", started_at: at, runtime_inventory: {
    schema_version: 1, captured_at: at, mode: "alerts", git_sha: "a".repeat(40), version: "0.9.108.3",
    state_backend: "gist", models: { writer: "actual-bot-writer", critic: "actual-critic", safety: "actual-safety" },
    flags: { autoship_on_critic_pass: false, writer_samples: 1, API_KEY: "do-not-project" },
    credentials_present: { anthropic: true, twitter: false, API_KEY: "do-not-project" },
    capabilities: { claim_extraction: "inactive" },
  } }
}

test("missing runtime never falls back to dashboard model settings", () => {
  const before = process.env.THEHEAT_WRITER_MODEL
  process.env.THEHEAT_WRITER_MODEL = "dashboard-only"
  try {
    const result = buildRuntimeConfig({}, { now })
    assert.equal(result.status, "unknown")
    assert.equal(result.writer_model, null)
    assert.deepEqual(result.flags, {})
  } finally {
    if (before === undefined) delete process.env.THEHEAT_WRITER_MODEL
    else process.env.THEHEAT_WRITER_MODEL = before
  }
})

test("bot inventory projects actual models and typed allowlisted flags without secrets", () => {
  const result = buildRuntimeConfig({ run_history: [run()] }, { now })
  assert.equal(result.status, "recorded")
  assert.equal(result.writer_model, "actual-bot-writer")
  assert.equal(result.critic_model, "actual-critic")
  assert.equal(result.safety_model, "actual-safety")
  assert.equal(result.claim_extract_model, null)
  assert.equal(result.flags.autoship_on_critic_pass, false)
  assert.equal(result.credentials_present.twitter, false)
  assert.equal(result.age_hours, 1)
  assert.equal(JSON.stringify(result).includes("do-not-project"), false)
})

test("stale, newer missing, unsupported and future reports cannot look current", () => {
  assert.equal(buildRuntimeConfig({ run_history: [run("2026-09-08T02:00:00Z")] }, { now }).status, "stale")
  assert.equal(buildRuntimeConfig({ run_history: [run(), { started_at: "2026-09-09T02:30:00Z" }] }, { now }).writer_model, null)
  assert.equal(buildRuntimeConfig({ run_history: [run("2026-09-10T02:00:00Z")] }, { now }).status, "unknown")
  const unsupported = run()
  unsupported.runtime_inventory.schema_version = 9
  assert.equal(buildRuntimeConfig({ run_history: [unsupported] }, { now }).status, "unknown")
  const malformed = run()
  malformed.runtime_inventory.captured_at = "2026-02-30T02:00:00Z"
  assert.equal(buildRuntimeConfig({ run_history: [malformed] }, { now }).status, "unknown")
  malformed.runtime_inventory.captured_at = "2026-09-09T01:00:00Z"
  assert.equal(buildRuntimeConfig({ run_history: [malformed] }, { now }).status, "unknown", "snapshot cannot predate its invocation")
})

test("dashboard deployment identity stays separate from bot inventory", () => {
  assert.deepEqual(dashboardDeployment({ VERCEL_GIT_COMMIT_SHA: "b".repeat(40), VERCEL_ENV: "production", SECRET: "secret" }), {
    git_sha: "b".repeat(40), environment: "production",
  })
  assert.equal(dashboardDeployment({ VERCEL_GIT_COMMIT_SHA: "bad" }).git_sha, null)
})

test("cadence skips and absent source statuses are never successful attempts", () => {
  assert.deepEqual(summarizeSourceAttempts([{ status: "skipped" }, {}]), {
    succeeded: 0, skipped: 1, active: 0, unknown: 1, success_rate: null,
  })
  assert.equal(summarizeSourceAttempts([{ status: "skipped" }, { status: "failed" }, { status: "success" }]).success_rate, 0.5)
})
