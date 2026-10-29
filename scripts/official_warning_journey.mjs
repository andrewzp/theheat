#!/usr/bin/env node
// New invented-data journey using established owned-process supervision.
import { createHash, randomBytes } from "node:crypto"
import { existsSync, mkdirSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs"
import { dirname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { options, portAvailable, startOwned, superviseJourney, waitOwnedReady } from "./operator_media_journey.mjs"
const root = resolve(dirname(fileURLToPath(import.meta.url)), ".."), dashboard = join(root, "dashboard")
const fixture = join(dashboard, "tests/fixtures/official-warning-journey"), selected = options(process.argv.slice(2))
const result = selected.result, origin = `http://127.0.0.1:${selected.port}`
if (existsSync(result)) throw new Error("Use a new private result directory")
if (!await portAvailable(selected.port)) throw new Error("Local fixture port is occupied; nothing was started")
mkdirSync(result, { recursive: true, mode: 0o700 })
for (const name of ["home", "tmp", "screens"]) mkdirSync(join(result, name), { mode: 0o700 })
symlinkSync(realpathSync(join(dashboard, "node_modules")), join(result, "node_modules"))
const env = { PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, HOME: join(result, "home"), TMPDIR: join(result, "tmp"),
  LC_ALL: "C", LANG: "C", TZ: "UTC", NETRC: "/dev/null", NEXT_TELEMETRY_DISABLED: "1", NO_PROXY: "*", no_proxy: "*",
  THEHEAT_WARNING_JOURNEY_DIST_DIR: relative(fixture, join(result, "next-dist")), THEHEAT_WARNING_JOURNEY_ROOT: root,
  THEHEAT_STATE_BACKEND: "gist", GIST_ID: "invented-warning-journey", DASHBOARD_USERNAME: "fixture", DASHBOARD_PASSWORD: "invented",
  THEHEAT_TEST_PYTHON: process.env.THEHEAT_TEST_PYTHON }
const receipt = { scope: "invented_official_warning_journey", origin, node: process.version, playwright: selected.playwright, chromium: selected.chromium, steps: [] }
const next = join(dashboard, "node_modules/next/dist/bin/next"), token = randomBytes(32).toString("hex")
let server, journey
try {
  const build = startOwned({ command: process.execPath, argv: [next, "build", fixture], cwd: dashboard, env, logPath: join(result, "fixture-build.log") })
  let buildTimedOut = false
  const timer = setTimeout(() => { buildTimedOut = true; build.stop() }, 300000)
  let built
  try { built = await build.exited } finally { clearTimeout(timer) }
  receipt.steps.push({ step: "fixture_build", ...built, timed_out: buildTimedOut })
  if (buildTimedOut || built.code !== 0) throw new Error("Invented fixture build failed")
  server = startOwned({ command: process.execPath, argv: [next, "start", fixture, "-H", "127.0.0.1", "-p", String(selected.port)], cwd: dashboard,
    env: { ...env, THEHEAT_OPERATOR_JOURNEY_TOKEN: token }, logPath: join(result, "fixture-server.log") })
  receipt.readiness = await waitOwnedReady({ origin, token, owned: server, deadline: Date.now() + 30000 })
  if (!receipt.readiness.ready) throw new Error("Owned warning fixture not ready")
  const config = join(result, "journey-config.json")
  writeFileSync(config, JSON.stringify({ origin, playwright: selected.playwright, chromium: selected.chromium, screens: join(result, "screens"), result: join(result, "journey-result.json") }), { flag: "wx" })
  journey = startOwned({ command: process.execPath, argv: ["--test", "tests/official-warning-journey.test.js"], cwd: dashboard,
    env: { ...env, THEHEAT_WARNING_JOURNEY_CONFIG: config }, logPath: join(result, "journey.log") })
  receipt.supervised = await superviseJourney({ journey, server })
  if (!receipt.supervised.success) throw new Error("Invented warning UI journey failed")
  receipt.passed = true
} catch (error) { receipt.failure = String(error); process.exitCode = 1 }
finally {
  journey?.stop(); server?.stop()
  if (journey) await journey.exited
  if (server) await server.exited
  receipt.logs = Object.fromEntries(["fixture-build.log", "fixture-server.log", "journey.log"].filter(name => existsSync(join(result, name))).map(name => [name, createHash("sha256").update(readFileSync(join(result, name))).digest("hex")]))
  writeFileSync(join(result, "launcher-receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx" })
}
