// Invented Gist transport, with the actual draft handlers and genuine Python PNG renderer.
import { spawnSync } from "node:child_process"
import manifest from "../../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { runtimeRun } from "../../helpers/review-policy.js"
const key = Symbol.for("theheat.invented.gist.temperature.journey")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const fixtureCode = `
import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from tests.dashboard_graphic_helpers import saved_temperature_preview
value=json.load(sys.stdin);state,request=saved_temperature_preview();draft=state['drafts'][0]
draft.update(content_revision=1,decision_revision=0,event_id=draft['review_context']['two_bot']['bundle']['event_id'],created_at=value['now'])
state.update(run_history=[value['runtime']],publish_ledger={},errors=[])
state['drafts'].append(dict(draft,id='invented-secondary'))
print(json.dumps(state,ensure_ascii=False))
`
const renderCode = `
import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin);state=json.loads(value['raw_state'])
sys.stdout.buffer.write(build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
`
function pythonOutput(code, input) {
  const started = performance.now()
  const result = spawnSync(python, ["-c", code], { cwd: process.env.THEHEAT_GIST_TEMPERATURE_JOURNEY_ROOT,
    input: JSON.stringify(input), encoding: "utf8", timeout: 30000,
    env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
      PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  console.error(JSON.stringify({ scope: "invented_temperature_worker", phase: code === fixtureCode ? "seed" : "preview",
    elapsed_ms: Math.round(performance.now() - started), status: result.status, signal: result.signal,
    error_code: result.error?.code ?? null }))
  if (result.status !== 0) throw new Error(`Invented fixture Python failed: ${result.stderr}`)
  return result.stdout
}
export function fixtureStore() {
  if (!globalThis[key]) {
    const raw = pythonOutput(fixtureCode, { now: new Date().toISOString(), runtime: runtimeRun(new Date().toISOString()) })
    globalThis[key] = { raw, seed: raw, writes: 0, refused: [], previews: 0, previewRefused: false }
  }
  return globalThis[key]
}
export function previewResponse(input) {
  const store = fixtureStore(); store.previews++
  if (store.previewRefused) return Response.json({ code: "graphic_unavailable", error: "Invented refused source preview" }, { status: 422 })
  try {
    const raw = pythonOutput(renderCode, { raw_state: store.raw, request: input, policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
    return new Response(raw, { headers: { "Content-Type": "application/json" } })
  } catch { return Response.json({ code: "preview_unavailable" }, { status: 503 }) }
}
export async function inventedFetch(url, options = {}) {
  const store = fixtureStore(), value = String(url)
  if (value === `${process.env.THEHEAT_GIST_TEMPERATURE_JOURNEY_ORIGIN}/api/graphic_preview`) return previewResponse(JSON.parse(options.body))
  if (value !== "https://api.github.com/gists/invented-gist-temperature-journey") {
    store.refused.push(value); throw new Error("External transport refused in invented temperature journey")
  }
  if (options.method === "PATCH") {
    store.raw = JSON.parse(options.body).files["state.json"].content; store.writes++
    if (store.raw.includes('"png_base64"')) throw new Error("PNG bytes must not be stored in Gist")
    return Response.json({})
  }
  return Response.json({ files: { "state.json": { content: store.raw } } })
}
export async function actualHandler(handler, request) {
  fixtureStore().lastRequest = { url: request.url, host: request.headers.get("host"), method: request.method }
  const previous = globalThis.fetch
  globalThis.fetch = inventedFetch
  try { return await handler(request) } finally { globalThis.fetch = previous }
}
