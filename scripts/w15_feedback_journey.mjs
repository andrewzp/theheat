#!/usr/bin/env node
// Owned invented-data journey for the W15 operator surfaces: revision feedback (actual
// /api/post-feedback over invented state and private feedback Gists), the Operations post
// history (actual /api/dashboard) and coverage match evidence (an assessment produced here by
// the real scripts/theheat_evaluation.py match-coverage on invented input). Reuses the owned
// process helpers; no source, model, platform or publication request.
//   node scripts/w15_feedback_journey.mjs --result-dir <new absolute private dir> \
//     --playwright-module <abs .../playwright/index.mjs> --chromium <abs binary> [--port 3361]
import { createHash, randomBytes } from "node:crypto"
import { execFileSync } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from "node:fs"
import { createServer } from "node:net"
import { dirname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { options, startOwned, superviseJourney, waitOwnedReady } from "./operator_media_journey.mjs"
const repo = resolve(dirname(fileURLToPath(import.meta.url)), ".."), dashboard = join(repo, "dashboard")
const fixture = join(dashboard, "tests/fixtures/w15-journey")
const selected = options(process.argv.slice(2)), result = selected.result, origin = `http://127.0.0.1:${selected.port}`
if (existsSync(result)) throw new Error("Use a new private result directory")
const probe = createServer()
await new Promise((resolve, reject) => { probe.once("error", reject); probe.listen(selected.port, "127.0.0.1", resolve) })
await new Promise(resolve => probe.close(resolve))
mkdirSync(result, { recursive: true, mode: 0o700 })
for (const dir of ["home", "tmp", "screens", "coverage"]) mkdirSync(join(result, dir), { mode: 0o700 })
symlinkSync(realpathSync(join(dashboard, "node_modules")), join(result, "node_modules"))
// Invented coverage input -> real reference intake and production matching (fresh processes).
const python = process.env.THEHEAT_TEST_PYTHON || "python3", sha = "a".repeat(64), cov = join(result, "coverage")
const ev = (event_id, extra = {}) => ({ event_id, origin: "reference", kind: "physical_event_candidate", source_class: "observed",
  hazards: [{ label: "Heat record", evidence_sha256: sha }], regions: [{ label: "Fictionville", evidence_sha256: sha }],
  event_start: "2026-10-10T00:00:00Z", event_end: "2026-10-11T00:00:00Z", issued_at: null, published_at: null, first_available_at: null,
  label_source: "invented reviewer table", ...extra })
writeFileSync(join(cov, "intake.json"), JSON.stringify({ schema: "theheat.reference-intake/v1", set_id: "fixture-w15-journey", created_at: "2026-10-20T12:00:00Z",
  selection: { scope_label: "Invented", method: "invented_fixture", independent_of_bot_output: false, protocol_document_sha256: "c".repeat(64) },
  comparison_window: { start: null, end: null }, events: [ev("ref-found"), ev("ref-wrong-place", { regions: [{ label: "Nowhereland", evidence_sha256: sha }] })] }))
writeFileSync(join(cov, "state.json"), JSON.stringify({ drafts: [{ id: "synthetic-post", event_id: "synthetic-event", type: "heat_record", status: "posted",
  publish_outcome: "confirmed", tweet_id: "1900000000000000001", city: "Fictionville", text: "Invented: Fictionville reached 49.1C.", content_revision: 1,
  posted_at: "2026-10-10T19:00:00.000Z", created_at: "2026-10-10T18:00:00.000Z", review_context: { source: "invented fixture only" } }], publish_ledger: {} }))
const pyEnv = { PATH: "/usr/bin:/bin", LC_ALL: "C", TZ: "UTC", PYTHONDONTWRITEBYTECODE: "1", HOME: join(result, "home") }
execFileSync(python, [join(repo, "scripts/theheat_evaluation.py"), "reference-intake", "--input", join(cov, "intake.json"), "--retained-at", "2026-10-20T12:00:00Z",
  "--output", join(cov, "record.json")], { cwd: repo, env: pyEnv })
execFileSync(python, [join(repo, "scripts/theheat_evaluation.py"), "match-coverage", "--record", join(cov, "record.json"), "--state", join(cov, "state.json"),
  "--cutoff", "2026-10-20T12:00:00Z", "--evaluated-at", "2026-10-20T13:00:00Z", "--policy-sha256", "f".repeat(64), "--invented-fixture",
  "--output", join(cov, "assessment.json")], { cwd: repo, env: pyEnv })
const env = { PATH: `${dirname(process.execPath)}:/usr/bin:/bin`, HOME: join(result, "home"), TMPDIR: join(result, "tmp"),
  LC_ALL: "C", LANG: "C", TZ: "UTC", NETRC: "/dev/null", NEXT_TELEMETRY_DISABLED: "1", NO_PROXY: "*", no_proxy: "*",
  THEHEAT_W15_JOURNEY_DIST_DIR: relative(fixture, join(result, "next-dist")), THEHEAT_STATE_BACKEND: "gist", GIST_ID: "invented_w15_state",
  THEHEAT_FEEDBACK_GIST_ID: "invented_w15_feedback", GITHUB_TOKEN: "invented-not-a-real-token",
  DASHBOARD_USERNAME: "fixture", DASHBOARD_PASSWORD: "invented", THEHEAT_W15_ASSESSMENT: join(cov, "assessment.json") }
const receipt = { scope: "invented_w15_feedback_outcome_coverage_journey", origin, node: process.version, playwright: selected.playwright,
  chromium: selected.chromium, assessment_sha256: createHash("sha256").update(readFileSync(join(cov, "assessment.json"))).digest("hex"), steps: [] }
const next = join(dashboard, "node_modules/next/dist/bin/next"), token = randomBytes(32).toString("hex")
let server, journey
try {
  const build = startOwned({ command: process.execPath, argv: [next, "build", fixture], cwd: dashboard, env, logPath: join(result, "fixture-build.log") })
  const timer = setTimeout(() => build.stop(), 300000)
  let built
  try { built = await build.exited } finally { clearTimeout(timer) }
  receipt.steps.push({ step: "fixture_build", ...built })
  if (built.code !== 0) throw new Error("Invented fixture build failed")
  server = startOwned({ command: process.execPath, argv: [next, "start", fixture, "-H", "127.0.0.1", "-p", String(selected.port)], cwd: dashboard,
    env: { ...env, THEHEAT_OPERATOR_JOURNEY_TOKEN: token }, logPath: join(result, "fixture-server.log") })
  receipt.readiness = await waitOwnedReady({ origin, token, owned: server, deadline: Date.now() + 30000 })
  if (!receipt.readiness.ready) throw new Error("Owned invented fixture not ready")
  const config = join(result, "journey-config.json")
  writeFileSync(config, JSON.stringify({ origin, playwright: selected.playwright, chromium: selected.chromium, screens: join(result, "screens"),
    result: join(result, "journey-result.json") }), { flag: "wx" })
  journey = startOwned({ command: process.execPath, argv: ["--test", "tests/remaining-campaign-w15-journey.test.js"], cwd: dashboard,
    env: { ...env, THEHEAT_W15_JOURNEY_CONFIG: config }, logPath: join(result, "journey.log") })
  receipt.supervised = await superviseJourney({ journey, server })
  if (!receipt.supervised.success) throw new Error("Invented W15 UI journey failed")
  receipt.passed = true
} catch (error) { receipt.failure = String(error); process.exitCode = 1 }
finally {
  journey?.stop(); server?.stop()
  if (journey) await journey.exited
  if (server) await server.exited
  receipt.logs = Object.fromEntries(["fixture-build.log", "fixture-server.log", "journey.log"].filter(name => existsSync(join(result, name))).map(name => [name, createHash("sha256").update(readFileSync(join(result, name))).digest("hex")]))
  writeFileSync(join(result, "launcher-receipt.json"), JSON.stringify(receipt, null, 2) + "\n", { flag: "wx" })
}
