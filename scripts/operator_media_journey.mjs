#!/usr/bin/env node
// Explicit launcher for the invented mounted operator media journey.
//
// Builds dashboard/tests/fixtures/operator-journey into a NEW private result
// directory, serves it on an owned loopback port, runs
// dashboard/tests/operator-media-journey.test.js against it with headless
// Chromium, then stops the server. Every pin is explicit and absolute: nothing
// is installed, downloaded or discovered from a personal browser profile.
//
//   node scripts/operator_media_journey.mjs --result-dir <new absolute private dir> \
//     --playwright-module <absolute .../playwright/index.mjs> --chromium <absolute Chrome for Testing binary> [--port 3291]
//
// Ownership: the spawned server gets a random per-run token; readiness needs
// that exact token from the fixture's /operator-journey-ready route while the
// child is alive. A child that exits or cannot spawn ends readiness at once,
// and an occupied port is refused before any build. A foreign listener is
// never signalled and its content is never accepted as evidence.
//
// API replies are invented by the test. A pass is UI evidence only: source,
// PostgreSQL, native, hosted, platform and human approval stay unperformed.
import { spawn } from "node:child_process"
import { createHash, randomBytes } from "node:crypto"
import { chmodSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs"
import { createServer } from "node:net"
import { dirname, isAbsolute, join, relative, resolve } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const dashboard = join(repo, "dashboard")
const fixture = join(dashboard, "tests", "fixtures", "operator-journey")
const TEST = "tests/operator-media-journey.test.js"
const SCOPE = "invented_operator_media_journey"
export const READY_PATH = "/operator-journey-ready"

export function options(argv) {
  const known = new Set(["--result-dir", "--playwright-module", "--chromium", "--port"])
  const value = {}
  for (let i = 0; i < argv.length; i += 2) {
    if (!known.has(argv[i]) || argv[i + 1] === undefined || Object.hasOwn(value, argv[i])) {
      throw new Error(`unexpected argument ${JSON.stringify(argv[i])}`)
    }
    value[argv[i]] = argv[i + 1]
  }
  const missing = ["--result-dir", "--playwright-module", "--chromium"].filter((name) => !value[name])
  if (missing.length) throw new Error(`explicit pins are required and missing: ${missing.join(", ")}; the journey stays unperformed`)
  // Absolute as supplied: a relative pin is refused before any normalization.
  for (const name of ["--result-dir", "--playwright-module", "--chromium"]) {
    if (!isAbsolute(value[name])) throw new Error(`${name} must be an absolute path; the journey stays unperformed`)
  }
  for (const name of ["--playwright-module", "--chromium"]) {
    if (!existsSync(value[name])) throw new Error(`${name} pin does not exist: ${value[name]}; the journey stays unperformed`)
  }
  const port = Number(value["--port"] ?? 3291)
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("--port must be an integer from 1024 to 65535")
  return { result: value["--result-dir"], playwright: value["--playwright-module"], chromium: value["--chromium"], port }
}

// A clear early refusal for an occupied port. This bind check is not ownership:
// the port can still be taken before the child binds, which the token covers.
export function portAvailable(port, host = "127.0.0.1") {
  return new Promise((done) => {
    const probe = createServer()
    probe.once("error", () => done(false))
    probe.listen({ port, host, exclusive: true }, () => probe.close(() => done(true)))
  })
}

// Spawn one owned child with its log descriptor; every path closes it exactly once.
export function startOwned({ command, argv, cwd, env, logPath }) {
  const log = openSync(logPath, "wx", 0o600)
  let closed = false
  const closeLog = () => { if (!closed) { closed = true; closeSync(log) } }
  let child
  try {
    child = spawn(command, argv, { cwd, env, stdio: ["ignore", log, log] })
  } finally {
    closeLog() // the child holds its own copy
  }
  let alive = true, outcome = null
  const exited = new Promise((done) => {
    const finish = (value) => { if (!outcome) { outcome = value; alive = false; done(value) } }
    child.once("error", (error) => finish({ code: null, signal: null, error: error.code || "spawn_error" }))
    child.once("exit", (code, signal) => finish({ code, signal, error: null }))
  })
  let stopping = null
  return {
    child, exited,
    alive: () => alive,
    stop() {
      if (!stopping) {
        stopping = (async () => {
          if (!alive) return exited
          child.kill("SIGTERM")
          const timer = setTimeout(() => { if (alive) child.kill("SIGKILL") }, 5000)
          try { return await exited } finally { clearTimeout(timer) }
        })()
      }
      return stopping
    },
  }
}

// Ready only when the owned child is alive AND the origin returns its exact token.
export async function waitOwnedReady({ origin, token, owned, deadline, fetcher = fetch }) {
  const ended = owned.exited.then((value) => ({ ended: value }))
  while (Date.now() < deadline) {
    if (!owned.alive()) return { ready: false, reason: "owned_server_exited", exit: await owned.exited }
    const attempt = (async () => {
      try {
        const response = await fetcher(origin + READY_PATH, { redirect: "error", cache: "no-store", signal: AbortSignal.timeout(2000) })
        if (!response.ok) return { ready: false }
        const value = await response.json()
        return { ready: value?.token === token }
      } catch { return { ready: false } }
    })()
    const result = await Promise.race([attempt, ended])
    if (result.ended) return { ready: false, reason: "owned_server_exited", exit: result.ended }
    if (result.ready && owned.alive()) return { ready: true, reason: "owned_token_verified" }
    await Promise.race([new Promise((resolveWait) => setTimeout(resolveWait, 200)), ended])
  }
  return { ready: false, reason: owned.alive() ? "owned_token_not_served" : "owned_server_exited" }
}

async function main() {
  let selected
  try {
    selected = options(process.argv.slice(2))
  } catch (error) {
    process.stderr.write(`operator media journey: ${error.message}\n`)
    process.exit(2)
  }
  const { result, playwright, chromium, port } = selected
  const nextBin = join(dashboard, "node_modules", "next", "dist", "bin", "next")
  if (!existsSync(nextBin)) {
    process.stderr.write("operator media journey: dashboard/node_modules is missing; link the locked dependency set first (no install is performed)\n")
    process.exit(2)
  }
  if (existsSync(result)) {
    process.stderr.write(`operator media journey: result directory already exists: ${result}\n`)
    process.exit(2)
  }
  mkdirSync(result, { recursive: true, mode: 0o700 })
  chmodSync(result, 0o700)
  for (const folder of ["home", "tmp", "screens"]) mkdirSync(join(result, folder), { mode: 0o700 })
  // The private build resolves the same locked packages through this link; nothing is installed.
  symlinkSync(realpathSync(join(dashboard, "node_modules")), join(result, "node_modules"))

  const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex")
  const version = (path) => JSON.parse(readFileSync(path, "utf8")).version
  const sources = [
    "app/components/DraftWorkbench.js", "app/components/GraphicPreview.js", "app/components/EditorMedia.js",
    "lib/graphic-preview.js", "lib/editor-media.js", "app/dashboard.css", TEST,
    "tests/fixtures/operator-journey/app/page.js", "tests/fixtures/operator-journey/app/layout.js",
    "tests/fixtures/operator-journey/app/operator-journey-ready/route.js",
    "tests/fixtures/operator-journey/next.config.mjs", "package-lock.json",
  ]
  const receipt = {
    scope: SCOPE, node: process.execPath, node_version: process.version,
    next_version: version(join(dashboard, "node_modules", "next", "package.json")),
    react_version: version(join(dashboard, "node_modules", "react", "package.json")),
    playwright_module: playwright, playwright_version: version(join(dirname(playwright), "package.json")),
    chromium, origin: `http://127.0.0.1:${port}`,
    source_sha256: Object.fromEntries(sources.map((path) => [path, sha256(join(dashboard, path))])),
    steps: [], api_writes_permitted: 0, hosted_or_human_acceptance: false,
  }
  const writeReceipt = () => writeFileSync(join(result, "launcher-receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx", mode: 0o600 })

  if (!await portAvailable(port)) {
    receipt.failure = "port_occupied"
    receipt.exit_code = 3
    writeReceipt()
    process.stderr.write(`operator media journey: 127.0.0.1:${port} is already in use; refusing to build or start the journey\n`)
    process.exit(3)
  }

  const token = randomBytes(32).toString("hex")
  const environment = {
    PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, HOME: join(result, "home"), TMPDIR: join(result, "tmp"),
    LC_ALL: "C", LANG: "C", TZ: "UTC", NEXT_TELEMETRY_DISABLED: "1", NETRC: "/dev/null", NO_PROXY: "*", no_proxy: "*",
    THEHEAT_OPERATOR_JOURNEY_DIST_DIR: relative(fixture, join(result, "next-dist")),
  }

  async function run(label, argv, { env = environment, timeoutMs }) {
    const started = Date.now()
    const owned = startOwned({ command: process.execPath, argv, cwd: dashboard, env, logPath: join(result, `${label}.log`) })
    const timer = setTimeout(() => owned.stop(), timeoutMs)
    const exit = await owned.exited
    clearTimeout(timer)
    const step = { label, argv, cwd: dashboard, code: exit.code, signal: exit.signal, error: exit.error,
      seconds: (Date.now() - started) / 1000, log_sha256: sha256(join(result, `${label}.log`)) }
    receipt.steps.push(step)
    return step
  }

  let server = null, exitCode = 1
  try {
    const build = await run("fixture-build", [nextBin, "build", fixture], { timeoutMs: 300000 })
    if (build.code !== 0) throw new Error("fixture build failed")
    server = startOwned({ command: process.execPath, argv: [nextBin, "start", fixture, "-H", "127.0.0.1", "-p", String(port)],
      cwd: dashboard, env: { ...environment, THEHEAT_OPERATOR_JOURNEY_TOKEN: token }, logPath: join(result, "fixture-server.log") })
    const readiness = await waitOwnedReady({ origin: receipt.origin, token, owned: server, deadline: Date.now() + 30000 })
    receipt.readiness = { ready: readiness.ready, reason: readiness.reason, ...(readiness.exit ? { server_exit: readiness.exit } : {}) }
    if (!readiness.ready) throw new Error(`owned fixture server not ready: ${readiness.reason}`)
    const config = join(result, "journey-config.json")
    writeFileSync(config, JSON.stringify({ scope: SCOPE, origin: receipt.origin, playwright_entry: playwright, chromium,
      result: join(result, "journey-result.json"), screens: join(result, "screens") }, null, 2) + "\n", { flag: "wx", mode: 0o600 })
    const started = Date.now()
    const journey = startOwned({ command: process.execPath, argv: ["--test", "--test-concurrency=1", TEST], cwd: dashboard,
      env: { ...environment, THEHEAT_OPERATOR_JOURNEY_CONFIG: config }, logPath: join(result, "journey.log") })
    // The journey's lifetime is bound to the owned server: if the server ends first, the journey is stopped.
    const first = await Promise.race([journey.exited.then((exit) => ({ journey: exit })), server.exited.then((exit) => ({ server: exit }))])
    if (first.server) {
      receipt.failure = "owned_server_exited_during_journey"
      receipt.server_exit = first.server
      await journey.stop()
    }
    const exit = await journey.exited
    receipt.steps.push({ label: "journey", argv: ["--test", "--test-concurrency=1", TEST], cwd: dashboard, code: exit.code,
      signal: exit.signal, error: exit.error, seconds: (Date.now() - started) / 1000, log_sha256: sha256(join(result, "journey.log")) })
    exitCode = exit.code === 0 && !first.server ? 0 : 1
  } catch (error) {
    receipt.failure = receipt.failure ?? String(error?.message || error)
  } finally {
    if (server) {
      receipt.server_exit = receipt.server_exit ?? await server.stop()
      receipt.server_stopped = true
    }
    receipt.exit_code = exitCode
    writeReceipt()
  }
  process.exit(exitCode)
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main()
