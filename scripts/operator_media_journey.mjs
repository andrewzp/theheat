#!/usr/bin/env node
// Explicit launcher for the invented mounted operator media journey.
//
// Builds dashboard/tests/fixtures/operator-journey into a NEW private result
// directory, serves it on an owned loopback port, runs
// dashboard/tests/operator-media-journey.test.js against it with headless
// Chromium, then stops the server. Every pin is explicit: nothing is
// installed, downloaded or discovered from a personal browser profile.
//
//   node scripts/operator_media_journey.mjs --result-dir <new private dir> \
//     --playwright-module <.../playwright/index.mjs> --chromium <Chrome for Testing binary> [--port 3291]
//
// API replies are invented by the test. A pass is UI evidence only: source,
// PostgreSQL, native, hosted, platform and human approval stay unperformed.
import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import { chmodSync, existsSync, mkdirSync, openSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs"
import { dirname, isAbsolute, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const dashboard = join(repo, "dashboard")
const fixture = join(dashboard, "tests", "fixtures", "operator-journey")
const TEST = "tests/operator-media-journey.test.js"
const SCOPE = "invented_operator_media_journey"

function fail(message, code = 2) {
  process.stderr.write(`operator media journey: ${message}\n`)
  process.exit(code)
}

function options(argv) {
  const known = new Set(["--result-dir", "--playwright-module", "--chromium", "--port"])
  const value = {}
  for (let i = 0; i < argv.length; i += 2) {
    if (!known.has(argv[i]) || argv[i + 1] === undefined || Object.hasOwn(value, argv[i])) fail(`unexpected argument ${JSON.stringify(argv[i])}`)
    value[argv[i]] = argv[i + 1]
  }
  return value
}

const args = options(process.argv.slice(2))
const missing = ["--result-dir", "--playwright-module", "--chromium"].filter((name) => !args[name])
if (missing.length) fail(`explicit pins are required and missing: ${missing.join(", ")}; the journey stays unperformed`)
const result = resolve(args["--result-dir"])
const playwright = resolve(args["--playwright-module"])
const chromium = resolve(args["--chromium"])
const port = Number(args["--port"] ?? 3291)
if (!Number.isInteger(port) || port < 1024 || port > 65535) fail("--port must be an integer from 1024 to 65535")
for (const [name, path] of [["--playwright-module", playwright], ["--chromium", chromium]]) {
  if (!isAbsolute(path) || !existsSync(path)) fail(`${name} pin does not exist: ${path}; the journey stays unperformed`)
}
const nextBin = join(dashboard, "node_modules", "next", "dist", "bin", "next")
if (!existsSync(nextBin)) fail("dashboard/node_modules is missing; link the locked dependency set first (no install is performed)")
if (existsSync(result)) fail(`result directory already exists: ${result}`)
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
const environment = {
  PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, HOME: join(result, "home"), TMPDIR: join(result, "tmp"),
  LC_ALL: "C", LANG: "C", TZ: "UTC", NEXT_TELEMETRY_DISABLED: "1", NETRC: "/dev/null", NO_PROXY: "*", no_proxy: "*",
  THEHEAT_OPERATOR_JOURNEY_DIST_DIR: relative(fixture, join(result, "next-dist")),
}

function run(label, command, argv, { cwd, env = environment, timeoutMs }) {
  return new Promise((done) => {
    const started = Date.now(), log = openSync(join(result, `${label}.log`), "wx", 0o600)
    const child = spawn(command, argv, { cwd, env, stdio: ["ignore", log, log] })
    const timer = setTimeout(() => child.kill("SIGKILL"), timeoutMs)
    child.on("exit", (code, signal) => {
      clearTimeout(timer)
      const step = { label, argv, cwd, code, signal, seconds: (Date.now() - started) / 1000,
        log_sha256: sha256(join(result, `${label}.log`)) }
      receipt.steps.push(step)
      done(step)
    })
  })
}

async function ready(origin, deadline) {
  while (Date.now() < deadline) {
    try {
      const response = await fetch(origin, { redirect: "error", signal: AbortSignal.timeout(2000) })
      if (response.ok) return true
    } catch { /* not listening yet */ }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250))
  }
  return false
}

let server = null, exitCode = 1
try {
  const build = await run("fixture-build", process.execPath, [nextBin, "build", fixture], { cwd: dashboard, timeoutMs: 300000 })
  if (build.code !== 0) throw new Error("fixture build failed")
  const serverLog = openSync(join(result, "fixture-server.log"), "wx", 0o600)
  server = spawn(process.execPath, [nextBin, "start", fixture, "-H", "127.0.0.1", "-p", String(port)],
    { cwd: dashboard, env: environment, stdio: ["ignore", serverLog, serverLog] })
  if (!await ready(receipt.origin, Date.now() + 30000)) throw new Error("fixture server did not become ready")
  const config = join(result, "journey-config.json")
  writeFileSync(config, JSON.stringify({ scope: SCOPE, origin: receipt.origin, playwright_entry: playwright, chromium,
    result: join(result, "journey-result.json"), screens: join(result, "screens") }, null, 2) + "\n", { flag: "wx", mode: 0o600 })
  const journey = await run("journey", process.execPath, ["--test", "--test-concurrency=1", TEST],
    { cwd: dashboard, env: { ...environment, THEHEAT_OPERATOR_JOURNEY_CONFIG: config }, timeoutMs: 900000 })
  exitCode = journey.code === 0 ? 0 : 1
} catch (error) {
  receipt.failure = String(error?.message || error)
} finally {
  if (server) {
    server.kill("SIGTERM")
    await new Promise((resolveStop) => {
      const timer = setTimeout(() => { server.kill("SIGKILL"); resolveStop() }, 5000)
      server.on("exit", () => { clearTimeout(timer); resolveStop() })
    })
    receipt.server_stopped = true
  }
  receipt.exit_code = exitCode
  writeFileSync(join(result, "launcher-receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx", mode: 0o600 })
}
process.exit(exitCode)
