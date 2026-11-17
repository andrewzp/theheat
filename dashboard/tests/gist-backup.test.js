import test from "node:test"
import assert from "node:assert/strict"
import { collectGistBackupManifest, BACKUP_LIMITS } from "../lib/gist-backup.js"
import { GET, HEAD, POST } from "../app/api/backup-manifest/route.js"

const ID = "a".repeat(32), OTHER = "b".repeat(32)
const REVISION = "1".repeat(40), RAW = "2".repeat(40)
const KEYS = ["NODE_ENV", "DASHBOARD_AUTH_DISABLED", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD",
  "VERCEL_URL", "THEHEAT_LOCAL_COMMAND_URL", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH",
  "GITHUB_TOKEN", "GIST_ID", "THEHEAT_FEEDBACK_GIST_ID"]
let previous, fetchBefore
test.beforeEach(() => {
  previous = Object.fromEntries(KEYS.map(key => [key, process.env[key]]))
  KEYS.forEach(key => delete process.env[key])
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "operator",
    DASHBOARD_PASSWORD: "invented-password", GITHUB_TOKEN: "invented-github-token",
    GIST_ID: ID, THEHEAT_STATE_BACKEND: "gist" })
  fetchBefore = globalThis.fetch
})
test.afterEach(() => {
  KEYS.forEach(key => previous[key] === undefined ? delete process.env[key] : process.env[key] = previous[key])
  globalThis.fetch = fetchBefore
})
function metadata(id = ID, names = ["state.json"]) {
  return { id, truncated: false, owner: { login: "InventedOwner" }, history: [{ version: REVISION }],
    files: Object.fromEntries(names.map(filename => [filename, { filename, size: 17, truncated: true,
      content: "INCOMPLETE API TEXT: never export this",
      raw_url: `https://gist.githubusercontent.com/InventedOwner/${id}/raw/${RAW}/${encodeURIComponent(filename)}` }])) }
}
function transport(transform = value => value) {
  const calls = []
  const fetch = async (url, options) => {
    calls.push({ url, options })
    assert.equal(options.method, "GET"); assert.equal(options.redirect, "error")
    assert.equal(options.cache, "no-store")
    assert.equal(options.headers.Authorization, "Bearer invented-github-token")
    assert.match(url, /^https:\/\/api\.github\.com\/gists\/[ab]{32}(?:\/[1]{40})?$/)
    const id = new URL(url).pathname.split("/")[2]
    const value = transform(metadata(id), calls.length)
    return value instanceof Response ? value : Response.json(value)
  }
  return { calls, fetch }
}
function request(method = "GET", path = "/api/backup-manifest", host = "dashboard.example") {
  return new Request(`https://${host}${path}`, { method, headers: { host,
    authorization: `Basic ${Buffer.from("operator:invented-password").toString("base64")}` } })
}

test("actual authenticated GET pins revision, preserves raw identity, exports no content or credentials", async () => {
  const wire = transport(); globalThis.fetch = wire.fetch
  const response = await GET(request()), body = await response.json()
  assert.equal(response.status, 200)
  assert.equal(response.headers.get("cache-control"), "private, no-store")
  assert.equal(wire.calls.length, 2)
  assert.equal(wire.calls[1].url, `https://api.github.com/gists/${ID}/${REVISION}`)
  assert.equal(body.sources[0].revision, REVISION)
  assert.equal(body.sources[0].files[0].raw_revision, RAW)
  assert.deepEqual(body.sources[0].roles, ["state"])
  assert.equal(body.sources[0].files[0].filename, "state.json")
  assert.equal(body.sources[0].files[0].source_bytes, 17)
  assert.ok(body.capture_started_at <= body.capture_finished_at)
  const encoded = JSON.stringify(body)
  for (const hidden of ["invented-github-token", "invented-password", "INCOMPLETE API TEXT", "Authorization"]) {
    assert.ok(!encoded.includes(hidden))
  }
})

test("same configured Gist has two roles and one capture; distinct Gists use four reads", async () => {
  for (const feedback of [ID, OTHER]) {
    process.env.THEHEAT_FEEDBACK_GIST_ID = feedback
    const wire = transport(), result = await collectGistBackupManifest({ fetchImpl: wire.fetch })
    assert.equal(wire.calls.length, feedback === ID ? 2 : 4)
    assert.equal(result.sources.length, feedback === ID ? 1 : 2)
    assert.deepEqual(result.sources[0].roles, feedback === ID ? ["state", "feedback"] : ["state"])
    assert.equal(result.metadata_requests, wire.calls.length)
  }
})

