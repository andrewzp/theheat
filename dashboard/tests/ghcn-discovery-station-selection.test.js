import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const response = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c",
  'import json; from dashboard.tests.fixtures.ghcn_discovery_producer import produce; print(json.dumps({"fresh":produce(), "error400":produce("error400"), "sampled":produce(extra_stations=1000)}))'], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, LC_ALL: "C", LANG: "C", PYTHON_DOTENV_DISABLED: "1",
    PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(response.status, 0, response.stderr)
const fixtures = JSON.parse(response.stdout)
const metrics = state => state.run_history[0].sources[0].details.pipeline_metrics
const project = state => buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" })
  .sources.find(row => row.source === "open_meteo_extreme_signals").outcome

test("actual nomination and400 producer records retain sampled scope and original archive detail", () => {
  for (const name of ["fresh", "error400"]) {
    const state = structuredClone(fixtures[name]), before = structuredClone(state), out = project(state)
    assert.equal(out.state, name === "fresh" ? "supplying" : "ghcn_archive_intake_empty")
    assert.match(out.detail, /1 of 1 eligible stations requested; 0 outside this request/)
    assert.match(out.detail, /sample only/i)
    assert.match(out.detail, /Lookup values are not observations/)
    assert.match(out.detail, /verified station archives/)
    assert.equal(state.request_count, name === "fresh" ? 33 : 32)
    if (name === "error400") assert.match(out.detail, /HTTP 400.*Untrusted provider error/)
    else assert.match(out.detail, /2 accepted daily values/)
    assert.deepEqual(state, before)
  }
})

test("older saved lookup shapes remain readable without inventing a sampled denominator", () => {
  for (const name of ["fresh", "error400"]) {
    const state = structuredClone(fixtures[name])
    delete metrics(state).station_discovery.station_selection
    const out = project(state)
    assert.equal(out.state, name === "fresh" ? "supplying" : "ghcn_archive_intake_empty")
    assert.match(out.detail, /verified station archives/)
    assert.doesNotMatch(out.detail, /eligible stations requested|outside this request/)
  }
})

test("an actual1001-station source pool displays the finite500-station request, not the full pool as queried", () => {
  const state = fixtures.sampled, out = project(state)
  assert.equal(out.state, "supplying")
  assert.match(out.detail, /500 of 1001 eligible stations requested; 501 outside this request/)
  assert.match(out.detail, /Requested sample only/)
  assert.match(out.detail, /1 archive nomination/)
  assert.equal(metrics(state).station_discovery.station_selection.request_uri_bytes, 7167)
  assert.equal(state.request_count, 33)
})

test("disjoint eligible untracked and verified active tracked sets must fit the active population", async t => {
  for (const name of ["error400", "sampled"]) await t.test(name, () => {
    const state = structuredClone(fixtures[name])
    metrics(state).stations_active--
    const out = project(state)
    assert.equal(out.state, name === "sampled" ? "supplying" : "ghcn_intake_unavailable")
    assert.match(out.detail, /intake details are unavailable or inconsistent/)
    assert.doesNotMatch(out.detail, /eligible stations requested|verified station archives|Untrusted provider error/)
  })
})

test("a supplied inconsistent selection cannot borrow older lookup or archive diagnostics", async t => {
  const changes = [
    s => { s.schema_version = 2 }, s => { s.scope = "all_current_weather" },
    s => { s.strategy = "caller_claim" }, s => { s.limit = 501 },
    s => { s.selected_stations = 0 }, s => { s.selected_stations = 2 },
    s => { s.eligible_stations = 2 }, s => { s.unselected_stations = 1 },
    s => { s.cycle_chunks = 2 }, s => { s.chunk_index = 1 },
    s => { s.bucket_start = "2026-11-21T08:00:00Z" },
    s => { s.bucket_start = "2026-11-21T12:01:00Z" },
    s => { s.pool_sha256 = "bad" }, s => { s.selection_sha256 = "a".repeat(64) },
    s => { s.coverage_guaranteed = true }, s => { s.request_uri_bytes++ },
    s => { s.request_uri_bytes = 8193 }, s => { s.extra = "unsupported" },
  ]
  for (const change of changes) await t.test(change.toString(), () => {
    const state = structuredClone(fixtures.error400)
    change(metrics(state).station_discovery.station_selection)
    const out = project(state)
    assert.equal(out.state, "ghcn_intake_unavailable")
    assert.doesNotMatch(out.detail, /verified station archives|Untrusted provider error|eligible stations requested/)
  })
  for (const value of [null, [], {}, "caller supplied"]) await t.test(JSON.stringify(value), () => {
    const state = structuredClone(fixtures.error400)
    metrics(state).station_discovery.station_selection = value
    assert.equal(project(state).state, "ghcn_intake_unavailable")
  })
})
