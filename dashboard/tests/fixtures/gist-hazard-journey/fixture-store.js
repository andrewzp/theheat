// Invented Gist transport and an explicit invented clock around the actual draft
// handlers and the genuine Python PNG renderer. The clock is a labelled fixture
// boundary: the route's Date.now and the Python preview both read it.
import { spawnSync } from "node:child_process"
import manifest from "../../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { runtimeRun } from "../../helpers/review-policy.js"
const key = Symbol.for("theheat.invented.gist.hazard.journey")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const SENTINEL = "2000-01-01T00:00:00.000Z"
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const fixtureCode = trap + `
from tests.gist_hazard_helpers import CLOCKS, saved_state
value=json.load(sys.stdin)
drafts=[]
for family in ('pm25','modis','viirs'):
    drafts.append(saved_state(family)['drafts'][0])
state={'drafts':drafts,'publish_ledger':{},'errors':[],'unrelated':{'preserve':True},'run_history':[value['runtime']]}
print(json.dumps(dict(raw=json.dumps(state,ensure_ascii=False),clocks={k:list(v) for k,v in CLOCKS.items()})))
`
const renderCode = trap + `
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin);state=json.loads(value['raw_state'])
with freeze_time(value['now']):
    body=build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget())
sys.stdout.buffer.write(body)
`
function pythonOutput(code, input) {
  const started = performance.now()
  const result = spawnSync(python, ["-c", code], { cwd: process.env.THEHEAT_GIST_HAZARD_JOURNEY_ROOT,
    input: JSON.stringify(input), encoding: "utf8", timeout: 60000,
    env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
      PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  console.error(JSON.stringify({ scope: "invented_hazard_worker", phase: code === fixtureCode ? "seed" : "preview",
    elapsed_ms: Math.round(performance.now() - started), status: result.status, signal: result.signal,
    error_code: result.error?.code ?? null }))
  if (result.status !== 0) throw new Error(`Invented fixture Python failed: ${result.stderr}`)
  return result.stdout
}
const realNow = Date.now
export function setClock(iso) {
  const store = fixtureStore()
  store.now = Date.parse(iso)
  // Re-stamp only the invented bot report textually; retained source spellings stay intact.
  const next = new Date(store.now - 60000).toISOString()
  store.raw = store.raw.split(store.stamp).join(next); store.stamp = next
}
export function fixtureStore() {
  if (!globalThis[key]) {
    const value = JSON.parse(pythonOutput(fixtureCode, { runtime: runtimeRun(SENTINEL) }))
    const now = Date.parse(value.clocks.pm25[0]), stamp = new Date(now - 60000).toISOString()
    const raw = value.raw.split(SENTINEL).join(stamp)
    globalThis[key] = { raw, seed: raw, stamp, seedStamp: stamp, now, clocks: value.clocks, writes: 0, refused: [],
      dispatches: [], previews: 0, previewRefused: false }
    Date.now = () => globalThis[key]?.now ?? realNow()
  }
  return globalThis[key]
}
export function previewResponse(input) {
  const store = fixtureStore(); store.previews++
  if (store.previewRefused) return Response.json({ code: "graphic_unavailable", error: "Invented refused source preview" }, { status: 422 })
  try {
    const raw = pythonOutput(renderCode, { raw_state: store.raw, request: input, now: new Date(store.now).toISOString(),
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
    return new Response(raw, { headers: { "Content-Type": "application/json" } })
  } catch { return Response.json({ code: "preview_unavailable" }, { status: 503 }) }
}
export async function inventedFetch(url, options = {}) {
  const store = fixtureStore(), value = String(url)
  if (value === `${process.env.THEHEAT_GIST_HAZARD_JOURNEY_ORIGIN}/api/graphic_preview`) return previewResponse(JSON.parse(options.body))
  if (value === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
    store.dispatches.push(JSON.parse(options.body)); return new Response(null, { status: 204 })
  }
  if (value !== "https://api.github.com/gists/invented-gist-hazard-journey") {
    store.refused.push(value); throw new Error("External transport refused in invented hazard journey")
  }
  if (options.method === "PATCH") {
    store.raw = JSON.parse(options.body).files["state.json"].content; store.writes++
    if (store.raw.includes('"png_base64"') || store.raw.includes("iVBORw0KGgo")) throw new Error("PNG bytes must not be stored in Gist")
    return Response.json({})
  }
  return Response.json({ files: { "state.json": { content: store.raw } } })
}
export async function actualHandler(handler, request) {
  fixtureStore()
  const previous = globalThis.fetch
  globalThis.fetch = inventedFetch
  try { return await handler(request) } finally { globalThis.fetch = previous }
}
