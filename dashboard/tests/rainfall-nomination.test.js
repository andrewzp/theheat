import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { spawnSync } from "node:child_process"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { buildSourceHealthPayload } from "../lib/source-health.js"
import { sourceOutcome } from "../lib/live-content-status.js"

// Invented readings passed through the real Python nominate, enqueue and source
// telemetry functions. Only the clock/settings were fixed; no drains or SDKs ran.
const FIXTURES = JSON.parse(readFileSync(new URL("./fixtures/rainfall-nomination-counts.json", import.meta.url)))
const AS_OF = "2026-11-16T17:02:00Z"
const copy = name => structuredClone(FIXTURES[name])
const row = state => state.run_history[0].sources[0]
const report = state => row(state).details.rainfall_observed_report
const counts = state => report(state).nomination
const projected = state => buildSourceHealthPayload(state, { asOf: AS_OF }).sources.find(s => s.source === "gpm_imerg")
const unavailable = value => {
  // The source can still supply a different candidate; an unavailable report
  // diagnostic does not erase that retained source-level promotion count.
  if (value.outcome.state === "supplying") assert.ok(value.total_promoted > 0)
  else assert.equal(value.outcome.state, "rainfall_nominations_unavailable")
  assert.equal(value.outcome.detail, "Rainfall report nomination counts are unavailable for this saved source run.")
}

test("actual producer dispositions reach the existing source-health reader without changing state", () => {
  for (const [name, fragment] of Object.entries({
    empty: "0 input rows; 0 qualified events; 0 nominated; 0 queued",
    range: "outside the automatic amount range: 1",
    expired: "completed window not current at nomination: 1",
    history: "held by retained draft/publication history: 1",
    untyped: "untyped input rows: 1",
    identity_missing: "rows without a usable identity: 1",
    identity_conflict: "rows with conflicting identities: 2",
    duplicate: "duplicate qualified rows: 1",
    cap: "5 qualified events; 3 nominated; 3 queued",
    queued: "1 qualified events; 1 nominated; 1 queued",
  })) {
    const state = copy(name), before = structuredClone(state)
    const value = projected(state)
    assert.ok(value.outcome.detail?.includes(fragment), `${name}: ${value.outcome.detail}`)
    assert.match(value.outcome.detail, /Saved rainfall report nominations:/)
    assert.match(value.outcome.detail, /not coverage, source truth, drafts or posts/)
    if (name === "cap") assert.match(value.outcome.detail, /excluded by the nomination cap: 2/)
    assert.deepEqual(state, before)
  }
})

test("settings hold stays held without manufacturing nomination counts", () => {
  const value = projected(copy("settings_held"))
  assert.equal(value.outcome.state, "rainfall_reports_held")
  assert.equal(value.outcome.detail, "Saved rainfall report nomination held: publication settings paused. Nomination counts were not recorded.")
  assert.doesNotMatch(value.outcome.detail, /0 input|0 qualified/)
  const state = copy("settings_held")
  report(state).reason = "<img src=x onerror=alert(1)>"
  unavailable(projected(state))
  report(state).reason = "rainfall_report_publication_paused"
  report(state).nomination = counts(copy("empty"))
  unavailable(projected(state))
})

test("missing latest evidence never borrows an older successful nomination", () => {
  const state = copy("range")
  state.run_history.unshift({ ...structuredClone(state.run_history[0]), id: "newer", started_at: "2026-11-16T17:01:00Z", sources: [{ ...row(state), details: {} }] })
  unavailable(projected(state))
  const missing = copy("range")
  delete row(missing).details
  unavailable(projected(missing))
})

test("durable source history must bind the selected collection interval and counters", () => {
  const state = copy("range")
  state.source_health = { gpm_imerg: { success: 1, runs: [{ ts: "2026-11-16T17:00:00Z", status: "success", observed: 1, promoted: 0 }] } }
  assert.match(projected(state).outcome.detail, /outside the automatic amount range: 1/)
  for (const change of [{ ts: "2026-11-16T17:01:30Z" }, { ts: "invalid" }, { observed: 2 }, { promoted: 1 }, { status: "skipped" }]) {
    const changed = structuredClone(state)
    Object.assign(changed.source_health.gpm_imerg.runs[0], change)
    unavailable(projected(changed))
  }
})

test("unbound, future and contradictory collection rows cannot supply the counts", () => {
  for (const change of [{ started_at: "invalid" }, { ended_at: undefined }, { ended_at: "2026-11-16T16:58:00Z" }, { ended_at: "2026-11-16T17:03:00Z" }]) {
    const state = copy("range")
    Object.assign(state.run_history[0], change)
    unavailable(projected(state))
  }
  const duplicate = copy("range")
  duplicate.run_history[0].sources.push(structuredClone(row(duplicate)))
  unavailable(projected(duplicate))
})

test("noninteger, boolean, negative and unsafe counts are unavailable, never coerced", () => {
  for (const key of Object.keys(counts(copy("cap"))).filter(k => typeof counts(copy("cap"))[k] === "number")) {
    for (const value of [-1, 0.5, true, "0", null, Number.MAX_SAFE_INTEGER + 1]) {
      const state = copy("cap")
      counts(state)[key] = value
      unavailable(projected(state))
    }
  }
  for (const key of ["nominated", "queued"]) {
    const state = copy("cap")
    report(state)[key] = true
    unavailable(projected(state))
  }
})

