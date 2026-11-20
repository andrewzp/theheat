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

const output = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.rainfall_grid_hold_producer"], {
  cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 20000,
  env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
})
assert.equal(output.status, 0, output.stderr)
const fixtures = JSON.parse(output.stdout)
const copy = name => structuredClone(fixtures[name])
const row = state => state.run_history[0].sources[0]
const projected = state => buildSourceHealthPayload(state, { asOf: "2026-11-16T17:02:00Z" }).sources.find(s => s.source === "gpm_imerg")
const labels = { time: "source time metadata", units: "precipitation units", axes: "coordinate axes", counts: "dataset structure", scaling: "packed or scaled data" }

test("actual HTTP/HDF5 collector and durable rows explain an inland refusal without inventing zero weather", () => {
  for (const [name, label] of Object.entries(labels)) {
    const state = copy(name), before = structuredClone(state), outcome = projected(state).outcome
    assert.equal(outcome.state, "rainfall_grid_held")
    assert.match(outcome.detail, /Saved inland rainfall scan held:/)
    assert.ok(outcome.detail.includes(label), outcome.detail)
    assert.match(outcome.detail, /1 input rows; 0 qualified events; 0 nominated; 0 queued/)
    assert.deepEqual(state, before)
  }
  assert.equal(projected(copy("city")).outcome.state, "supplying")
  assert.match(projected(copy("city")).outcome.detail, /Saved inland rainfall scan held:/)
  assert.doesNotMatch(projected(copy("qualified")).outcome.detail, /scan held/)
})

test("legacy, unknown and malformed codes never render supplied strings or claim qualification", () => {
  for (const change of [
    d => { delete d.hold_code }, d => { d.hold_code = "<script>private-token</script>" },
    d => { d.hold_code = "constructor" }, d => { d.hold_code = { toString: "private-token" } },
  ]) {
    const state = copy("time")
    change(row(state).details.rainfall_grid_discovery)
    const out = projected(state).outcome
    assert.equal(out.state, "rainfall_grid_held")
    assert.match(out.detail, /specific cause was not retained/)
    assert.doesNotMatch(JSON.stringify(out), /private-token|<script>|constructor/)
  }
  const extra = copy("time")
  row(extra).details.rainfall_grid_discovery.prose = "private-token"
  assert.equal(projected(extra).outcome.state, "alternate_served")
  assert.doesNotMatch(JSON.stringify(projected(extra).outcome), /private-token|Saved inland rainfall scan held/)
})

test("a mismatched durable source interval cannot lend currency to the scan or nomination", () => {
  const state = copy("time")
  state.source_health.gpm_imerg.runs.at(-1).ts = "2026-11-16T17:01:30Z"
  const out = projected(state).outcome
  assert.equal(out.state, "alternate_served")
  assert.doesNotMatch(JSON.stringify(out), /Saved inland rainfall scan held/)
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
test("SourcesView renders actual producer refusal and city counts without any publication action", () => {
  for (const name of Object.keys(labels)) {
    const state = copy(name), payload = buildSourceHealthPayload(state, { asOf: "2026-11-16T17:02:00Z" })
    const markup = renderToStaticMarkup(createElement(SourcesView, payload))
    assert.match(markup, /Saved inland rainfall scan held:/)
    assert.ok(markup.includes(labels[name]))
    assert.match(markup, /Inland rainfall scan held/)
    assert.doesNotMatch(markup, /private-token|Approve|Post now|190\.5/)
  }
})
