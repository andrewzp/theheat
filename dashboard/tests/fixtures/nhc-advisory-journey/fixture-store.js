import { spawnSync } from "node:child_process"
import { runtimeRun } from "../../helpers/review-policy.js"
const key = Symbol.for("theheat.invented.nhc-advisory.journey")
// The actual trial proposal inserted by the actual import plan; no NHC/model/Gist/X request.
const code = `import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external request trapped'))
from tests.nhc_advisory_import_helpers import imported_state
value=json.load(sys.stdin);state,policy=imported_state(value['runtime'])
print(json.dumps(state,ensure_ascii=False))
`
const CURRENT = "2026-10-29T21:30:00.000Z", STAMP = "2026-10-29T21:29:00.000Z"
const LATE = "2026-10-29T21:56:30.000Z"  // Past the operator freshness deadline (capture + 30 minutes).
export function fixtureStore() {
  if (!globalThis[key]) {
    const result = spawnSync(process.env.THEHEAT_TEST_PYTHON, ["-c", code], { cwd: process.env.THEHEAT_NHC_JOURNEY_ROOT,
      input: JSON.stringify({ runtime: runtimeRun(STAMP) }), encoding: "utf8", timeout: 30000,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, LC_ALL: "C", LANG: "C", PYTHON_DOTENV_DISABLED: "1",
        PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
    if (result.status !== 0) throw new Error("Invented NHC advisory fixture failed: " + result.stderr)
    globalThis[key] = { raw: result.stdout, seed: result.stdout, now: Date.parse(CURRENT), stamp: STAMP, writes: 0, dispatches: [], refused: [] }
  }
  return globalThis[key]
}
export function reset() { Object.assign(fixtureStore(), { raw: fixtureStore().seed, now: Date.parse(CURRENT), stamp: STAMP, writes: 0, dispatches: [], refused: [] }) }
export function passDeadline() {
  // Only the fixture clock moves; the runtime report stays fresh so the source hold is the only reason.
  const store = fixtureStore(); store.now = Date.parse(LATE)
  const next = new Date(store.now - 60000).toISOString()
  store.raw = store.raw.split(store.stamp).join(next); store.stamp = next
}
async function inventedFetch(url, options = {}) {
  const store = fixtureStore()
  if (String(url) === "https://api.github.com/gists/invented-nhc-journey") {
    if (options.method === "PATCH") { store.raw = JSON.parse(options.body).files["state.json"].content; store.writes++; return Response.json({}) }
    return Response.json({ files: { "state.json": { content: store.raw } } })
  }
  if (String(url) === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
    store.dispatches.push(JSON.parse(options.body)); return new Response(null, { status: 204 })
  }
  store.refused.push(String(url)); throw new Error("External request refused in invented NHC advisory fixture")
}
export async function actualHandler(handler, request) {
  const store = fixtureStore(), originalFetch = globalThis.fetch, originalNow = Date.now
  globalThis.fetch = inventedFetch; Date.now = () => store.now
  try { return await handler(request) } finally { globalThis.fetch = originalFetch; Date.now = originalNow }
}
