import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const output = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.ghcn_fetch_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(output.status, 0, output.stderr)
const fixtures = JSON.parse(output.stdout), key = "open_meteo_extreme_signals"
const copy = name => structuredClone(fixtures[name])
const row = state => state.run_history[0].sources[0]
const metrics = state => row(state).details.pipeline_metrics ?? row(state).details.ghcn_pipeline_metrics
const projected = state => buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" }).sources.find(s => s.source === key).outcome

test("actual HTTP and transport outcomes reach the source readout without becoming zero weather", () => {
  for (const [name, expected] of [["404", /30 HTTP 404/], ["401", /30 HTTP 401/], ["403", /30 HTTP 403/],
    ["429", /30 HTTP 429/], ["503", /30 HTTP 5xx/], ["timeout", /30 timeouts/], ["connection", /30 connection errors/]]) {
    const state = copy(name), before = structuredClone(state), out = projected(state)
    assert.equal(out.state, "ghcn_fetch_unavailable")
    assert.match(out.label, /No GHCN diff payload returned/)
    assert.match(out.detail, /30 client calls/)
    assert.match(out.detail, expected)
    assert.doesNotMatch(JSON.stringify(out), /invented-private-detail|secret\.invalid|token=invented|no extreme weather|healthy feed/i)
    assert.deepEqual(state, before)
  }
})

test("returned bodies retain the separate real parsing and station-day denominator", () => {
  const out = projected(copy("payload"))
  assert.match(out.detail, /3 client calls; 3 payloads returned/)
  assert.match(out.detail, /Saved GHCN intake:/)
  assert.match(out.detail, /1 station-day retained/)
  assert.notEqual(out.state, "ghcn_fetch_unavailable")
})

test("missing, stale, contradictory or unbound acquisition facts remain unknown", () => {
  const changes = [
    m => { delete m.diff_fetch },
    m => { m.diff_fetch.schema_version = 2 },
    m => { m.diff_fetch.scope = "wire_requests" },
    m => { m.diff_fetch.window_day = "2026-11-20" },
    m => { m.diff_fetch.target_count = 2 },
    m => { m.diff_fetch.get_calls = 31 },
    m => { m.diff_fetch.counts.http_404 = "30" },
    m => { m.diff_fetch.counts.payload_returned = 1 },
    m => { m.diff_fetch.counts.http_404 = -1 },
    m => { m.diff_fetch.counts.extra = "invented-private-detail" },
    m => { m.diff_fetch.extra = "invented-private-detail" },
    m => { m.diff_missing_dates = ["2026-11-20", "2026-11-20", "2026-11-20"] },
    m => { m.diff_fetch_failed = 0 },
    m => { m.stations_with_obs = 1 },
  ]
  for (const change of changes) {
    const state = copy("404")
    change(metrics(state))
    const out = projected(state)
    assert.equal(out.state, "ghcn_intake_unavailable")
    assert.doesNotMatch(JSON.stringify(out), /30 client calls|invented-private-detail|0 station-days retained/)
  }
  const newer = copy("404")
  newer.source_health[key].runs.at(-1).ts = "2026-11-21T12:01:30Z"
  assert.equal(projected(newer).state, "ghcn_intake_unavailable")
  const duplicate = copy("404")
  duplicate.run_history[0].sources.push(structuredClone(row(duplicate)))
  assert.equal(projected(duplicate).state, "ghcn_intake_unavailable")
})

test("old useful intakes and recorded checker rejection retain their original meaning", () => {
  const old = copy("payload")
  delete metrics(old).diff_fetch
  assert.match(projected(old).detail, /1 station-day retained/)
  assert.doesNotMatch(projected(old).detail, /client calls/)
  const rejected = copy("payload")
  rejected.suppressions = [{ source: key, stage: "critic" }]
  assert.equal(projected(rejected).state, "writer_or_check_rejection")
  assert.match(projected(rejected).detail, /Saved GHCN intake:/)
})
