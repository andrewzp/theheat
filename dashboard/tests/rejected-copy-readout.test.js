import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { spawnSync } from "node:child_process"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { fingerprint, textHash } from "../lib/draft-revisions.js"
import { importFresh } from "./helpers/import-fresh.js"
import { projectSuppression, rejectedCopyPreview } from "../lib/rejected-copy.js"

function row() {
  const text = "Invented station: <script>not executable</script> — 40°C."
  const bundle = { event_id: "invented-event", signal_kind: "invented-observation", current_facts: [] }
  return { id: "invented-suppression", ts: "2026-11-21T01:00:00Z", source: "alerts", stage: "critic",
    event_id: bundle.event_id, reasons: ["redundant_event"],
    rejected_candidate: { schema_version: 2, scope: "selected_critic_rejection", stage: "critic",
      status: "retained", attempt: 1, text, text_sha256: textHash(text), bundle,
      bundle_sha256: fingerprint(bundle), bundle_phase: "before_critic",
      verdict: { check_path: "critic_review", passed: false, verdict: "KILL", kill_reason: "redundant_event",
        response_diagnostic: "response_chars=7 response_sha256=" + "a".repeat(64) } } }
}

async function apiRows(route, records, authorization = true) {
  const originalEnv = { ...process.env }, originalFetch = globalThis.fetch
  let reads = 0
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented-reviewer",
    DASHBOARD_PASSWORD: "invented-password", THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "",
    GIST_ID: "invented-gist", GITHUB_TOKEN: "invented-token" })
  const state = { drafts: [], suppressions: records, run_history: [] }, before = structuredClone(state)
  globalThis.fetch = async (url, options) => {
    assert.ok(!options?.method || options.method === "GET", "read-only fixture")
    reads++
    const payload = String(url).includes("/gists/")
      ? { files: { "state.json": { content: JSON.stringify(state) } } } : { workflow_runs: [] }
    return { ok: true, status: 200, json: async () => payload, text: async () => JSON.stringify(payload) }
  }
  try {
    const { GET } = await importFresh(`app/api/${route}/route.js`)
    const headers = authorization ? { authorization: "Basic " + Buffer.from("invented-reviewer:invented-password").toString("base64") } : {}
    const response = await GET(new Request(`http://localhost/api/${route}`, { headers }))
    const payload = response.status === 200 ? await response.json() : {}
    assert.deepEqual(state, before)
    return { status: response.status, rows: route === "dashboard" ? payload.suppressions?.suppressions : payload.suppressions, reads }
  } finally {
    globalThis.fetch = originalFetch
    for (const name of Object.keys(process.env)) if (!(name in originalEnv)) delete process.env[name]
    Object.assign(process.env, originalEnv)
  }
}

for (const route of ["dashboard", "suppressions"]) {
  test(`${route}: retained critic copy reaches the existing protected read-only payload`, async () => {
    const record = row()
    const result = await apiRows(route, [record])
    assert.equal(result.status, 200)
    assert.equal(result.rows[0].rejected_copy?.status, "retained")
    assert.equal(result.rows[0].rejected_copy.text, record.rejected_candidate.text)
    assert.equal(result.rows[0].rejected_copy.characters, [...record.rejected_candidate.text].length)
    assert.equal(result.rows[0].rejected_copy.bundle, undefined)
    assert.equal(result.rows[0].rejected_copy.response_diagnostic, undefined)
    assert.deepEqual(result.rows[0].rejected_candidate, record.rejected_candidate)
  })
  test(`${route}: unauthorized requests read no state or workflow`, async () => {
    const result = await apiRows(route, [row()], false)
    assert.equal(result.status, 401)
    assert.equal(result.reads, 0)
  })
}

