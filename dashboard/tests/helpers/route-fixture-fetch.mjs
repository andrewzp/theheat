// OFFLINE FIXTURE ONLY (P00c proofs). Preloaded with `node --import` into independently
// started client/consumer processes. It replaces globalThis.fetch with a file-backed model of
// the GitHub Gist REST semantics the route depends on: a GET returns every file's whole
// content; a PATCH replaces each named file wholesale (null deletes) with NO server merge.
// Each request is atomic (a mkdir lock held only for that request, like one GitHub API call),
// never across requests, so an ordinary GET->PATCH writer can interleave with another.
// An explicit interleaving hook (a barrier after a process's Nth state-Gist GET) forces that
// interleaving. No network, no credentials, no real GitHub.
import { mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync, existsSync, appendFileSync } from "node:fs"
import path from "node:path"

const ROOT = process.env.ROUTE_FIXTURE_ROOT
if (!ROOT) throw new Error("ROUTE_FIXTURE_ROOT is required for the offline route fixture")
const STATE_GIST = process.env.GIST_ID || ""
let stateGets = 0

function sleepSync(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms) }

function withLock(name, run) {
  const lock = path.join(ROOT, "locks", `${name}.lock`)
  mkdirSync(path.dirname(lock), { recursive: true })
  const deadline = Date.now() + 20000
  while (true) {
    try { mkdirSync(lock); break } catch (error) {
      if (error.code !== "EEXIST" || Date.now() > deadline) throw error
      sleepSync(2)
    }
  }
  try { return run() } finally { rmSync(lock, { recursive: true, force: true }) }
}

function gistPath(id) { return path.join(ROOT, "gists", `${id}.json`) }
function log(event) { appendFileSync(path.join(ROOT, "events.jsonl"), JSON.stringify({ pid: process.pid, role: process.env.ROUTE_FIXTURE_ROLE || "", ...event }) + "\n") }

function readGist(id) {
  return withLock(`gist-${id}`, () => JSON.parse(readFileSync(gistPath(id), "utf8")))
}

function patchGist(id, files) {
  return withLock(`gist-${id}`, () => {
    const gist = JSON.parse(readFileSync(gistPath(id), "utf8"))
    for (const [name, value] of Object.entries(files)) {
      if (value === null) delete gist.files[name]
      else gist.files[name] = { content: value.content }
    }
    gist.version += 1
    const tmp = `${gistPath(id)}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(gist))
    renameSync(tmp, gistPath(id))
    return gist.version
  })
}

function barrier() {
  const spec = process.env.ROUTE_FIXTURE_BARRIER
  if (!spec) return
  const [dir, parties, timeoutMs, afterGet] = spec.split("|")
  if (stateGets !== Number(afterGet)) return
  mkdirSync(dir, { recursive: true })
  writeFileSync(path.join(dir, `arrived-${process.pid}`), "")
  const deadline = Date.now() + Number(timeoutMs)
  while (readdirSync(dir).filter(name => name.startsWith("arrived-")).length < Number(parties)) {
    if (Date.now() > deadline) { log({ event: "barrier_timeout" }); return }
    sleepSync(5)
  }
  log({ event: "barrier_passed" })
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
}

globalThis.fetch = async (url, init = {}) => {
  const target = new URL(String(url))
  const method = (init.method || "GET").toUpperCase()
  const gist = target.pathname.match(/^\/gists\/([A-Za-z0-9_]+)$/)
  if (target.hostname === "api.github.com" && gist) {
    const id = gist[1]
    if (!existsSync(gistPath(id))) return json({ message: "Not Found" }, 404)
    if (method === "GET") {
      const value = readGist(id)
      if (id === STATE_GIST) { stateGets += 1; log({ event: "get", gist: id, version: value.version, n: stateGets }) }
      const files = Object.fromEntries(Object.entries(value.files).map(([name, file]) =>
        [name, { filename: name, content: file.content, truncated: false, raw_url: `https://gist.githubusercontent.com/fixture/${id}/raw/${name}` }]))
      const response = json({ id, public: false, files })
      if (id === STATE_GIST) barrier()
      return response
    }
    if (method === "PATCH") {
      const body = JSON.parse(init.body)
      if (process.env.ROUTE_FIXTURE_EXIT_BEFORE_PATCH === "1") { log({ event: "exit_before_patch" }); process.exit(96) }
      const version = patchGist(id, body.files)
      log({ event: "patch", gist: id, version, files: Object.keys(body.files).sort() })
      if (process.env.ROUTE_FIXTURE_EXIT_AFTER_PATCH === "1") { log({ event: "exit_after_patch" }); process.exit(97) }
      return json({ id })
    }
  }
  const dispatch = target.pathname.match(/^\/repos\/[^/]+\/[^/]+\/actions\/workflows\/([^/]+)\/dispatches$/)
  if (target.hostname === "api.github.com" && dispatch && method === "POST") {
    const dir = path.join(ROOT, "dispatches")
    mkdirSync(dir, { recursive: true })
    const name = `${Date.now()}-${process.pid}-${Math.random().toString(16).slice(2)}.json`
    writeFileSync(path.join(dir, name), JSON.stringify({ workflow: dispatch[1], body: JSON.parse(init.body) }))
    log({ event: "dispatch", workflow: dispatch[1] })
    if (process.env.ROUTE_FIXTURE_LOSE_DISPATCH_RESPONSE === "1") throw new TypeError("fetch failed")
    return new Response(null, { status: 204 })
  }
  if (target.hostname === "api.github.com" && /^\/repos\/[^/]+\/[^/]+\/actions\/artifacts$/.test(target.pathname) && method === "GET") {
    const dir = path.join(ROOT, "artifacts")
    const artifacts = existsSync(dir) ? readdirSync(dir).filter(n => n.endsWith(".json")).map(n => JSON.parse(readFileSync(path.join(dir, n), "utf8"))) : []
    return json({ total_count: artifacts.length, artifacts })
  }
  throw new Error(`Offline route fixture refuses ${method} ${target.hostname}${target.pathname}`)
}
