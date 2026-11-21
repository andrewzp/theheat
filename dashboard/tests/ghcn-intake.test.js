import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"

const output = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.ghcn_intake_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 30000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(output.status, 0, output.stderr)
const fixtures = JSON.parse(output.stdout), key = "open_meteo_extreme_signals"
const copy = name => structuredClone(fixtures[name])
const row = state => state.run_history[0].sources[0]
const metrics = state => row(state).details.pipeline_metrics ?? row(state).details.ghcn_pipeline_metrics
const projected = state => buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" }).sources.find(s => s.source === key)

test("actual source engine and durable JSON distinguish empty intake from no temperature updates", () => {
  for (const name of ["empty", "inactive", "no_temperature"]) {
    const state = copy(name), before = structuredClone(state), out = projected(state).outcome
    assert.equal(out.state, "ghcn_intake_empty")
    assert.match(out.detail, /Saved GHCN intake:/)
    assert.match(out.detail, /0 station-days retained/)
    assert.doesNotMatch(out.detail, /no extreme weather|global coverage|healthy feed/i)
    assert.deepEqual(state, before)
  }
  assert.match(projected(copy("empty")).outcome.detail, /3 usable updates; 2 deletions; 1 unusable update/)
  assert.match(projected(copy("inactive")).outcome.detail, /3 inactive-station rows/)
  assert.match(projected(copy("no_temperature")).outcome.detail, /0 temperature updates parsed/)
})

test("available station-days and combined provider retain their distinct denominations", () => {
  for (const name of ["mixed", "combined", "missing"]) {
    const out = projected(copy(name)).outcome
    assert.match(out.detail, /Saved GHCN intake:/)
    assert.match(out.detail, name === "missing" ? /1 of 3 diffs fetched/ : /3 of 3 diffs fetched/)
    assert.match(out.detail, name === "missing" ? /2 station-days retained/ : /1 station-day retained/)
  }
})

test("missing, malformed and contradictory counts stay unavailable rather than zero", () => {
  const changes = [
    m => { delete m.diff_intake },
    m => { delete m.diff_intake.counts.future_rows },
    m => { m.diff_intake.counts.final_values = 3 },
    m => { m.diff_intake.counts.parsed_temperature_rows = 10 },
    m => { m.diff_intake.counts.future_rows = true },
    m => { m.diff_intake.counts.usable_updates = -1 },
    m => { m.diff_intake.counts.final_station_days = Number.MAX_SAFE_INTEGER + 1 },
    m => { m.diff_dates_missing = 1 },
    m => { m.station_obs_pairs = 2 },
    m => { m.diff_intake.window_day = "2026-11-20" },
    m => { m.diff_intake.cutoff_day = "2026-12-01" },
    m => { m.diff_intake.counts.extra = "<script>private-token</script>" },
  ]
  for (const change of changes) {
    const state = copy("empty")
    change(metrics(state))
    const out = projected(state).outcome
    assert.equal(out.state, "ghcn_intake_unavailable")
    assert.doesNotMatch(JSON.stringify(out), /private-token|<script>|0 temperature updates parsed/)
  }
  const legacy = copy("unavailable")
  delete metrics(legacy).diff_fetch
  delete metrics(legacy).station_archive_intake
  assert.equal(projected(legacy).outcome.state, "ghcn_intake_unavailable")
})

test("an older row cannot borrow currency from newer health or another provider", () => {
  const state = copy("empty")
  state.source_health[key].runs.at(-1).ts = "2026-11-21T12:01:30Z"
  assert.equal(projected(state).outcome.state, "ghcn_intake_unavailable")
  const duplicate = copy("empty")
  duplicate.run_history[0].sources.push(structuredClone(row(duplicate)))
  assert.equal(projected(duplicate).outcome.state, "ghcn_intake_unavailable")
  const malformed = copy("empty")
  malformed.run_history[0].started_at = { toString: "private-token" }
  assert.equal(projected(malformed).outcome.state, "ghcn_intake_unavailable")
  const other = copy("mixed")
  row(other).details.provider = "open_meteo"
  assert.doesNotMatch(projected(other).outcome.detail ?? "", /Saved GHCN intake:/)
})

test("a usable update cannot vanish without a removal-capable update", () => {
  const state = copy("no_temperature"), c = metrics(state).diff_intake.counts
  c.parsed_temperature_rows = c.usable_updates = 1
  assert.equal(c.delete_updates + c.unusable_updates, 0)
  assert.equal(projected(state).outcome.state, "ghcn_intake_unavailable")
  // The real producer's later delete/QC updates can legitimately remove all keys.
  assert.equal(projected(copy("empty")).outcome.state, "ghcn_intake_empty")
})

test("writer rejection and other supplying legs retain precedence", () => {
  const rejected = copy("mixed")
  rejected.suppressions = [{ source: key, stage: "critic" }]
  assert.equal(projected(rejected).outcome.state, "writer_or_check_rejection")
  assert.match(projected(rejected).outcome.detail, /Saved GHCN intake:/)
  const supplied = copy("mixed")
  row(supplied).promoted = 1
  supplied.source_health[key].runs.at(-1).promoted = 1
  assert.equal(projected(supplied).outcome.state, "supplying")
  assert.match(projected(supplied).outcome.detail, /Saved GHCN intake:/)
})

const require = createRequire(import.meta.url), modules = new Map()
function component(filename) {
  if (modules.has(filename)) return modules.get(filename).exports
  const module = { exports: {} }
  modules.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  new Function("require", "module", "exports", code)(name => name.startsWith(".") ? component(resolve(dirname(filename), name)) : require(name), module, module.exports)
  return module.exports
}
const { SourcesView } = component(fileURLToPath(new URL("../app/components/SourcesView.js", import.meta.url)))
test("actual SourcesView names the recorded intake without publication authority", () => {
  const state = copy("empty"), before = structuredClone(state)
  const markup = renderToStaticMarkup(createElement(SourcesView, buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" })))
  assert.match(markup, /Saved GHCN intake:/)
  assert.match(markup, /0 station-days retained/)
  assert.doesNotMatch(markup, /Approve \+ Post/)
  assert.deepEqual(state, before)
})

test("actual SourcesView separates missing diffs from already-verified archive inputs", () => {
  const state = copy("unavailable"), before = structuredClone(state)
  const markup = renderToStaticMarkup(createElement(SourcesView, buildSourceHealthPayload(state, { asOf: "2026-11-21T12:02:00Z" })))
  assert.match(markup, /already-verified station archives/)
  assert.match(markup, /Diff acquisition remains unavailable/)
  assert.match(markup, /30 HTTP 404/)
  assert.doesNotMatch(markup, /0 station-days retained|Approve \+ Post/)
  assert.deepEqual(state, before)
})
