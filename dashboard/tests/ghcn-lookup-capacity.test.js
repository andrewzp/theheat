import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const script = `
import json
from unittest.mock import patch
from src.data import ghcn_discovery
from dashboard.tests.fixtures.ghcn_discovery_producer import produce
values = {"quiet": produce("quiet"), "capacity": produce("error400_capacity"), "current": produce(extra_stations=1000)}
# Explicit historical fixture only: preserve the former 500-ID trace shape.
# This never changes the production request limit or contacts an actual server.
with patch.object(ghcn_discovery, "MAX_STATIONS", 500):
    values["legacy"] = produce(extra_stations=1000)
print(json.dumps(values))
`
const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", script], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1",
    LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(result.status, 0, result.stderr)
const fixtures = JSON.parse(result.stdout)
const metrics = state => state.run_history[0].sources[0].details.pipeline_metrics
const outcome = state => buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" })
  .sources.find(row => row.source === "open_meteo_extreme_signals").outcome

test("actual quiet lookup and original archives remain distinct in the durable Sources reader", () => {
  const state = fixtures.quiet, before = structuredClone(state), m = metrics(state), out = outcome(state)
  assert.equal(m.station_discovery.status, "no_nominations")
  assert.equal(m.station_discovery.http_status, 200)
  assert.equal(m.station_discovery.nominated_stations, 0)
  assert.equal(m.station_archive_intake.sampling_source, "cached_active_stations_after_lookup_no_nominations")
  assert.equal(out.state, "supplying")
  assert.equal(out.status, "degraded")
  assert.match(out.detail, /0 archive nominations/)
  assert.match(out.detail, /Unhinted archive sample/)
  assert.match(out.detail, /2 accepted daily values/)
  assert.doesNotMatch(out.detail, /source recovered|healthy|complete global coverage/)
  assert.equal(state.request_count, 33)
  assert.deepEqual(state, before)
})

test("a reported station capacity is inert diagnostic text with no reflected provider value", () => {
  const out = outcome(fixtures.capacity)
  assert.match(out.detail, /Untrusted provider error: stations: reported maximum of 100 stations/)
  assert.doesNotMatch(out.detail, /ignored-provider-value/)
  const changed = structuredClone(fixtures.capacity)
  metrics(changed).station_discovery.provider_error.fields[0].field = "units"
  assert.doesNotMatch(outcome(changed).detail, /reported maximum/)
})

test("both exact current100 and legacy500 trace limits remain readable without source authority", () => {
  for (const [name, limit] of [["current", 100], ["legacy", 500]]) {
    const state = fixtures[name], m = metrics(state), out = outcome(state)
    assert.equal(m.station_discovery.station_selection.limit, limit)
    assert.match(out.detail, new RegExp(`${limit} of 1001 eligible stations requested`))
    assert.match(out.detail, /Requested sample only/)
    assert.doesNotMatch(out.detail, /intake details are unavailable or inconsistent/)
    assert.equal(m.station_discovery.get_calls, 1)
  }
})

test("quiet sampling cannot borrow HTTP400, failed headers or an asserted nomination", async t => {
  const changes = [
    m => { m.station_discovery.http_status = 400 },
    m => { m.station_discovery.status = "unavailable" },
    m => { m.station_discovery.reason = "headers_unsupported" },
    m => { m.station_discovery.nominated_stations = 1 },
    m => { m.station_discovery.schema_version = 2 },
    m => { m.station_archive_intake.sampling_source = "cached_active_stations_after_lookup_400" },
    m => { m.station_discovery.station_selection.limit = 99 },
  ]
  for (const mutate of changes) await t.test(mutate.toString(), () => {
    const state = structuredClone(fixtures.quiet)
    mutate(metrics(state))
    assert.match(outcome(state).detail, /intake details are unavailable or inconsistent/)
    assert.doesNotMatch(outcome(state).detail, /Unhinted archive sample/)
  })
})