test("auth, method, query, preview and backend refusals make zero provider reads", async () => {
  let calls = 0; globalThis.fetch = async () => { calls++; throw Error("must not run") }
  assert.equal((await GET(new Request("https://dashboard.example/api/backup-manifest"))).status, 401)
  assert.equal((await HEAD(request("HEAD"))).status, 405)
  assert.equal((await POST(request("POST"))).status, 405)
  assert.equal((await GET(request("GET", "/api/backup-manifest?id=unconfigured"))).status, 400)
  process.env.THEHEAT_STATE_BACKEND = "sqlite"
  assert.equal((await GET(request())).status, 503)
  process.env.THEHEAT_STATE_BACKEND = "gist"
  process.env.THEHEAT_LOCAL_COMMAND_URL = "http://127.0.0.1:3137"
  assert.notEqual((await GET(request())).status, 200)
  assert.equal(calls, 0)
})

test("protected generated host is required when Basic auth is disabled", async () => {
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.VERCEL_URL = "dashboard-backup-invented-project.vercel.app"
  const wire = transport(); globalThis.fetch = wire.fetch
  assert.equal((await GET(request())).status, 307)
  assert.equal(wire.calls.length, 0)
  assert.equal((await GET(request("GET", "/api/backup-manifest", process.env.VERCEL_URL))).status, 200)
})

for (const [name, corrupt] of [
  ["resource", value => { value.id = OTHER }],
  ["revision", value => { value.history[0].version = "3".repeat(40) }],
  ["truncated list", value => { value.truncated = true }],
  ["unknown inventory", value => { delete value.truncated }],
  ["filename", value => { value.files["state.json"].filename = "other.json" }],
  ["raw host", value => { value.files["state.json"].raw_url = value.files["state.json"].raw_url.replace("gist.githubusercontent.com", "attacker.example") }],
  ["raw Gist", value => { value.files["state.json"].raw_url = value.files["state.json"].raw_url.replace(ID, OTHER) }],
  ["raw query", value => { value.files["state.json"].raw_url += "?credential=never-forward" }],
  ["raw filename", value => { value.files["state.json"].raw_url += "-other" }],
  ["raw unpinned", value => { value.files["state.json"].raw_url = value.files["state.json"].raw_url.replace(`/${RAW}/`, "/") }],
  ["negative size", value => { value.files["state.json"].size = -1 }],
  ["oversized file", value => { value.files["state.json"].size = BACKUP_LIMITS.fileBytes + 1 }],
]) {
  test(`pinned ${name} drift refuses complete descriptors`, async () => {
    const wire = transport((value, count) => { if (count === 2) corrupt(value); return value })
    await assert.rejects(collectGistBackupManifest({ fetchImpl: wire.fetch }))
    assert.equal(wire.calls.length, 2)
  })
}

test("provider errors never expose response bodies or thrown credential text", async () => {
  for (const fetch of [async () => new Response("private provider body", { status: 401 }),
    async () => { throw Error("private token and source data") }]) {
    globalThis.fetch = fetch
    const response = await GET(request()), text = await response.text()
    assert.equal(response.status, 503)
    assert.ok(!text.includes("private")); assert.ok(!text.includes("token and source"))
  }
})

test("duplicate metadata keys, oversized metadata and combined inventory bounds hold", async () => {
  const duplicate = JSON.stringify(metadata()).replace('"truncated":false', '"truncated":true,"truncated":false')
  for (const result of [() => new Response(duplicate),
    () => new Response("{}", { headers: { "content-length": String(BACKUP_LIMITS.metadataBytes + 1) } }),
    () => Response.json(metadata(ID, Array.from({ length: 33 }, (_, i) => `file-${i}.json`)))]) {
    await assert.rejects(collectGistBackupManifest({ fetchImpl: async () => result() }))
  }
})

test("deadline holds even when a transport ignores abort; late headers cannot start another read", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] })
  let finish, calls = 0
  const pending = collectGistBackupManifest({ fetchImpl: () => {
    calls++; return new Promise(resolve => { finish = resolve })
  } })
  const refused = assert.rejects(pending, /backup_metadata_deadline/)
  t.mock.timers.tick(BACKUP_LIMITS.metadataMilliseconds + 1)
  await refused
  finish(Response.json(metadata()))
  await Promise.resolve(); await Promise.resolve()
  assert.equal(calls, 1)
})
