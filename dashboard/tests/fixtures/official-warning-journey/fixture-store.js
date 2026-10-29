import { spawnSync } from "node:child_process"
import { runtimeRun } from "../../helpers/review-policy.js"
const key = Symbol.for("theheat.invented.official-warning.journey")
const code = `import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external request trapped'))
from tests.warning_journey_helpers import generated_state
value=json.load(sys.stdin);state,policy=generated_state(value['runtime'])
print(json.dumps(state,ensure_ascii=False))
`
const CURRENT = "2026-10-29T12:00:00.000Z", STAMP = "2026-10-29T11:59:00.000Z"
export function fixtureStore() {
  if (!globalThis[key]) {
    const result = spawnSync(process.env.THEHEAT_TEST_PYTHON, ["-c", code], { cwd: process.env.THEHEAT_WARNING_JOURNEY_ROOT,
      input: JSON.stringify({ runtime: runtimeRun(STAMP) }), encoding: "utf8", timeout: 30000,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, LC_ALL: "C", LANG: "C", PYTHON_DOTENV_DISABLED: "1",
        PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
    if (result.status !== 0) throw new Error("Invented warning generation fixture failed: " + result.stderr)
    globalThis[key] = { raw: result.stdout, seed: result.stdout, now: Date.parse(CURRENT), stamp: STAMP, writes: 0, dispatches: [], refused: [] }
  }
  return globalThis[key]
}
export function reset() { Object.assign(fixtureStore(), { raw: fixtureStore().seed, now: Date.parse(CURRENT), stamp: STAMP, writes: 0, dispatches: [], refused: [] }) }
export function expire() {
  const store = fixtureStore(); store.now = Date.parse("2026-10-30T00:00:00.000Z")
  const next = new Date(store.now - 60000).toISOString()
  store.raw = store.raw.split(store.stamp).join(next); store.stamp = next
}
async function inventedFetch(url, options = {}) {
  const store = fixtureStore()
  if (String(url) === "https://api.github.com/gists/invented-warning-journey") {
    if (options.method === "PATCH") { store.raw = JSON.parse(options.body).files["state.json"].content; store.writes++; return Response.json({}) }
    return Response.json({ files: { "state.json": { content: store.raw } } })
  }
  if (String(url) === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
    store.dispatches.push(JSON.parse(options.body)); return new Response(null, { status: 204 })
  }
  store.refused.push(String(url)); throw new Error("External request refused in invented warning fixture")
}
export async function actualHandler(handler, request) {
  const store = fixtureStore(), originalFetch = globalThis.fetch, originalNow = Date.now
  globalThis.fetch = inventedFetch; Date.now = () => store.now
  try { return await handler(request) } finally { globalThis.fetch = originalFetch; Date.now = originalNow }
}
