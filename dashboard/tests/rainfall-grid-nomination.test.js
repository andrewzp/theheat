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
import { sourceOutcome } from "../lib/live-content-status.js"

const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.rainfall_grid_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 20000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(result.status, 0, result.stderr)
const FIXTURES = JSON.parse(result.stdout)
const copy = name => structuredClone(FIXTURES[name])
const row = state => state.run_history[0].sources[0]
const counts = state => row(state).details.rainfall_observed_report.nomination
const projected = state => buildSourceHealthPayload(state, { asOf: "2026-11-16T17:02:00Z" }).sources.find(s => s.source === "gpm_imerg")
const unavailable = state => {
  const outcome = projected(state).outcome
  assert.equal(outcome.detail, "Rainfall report nomination counts are unavailable for this saved source run.")
  assert.doesNotMatch(JSON.stringify(outcome), /private-value|<script>/)
}

test("actual joint producer and durable serializer reconcile city, grid and unique cell counts", () => {
  const expected = {
    grid_only: "0 city input rows; 1 grid cell report inputs; 1 qualified cells; 1 nominated; 1 queued",
    mixed: "1 city input rows; 1 grid cell report inputs; 1 qualified cells; 1 nominated; 1 queued",
    same_cell: "same-cell events joined: 1", duplicate: "duplicate grid rows: 1",
    conflict: "grid inputs with unusable or conflicting identities: 2",
    qualification: "grid inputs held by qualification: 1", history: "grid inputs held by history: 1",
    city_grid_conflict: "city rows with conflicting identities: 1", cap: "excluded by the nomination cap: 1",
  }
  for (const [name, fragment] of Object.entries(expected)) {
    const state = copy(name), before = structuredClone(state)
    assert.equal(counts(state).schema, "rainfall-nomination-counts-v2")
    const outcome = projected(state).outcome
    assert.match(outcome.detail, /Saved rainfall report nominations:/)
    assert.ok(outcome.detail.includes(fragment), `${name}: ${outcome.detail}`)
    assert.match(outcome.detail, /not coverage, source truth, drafts or posts/)
    assert.deepEqual(state, before)
  }
})

test("every city, grid and joint denominator is strict and cannot cross-count", () => {
  for (const name of Object.keys(FIXTURES)) {
    for (const group of ["city", "grid", "joint"]) {
      for (const [key, value] of Object.entries(counts(copy(name))[group])) {
        if (typeof value !== "number") continue
        for (const invalid of [-1, .5, true, "0", null, Number.MAX_SAFE_INTEGER + 1, value + 1]) {
          const state = copy(name)
          counts(state)[group][key] = invalid
          unavailable(state)
        }
      }
    }
  }
})

test("missing, extra, supplied prose and prototype keys never clear the strict v2 contract", () => {
  for (const group of [null, "city", "grid", "joint"]) {
    for (const key of Reflect.ownKeys(group ? counts(copy("mixed"))[group] : counts(copy("mixed")))) {
      const state = copy("mixed"), target = group ? counts(state)[group] : counts(state)
      delete target[key]
      unavailable(state)
    }
    for (const value of [[], null, true, "private-value"]) {
      const state = copy("mixed")
      if (group) counts(state)[group] = value
      else row(state).details.rainfall_observed_report.nomination = value
      unavailable(state)
    }
    const extra = copy("mixed")
    ;(group ? counts(extra)[group] : counts(extra)).extra = "private-value"
    unavailable(extra)
  }
  for (const holds of [{ "<script>private-value</script>": 1 }, JSON.parse('{"__proto__":1}'), { constructor: 1 }]) {
    const state = copy("mixed")
    counts(state).city.qualification_holds = holds
    unavailable(state)
  }
})

test("outer queue, source interval and durable row remain bound for grid-only runs", () => {
  for (const change of [
    state => { row(state).observed++ },
    state => { row(state).promoted = 0 },
    state => { row(state).details.rainfall_observed_report.queued++ },
    state => { row(state).details.rainfall_observed_report.status = "no_qualified_report" },
    state => { state.source_health.gpm_imerg.runs.at(-1).ts = "2026-11-16T17:01:30Z" },
    state => { delete state.source_health.gpm_imerg.runs.at(-1).promoted },
    state => { state.run_history[0].ended_at = "2026-11-16T17:03:00Z" },
  ]) {
    const state = copy("grid_only")
    change(state)
    unavailable(state)
  }
  assert.equal(sourceOutcome({ ...row(copy("grid_only")), source: "other" }).detail, null)
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
test("the actual SourcesView renders actual joint producer counts without claiming a draft or post", () => {
  for (const name of Object.keys(FIXTURES)) {
    const state = copy(name), payload = buildSourceHealthPayload(state, { asOf: "2026-11-16T17:02:00Z" })
    const markup = renderToStaticMarkup(createElement(SourcesView, payload))
    assert.ok(markup.includes(projected(state).outcome.detail))
    assert.doesNotMatch(markup, /nomination counts are unavailable|Approve|Post now|190\.5|Brasilia/)
  }
})
