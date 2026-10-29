// Actual draft handlers and generated warning; only Gist/workflow transports
// and the fixture's clock are replaced. No source/model/platform request.
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { importFresh } from "./import-fresh.js"
import { runtimeRun } from "./review-policy.js"
import { draftIdentity } from "../../lib/draft-revisions.js"

export const NOW = "2026-10-29T12:00:00.000Z"
const root = path.resolve(new URL("../../..", import.meta.url).pathname)
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external request trapped'))\n"
const seedCode = trap + `
from tests.warning_journey_helpers import generated_state
value=json.load(sys.stdin)
state,policy=generated_state(value.get('runtime'))
print(json.dumps(dict(raw_state=json.dumps(state,ensure_ascii=False),policy=policy)))
`
export function pythonJSON(code, input) {
  const result = spawnSync(python, ["-c", code], { cwd: root, input: JSON.stringify(input), encoding: "utf8", timeout: 60000,
    env: { PATH: process.env.PATH, HOME: "/private/tmp", LC_ALL: "C", LANG: "C", PYTHON_DOTENV_DISABLED: "1",
      PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  assert.equal(result.status, 0, result.stderr?.slice(-3500))
  return JSON.parse(result.stdout)
}
export function generatedWarning() {
  return pythonJSON(seedCode, { runtime: runtimeRun("2026-10-29T11:59:00.000Z") })
}
export const revision = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
export const body = (draft, action, extra = {}) => ({ action, draftId: draft.id, expectedRevision: revision(draft), ...extra })

export async function withWarningGist(run, { seed = generatedWarning() } = {}) {
  let raw = seed.raw_state, now = Date.parse(NOW)
  const originalFetch = globalThis.fetch, originalNow = Date.now
  const names = ["NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "GIST_ID", "GITHUB_TOKEN"]
  const before = Object.fromEntries(names.map(name => [name, process.env[name]]))
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "fixture", DASHBOARD_PASSWORD: "invented", THEHEAT_STATE_BACKEND: "gist", GIST_ID: "invented-warning-journey" })
  delete process.env.THEHEAT_DB_PATH; delete process.env.GITHUB_TOKEN
  const patches = [], dispatches = []
  const state = () => JSON.parse(raw), get = () => state().drafts[0]
  Date.now = () => now
  globalThis.fetch = async (url, options = {}) => {
    if (String(url) === "https://api.github.com/gists/invented-warning-journey") {
      if (options.method === "PATCH") {
        const value = JSON.parse(options.body)
        assert.deepEqual(Object.keys(value.files), ["state.json"])
        raw = value.files["state.json"].content; patches.push(raw)
        return new Response("{}")
      }
      assert.ok(!options.method || options.method === "GET")
      return Response.json({ files: { "state.json": { content: raw } } })
    }
    if (String(url) === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
      dispatches.push(JSON.parse(options.body)); return new Response(null, { status: 204 })
    }
    assert.fail(`Unallowed request in invented warning fixture: ${url}`)
  }
  try {
    const route = await importFresh(path.join(root, "dashboard/app/api/drafts/route.js"))
    const headers = { "Content-Type": "application/json", authorization: "Basic Zml4dHVyZTppbnZlbnRlZA==" }
    async function post(value) {
      const response = await route.POST(new Request("http://127.0.0.1/api/drafts", { method: "POST", headers, body: JSON.stringify(value) }))
      return { status: response.status, body: await response.json() }
    }
    async function list() {
      const response = await route.GET(new Request("http://127.0.0.1/api/drafts", { headers }))
      assert.equal(response.status, 200)
      return (await response.json()).drafts
    }
    await run({ state, get, raw: () => raw, post, list, patches, dispatches, policy: seed.policy,
      replace: value => { raw = JSON.stringify(value) }, at: value => { now = Date.parse(value) } })
  } finally {
    globalThis.fetch = originalFetch; Date.now = originalNow
    for (const name of names) { if (before[name] === undefined) delete process.env[name]; else process.env[name] = before[name] }
  }
}