const require = createRequire(import.meta.url)
function component(filename) {
  const module = { exports: {} }
  const code = transformSync(readFileSync(filename, "utf8"), { filename,
    jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" } }).code
  new Function("require", "module", "exports", code)(name => name.startsWith(".")
    ? component(resolve(dirname(filename), name)) : require(name), module, module.exports)
  return module.exports
}
const { SuppressedView } = component(resolve(dirname(fileURLToPath(import.meta.url)), "../app/components/SuppressedView.js"))
test("actual Suppressed view discloses escaped rejected text with no publishing action", () => {
  const record = row()
  record.rejected_copy = { status: "retained", stage: "critic", attempt: 1, text: record.rejected_candidate.text,
    characters: [...record.rejected_candidate.text].length, reasons: ["redundant_event"] }
  const html = renderToStaticMarkup(createElement(SuppressedView, { suppressions: [record], stats: {},
    sourceFilter: "", stageFilter: "", setSourceFilter() {}, setStageFilter() {} }))
  assert.match(html, /<details/)
  assert.match(html, /Read rejected draft/)
  assert.match(html, /&lt;script&gt;not executable&lt;\/script&gt;/)
  assert.doesNotMatch(html, /<script|Approve|Post now|Request draft|response_sha256=/)
  assert.match(html, /not approval/i)
})

const mutations = {
  "changed text": r => { r.rejected_candidate.text += " changed" },
  "changed evidence": r => { r.rejected_candidate.bundle.current_facts.push({ value: 99 }) },
  "wrong event even with rehashed bundle": r => { r.rejected_candidate.bundle.event_id = "another-event"; r.rejected_candidate.bundle_sha256 = fingerprint(r.rejected_candidate.bundle) },
  "wrong parent stage": r => { r.stage = "safety" },
  "wrong schema": r => { r.rejected_candidate.schema_version = 1 },
  "wrong scope": r => { r.rejected_candidate.scope = "selected_safety_rejection" },
  "wrong packet stage": r => { r.rejected_candidate.stage = "safety" },
  "wrong phase": r => { r.rejected_candidate.bundle_phase = "before_safety" },
  "wrong attempt": r => { r.rejected_candidate.attempt = 3 },
  "boolean attempt": r => { r.rejected_candidate.attempt = true },
  "passing verdict": r => { r.rejected_candidate.verdict.passed = true },
  "REVISE is not terminal KILL": r => { r.rejected_candidate.verdict.verdict = "REVISE" },
  "wrong checker": r => { r.rejected_candidate.verdict.check_path = "safety_pipeline" },
  "reason disagrees with parent": r => { r.reasons = ["another-reason"] },
  "no provider diagnostic": r => { r.rejected_candidate.verdict.response_diagnostic = "" },
  "wrong hash shape": r => { r.rejected_candidate.text_sha256 = "unsafe" },
  "invalid Unicode": r => { r.rejected_candidate.text = "\ud800" },
  "oversized text": r => { r.rejected_candidate.text = "a".repeat(4097); r.rejected_candidate.text_sha256 = textHash(r.rejected_candidate.text) },
  "empty text": r => { r.rejected_candidate.text = ""; r.rejected_candidate.text_sha256 = textHash("") },
  "nonfinite evidence": r => { r.rejected_candidate.bundle.value = Infinity },
  "unsafe integer evidence": r => { r.rejected_candidate.bundle.value = Number.MAX_SAFE_INTEGER + 1; r.rejected_candidate.bundle_sha256 = fingerprint(r.rejected_candidate.bundle) },
  "oversized full packet": r => { r.rejected_candidate.bundle.padding = "a".repeat(40960); r.rejected_candidate.bundle_sha256 = fingerprint(r.rejected_candidate.bundle) },
  "unknown schema fields": r => { r.rejected_candidate.unrecognized = "not the known schema" },
  "non-JSON evidence": r => { r.rejected_candidate.extra = () => "not JSON" },
}
for (const [name, mutate] of Object.entries(mutations)) test(`display refuses ${name} without raw-copy fallback`, () => {
  const record = row(); mutate(record)
  const result = rejectedCopyPreview(record)
  assert.deepEqual(result, { status: "invalid" })
  assert.equal(result.text, undefined)
})

test("missing, unavailable and malformed stay distinct; forged previews are overwritten", () => {
  const missing = row(); delete missing.rejected_candidate
  assert.deepEqual(rejectedCopyPreview(missing), { status: "missing" })
  const unavailable = row(); unavailable.rejected_candidate.status = "unavailable"
  unavailable.rejected_candidate.reason = "private-provider-error"
  assert.deepEqual(rejectedCopyPreview(unavailable), { status: "unavailable" })
  assert.deepEqual(rejectedCopyPreview({ ...row(), rejected_candidate: null }), { status: "invalid" })
  missing.rejected_copy = { status: "retained", text: "forged" }
  const before = structuredClone(missing)
  assert.deepEqual(projectSuppression(missing).rejected_copy, { status: "missing" })
  assert.deepEqual(missing, before)
})

test("Unicode scalars, exact copy and caller state are preserved", () => {
  const record = row(); record.rejected_candidate.text = "Invented −45.5°C 🌡️\nSecond line."
  record.rejected_candidate.text_sha256 = textHash(record.rejected_candidate.text)
  const before = structuredClone(record), out = rejectedCopyPreview(record)
  assert.equal(out.status, "retained")
  assert.equal(out.text, record.rejected_candidate.text)
  assert.equal(out.characters, [...out.text].length)
  assert.deepEqual(record, before)
})

test("the terminal first reason cannot be replaced by a matching later entry", () => {
  const valid = row(); valid.reasons.push("news_boost=+8")
  assert.equal(rejectedCopyPreview(valid).status, "retained")
  valid.reasons = ["different terminal reason", "redundant_event"]
  assert.deepEqual(rejectedCopyPreview(valid), { status: "invalid" })
})

function factRow() {
  const record = row(), p = record.rejected_candidate
  record.stage = "fact_check"; record.reasons = ["invented failure"]
  p.schema_version = 1; p.scope = "selected_fact_check_rejection"; delete p.stage
  p.bundle_phase = "before_local_fact_check"
  p.verdict = { check_path: "required_checker", passed: false, failures: ["invented failure"],
    extracted_claims: [], response_diagnostic: "response_chars=0 response_sha256=" + "a".repeat(64) }
  return record
}
test("malformed factual claims cannot become a retained preview", () => {
  const record = factRow(); assert.equal(rejectedCopyPreview(record).status, "retained")
  record.rejected_candidate.verdict.extracted_claims = [null]
  assert.deepEqual(rejectedCopyPreview(record), { status: "invalid" })
})
test("a blank diagnostic cannot become a retained factual preview", () => {
  const record = factRow(); record.rejected_candidate.verdict.response_diagnostic = ""
  assert.deepEqual(rejectedCopyPreview(record), { status: "invalid" })
})
test("supported fact diagnostic forms and actual claim shape remain readable", () => {
  for (const diagnostic of ["response_chars=0 response_sha256=" + "a".repeat(64), "response_type=NoneType"]) {
    const record = factRow(); record.rejected_candidate.verdict.response_diagnostic = diagnostic
    record.rejected_candidate.verdict.extracted_claims = [{ text: "Invented claim", kind: "temperature" }]
    assert.equal(rejectedCopyPreview(record).status, "retained")
  }
  for (const claim of [null, "claim", {}, { text: "missing kind" }, { text: 7, kind: "temperature" }]) {
    const record = factRow(); record.rejected_candidate.verdict.extracted_claims = [claim]
    assert.deepEqual(rejectedCopyPreview(record), { status: "invalid" })
  }
})
test("ASCII-escaped Unicode and Python separator spaces count toward the producer cap", () => {
  const record = row(), p = record.rejected_candidate
  record.stage = p.stage = "copy_gate"; p.scope = "selected_copy_gate_rejection"; p.bundle_phase = "before_copy_gate"
  p.verdict = { check_path: "local_copy_gate", passed: false, reason: "source_led_opener", subsequent_checks: "not_run" }
  record.reasons = ["source_led_opener"]
  p.bundle.current_facts = [{ note: "🌧".repeat(700) }]; p.bundle_sha256 = fingerprint(p.bundle)
  assert.ok(Buffer.byteLength(JSON.stringify(p)) < 8192, "old compact UTF-8 check accepts it")
  assert.deepEqual(rejectedCopyPreview(record), { status: "invalid" })
})

test("actual Python copy producer agrees on retained Unicode and oversized escaped packets", () => {
  const program = `
import json,socket
socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network forbidden"))
from src.two_bot.types import StoryBundle
from src.two_bot.rejected_candidate import capture_fact_input,capture_copy_rejection
from src.two_bot.copy_gates import copy_rejection
text="NWS: Invented station reached 40°C 🌧."
def capture(count):
 b=StoryBundle(signal_kind="invented",where="Invented",when="2026-11-21",event_id="invented-event",headline_metric={},current_facts=[{"note":"🌧"*count}])
 reason=copy_rejection(text,b); c=capture_fact_input(b)
 return c.payload(),reason,capture_copy_rejection(text,b,c,reason,attempt=1)
small,reason,p=capture(1);large,_,held=capture(700)
print(json.dumps({"small":p,"large_bundle":large,"held":held,"reason":reason}))
`
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", program], {
    cwd: resolve(dirname(fileURLToPath(import.meta.url)), "../.."), encoding: "utf8", timeout: 30000 })
  assert.equal(result.status, 0, result.stderr)
  const { small, large_bundle, held, reason } = JSON.parse(result.stdout)
  assert.equal(small.status, "retained"); assert.equal(held.status, "unavailable"); assert.equal(held.reason, "packet_too_large")
  const record = { ...row(), stage: "copy_gate", reasons: [reason], rejected_candidate: small }
  assert.equal(rejectedCopyPreview(record).status, "retained")
  record.rejected_candidate.bundle = large_bundle; record.rejected_candidate.bundle_sha256 = fingerprint(large_bundle)
  assert.deepEqual(rejectedCopyPreview(record), { status: "invalid" })
})

