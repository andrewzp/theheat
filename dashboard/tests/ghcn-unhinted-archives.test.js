import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c",
  "import json; from dashboard.tests.fixtures.ghcn_discovery_producer import produce; print(json.dumps({p: produce('error400_sampled', provider=p) for p in ['ghcn','both_global']} | {'failed': produce('error400_sampled', archive_failure=True), 'one': produce('error400_sampled', archive_limit=1)}))"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(result.status, 0, result.stderr)
const fixtures = JSON.parse(result.stdout)
const metrics = s => s.run_history[0].sources[0].details.pipeline_metrics
  ?? s.run_history[0].sources[0].details.ghcn_pipeline_metrics
const outcome = s => buildSourceHealthPayload(s, { asOf: "2026-11-21T12:02:00Z" })
  .sources.find(v => v.source === "open_meteo_extreme_signals").outcome

test("real collector and durable JSON distinguish sampled original archives from failed lookup", () => {
  for (const value of [fixtures.ghcn, fixtures.both_global]) {
    const before = structuredClone(value), m = metrics(value), out = outcome(value)
    assert.equal(out.state, "supplying")
    assert.equal(out.status, "degraded")
    assert.equal(m.station_discovery.http_status, 400)
    assert.equal(m.station_discovery.nominated_stations, 0)
    assert.equal(m.station_archive_intake.schema_version, 3)
    assert.equal(m.archive_verification_attempted, 2)
    assert.equal(value.request_count, 33)
    assert.match(out.detail, /sampled verified station archives: 2 checked/)
    assert.match(out.detail, /2 accepted daily values; 1 station-day/)
    assert.match(out.detail, /Unhinted archive sample: 1 of 1 cached active stations/)
    assert.match(out.detail, /reply unavailable \(HTTP 400\)/)
    assert.match(out.detail, /Diff acquisition remains unavailable/)
    assert.doesNotMatch(out.detail, /source recovered|healthy|49/)
    assert.deepEqual(value, before)
  }
})

test("sample scope cannot be lent to missing, inconsistent, stale or relabelled evidence", async t => {
  const changes = [
    m => { delete m.station_discovery },
    m => { m.station_discovery.http_status = 200 },
    m => { m.station_discovery.http_status = 503 },
    m => { m.station_discovery.nominated_stations = 1 },
    m => { m.station_archive_intake.sampling_source = "provider_verified" },
    m => { m.station_archive_intake.sampling_pool_stations = 0 },
    m => { m.station_archive_intake.sampling_pool_stations = true },
    m => { m.station_archive_intake.sampling_pool_stations = 2 },
    m => { delete m.station_archive_intake.sampling_pool_stations },
    m => { m.station_archive_intake.scope = "verified_selected_station_archives" },
    m => { m.station_archive_intake.schema_version = 2 },
    m => { m.station_archive_intake.retrieved_at = "2026-11-20T12:00:00Z" },
    m => { m.archive_selection.candidates.pool_stations = 2 },
    m => { m.archive_selection.tracked.reserved_slots = 0 },
    m => { m.archive_selection.candidates.verified_stations = 2 },
    m => { m.station_archive_intake.counts.accepted_values = 0 },
    m => { m.diff_fetch.counts.http_404 -= 1; m.diff_fetch.counts.http_403 += 1 },
    m => { m.diff_dates_fetched = 1 },
    m => { delete m.station_discovery.station_selection },
    m => { m.station_discovery.schema_version = 1; delete m.station_discovery.provider_error },
    m => { m.station_discovery.cutoff_day = "2026-11-20" },
    m => { m.archive_selection.candidates.stable_sweep_opportunities = 0 },
    m => { m.archive_selection.tracked.stable_sweep_opportunities = 0 },
    m => { m.archive_selection.timely_verification_guaranteed = true },
    m => { m.archive_selection.same_bucket_retries_reuse_selection = false },
    m => { m.archive_selection.coverage_bound_scope = "Complete global coverage" },
    m => { m.archive_selection.verification_scope = "Source truth verified" },
  ]
  for (const change of changes) await t.test(change.toString(), () => {
    const value = structuredClone(fixtures.ghcn)
    change(metrics(value))
    const out = outcome(value)
    // Positive outer candidate counts retain their existing supplying
    // precedence. They cannot lend an interpretation to this malformed trace.
    assert.match(out.detail, /intake details are unavailable or inconsistent/)
    assert.doesNotMatch(out.detail, /sampled verified|Unhinted archive sample/)
    assert.notEqual(out.status, "healthy")
  })
})

test("the real one-slot candidate turn keeps its nonempty unselected tracked pool", () => {
  const m = metrics(fixtures.one), out = outcome(fixtures.one)
  assert.equal(m.archive_selection.tracked.pool_stations, 1)
  assert.equal(m.archive_selection.tracked.selected_stations, 0)
  assert.equal(m.archive_selection.candidates.selected_stations, 1)
  assert.equal(out.state, "supplying")
  assert.match(out.detail, /sampled verified station archives: 1 checked/)
  assert.match(out.detail, /Unhinted archive sample: 1 of 1/)
})

test("a coherent but impossible cold-start interpretation remains unavailable", () => {
  const value = structuredClone(fixtures.one), m = metrics(value), s = m.archive_selection
  s.tracked = { pool_stations: 0, selected_stations: 0, unselected_stations: 0,
    reserved_slots: 0, verified_stations: 0, unverified_stations: 0, stable_sweep_opportunities: 0 }
  s.eligible_unique_stations = 1
  s.unselected_unique_stations = 0
  s.candidates.stable_sweep_opportunities = 1
  m.archive_verification_exhausted = 0
  m.tracked_stations_unscanned = 0
  const out = outcome(value)
  assert.match(out.detail, /intake details are unavailable or inconsistent/)
  assert.doesNotMatch(out.detail, /sampled verified|Unhinted archive sample/)
})

test("real failed archives retain unavailable verdict and unhinted attempt origin", () => {
  const value = fixtures.failed, m = metrics(value), out = outcome(value)
  assert.equal(m.archive_verification_attempted, 2)
  assert.equal(m.archive_verification_failed, 2)
  assert.equal(m.station_archive_intake.active_archives, 0)
  assert.equal(out.state, "ghcn_archive_intake_unavailable")
  assert.match(out.detail, /2 attempted; 2 failed; 0 verified; 0 active/)
  assert.match(out.detail, /Unhinted archive sample: 1 of 1/)
  assert.doesNotMatch(out.detail, /record qualified|source recovered|source healthy/)
})

test("a coherent zero-allowance trace cannot borrow the counted lookup", () => {
  const value = structuredClone(fixtures.failed), m = metrics(value), s = m.archive_selection
  s.limit = 0
  s.selected_unique_stations = 0
  s.unselected_unique_stations = 2
  for (const lane of [s.tracked, s.candidates]) {
    lane.selected_stations = 0
    lane.unselected_stations = lane.pool_stations
    lane.reserved_slots = 0
    lane.verified_stations = 0
    lane.unverified_stations = lane.pool_stations
    lane.stable_sweep_opportunities = null
  }
  m.archive_verification_attempted = 0
  m.archive_verification_failed = 0
  m.archive_verification_exhausted = 2
  const out = outcome(value)
  assert.match(out.detail, /intake details are unavailable or inconsistent/)
  assert.doesNotMatch(out.detail, /Unhinted archive sample/)
})
