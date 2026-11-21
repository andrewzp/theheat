import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.ghcn_discovery_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(result.status, 0, result.stderr)
const fixtures = JSON.parse(result.stdout)
const row = s => s.run_history[0].sources[0]
const metrics = s => row(s).details.pipeline_metrics ?? row(s).details.ghcn_pipeline_metrics
const project = s => buildSourceHealthPayload(s, { asOf: "2026-11-21T12:02:00Z" }).sources
  .find(v => v.source === "open_meteo_extreme_signals").outcome

test("provider text and echoed values cannot survive durable storage or Sources", () => {
  const s = fixtures.error400_private, out = project(s)
  for (const value of [JSON.stringify(s), out.detail]) {
    assert.doesNotMatch(value, /PRIVATE_FIXTURE_VALUE|Authorization|INVENTED_TOKEN|ftp:\/\//)
  }
  assert.equal(out.state, "ghcn_archive_intake_empty")
  assert.equal(s.request_count, 32)
})

test("real400 diagnostic survives durable serialization as untrusted operator text only", () => {
  for (const name of ["error400", "error400_unicode"]) {
    const s = structuredClone(fixtures[name]), before = structuredClone(s), out = project(s)
    assert.equal(out.state, "ghcn_archive_intake_empty")
    assert.equal(out.status, "degraded")
    assert.equal(s.request_count, 32)
    assert.match(out.detail, /0 accepted daily values/)
    assert.match(out.detail, /HTTP 400/)
    assert.match(out.detail, /Untrusted provider error/)
    assert.match(out.detail, name === "error400" ? /invalid units; standard or metric expected/ : /details withheld/)
    assert.doesNotMatch(JSON.stringify(s), /🧭/u)
    assert.doesNotMatch(out.detail, /ignored-provider-value|recovered|source healthy/)
    assert.deepEqual(s, before)
  }
  const unknown = project(fixtures.error400_unknown)
  assert.equal(unknown.state, "ghcn_archive_intake_empty")
  assert.match(unknown.detail, /HTTP 400/)
  assert.match(unknown.detail, /No bounded provider diagnostic is available/)
})

test("inconsistent400 diagnostics cannot supply a numerical or trusted explanation", async t => {
  const changes = [
    h => { delete h.provider_error },
    h => { h.http_status = 200 },
    h => { h.schema_version = 1 },
    h => { h.provider_error.scope = "observations" },
    h => { h.provider_error.body_bytes = 1 },
    h => { h.provider_error.body_bytes = 8193 },
    h => { h.provider_error.body_sha256 = "bad" },
    h => { h.provider_error.fields[0].field = "unrecognized" },
    h => { h.provider_error.fields[0].message_code = "unknown" },
    h => { h.provider_error.fields[0].message_code = {} },
    h => { h.provider_error.fields[0].field = "bbox" },
    h => { h.provider_error.fields[0].message = "PRIVATE_FIXTURE_VALUE" },
    h => { h.provider_error.fields[0] = { field: "units", message: "PRIVATE_FIXTURE_VALUE" } },
    h => { h.provider_error.fields[0].value = "not-exported" },
    h => { h.provider_error.fields = [] },
    h => { h.provider_error.fields = Array(9).fill(h.provider_error.fields[0]) },
  ]
  for (const change of changes) await t.test(change.toString(), () => {
    const s = structuredClone(fixtures.error400)
    change(metrics(s).station_discovery)
    const out = project(s)
    assert.doesNotMatch(out.detail, /Untrusted provider error|selected verified station archives/)
    assert.notEqual(out.status, "healthy")
  })
})

test("real invented nominations and archived values survive durable source serialization", () => {
  for (const name of ["fresh", "combined"]) {
    const s = structuredClone(fixtures[name]), before = structuredClone(s)
    const out = project(s)
    assert.equal(out.state, "supplying")
    assert.equal(out.status, "degraded")
    assert.match(out.detail, /selected verified station archives: 2 checked/)
    assert.match(out.detail, /2 accepted daily values; 1 station-day/)
    assert.match(out.detail, /1 client call; 1 archive nomination\./)
    assert.match(out.detail, /Lookup values are not observations/)
    assert.match(out.detail, /30 HTTP 404/)
    assert.doesNotMatch(out.detail, /49|global coverage|source recovered/)
    assert.equal(s.request_count, 33)
    assert.deepEqual(s, before)
  }
})

test("QC refusal and unavailable lookup never become healthy or absence of weather", () => {
  for (const name of ["qc", "unavailable", "malformed"]) {
    const s = fixtures[name], out = project(s)
    assert.equal(out.state, "ghcn_archive_intake_empty")
    assert.equal(out.status, "degraded")
    assert.match(out.detail, /0 accepted daily values/)
    assert.match(out.detail, /Lookup values are not observations/)
    if (name !== "qc") assert.match(out.detail, /reply unavailable/)
    assert.doesNotMatch(out.label, /healthy|recovered|no events/i)
    assert.equal(s.request_count, name === "qc" ? 33 : 32)
  }
})

test("v2 needs its real lookup, selection and archive conservation links", async t => {
  const changes = [
    m => { delete m.station_discovery },
    m => { m.station_discovery.scope = "observations" },
    m => { m.station_discovery.get_calls = 0 },
    m => { m.station_discovery.get_calls = 2 },
    m => { m.station_discovery.nominated_stations = "1" },
    m => { m.station_discovery.rows_received = null },
    m => { m.station_discovery.response_bytes = null },
    m => { m.station_discovery.response_sha256 = "bad" },
    m => { m.station_discovery.cutoff_day = "2026-11-01" },
    m => { m.station_discovery.held_stations = 2 },
    m => { m.station_discovery.status = "unavailable" },
    m => { m.station_archive_intake.nominated_stations = 2 },
    m => { m.station_archive_intake.scope = "already_verified_tracked_archives" },
    m => { m.station_archive_intake.nomination_source = "approved_readings" },
    m => { m.archive_selection.candidates.verified_stations = 0 },
    m => { m.archive_selection.candidates.reserved_slots = 0 },
    m => { m.archive_selection.candidates.pool_stations = 2 },
    m => { m.archive_selection.overlap_stations = 1 },
    m => { m.archive_selection.tracked.selected_stations = 2 },
    m => { m.archive_selection.selected_unique_stations = 3 },
    m => { m.archive_verification_attempted = 1 },
    m => { delete m.diff_fetch },
    m => { m.diff_fetch.counts.http_404 = 0; m.diff_fetch.counts.http_401 = 30 },
    m => { m.station_discovery.response_bytes = 0 },
    m => { m.station_discovery.response_bytes = 4 },
  ]
  for (const change of changes) {
    await t.test(change.toString(), () => {
      const s = structuredClone(fixtures.fresh)
      change(metrics(s))
      const out = project(s)
      // The independent promoted count still means candidates were supplied.
      // Inconsistent supplemental intake evidence must not supply numeric claims.
      assert.equal(out.state, "supplying", change.toString())
      assert.match(out.detail, /intake details are unavailable or inconsistent/, change.toString())
      assert.doesNotMatch(out.detail, /selected verified station archives|2 accepted daily values|archive nomination/, change.toString())
    })
  }
})

test("an unavailable lookup on the original tracked-only scope still requires all-404 acquisition", async t => {
  for (const name of ["unavailable", "malformed"]) {
    for (const change of [m => { delete m.diff_fetch },
      m => { m.diff_fetch.counts.http_404 = 0; m.diff_fetch.counts.http_401 = 30 }]) {
      await t.test(`${name}: ${change}`, () => {
        const s = structuredClone(fixtures[name])
        assert.equal(metrics(s).station_archive_intake.schema_version, 1)
        change(metrics(s))
        const out = project(s)
        assert.match(out.detail, /intake details are unavailable or inconsistent/)
        assert.doesNotMatch(out.detail, /verified station archives|accepted daily values|archive nomination/)
      })
    }
  }
})

test("each nominated station needs a distinct row and its minimum supported encoded bytes", async t => {
  const original = fixtures.two_nominees
  assert.equal(metrics(original).station_discovery.rows_received, 2)
  assert.equal(metrics(original).station_discovery.response_bytes, 128)
  assert.match(project(original).detail, /2 archive nominations/)
  assert.equal(original.request_count, 34)
  const smallest = JSON.stringify(["SFX00000002", "SFX00000003"]
    .map(STATION => ({ STATION, DATE: "2026-11-18", TMAX: 0 })))
  assert.equal(Buffer.byteLength(smallest), 111)
  for (const change of [m => { m.station_discovery.rows_received = 1 },
    m => { m.station_discovery.response_bytes = 59 },
    m => { m.station_discovery.held_stations = 1; m.station_discovery.eligible_untracked_stations = 3 }]) {
    await t.test(change.toString(), () => {
      const s = structuredClone(original)
      change(metrics(s))
      const out = project(s)
      assert.equal(out.state, "supplying")
      assert.match(out.detail, /intake details are unavailable or inconsistent/)
      assert.doesNotMatch(out.detail, /verified station archives|archive nominations|accepted daily values/)
    })
  }
})