test("all disposition totals, hold totals, cap and outer queue arithmetic must reconcile", () => {
  const mutations = [
    state => counts(state).input_rows++,
    state => counts(state).qualified_events++,
    state => counts(state).nomination_cap_excluded++,
    state => { counts(state).nominated_events--; counts(state).nomination_cap_excluded++; report(state).nominated--; report(state).queued-- },
    state => { report(state).queued = 4 },
    state => { row(state).observed++ },
    state => { row(state).promoted = 2 },
    state => { report(state).status = "no_qualified_report" },
    state => { counts(state).qualification_holds = { rainfall_report_unqualified: 1 } },
    state => { counts(state).untyped_rows = Number.MAX_SAFE_INTEGER; counts(state).input_rows = Number.MAX_SAFE_INTEGER },
  ]
  for (const change of mutations) {
    const state = copy("cap")
    change(state)
    unavailable(projected(state))
  }
  const held = copy("range")
  counts(held).qualification_holds.rainfall_outside_automatic_range = 0
  unavailable(projected(held))
})

test("unknown keys, schema versions, raw strings and prototype codes are never rendered", () => {
  const mutations = [
    state => { counts(state).schema = "rainfall-nomination-counts-v2" },
    state => { counts(state).schema = [] },
    state => { counts(state).extra = "private-source-body" },
    state => { report(state).extra = "private-source-body" },
    state => { counts(state).scope = "private-source-body" },
    state => { counts(state).qualification_holds = { "<script>private-source-body</script>": 1 } },
    state => { counts(state).qualification_holds = JSON.parse('{"__proto__":1}') },
    state => { counts(state).qualification_holds = { constructor: 1 } },
    state => { counts(state).qualification_holds = Object.create({ rainfall_outside_automatic_range: 1 }) },
  ]
  for (const change of mutations) {
    const state = copy("range")
    change(state)
    unavailable(projected(state))
    assert.doesNotMatch(JSON.stringify(projected(state).outcome), /private-source-body|<script>/)
  }
  for (const key of Object.keys(counts(copy("range")))) {
    const state = copy("range")
    delete counts(state)[key]
    unavailable(projected(state))
  }
})

test("rainfall details do not replace access failures or explain another source", () => {
  const source = row(copy("range"))
  assert.equal(sourceOutcome({ ...source, source: "other" }).detail, null)
  assert.equal(sourceOutcome({ ...source, status: "failed", error: "token expired 2026-11-01" }).state, "access_expired")
  assert.equal(sourceOutcome({ ...source, status: "failed" }).state, "unavailable")
  const sourceWithOtherCandidate = { ...source, promoted: 1, drafted: 0 }
  const value = sourceOutcome(sourceWithOtherCandidate)
  assert.equal(value.state, "supplying")
  assert.match(value.detail, /0 nominated; 0 queued/)
  assert.match(value.next_action, /no saved draft/)
})

// Compile the actual SourcesView and its real local imports with Next's installed
// compiler. No production component or source outcome is substituted.
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
test("real producer JSON reaches the actual rendered SourcesView with no draft or posting claim", () => {
  for (const name of ["range", "cap", "settings_held"]) {
    const payload = buildSourceHealthPayload(copy(name), { asOf: AS_OF })
    const markup = renderToStaticMarkup(createElement(SourcesView, payload))
    assert.ok(markup.includes(projected(copy(name)).outcome.detail))
    assert.match(markup, /data-outcome="(?:supplying|rainfall_nominations|rainfall_reports_held)"/)
    assert.match(markup, /Past collection results, not a live source check/)
    assert.doesNotMatch(markup, /Approve|Post now|Paris|180\.5/)
  }
})

const DURABLE = JSON.parse(readFileSync(new URL("./fixtures/rainfall-durable-health.json", import.meta.url)))
test("the actual Python producer still emits the durable fixture used by this reader", () => {
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "dashboard.tests.fixtures.rainfall_durable_producer"], {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), encoding: "utf8", timeout: 20000,
    env: { PATH: process.env.PATH, PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", LC_ALL: "C", LANG: "C", NO_PROXY: "*", no_proxy: "*" },
  })
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout), DURABLE)
})
test("actual telemetry and durable zero-eliding serializer reach the real reader and SourcesView", () => {
  for (const name of ["empty", "range", "queued"]) {
    const state = structuredClone(DURABLE[name]), before = structuredClone(state)
    const latest = state.source_health.gpm_imerg.runs.at(-1)
    assert.equal(Object.hasOwn(latest, "promoted"), name === "queued")
    assert.equal(Object.hasOwn(latest, "observed"), name !== "empty")
    const payload = buildSourceHealthPayload(state, { asOf: AS_OF })
    const outcome = payload.sources.find(s => s.source === "gpm_imerg").outcome
    assert.match(outcome.detail, /Saved rainfall report nominations:/)
    assert.equal(outcome.state, name === "queued" ? "supplying" : "rainfall_nominations")
    assert.ok(renderToStaticMarkup(createElement(SourcesView, payload)).includes(outcome.detail))
    assert.deepEqual(state, before)
  }
})

test("zero elision applies only to explicit source zeros in the bound run", () => {
  const mutations = [
    state => { delete state.source_health.gpm_imerg.runs.at(-1).observed },
    state => { state.source_health.gpm_imerg.runs.at(-1).promoted = null },
    state => { state.source_health.gpm_imerg.runs.at(-1).promoted = false },
    state => { state.source_health.gpm_imerg.runs.at(-1).promoted = "0" },
    state => { state.source_health.gpm_imerg.runs.at(-1).promoted = -1 },
    state => { state.source_health.gpm_imerg.runs.at(-1).ts = "2026-11-16T17:01:30Z" },
    state => { delete row(state).promoted },
    state => { row(state).observed = 0 },
  ]
  for (const change of mutations) {
    const state = structuredClone(DURABLE.range)
    change(state)
    unavailable(projected(state))
  }
  const positive = structuredClone(DURABLE.queued)
  delete positive.source_health.gpm_imerg.runs.at(-1).promoted
  unavailable(projected(positive))
})