test("actual Python capture producers join through both GET payloads for all four stages", async () => {
  const program = `
import json, socket
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden"))
from src.two_bot.types import StoryBundle, FactCheckResult, CriticResult
from src.two_bot.rejected_candidate import capture_fact_input, capture_fact_rejection, capture_critic_rejection, capture_safety_rejection, capture_copy_rejection
from src.two_bot.copy_gates import copy_rejection
b=StoryBundle(signal_kind="invented",where="Invented station",when="2026-11-21",event_id="invented-event",headline_metric={},current_facts=[])
c=capture_fact_input(b)
text="Invented station reached 40°C."
copy_text="NWS: An invented station reached 40°C."
copy_reason=copy_rejection(copy_text,b)
assert copy_reason is not None
values=[("fact_check","invented_fact_failure",capture_fact_rejection(text,b,c,FactCheckResult(False,["invented_fact_failure"],"invented response"),origin="required_checker",attempt=1)),
("safety","invented_safety_refusal",capture_safety_rejection(text,b,c,False,"invented_safety_refusal",attempt=2)),
("critic","redundant_event",capture_critic_rejection(text,b,c,CriticResult(passed=False,kill_reason="redundant_event",raw_response="invented response"),attempt=1)),
("copy_gate",copy_reason,capture_copy_rejection(copy_text,b,c,copy_reason,attempt=1))]
print(json.dumps([dict(id=stage,ts="2026-11-21T01:00:00Z",event_id=b.event_id,source="invented",stage=stage,reasons=[reason],rejected_candidate=packet) for stage,reason,packet in values]))
`
  const result = spawnSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-c", program], {
    cwd: resolve(dirname(fileURLToPath(import.meta.url)), "../.."), encoding: "utf8", timeout: 30000 })
  assert.equal(result.status, 0, result.stderr)
  const rows = JSON.parse(result.stdout)
  assert.equal(rows.length, 4)
  for (const route of ["dashboard", "suppressions"]) {
    const response = await apiRows(route, rows)
    assert.equal(response.status, 200)
    for (const record of response.rows) {
      assert.equal(record.rejected_candidate.status, "retained", record.stage)
      assert.equal(record.rejected_copy.status, "retained", record.stage)
      assert.equal(record.rejected_copy.text, record.rejected_candidate.text)
      assert.equal(record.rejected_copy.stage, record.stage)
      const before = structuredClone(record)
      for (const mutate of [r => { r.rejected_candidate.verdict.passed = true },
        r => { r.reasons = ["not-this-rejection"] }, r => { r.event_id = "other-event" }]) {
        const changed = structuredClone(record); mutate(changed)
        assert.deepEqual(rejectedCopyPreview(changed), { status: "invalid" }, record.stage)
      }
      assert.deepEqual(record, before)
    }
  }
})
