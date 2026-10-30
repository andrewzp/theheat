// Invented Gist transport and an explicit invented clock around the actual draft
// handlers and the genuine Python PNG renderer. The clock is a labelled fixture
// boundary: the route's Date.now and the Python preview both read it.
import { spawnSync } from "node:child_process"
import manifest from "../../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { runtimeRun } from "../../helpers/review-policy.js"
const key = Symbol.for("theheat.invented.gist.store.journey")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const SENTINEL = "2000-01-01T00:00:00.000Z"
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const fixtureCode = trap + `
import os
from pathlib import Path
from src.media import gist_assets
from tests.gist_store_helpers import CLOCKS, retain, saved_state
value=json.load(sys.stdin)
# Seeding is retention: the explicit writer capability on this run's private local store.
store=gist_assets.configured_writer({gist_assets.WRITER_ENV: os.environ[gist_assets.ENV]})
drafts,retained=[],{}
for family in ('crw','crw_collected','radar','cone'):
    drafts.append(saved_state(family)['drafts'][0])
    retained[family]=retain(family,store)
# A different valid CRW packet (same bytes, other acquisition times): never the collected draft's own.
from src.media import gist_crw_media
from tests.gist_crw_helpers import varied_inputs
retained['crw_other']=gist_crw_media.retain_packet(store,{**varied_inputs('caribbean')[1],'csv_retrieved_at':'2026-06-16T12:45:00Z'})
state={'drafts':drafts,'publish_ledger':{},'errors':[],'unrelated':{'preserve':True},'run_history':[value['runtime']]}
print(json.dumps(dict(raw=json.dumps(state,ensure_ascii=False),clocks={k:list(v) for k,v in CLOCKS.items()},retained=retained)))
`
// Mirrors the real handler's reply: a PreviewError becomes its fixed public JSON and status.
const renderCode = trap + `
from freezegun import freeze_time
from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin);state=json.loads(value['raw_state'])
try:
    with freeze_time(value['now']):
        body=build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget())
    sys.stdout.buffer.write(json.dumps({'status':200,'body':json.loads(body)}).encode())
except PreviewError as exc:
    sys.stdout.buffer.write(json.dumps({'status':exc.status,'body':exc.payload()}).encode())
`
function pythonOutput(code, input) {
  const result = spawnSync(python, ["-c", code], { cwd: process.env.THEHEAT_GIST_STORE_JOURNEY_ROOT,
    input: JSON.stringify(input), encoding: "utf8", timeout: 60000, maxBuffer: 16 * 1024 * 1024,
    env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
      PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*",
      // The owned journey's private local media store (invented retained inputs only).
      THEHEAT_MEDIA_STORE: process.env.THEHEAT_MEDIA_STORE } })
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
    const now = Date.parse(value.clocks.crw[0]), stamp = new Date(now - 60000).toISOString()
    const raw = value.raw.split(SENTINEL).join(stamp)
    globalThis[key] = { raw, seed: raw, stamp, seedStamp: stamp, now, clocks: value.clocks, retained: value.retained, writes: 0, refused: [],
      dispatches: [], previews: 0, previewRefused: false }
    Date.now = () => globalThis[key]?.now ?? realNow()
  }
  return globalThis[key]
}
export function previewResponse(input) {
  const store = fixtureStore(); store.previews++
  // Simulates a deployment without a configured media store: the real closed hold reply.
  if (store.previewRefused) return Response.json({ code: "media_hold", hold: "media_store_unavailable", error: "Invented unconfigured store" }, { status: 422 })
  try {
    const reply = JSON.parse(pythonOutput(renderCode, { raw_state: store.raw, request: input, now: new Date(store.now).toISOString(),
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 }))
    return Response.json(reply.body, { status: reply.status })
  } catch { return Response.json({ code: "preview_unavailable" }, { status: 503 }) }
}
export async function inventedFetch(url, options = {}) {
  const store = fixtureStore(), value = String(url)
  if (value === `${process.env.THEHEAT_GIST_STORE_JOURNEY_ORIGIN}/api/graphic_preview`) return previewResponse(JSON.parse(options.body))
  if (value === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
    store.dispatches.push(JSON.parse(options.body)); return new Response(null, { status: 204 })
  }
  if (value !== "https://api.github.com/gists/invented-gist-store-journey") {
    store.refused.push(value); throw new Error("External transport refused in invented retained-asset journey")
  }
  if (options.method === "PATCH") {
    store.raw = JSON.parse(options.body).files["state.json"].content; store.writes++
    if (store.raw.includes('"png_base64"') || store.raw.includes("iVBORw0KGgo") || store.raw.includes("R0lGOD")) throw new Error("Image bytes must not be stored in Gist")
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
