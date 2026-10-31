// OFFLINE FIXTURE ONLY (P00c): in-process whole-file Gist GET/PATCH (no server merge), a
// workflow_dispatch recorder and an artifact listing. Never a network call or credential.
export function installMemoryGist({ gists = {}, artifacts = [], dispatchStatus = 204, dispatchThrows = false, patchStatus = 200 } = {}) {
  const store = Object.fromEntries(Object.entries(gists).map(([id, files]) => [id, { ...files }]))
  const patches = [], dispatches = [], gets = []
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
      dispatches.push({ workflow: target.pathname.split("/").at(-2), body: JSON.parse(init.body) })
      if (dispatchThrows) throw new TypeError("fetch failed")
      return new Response(null, { status: dispatchStatus })
    }
    if (/\/actions\/artifacts$/.test(target.pathname)) return new Response(JSON.stringify({ artifacts }), { status: 200 })
    throw new Error(`memory gist refuses ${method} ${target.href}`)
  }
  return { store, patches, dispatches, gets, artifacts, restore() { globalThis.fetch = original } }
}

export function routeEnv(extra = {}) {
  const keys = ["THEHEAT_GIST_WRITE_ROUTE", "THEHEAT_SERIALIZED_WRITER", "GITHUB_RUN_ID", "GIST_ID", "GITHUB_TOKEN",
    "THEHEAT_FEEDBACK_GIST_ID", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD"]
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  for (const key of keys) delete process.env[key]
  Object.assign(process.env, { GIST_ID: "routestategist", GITHUB_TOKEN: "invented-not-a-credential", THEHEAT_FEEDBACK_GIST_ID: "routefeedbackgist",
    THEHEAT_STATE_BACKEND: "gist", NODE_ENV: "production", DASHBOARD_USERNAME: "reviewer", DASHBOARD_PASSWORD: "invented-pass" }, extra)
  return () => { for (const key of keys) { if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key] } }
}

export const consumerMarker = { GITHUB_RUN_ID: "4242", THEHEAT_SERIALIZED_WRITER: "4242:consume" }
