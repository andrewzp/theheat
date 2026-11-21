import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.ghcn_archive_intake_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(result.status, 0, result.stderr)
const fixtures = JSON.parse(result.stdout)
const row = state => state.run_history[0].sources[0]
const metrics = state => row(state).details.pipeline_metrics ?? row(state).details.ghcn_pipeline_metrics
const project = state => buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" }).sources
  .find(s => s.source === "open_meteo_extreme_signals").outcome

test("real archive-derived source supply is explained separately from all missing diffs", () => {
  for (const name of ["fresh", "combined"]) {
    const state = structuredClone(fixtures[name]), before = structuredClone(state)
    const out = project(state)
    assert.match(out.detail, /already-verified station archives/)
    assert.match(out.detail, /2 accepted daily values; 1 station-day/)
    assert.match(out.detail, /30 HTTP 404/)
    assert.doesNotMatch(out.detail, /source recovered|global coverage|no observations|no weather/i)
    assert.equal(out.status, "degraded")
    assert.equal(state.request_count, 31)
    assert.deepEqual(state, before)
  }
})

test("empty or excluded archive samples remain explicitly limited, not a healthy feed", () => {
  for (const name of ["empty", "stale", "future", "qc"]) {
    const out = project(structuredClone(fixtures[name]))
    assert.equal(out.state, "ghcn_archive_intake_empty")
    assert.match(out.detail, /0 accepted daily values; 0 station-days/)
    assert.match(out.detail, /30 HTTP 404/)
    assert.doesNotMatch(out.label, /healthy|recovered|no events/i)
  }
})

test("archive counts need the exact completed current run and conservation relations", () => {
  const changes = [
    m => { delete m.station_archive_intake },
    m => { m.station_archive_intake.schema_version = 2 },
    m => { m.station_archive_intake.scope = "entire_global_catalogue" },
    m => { m.station_archive_intake.trigger = "partial_diff" },
    m => { m.station_archive_intake.window_day = "2026-11-20" },
    m => { m.station_archive_intake.retrieved_at = "2026-11-21T11:58:59Z" },
    m => { m.station_archive_intake.retrieved_at = "2026-11-21T12:01:01Z" },
    m => { m.station_archive_intake.cutoff_day = "2026-11-22" },
    m => { m.station_archive_intake.verified_archives = 21 },
    m => { m.station_archive_intake.active_archives = 2 },
    m => { m.station_archive_intake.counts.accepted_values = 3 },
    m => { m.station_archive_intake.counts.temperature_rows++ },
    m => { m.station_archive_intake.counts.too_old_rows = -1 },
    m => { m.station_archive_intake.counts.unusable_rows = "0" },
    m => { delete m.station_archive_intake.counts.future_rows },
    m => { m.station_archive_intake.counts.extra = "private arbitrary detail" },
    m => { m.station_obs_pairs++ },
    m => { m.stations_with_obs++ },
    m => { m.archive_verification_verified++ },
    m => { m.archive_selection.selected_unique_stations++ },
    m => { m.archive_selection.schema_version = 2 },
    m => { m.archive_selection.strategy = "unbounded" },
    m => { m.diff_missing_dates = ["2026-11-20", "2026-11-20", "2026-11-20"] },
    m => { m.diff_dates_fetched = 1 },
    m => { m.diff_fetch_failed = 0 },
    m => { m.diff_intake = {} },
  ]
  for (const change of changes) {
    const state = structuredClone(fixtures.fresh)
    change(metrics(state))
    const out = project(state)
    // The independently saved positive nomination stays visible; the invalid
    // diagnostic must not claim archive counts or source recovery.
    assert.equal(out.state, "supplying", change.toString())
    assert.match(out.detail, /intake details are unavailable or inconsistent/)
    assert.doesNotMatch(out.detail, /already-verified station archives|2 accepted daily values|private arbitrary detail/)
  }
  const newer = structuredClone(fixtures.fresh)
  newer.source_health.open_meteo_extreme_signals.runs.at(-1).ts = "2026-11-21T12:01:30Z"
  assert.match(project(newer).detail, /intake details are unavailable or inconsistent/)
})

test("source or required-check failures keep their priority over an intake explanation", () => {
  const failed = structuredClone(fixtures.fresh)
  row(failed).status = "failed"
  failed.source_health.open_meteo_extreme_signals.runs.at(-1).status = "failed"
  assert.equal(project(failed).state, "unavailable")
  const rejected = structuredClone(fixtures.fresh)
  rejected.suppressions = [{ source: "open_meteo_extreme_signals", stage: "critic" }]
  assert.equal(project(rejected).state, "writer_or_check_rejection")
  assert.match(project(rejected).detail, /already-verified station archives/)
})
