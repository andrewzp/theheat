// OFFLINE FIXTURE ONLY (P00c): in-process whole-file Gist GET/PATCH (no server merge), a
// workflow_dispatch recorder, an artifact listing (exact-name filter, DELETE) and a workflow-run
// listing. Never a network call or credential.
export function installMemoryGist({ gists = {}, artifacts = [], runs = [], dispatchStatus = 204, dispatchThrows = false, patchStatus = 200,
  dispatchHandler = null } = {}) {
  const store = Object.fromEntries(Object.entries(gists).map(([id, files]) => [id, { ...files }]))
  const patches = [], dispatches = [], gets = [], deleted = []
  const original = globalThis.fetch
  globalThis.fetch = async (url, init = {}) => {
    const target = new URL(String(url))
    const method = (init.method || "GET").toUpperCase()
    const gist = target.pathname.match(/^\/gists\/([A-Za-z0-9_]+)$/)
    if (gist) {
      const id = gist[1]
      if (!store[id]) return new Response(JSON.stringify({ message: "Not Found" }), { status: 404 })
      if (method === "GET") {
        gets.push(id)
        const files = Object.fromEntries(Object.entries(store[id]).map(([name, content]) => [name, { filename: name, content, truncated: false }]))
        return new Response(JSON.stringify({ id, public: false, files }), { status: 200 })
      }
      if (method === "PATCH") {
        const body = JSON.parse(init.body)
        patches.push({ id, files: Object.keys(body.files).sort() })
        if (patchStatus !== 200) return new Response("{}", { status: patchStatus })
        for (const [name, value] of Object.entries(body.files)) {
          if (value === null) delete store[id][name]
          else store[id][name] = value.content
        }
        return new Response(JSON.stringify({ id }), { status: 200 })
      }
    }
    if (/\/actions\/workflows\/[^/]+\/dispatches$/.test(target.pathname) && method === "POST") {
      const row = { workflow: target.pathname.split("/").at(-2), body: JSON.parse(init.body) }
      dispatches.push(row)
      if (dispatchHandler) return dispatchHandler(row)
      if (dispatchThrows) throw new TypeError("fetch failed")
      return new Response(null, { status: dispatchStatus })
    }
    const artifact = target.pathname.match(/\/actions\/artifacts\/(\d+)$/)
    if (artifact && method === "DELETE") {
      const index = artifacts.findIndex(row => row.id === Number(artifact[1]))
      if (index < 0) return new Response(null, { status: 404 })
      deleted.push(artifacts[index].id)
      artifacts.splice(index, 1)
      return new Response(null, { status: 204 })
    }
    if (/\/actions\/artifacts$/.test(target.pathname)) {
      const name = target.searchParams.get("name")
      return new Response(JSON.stringify({ artifacts: name ? artifacts.filter(row => row.name === name) : artifacts }), { status: 200 })
    }
    const run = target.pathname.match(/\/actions\/runs\/(\d+)$/)
    if (run) {
      const found = runs.find(row => row.id === Number(run[1]))
      return found ? new Response(JSON.stringify(found), { status: 200 }) : new Response("{}", { status: 404 })
    }
    if (/\/actions\/workflows\/bot\.yml\/runs$/.test(target.pathname)) {
      return new Response(JSON.stringify({ workflow_runs: runs }), { status: 200 })
    }
    throw new Error(`memory gist refuses ${method} ${target.href}`)
  }
  return { store, patches, dispatches, gets, artifacts, runs, deleted, restore() { globalThis.fetch = original } }
}

// Invented test-only seal key (32 bytes of 0x07); never a real secret.
export const TEST_SEAL_KEY = `k-test:${Buffer.alloc(32, 7).toString("base64")}`
export const OTHER_SEAL_KEY = `k-test:${Buffer.alloc(32, 9).toString("base64")}`
export const ROUTE_ACTIVATION = "00000000-0000-4000-8000-000000000001"
export function routeRecord(mode = "serialized", commandId = ROUTE_ACTIVATION) {
  return JSON.stringify({ schema_version: 1, mode, generation: 1, changed_at: "2026-10-30T12:00:00Z", changed_by_run: "77:consume", command_id: commandId })
}

export function routeEnv(extra = {}) {
  const keys = ["THEHEAT_GIST_WRITE_ROUTE", "THEHEAT_SERIALIZED_WRITER", "GITHUB_RUN_ID", "GIST_ID", "GITHUB_TOKEN",
    "THEHEAT_FEEDBACK_GIST_ID", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD",
    "THEHEAT_COMMAND_SEAL_KEY", "THEHEAT_GIST_CREDENTIAL", "THEHEAT_LEGACY_CREDENTIALS_PRESENT"]
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  for (const key of keys) delete process.env[key]
  Object.assign(process.env, { GIST_ID: "routestategist", GITHUB_TOKEN: "invented-not-a-credential", THEHEAT_FEEDBACK_GIST_ID: "routefeedbackgist",
    THEHEAT_STATE_BACKEND: "gist", NODE_ENV: "production", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "invented-pass" }, extra)
  return () => { for (const key of keys) { if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key] } }
}

export const consumerMarker = { GITHUB_RUN_ID: "4242", THEHEAT_SERIALIZED_WRITER: "4242:consume" }
// The route-era consumer job environment (new writer secret name, legacy names deleted).
export const routeConsumerEnv = { ...consumerMarker, THEHEAT_GIST_CREDENTIAL: "route", THEHEAT_LEGACY_CREDENTIALS_PRESENT: "false" }
