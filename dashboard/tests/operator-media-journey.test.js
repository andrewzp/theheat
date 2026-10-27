import test from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { createHash, randomBytes } from "node:crypto"
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs"
import { createServer } from "node:http"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { crc32, deflateSync } from "node:zlib"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }
import { graphicRequest } from "../lib/graphic-preview.js"
import { boundRetainedMediaBlob, jointConfirmations } from "../lib/editor-media.js"
import { fingerprint, initializeRevision, policy, projectDraft } from "./helpers/review-policy.js"
import { JOURNEY_TIMEOUT_MS, READY_PATH, options as launcherOptions, startOwned, superviseJourney, waitOwnedReady }
  from "../../scripts/operator_media_journey.mjs"

// An explicit, finite browser profile mounts the actual DraftWorkbench, which
// mounts the actual GraphicPreview and EditorMedia with their real library
// controllers, in the invented fixture app under fixtures/operator-journey.
// Every draft and API reply here is invented; commands are spies and every
// other API mutation is aborted and reported. A pass is UI evidence only:
// source, PostgreSQL, native, hosted, platform and human approval stay
// unperformed. Run it with scripts/operator_media_journey.mjs; ordinary Node
// runs skip it as unperformed and never start a browser.
const CONFIG = process.env.THEHEAT_OPERATOR_JOURNEY_CONFIG
const SCOPE = "invented_operator_media_journey"
const hash = (value) => createHash("sha256").update(value).digest("hex")
const LONG = "Invented-unbroken-place-name-" + "w".repeat(120)
const unavailable = "The preview is unavailable. Your draft has not changed; try again later."

// Invented drafts: display fixtures only, never qualified source evidence.
function sourceDraft(id, { product = "MODIS_NRT", related = [], raw, local = false, role = "publisher", text } = {}) {
  const bundle = { event_id: `invented:${id}`, signal_kind: "fire", where: `${LONG} ${id}`, when: "2032-01-02",
    raw_signal_dump: raw ?? { source_product: product, acquisition_provenance: { source_product: product } }, related_signals: related }
  const draft = { id, type: "fire", event_id: bundle.event_id, status: "pending", created_at: "2032-01-01T00:00:00Z",
    // Long but breakable tweet text: unbroken tokens stay in place/source/description fields.
    text: text ?? `Invented ${id}: saved thermal detections near an invented place. ${"This invented sentence is long, ordinary and breakable. ".repeat(4)}No physical incident claim.`,
    review_context: { source: "Invented source only", two_bot: { bundle } } }
  const projected = { ...projectDraft(initializeRevision(draft)),
    editorial_policy: { status: "recorded", policy, policy_sha256: fingerprint(policy) }, automatic_publication: { enabled: false } }
  return local ? { ...projected, local_preview: true, operator_role: role } : projected
}
const revise = (draft, n = 2) => ({ ...structuredClone(draft), text: `${draft.text} Revised ${n}.`,
  revision_identity: { ...draft.revision_identity, content_revision: draft.revision_identity.content_revision + n, text_sha256: hash(`${draft.id}:${n}`) } })
const changePolicy = (draft) => ({ ...structuredClone(draft), editorial_policy: { ...draft.editorial_policy, policy_sha256: "f".repeat(64) } })

const TEMPLATES = {
  MODIS_NRT: { template: "modis_thermal_detection_map", version: "p31-modis-locator-2-social", source: "NASA FIRMS · MODIS",
    adapter: "src/media/fire_map_graphic_adapter.py", context: { kind: "modis_acquisition", acquired_at: "2032-02-29T23:59:00Z" } },
  VIIRS_NOAA20_NRT: { template: "viirs_thermal_detection_map", version: "p31-viirs-locator-1", source: "NASA FIRMS · VIIRS",
    adapter: "src/media/viirs_map_graphic_adapter.py", context: { kind: "viirs_acquisition", acquired_at: "2032-02-29T23:58:00Z" } },
}
function previewValue(draft, product = "MODIS_NRT") {
  const request = graphicRequest(draft, manifest), files = manifest.identity.files, template = TEMPLATES[product]
  const binding = { template: template.template, template_version: template.version, source_evidence_sha256: hash(`source:${draft.id}`),
    renderer: { library: "ReportLab", version: "4.4.9", format: "svg", schema_version: 1, width: 1200, height: 1500,
      implementation_sha256: files["src/media/evidence_graphic_render.py"], contract_sha256: files["src/media/evidence_graphic.py"],
      adapter_sha256: files[template.adapter], font_sha256: files["src/media/fonts/DejaVuSansMono.ttf"] } }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1500" viewBox="0 0 1200 1500"><title>${draft.id}</title><rect width="1200" height="1500" fill="#334"/></svg>`
  return { schema_version: 2, draft_id: request.draft_id, revision_identity: request.expected_revision,
    policy_source_sha256: request.expected_policy_source_sha256, preview_runtime_sha256: request.expected_preview_runtime_sha256,
    publication_approved: false, attachment: false, width: 1200, height: 1500, source: template.source, source_context: template.context,
    title: `Invented preview title for ${draft.id} ${LONG}`, alt_text: `Invented complete graphic description for ${draft.id}: ${LONG}. Saved detections only.`,
    scope: `Invented scope for ${draft.id}; ${LONG}`, svg_utf8: svg, svg_sha256: hash(svg), binding, cache_key: fingerprint(binding) }
}

// Minimal truecolor PNG with exact IHDR dimensions.
function png(width, height, rgb) {
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]), out = Buffer.alloc(body.length + 8)
    out.writeUInt32BE(data.length, 0); body.copy(out, 4); out.writeUInt32BE(crc32(body), body.length + 4)
    return out
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header.set([8, 2, 0, 0, 0], 8)
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({ length: width }, () => rgb).flat())])
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(Array.from({ length: height }, () => row)))), chunk("IEND", Buffer.alloc(0))])
}
const IMAGE = png(120, 150, [40, 90, 160]), CHANGED = png(120, 150, [160, 40, 40])
const proposal = (n = 1) => hash(`invented-proposal-${n}`)
function mediaView(draft, overrides = {}, image = IMAGE, n = 1) {
  const packet = { schema_version: 1, packet_sha256: hash(`invented-packet-${n}`), media: { mime_type: "image/png",
    png_sha256: hash(image), byte_count: image.length, width: 120, height: 150,
    alt_text: `Invented complete image description ${n}: ${LONG}. Forecast qualifiers and date stay visible.` } }
  return { draft_id: draft.id, target: { draft_id: draft.id, ...draft.revision_identity }, publication_approved: false,
    local_preview: true, status: "prepared", text: draft.text, source_label: `Invented source label ${LONG}`,
    expected_policy_sha256: "1".repeat(64), expected_renderer_profile_sha256: "2".repeat(64),
    expected_review_sha256: "3".repeat(64), expected_check_completion_sha256: "4".repeat(64),
    preparation: { proposal_sha256: proposal(n) }, packet, review_current: false, checks_status: "not_requested", ...overrides }
}

const deferred = () => { let release; const promise = new Promise((resolve) => { release = resolve }); return { promise, release } }
async function until(predicate, message, ms = 10000) {
  const end = Date.now() + ms
  while (!await predicate()) {
    assert.ok(Date.now() < end, message)
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}

// --- Launcher ownership (ordinary Node, invented loopback children, no browser) ---
const LAUNCHER = fileURLToPath(new URL("../../scripts/operator_media_journey.mjs", import.meta.url))
const scratch = () => realpathSync(mkdtempSync(join(tmpdir(), "operator-launcher-")))
async function listen(handler) {
  const server = createServer(handler)
  await new Promise((done) => server.listen(0, "127.0.0.1", done))
  return { server, port: server.address().port, close: () => new Promise((done) => server.close(done)) }
}
async function freePort() {
  const probe = await listen(() => {})
  await probe.close()
  return probe.port
}
function invented(kind, port) {
  // An invented child: serves the ownership route with its env token, or exits, or fails to bind.
  return { command: process.execPath, argv: ["-e", `
    const http = require("node:http")
    if (${JSON.stringify(kind)} === "exit") process.exit(7)
    const server = http.createServer((request, response) => {
      response.writeHead(200, { "content-type": "application/json" })
      response.end(JSON.stringify(request.url === ${JSON.stringify(READY_PATH)}
        ? { token: ${JSON.stringify(kind)} === "wrong" ? "not-the-token" : process.env.THEHEAT_OPERATOR_JOURNEY_TOKEN } : {}))
    })
    server.on("error", () => process.exit(1))
    server.listen(${port}, "127.0.0.1")`] }
}
function owned(kind, port, token, dir) {
  const { command, argv } = invented(kind, port)
  return startOwned({ command, argv, cwd: dir, env: { PATH: "/usr/bin:/bin", THEHEAT_OPERATOR_JOURNEY_TOKEN: token },
    logPath: join(dir, `${kind}-${randomBytes(4).toString("hex")}.log`) })
}

test("launcher pins and the result directory must be absolute as supplied", () => {
  const dir = scratch(), pin = join(dir, "pin")
  writeFileSync(pin, "invented pin\n")
  const base = ["--result-dir", join(dir, "out"), "--playwright-module", pin, "--chromium", pin]
  assert.deepEqual(launcherOptions(base), { result: join(dir, "out"), playwright: pin, chromium: pin, port: 3291 })
  for (const [index, name] of [[1, "--result-dir"], [3, "--playwright-module"], [5, "--chromium"]]) {
    const relativeArgs = [...base]
    relativeArgs[index] = "relative/pin"
    assert.throws(() => launcherOptions(relativeArgs), new RegExp(`${name} must be an absolute path`))
  }
  assert.throws(() => launcherOptions(base.slice(0, 4)), /explicit pins are required and missing: --chromium/)
  assert.throws(() => launcherOptions([...base.slice(0, 5), join(dir, "missing")]), /--chromium pin does not exist/)
})

test("an occupied port is refused before any build or browser; the foreign listener is untouched", async () => {
  const dir = scratch(), pins = join(dir, "pins")
  mkdirSync(join(pins, "playwright"), { recursive: true })
  writeFileSync(join(pins, "playwright", "index.mjs"), "// invented pin, never imported by a refusal\n")
  writeFileSync(join(pins, "playwright", "package.json"), JSON.stringify({ version: "invented" }))
  writeFileSync(join(pins, "chromium"), "invented pin\n")
  let requests = 0
  const foreign = await listen((request, response) => { requests++; response.end("invented foreign listener") })
  try {
    const result = join(dir, "run")
    const child = spawn(process.execPath, [LAUNCHER, "--result-dir", result, "--playwright-module", join(pins, "playwright", "index.mjs"),
      "--chromium", join(pins, "chromium"), "--port", String(foreign.port)], { env: { PATH: "/usr/bin:/bin" }, stdio: ["ignore", "ignore", "pipe"] })
    let stderr = ""
    child.stderr.on("data", (chunk) => { stderr += chunk })
    const code = await new Promise((done) => child.on("exit", done))
    assert.equal(code, 3)
    assert.match(stderr, new RegExp(`127\\.0\\.0\\.1:${foreign.port} is already in use; refusing to build or start the journey`))
    const receipt = JSON.parse(readFileSync(join(result, "launcher-receipt.json"), "utf8"))
    assert.equal(receipt.failure, "port_occupied")
    assert.equal(receipt.exit_code, 3)
    assert.deepEqual(receipt.steps, [])
    assert.deepEqual(readdirSync(result).sort(), ["home", "launcher-receipt.json", "node_modules", "screens", "tmp"])
    assert.equal(requests, 0, "the launcher sent a request to a foreign listener")
    assert.equal(await (await fetch(`http://127.0.0.1:${foreign.port}/`)).text(), "invented foreign listener")
  } finally { await foreign.close() }
})

test("an owned child that exits or cannot spawn ends readiness, even with a foreign 200 on the port", async () => {
  const dir = scratch(), token = randomBytes(16).toString("hex")
  const foreign = await listen((request, response) => {
    response.writeHead(200, { "content-type": "application/json" })
    response.end(JSON.stringify({ token: "foreign" }))
  })
  try {
    for (const kind of ["exit", "bind"]) {
      const child = owned(kind, foreign.port, token, dir)
      const readiness = await waitOwnedReady({ origin: `http://127.0.0.1:${foreign.port}`, token, owned: child, deadline: Date.now() + 15000 })
      assert.equal(readiness.ready, false)
      assert.equal(readiness.reason, "owned_server_exited")
      assert.equal(readiness.exit.code, kind === "exit" ? 7 : 1)
      assert.equal(child.alive(), false)
      assert.equal(child.stop(), child.stop(), "stop must be idempotent")
      await child.stop()
    }
    const missing = startOwned({ command: join(dir, "no-such-invented-binary"), argv: [], cwd: dir, env: { PATH: "/usr/bin:/bin" },
      logPath: join(dir, "spawn-error.log") })
    const readiness = await waitOwnedReady({ origin: `http://127.0.0.1:${foreign.port}`, token, owned: missing, deadline: Date.now() + 15000 })
    assert.deepEqual([readiness.ready, readiness.reason, readiness.exit.error], [false, "owned_server_exited", "ENOENT"])
    assert.ok(existsSync(join(dir, "spawn-error.log")))
    assert.equal(await (await fetch(`http://127.0.0.1:${foreign.port}/`)).text(), JSON.stringify({ token: "foreign" }))
  } finally { await foreign.close() }
})

test("only the owned child serving its exact token is ready; stop ends it exactly once", async () => {
  const dir = scratch(), token = randomBytes(16).toString("hex")
  const wrongPort = await freePort()
  const wrong = owned("wrong", wrongPort, token, dir)
  try {
    const readiness = await waitOwnedReady({ origin: `http://127.0.0.1:${wrongPort}`, token, owned: wrong, deadline: Date.now() + 2500 })
    assert.deepEqual([readiness.ready, readiness.reason], [false, "owned_token_not_served"])
  } finally { await wrong.stop() }
  const port = await freePort()
  const good = owned("serve", port, token, dir)
  const readiness = await waitOwnedReady({ origin: `http://127.0.0.1:${port}`, token, owned: good, deadline: Date.now() + 15000 })
  assert.deepEqual([readiness.ready, readiness.reason], [true, "owned_token_verified"])
  const first = good.stop(), second = good.stop()
  assert.equal(first, second)
  const exit = await first
  assert.equal(exit.signal, "SIGTERM")
  assert.equal(good.alive(), false)
  await assert.rejects(fetch(`http://127.0.0.1:${port}${READY_PATH}`, { signal: AbortSignal.timeout(2000) }))
})

// --- F5: the outer journey deadline (invented owned children, injected short bound) ---
function lingering(dir, name, termCode, readyDelayMs = 0) {
  // Stays alive until signalled; records each SIGTERM it receives, then exits with termCode.
  return startOwned({ command: process.execPath, argv: ["-e",
    `setTimeout(() => { process.on("SIGTERM", () => { process.stdout.write("term\\n"); process.exit(${termCode}) }); process.stdout.write("ready\\n") }, ${readyDelayMs}); setInterval(() => {}, 1000)`],
  cwd: dir, env: { PATH: "/usr/bin:/bin" }, logPath: join(dir, `${name}.log`) })
}
async function waitForHandlers(dir, entries) {
  try {
    await until(() => entries.every(([name, owned]) => {
      assert.ok(owned.alive(), "invented child exited before installing its signal handler")
      return /^ready$/m.test(readFileSync(join(dir, `${name}.log`), "utf8"))
    }), "invented child did not acknowledge its installed signal handler")
  } catch (error) {
    await Promise.all(entries.map(([, owned]) => owned.stop()))
    throw error
  }
}
function trackedTimers() {
  const active = new Set()
  return { active,
    setTimer: (callback, ms) => { const id = setTimeout(() => { active.delete(id); callback() }, ms); active.add(id); return id },
    clearTimer: (id) => { active.delete(id); clearTimeout(id) } }
}
const terms = (dir, name) => (readFileSync(join(dir, `${name}.log`), "utf8").match(/^term$/gm) || []).length
const exitsAfter = (dir, name, code) => startOwned({ command: process.execPath, argv: ["-e", `process.exit(${code})`], cwd: dir,
  env: { PATH: "/usr/bin:/bin" }, logPath: join(dir, `${name}.log`) })

test("the outer journey deadline ends both owned children and cannot report success", async () => {
  assert.equal(JOURNEY_TIMEOUT_MS, 900000)
  const dir = scratch(), timers = trackedTimers()
  let requests = 0
  const unrelated = await listen((request, response) => { requests++; response.end("invented unrelated listener") })
  try {
    // The journey exits 0 when signalled: a clean-looking exit during cleanup must stay a failure.
    const journey = lingering(dir, "journey", 0), server = lingering(dir, "server", 15)
    await waitForHandlers(dir, [["journey", journey], ["server", server]])
    const started = Date.now()
    const result = await superviseJourney({ journey, server, timeoutMs: 300, setTimer: timers.setTimer, clearTimer: timers.clearTimer })
    assert.ok(Date.now() - started < 10000)
    assert.equal(result.outcome, "journey_timed_out")
    assert.equal(result.success, false)
    assert.equal(result.timeout_ms, 300)
    assert.equal(result.journey_exit.code, 0)
    assert.equal(result.server_exit.code, 15)
    assert.equal(journey.alive(), false)
    assert.equal(server.alive(), false)
    await Promise.all([journey.stop(), server.stop()]) // the caller's later cleanup is idempotent
    assert.deepEqual([terms(dir, "journey"), terms(dir, "server")], [1, 1])
    assert.equal(timers.active.size, 0, "a deadline timer was left behind")
    assert.equal(requests, 0)
    assert.equal(await (await fetch(`http://127.0.0.1:${unrelated.port}/`)).text(), "invented unrelated listener")
  } finally { await unrelated.close() }
})

test("normal completion, journey failure, child error and early server exit clear the deadline", async () => {
  const dir = scratch()
  for (const [name, code, success] of [["passing", 0, true], ["failing", 1, false]]) {
    const timers = trackedTimers(), server = lingering(dir, `server-${name}`, 15)
    await waitForHandlers(dir, [[`server-${name}`, server]])
    const result = await superviseJourney({ journey: exitsAfter(dir, name, code), server, timeoutMs: 60000,
      setTimer: timers.setTimer, clearTimer: timers.clearTimer })
    assert.deepEqual([result.outcome, result.success, result.journey_exit.code], ["completed", success, code])
    assert.equal(server.alive(), true, "completion must leave the server to the caller's single cleanup")
    assert.equal(timers.active.size, 0)
    await server.stop()
    assert.equal(terms(dir, `server-${name}`), 1)
  }
  {
    const timers = trackedTimers(), server = lingering(dir, "server-error", 15)
    await waitForHandlers(dir, [["server-error", server]])
    const missing = startOwned({ command: join(dir, "no-such-invented-journey"), argv: [], cwd: dir, env: { PATH: "/usr/bin:/bin" },
      logPath: join(dir, "journey-error.log") })
    const result = await superviseJourney({ journey: missing, server, timeoutMs: 60000, setTimer: timers.setTimer, clearTimer: timers.clearTimer })
    assert.deepEqual([result.outcome, result.success, result.journey_exit.error], ["completed", false, "ENOENT"])
    assert.equal(timers.active.size, 0)
    await server.stop()
  }
  {
    const timers = trackedTimers(), journey = lingering(dir, "journey-early", 0)
    await waitForHandlers(dir, [["journey-early", journey]])
    const result = await superviseJourney({ journey, server: exitsAfter(dir, "server-early", 3), timeoutMs: 60000,
      setTimer: timers.setTimer, clearTimer: timers.clearTimer })
    assert.deepEqual([result.outcome, result.success, result.server_exit.code], ["owned_server_exited_during_journey", false, 3])
    assert.equal(journey.alive(), false)
    assert.equal(terms(dir, "journey-early"), 1)
    assert.equal(timers.active.size, 0)
  }
  {
    const timers = trackedTimers(), journey = lingering(dir, "journey-exception", 0)
    await waitForHandlers(dir, [["journey-exception", journey]])
    const broken = { exited: Promise.reject(new Error("invented supervision failure")), stop: () => Promise.resolve(null), alive: () => false }
    await assert.rejects(superviseJourney({ journey, server: broken, timeoutMs: 60000, setTimer: timers.setTimer,
      clearTimer: timers.clearTimer }), /invented supervision failure/)
    assert.equal(timers.active.size, 0, "an exception left the deadline timer running")
    await journey.stop()
  }
})

test("an acknowledged delayed handler observes cleanup after a fast journey", async () => {
  const dir = scratch(), timers = trackedTimers(), server = lingering(dir, "delayed-server", 15, 150)
  try {
    await waitForHandlers(dir, [["delayed-server", server]])
    const result = await superviseJourney({ journey: exitsAfter(dir, "fast-journey", 0), server, timeoutMs: 60000,
      setTimer: timers.setTimer, clearTimer: timers.clearTimer })
    assert.deepEqual([result.outcome, result.success], ["completed", true])
    assert.equal(server.alive(), true)
    assert.equal(timers.active.size, 0)
    await server.stop()
    assert.equal(terms(dir, "delayed-server"), 1)
    assert.equal((readFileSync(join(dir, "delayed-server.log"), "utf8").match(/^ready$/gm) || []).length, 1)
  } finally { await server.stop() }
})

// Ordinary Node: the bound loader itself, with an invented response and no browser.
test("joint review image must be the exact packet-bound PNG bytes, size and dimensions", async (t) => {
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const view = mediaView(sourceDraft("bound-unit", { local: true }))
  const serve = (bytes) => { globalThis.fetch = async () => new Response(bytes, { headers: { "content-type": "image/png" } }) }
  serve(IMAGE)
  const blob = await boundRetainedMediaBlob(view, new AbortController().signal)
  assert.deepEqual(Buffer.from(await blob.arrayBuffer()), IMAGE)
  const wrongSize = structuredClone(view); wrongSize.packet.media.width = 121
  for (const [bytes, current] of [[CHANGED, view], [Buffer.concat([IMAGE, Buffer.from([0])]), view], [IMAGE, wrongSize],
    [IMAGE, { ...view, packet: null }]]) {
    serve(bytes)
    await assert.rejects(boundRetainedMediaBlob(current, new AbortController().signal), /does not match this review packet/)
  }
  const aborted = new AbortController(); aborted.abort(); serve(IMAGE)
  await assert.rejects(boundRetainedMediaBlob(view, aborted.signal))
})

test("mounted operator media journey with invented API replies", {
  skip: !CONFIG && "unperformed: explicit browser profile (scripts/operator_media_journey.mjs)",
  timeout: 600000,
}, async (t) => {
  const config = JSON.parse(readFileSync(CONFIG, "utf8"))
  assert.equal(config.scope, SCOPE)
  const missing = ["playwright_entry", "chromium", "origin", "result", "screens"].filter((key) => !config[key]
    || (["playwright_entry", "chromium"].includes(key) && !existsSync(config[key])))
  assert.deepEqual(missing, [], `explicit journey pins missing: ${missing.join(", ")}; the journey is unperformed`)
  assert.match(config.origin, /^http:\/\/127\.0\.0\.1:\d+$/)
  const { chromium } = await import(pathToFileURL(config.playwright_entry).href)
  const origin = config.origin, deadline = Date.now() + 540000
  const evidence = { scope: SCOPE, cases: [], layout: [], page_errors: [], denied: [], mutations: [], console: [], late_fulfill_failures: 0,
    api_reads: 0, preview_posts: 0, bytes_served: 0, screenshots: [] }
  const browser = await chromium.launch({ executablePath: config.chromium, headless: true,
    env: { PATH: "/usr/bin:/bin", TZ: "UTC", LANG: "en_US.UTF-8" },
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] })

  async function scenario(name, setup, run, { width = 1280, transport = null } = {}) {
    assert.ok(Date.now() < deadline, "journey time budget exhausted")
    const api = { name, drafts: setup.drafts, selected: setup.selected, previews: new Map(), views: new Map(), images: new Map(),
      previewRequests: [], viewReads: new Map(), imageReads: 0, injected: [] }
    const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: "block", acceptDownloads: false, permissions: [] })
    const page = await context.newPage(); page.setDefaultTimeout(10000)
    const failures = [], consoles = []
    page.on("pageerror", (error) => { evidence.page_errors.push({ name, error: String(error) }) })
    page.on("console", (message) => { if (["warning", "error"].includes(message.type())) consoles.push({ type: message.type(), text: message.text() }) })
    await context.routeWebSocket(/.*/, (ws) => { evidence.denied.push({ name, url: ws.url() }); ws.close() })
    const fulfill = async (route, init) => {
      try { await route.fulfill(init) } catch { evidence.late_fulfill_failures++ }
      evidence.bytes_served += init.body?.length ?? 0
    }
    const json = (route, status, value) => fulfill(route, { status, contentType: "application/json", body: JSON.stringify(value) })
    await context.route("**/*", async (route) => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== origin) { evidence.denied.push({ name, url: url.origin }); return route.abort("blockedbyclient") }
      if (!url.pathname.startsWith("/api/")) return route.continue()
      try {
        if (request.method() === "POST" && url.pathname === "/api/graphic_preview") {
          // A preview build, not a state mutation; replies are invented here.
          assert.ok(++evidence.preview_posts <= 80, "bounded preview requests")
          const body = request.postDataJSON(); api.previewRequests.push(body)
          const queue = api.previews.get(body.draft_id) || []
          const reply = queue.shift(); assert.ok(reply, `unexpected preview request for ${body.draft_id}`)
          if (reply.hold) await reply.hold.promise
          if (reply.status !== 200) api.injected.push(reply.status)
          return await json(route, reply.status, reply.value)
        }
        if (request.method() !== "GET") {
          evidence.mutations.push({ name, method: request.method(), path: url.pathname })
          return await route.abort("blockedbyclient")
        }
        assert.ok(++evidence.api_reads <= 600, "bounded API reads")
        if (url.pathname === "/api/operator-journey/scenario") return await json(route, 200, { name, drafts: api.drafts, selected: api.selected })
        if (url.pathname === "/api/editor-media") {
          const draftId = url.searchParams.get("draftId"), wanted = url.searchParams.get("proposal")
          if (wanted) {
            api.imageReads++
            const image = api.images.get(wanted) ?? { status: 404 }
            if (image.hold) await image.hold.promise
            if (image.status !== 200) { api.injected.push(image.status); return await json(route, image.status, { code: "invented_missing_image" }) }
            return await fulfill(route, { status: 200, contentType: image.contentType ?? "image/png", body: image.bytes })
          }
          api.viewReads.set(draftId, (api.viewReads.get(draftId) || 0) + 1)
          const view = api.views.get(draftId)
          const value = typeof view === "function" ? view() : view
          if (value?.hold) await value.hold.promise
          return await json(route, 200, value?.view ?? value)
        }
        failures.push(`unexpected API route ${url.pathname}`)
        return await json(route, 404, { code: "invented_unknown_route" })
      } catch (error) { failures.push(String(error)); await route.abort("failed").catch(() => {}) }
    })
    const journal = () => page.evaluate(() => structuredClone(window.__operatorJourney.record))
    const act = (action, value) => page.evaluate(([name, arg]) => window.__operatorJourney.act[name](arg), [action, value])
    const settle = async (frames = 2) => { for (let i = 0; i < frames; i++) await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)))) }
    const queueItem = (id) => page.locator(".queue-item", { hasText: `Invented ${id}:` })
    const liveImages = async () => {
      const record = await journal(), revoked = new Set(record.revoked)
      const displayed = await page.locator("img").evaluateAll((images) => images.map((image) => image.getAttribute("src")))
      return { record, live: record.urls.filter((row) => !revoked.has(row.url)), displayed, revoked }
    }
    try {
      setup.configure?.(api)
      await page.goto(origin + (transport ? `/?transport=${transport}` : "/"))
      await page.locator(`[data-scenario="${name}"]`).waitFor()
      await run({ page, api, act, settle, journal, queueItem, liveImages })
      await settle()
      const urls = await liveImages()
      // Ownership: every revoked URL was created here, once; nothing displayed is revoked or foreign.
      assert.equal(new Set(urls.record.revoked).size, urls.record.revoked.length, "a Blob URL was revoked twice")
      assert.ok(urls.record.revoked.every((url) => urls.record.urls.some((row) => row.url === url)), "revoked a URL it did not create")
      for (const src of urls.displayed.filter((src) => src?.startsWith("blob:"))) {
        assert.ok(urls.live.some((row) => row.url === src), "displayed image uses a revoked or foreign URL")
      }
      assert.ok(urls.live.length <= urls.displayed.filter((src) => src?.startsWith("blob:")).length, "a retained Blob URL leaked")
      const record = await journal()
      assert.deepEqual(record.errors, [])
      for (const row of consoles) {
        const injected = row.type === "error" && api.injected.some((status) => row.text.includes(`status of ${status}`))
        if (!injected) failures.push(`console ${row.type}: ${row.text}`)
        evidence.console.push({ name, ...row, classification: injected ? "exact_injected_http_status" : "unexpected" })
      }
      assert.deepEqual(failures, [])
      evidence.cases.push({ name, width, transport, passed: true, preview_requests: api.previewRequests.length, image_reads: api.imageReads,
        view_reads: Object.fromEntries(api.viewReads), injected: api.injected, spy_calls: record.calls.map((call) => call.name) })
    } catch (error) {
      evidence.cases.push({ name, width, transport, passed: false, failure: String(error?.message || error).slice(0, 2000) })
      throw error
    } finally {
      for (const queue of api.previews.values()) for (const reply of queue) reply.hold?.release()
      await context.close()
    }
  }

  const previewA = sourceDraft("preview-a"), previewB = sourceDraft("preview-b", { product: "VIIRS_NOAA20_NRT" })
  const previewMissing = sourceDraft("preview-missing", { raw: { source_product: "MODIS_NRT" } })
  const previewMixed = sourceDraft("preview-mixed", { related: [{ signal_kind: "fire", acquisition_evidence: { source_product: "VIIRS_NOAA20_NRT" } }] })
  const previews = [previewA, previewB, previewMissing, previewMixed]
  const figureTitle = (page) => page.locator(".graphic-preview-figure figcaption strong")
  const previewStatus = (page) => page.locator(".graphic-preview [role=status]")
  const previewButton = (page) => page.getByRole("button", { name: /^(Preview graphic|Rebuild preview)$/ })
  const sideEffects = async (journal) => (await journal()).calls.filter((call) => ["draftAct", "submitLocalCommand"].includes(call.name))

  try {
    await t.test("late preview A cannot install over selected B; A is never displayed", () => scenario("stale-select", { drafts: previews, selected: "preview-a" }, async (h) => {
      const held = deferred()
      h.api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA), hold: held }])
      h.api.previews.set("preview-b", [{ status: 200, value: previewValue(previewB, "VIIRS_NOAA20_NRT") }])
      await previewButton(h.page).click()
      await previewStatus(h.page).getByText("Building the saved-source preview…").waitFor()
      await h.queueItem("preview-b").click()
      await previewButton(h.page).click()
      await figureTitle(h.page).getByText("Invented preview title for preview-b", { exact: false }).waitFor()
      held.release(); await h.settle(4)
      assert.equal(await h.page.getByText("Invented preview title for preview-a", { exact: false }).count(), 0)
      const urls = await h.liveImages()
      assert.deepEqual(urls.record.urls.map((row) => row.type), ["image/svg+xml"])
      // A late failure for A cannot put its error or controls on B either.
      const failing = deferred()
      h.api.previews.get("preview-a").push({ status: 500, value: { code: "invented" }, hold: failing })
      await h.queueItem("preview-a").click(); await previewButton(h.page).click()
      await previewStatus(h.page).getByText("Building the saved-source preview…").waitFor()
      await h.queueItem("preview-b").click(); failing.release(); await h.settle(4)
      assert.equal(await previewStatus(h.page).getByText(unavailable).count(), 0)
      assert.equal(await h.page.getByRole("button", { name: "Preview graphic", exact: true }).isEnabled(), true)
      assert.deepEqual(await sideEffects(h.journal), [])
    }))

    for (const [label, change] of [["revision", (draft) => revise(draft)], ["policy", changePolicy]]) {
      await t.test(`late preview cannot survive a ${label} change; the next request binds the new identity`, () => scenario(`stale-${label}`, { drafts: previews, selected: "preview-a" }, async (h) => {
        const held = deferred(), changed = change(previewA)
        h.api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA), hold: held }, { status: 200, value: previewValue(changed) }])
        await previewButton(h.page).click()
        await previewStatus(h.page).getByText("Building the saved-source preview…").waitFor()
        await h.act("setDrafts", [changed, ...previews.slice(1)])
        await previewButton(h.page).getByText("Preview graphic").waitFor()
        held.release(); await h.settle(4)
        assert.equal(await figureTitle(h.page).count(), 0)
        assert.equal((await h.liveImages()).record.urls.length, 0)
        await previewButton(h.page).click()
        await figureTitle(h.page).waitFor()
        assert.deepEqual(h.api.previewRequests[1].expected_revision, graphicRequest(changed, manifest).expected_revision)
        assert.equal(h.api.previewRequests.length, 2)
      }))
    }

    await t.test("unmount while building discards the late preview and owns no URL", () => scenario("stale-unmount", { drafts: previews, selected: "preview-a" }, async (h) => {
      const held = deferred()
      h.api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA), hold: held }])
      await previewButton(h.page).click()
      await previewStatus(h.page).getByText("Building the saved-source preview…").waitFor()
      await h.act("setMounted", false); await h.settle()
      held.release(); await h.settle(4)
      await h.act("setMounted", true)
      await previewButton(h.page).getByText("Preview graphic").waitFor()
      assert.equal(await figureTitle(h.page).count(), 0)
      assert.equal((await h.liveImages()).record.urls.length, 0)
    }))

    await t.test("an aborted request whose transport still resolves cannot install", () => scenario("abort-ignoring", { drafts: previews, selected: "preview-a" }, async (h) => {
      const held = deferred()
      h.api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA), hold: held }])
      h.api.previews.set("preview-b", [{ status: 200, value: previewValue(previewB, "VIIRS_NOAA20_NRT") }])
      await previewButton(h.page).click()
      await previewStatus(h.page).getByText("Building the saved-source preview…").waitFor()
      await h.queueItem("preview-b").click(); await h.settle()
      held.release(); await h.settle(6)
      assert.equal(await figureTitle(h.page).count(), 0)
      await previewButton(h.page).click()
      await figureTitle(h.page).getByText("Invented preview title for preview-b", { exact: false }).waitFor()
      const record = await h.journal()
      assert.ok(record.calls.some((call) => call.kind === "transport_signal_ignored"))
      assert.deepEqual(record.urls.map((row) => row.type), ["image/svg+xml"])
    }, { transport: "abort-ignoring" }))

    await t.test("preview states, edit/update transitions and manual retry without automatic retry or side effects", () => scenario("preview-states", { drafts: previews, selected: "preview-a" }, async (h) => {
      const schema = { ...previewValue(previewA), schema_version: 1 }
      h.api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA) }, { status: 409, value: { code: "invented" } },
        { status: 500, value: { code: "invented" } }, { status: 422, value: { code: "invented" } }, { status: 200, value: schema },
        { status: 200, value: previewValue(previewA) }])
      await previewButton(h.page).click()
      await figureTitle(h.page).waitFor()
      assert.equal(await h.page.getByRole("button", { name: "Rebuild preview" }).count(), 1)
      await h.page.getByRole("button", { name: "Edit", exact: true }).click()
      await h.page.getByText("Save or cancel your text edit before building a preview.").waitFor()
      assert.equal(await figureTitle(h.page).count(), 0)
      await h.act("cancelEditing"); await h.act("setUpdating", true)
      await h.page.getByText("Updating this draft. Build a new preview after it finishes.").waitFor()
      await h.act("setUpdating", false)
      await previewButton(h.page).getByText("Preview graphic").waitFor()
      assert.equal(await figureTitle(h.page).count(), 0, "edit/update transition left a stale image")
      for (const message of ["This draft changed or has conflicting versions. Refresh it before previewing.", unavailable,
        "The saved source or display limits cannot support this graphic. No substitute was used.", unavailable]) {
        await previewButton(h.page).click()
        await previewStatus(h.page).getByText(message, { exact: true }).waitFor()
        assert.equal(await figureTitle(h.page).count(), 0)
      }
      const before = h.api.previewRequests.length
      await h.page.waitForTimeout(1500)
      assert.equal(h.api.previewRequests.length, before, "automatic retry after an error")
      await previewButton(h.page).click()
      await figureTitle(h.page).waitFor()
      assert.equal(h.api.previewRequests.length, 6)
      await h.queueItem("preview-missing").click()
      await h.page.getByText("Saved fire source receipts are missing or incomplete. No graphic preview is available for this draft.").waitFor()
      await h.queueItem("preview-mixed").click()
      await h.page.getByText(/The saved source set is unsupported; no preview is available\.$/).waitFor()
      assert.equal(await previewButton(h.page).count(), 0)
      assert.deepEqual(await sideEffects(h.journal), [])
      const startEditing = (await h.journal()).calls.filter((call) => call.name === "startEditing")
      assert.equal(startEditing.length, 1)
    }))

    const mediaA = sourceDraft("media-a", { local: true }), mediaB = sourceDraft("media-b", { local: true })
    // The previously measured case: one 149-character unbroken token in multiline draft copy.
    const longToken = sourceDraft("long-token", { text: `Invented long-token: ${LONG}\nSecond invented line; ordinary copy follows.` })
    const media = [mediaA, mediaB]
    const fieldset = (page) => page.locator(".graphic-preview fieldset")
    const attach = (page) => page.getByRole("button", { name: /^(Attach reviewed graphic|Record new joint review)$/ })
    async function reviewWithKeyboard(h) {
      await fieldset(h.page).locator("legend").click()
      const focus = []
      const boxes = await fieldset(h.page).locator("input[type=checkbox]").count()
      for (let i = 0; i < boxes; i++) {
        await h.page.keyboard.press("Tab"); await h.page.keyboard.press("Space")
        focus.push(await h.page.evaluate(() => {
          const element = document.activeElement, style = getComputedStyle(element)
          return { type: element.type, visible: element.matches(":focus-visible") && style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0 }
        }))
      }
      await h.page.keyboard.press("Tab")
      await h.page.keyboard.type("Invented joint review note; checked image and text together.")
      focus.push(await h.page.evaluate(() => ({ type: document.activeElement.tagName, visible: document.activeElement.matches(":focus-visible")
        && getComputedStyle(document.activeElement).outlineStyle !== "none" })))
      return focus
    }
    const reviewState = (page) => page.evaluate(() => ({
      checked: [...document.querySelectorAll(".graphic-preview fieldset input[type=checkbox]")].map((box) => box.checked),
      note: document.querySelector(".graphic-preview fieldset textarea")?.value ?? null,
    }))
    const imageShown = (page) => page.locator(".graphic-preview-figure img")
    // Playwright never reports a <fieldset> itself as disabled; check it and every control in it.
    const reviewDisabled = (page) => page.evaluate(() => {
      const set = document.querySelector(".graphic-preview fieldset")
      return !!set && set.disabled && [...set.querySelectorAll("input, textarea, button")].every((control) => control.matches(":disabled"))
    })

    for (const [label, image, expected] of [["bound", { status: 200, bytes: IMAGE }, null],
      ["missing", { status: 404 }, "The retained graphic is unavailable"],
      ["corrupt", { status: 200, bytes: Buffer.from("invented bytes that are not a PNG image at all; length over 33") }, "Invalid retained PNG"],
      ["changed", { status: 200, bytes: CHANGED }, "changed"]]) {
      await t.test(`EditorMedia image validation: ${label} image ${expected ? "withholds" : "enables"} joint review`, () => scenario(`image-${label}`, { drafts: media, selected: "media-a",
        configure: (api) => { api.views.set("media-a", mediaView(mediaA)); api.images.set(proposal(1), image) } }, async (h) => {
        await h.page.getByText("Graphic prepared. It is not attached or reviewed yet.").waitFor()
        if (!expected) {
          await imageShown(h.page).waitFor()
          const focus = await reviewWithKeyboard(h)
          assert.ok(focus.every((row) => row.visible), `focus not visible: ${JSON.stringify(focus)}`)
          assert.equal(await attach(h.page).isEnabled(), true)
          await h.page.locator(".graphic-preview details summary").first().focus()
          await h.page.keyboard.press("Enter")
          await h.page.getByText(/^Invented complete image description 1:/).waitFor()
        } else {
          await h.page.waitForFunction(() => document.querySelector(".graphic-preview-figure img")
            || [...document.querySelectorAll(".graphic-preview-figure [role=status]")].some((node) => !node.textContent.startsWith("Loading")))
          await h.settle(4)
          assert.equal(await imageShown(h.page).count(), 0, `${label} image was displayed for joint review`)
          assert.equal(await reviewDisabled(h.page), true, `${label} image enabled joint review`)
          assert.equal(await attach(h.page).isEnabled(), false)
          if (expected !== "changed") await h.page.getByText(expected).waitFor()
        }
        assert.deepEqual(await sideEffects(h.journal), [])
      }))
    }

    const twoMedia = (api) => {
      api.views.set("media-a", mediaView(mediaA)); api.views.set("media-b", mediaView(mediaB, {}, IMAGE, 2))
      api.images.set(proposal(1), { status: 200, bytes: IMAGE }); api.images.set(proposal(2), { status: 200, bytes: IMAGE })
    }
    const fullReview = { checked: [true, true, true, true, true], note: "Invented joint review note; checked image and text together." }
    await t.test("a passive refresh with unchanged identities keeps review inputs and the bound image", () => scenario("passive-refresh", { drafts: media, selected: "media-a", configure: twoMedia }, async (h) => {
      await imageShown(h.page).waitFor(); await reviewWithKeyboard(h)
      assert.deepEqual(await reviewState(h.page), fullReview)
      const reads = h.api.viewReads.get("media-a"), imageReads = h.api.imageReads
      await h.act("passiveRefresh")
      await until(() => h.api.viewReads.get("media-a") > reads, "a passive refresh no longer re-reads the media view")
      await h.settle(6)
      assert.deepEqual(await reviewState(h.page), fullReview, "a passive refresh with unchanged identities erased the operator's review inputs")
      assert.equal(await imageShown(h.page).count(), 1)
      assert.equal(await attach(h.page).isEnabled(), true)
      assert.equal(h.api.imageReads, imageReads, "an unchanged bound image was reloaded")
      // Background check progress still arrives through the same passive refresh.
      h.api.views.set("media-a", mediaView(mediaA, { status: "attached", review_current: true, checks_status: "pending" }))
      await h.act("passiveRefresh")
      await h.page.getByText("Checks are pending. The separate local worker runs one stage at a time.").waitFor()
      h.api.views.set("media-a", mediaView(mediaA, { status: "attached", review_current: true, checks_status: "passed",
        checks: { deterministic: "passed", safety: "passed", fact_check: "passed", critic: "passed" } }))
      await h.act("passiveRefresh")
      await h.page.getByText("All four required checks passed for this text and graphic.").waitFor()
      assert.deepEqual(await sideEffects(h.journal), [])
    }))

    await t.test("review inputs reset on role, proposal, revision, policy and draft changes; a late old view cannot restore them", () => scenario("review-reset", { drafts: media, selected: "media-a",
      configure: (api) => {
        api.views.set("media-a", mediaView(mediaA)); api.views.set("media-b", mediaView(mediaB, {}, IMAGE, 2))
        api.images.set(proposal(1), { status: 200, bytes: IMAGE }); api.images.set(proposal(2), { status: 200, bytes: IMAGE })
      } }, async (h) => {
      const filled = async () => { await imageShown(h.page).waitFor(); await reviewWithKeyboard(h); assert.deepEqual(await reviewState(h.page), { checked: [true, true, true, true, true], note: "Invented joint review note; checked image and text together." }) }
      const empty = { checked: [false, false, false, false, false], note: "" }
      await h.page.getByText("Graphic prepared. It is not attached or reviewed yet.").waitFor()
      await filled()
      // Role change: the permitted reviewer changed, so inputs reset.
      await h.act("setRole", "editor"); await imageShown(h.page).waitFor(); await h.settle(4)
      assert.deepEqual(await reviewState(h.page), empty)
      await filled()
      // A different media proposal for the same revision resets inputs.
      h.api.views.set("media-a", mediaView(mediaA, {}, IMAGE, 3)); h.api.images.set(proposal(3), { status: 200, bytes: IMAGE })
      await h.page.getByRole("button", { name: "Refresh graphic status" }).click()
      await imageShown(h.page).waitFor(); await h.settle(4)
      assert.deepEqual(await reviewState(h.page), empty)
      await filled()
      // Revision change, with the old revision's view arriving late.
      const held = deferred(), revised = revise(mediaA)
      h.api.views.set("media-a", () => ({ view: mediaView(mediaA, {}, IMAGE, 3), hold: held }))
      await h.page.getByRole("button", { name: "Refresh graphic status" }).click(); await h.settle()
      h.api.views.set("media-a", mediaView(revised, {}, IMAGE, 4)); h.api.images.set(proposal(4), { status: 200, bytes: IMAGE })
      await h.act("setDrafts", [{ ...revised, operator_role: "editor" }, { ...mediaB, operator_role: "editor" }])
      await imageShown(h.page).waitFor(); held.release(); await h.settle(6)
      assert.deepEqual(await reviewState(h.page), empty)
      await filled()
      await h.act("setDrafts", [changePolicy({ ...revised, operator_role: "editor" }), { ...mediaB, operator_role: "editor" }])
      await imageShown(h.page).waitFor(); await h.settle(4)
      assert.deepEqual(await reviewState(h.page), empty)
      await filled()
      await h.queueItem("media-b").click(); await imageShown(h.page).waitFor(); await h.settle(4)
      assert.deepEqual(await reviewState(h.page), empty)
      await h.queueItem("media-a").click(); await imageShown(h.page).waitFor(); await h.settle(4)
      assert.deepEqual(await reviewState(h.page), empty)
      assert.deepEqual(await sideEffects(h.journal), [])
    }))

    await t.test("viewer, busy, editing, update-pending and unavailable states keep review controls disabled", () => scenario("disabled-states", { drafts: [{ ...mediaA, operator_role: "viewer" }, mediaB], selected: "media-a",
      configure: (api) => {
        api.views.set("media-a", mediaView(mediaA)); api.views.set("media-b", mediaView(mediaB, { status: "unavailable", code: "media_source_expired", packet: null,
          removal: { expected_proposal_sha256: proposal(2), requested_at: "2032-01-01T00:00:00Z", expires_at: "2032-01-01T00:05:00Z" } }, IMAGE, 2))
        api.images.set(proposal(1), { status: 200, bytes: IMAGE })
      } }, async (h) => {
      await imageShown(h.page).waitFor()
      assert.equal(await reviewDisabled(h.page), true, "viewer can use review controls")
      assert.equal(await attach(h.page).isEnabled(), false)
      assert.equal(await h.page.getByRole("button", { name: "Refresh graphic status" }).isEnabled(), true)
      await h.act("setRole", "editor"); await imageShown(h.page).waitFor()
      await h.act("setUpdating", true)
      await h.page.getByText("Waiting for the local action to finish. Previous review controls are paused.").waitFor()
      assert.equal(await h.page.locator(".graphic-preview fieldset, .graphic-preview img").count(), 0)
      await h.act("setUpdating", false); await h.act("setPending", true)
      await h.page.getByText("Waiting for the local action to finish. Previous review controls are paused.").waitFor()
      await h.act("setPending", false); await imageShown(h.page).waitFor()
      await h.page.getByRole("button", { name: "Edit", exact: true }).click()
      await h.page.getByText("Save or cancel the text edit before reviewing a graphic.").waitFor()
      assert.equal(await h.page.locator(".graphic-preview fieldset, .graphic-preview img").count(), 0)
      await h.act("cancelEditing")
      await h.queueItem("media-b").click()
      await h.page.getByText("Graphic unavailable for this saved revision. media source expired").waitFor()
      assert.equal(await h.page.getByRole("button", { name: /Prepare graphic|Attach reviewed|Park approval|Run fresh checks/ }).count(), 0)
      assert.deepEqual(await sideEffects(h.journal), [])
    }))

    await t.test("prepare → attach → checks → park → cancel → remove use exact spy envelopes for the current target", () => scenario("command-flow", { drafts: media, selected: "media-a",
      configure: (api) => { api.views.set("media-a", mediaView(mediaA, { status: "ready", packet: null, preparation: null })) } }, async (h) => {
      const sent = async (count) => {
        const calls = (await h.journal()).calls.filter((call) => call.name === "submitLocalCommand")
        assert.equal(calls.length, count); return calls.at(-1).args[0]
      }
      const envelope = (saved, action, draft, payload, extra = {}) => {
        assert.deepEqual(Object.keys(saved).sort(), ["action", "command", "draftId"])
        assert.equal(saved.action, action); assert.equal(saved.draftId, draft.id)
        const command = saved.command
        assert.match(command.command_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
        assert.equal(command.action, action)
        assert.deepEqual(command.targets, [{ draft_id: draft.id, ...draft.revision_identity }])
        assert.deepEqual(command.payload, payload)
        if (extra.window) assert.equal(Date.parse(command.expires_at) - Date.parse(command.requested_at), 300000)
        else assert.deepEqual([command.requested_at, command.expires_at], extra.at)
        return command.command_id
      }
      const refresh = () => h.page.getByRole("button", { name: "Refresh graphic status" }).click()
      const ids = new Set()
      await h.page.getByRole("button", { name: "Prepare graphic" }).click()
      ids.add(envelope(await sent(1), "prepare_media_revision", mediaA,
        { expected_policy_sha256: "1".repeat(64), expected_renderer_profile_sha256: "2".repeat(64) }, { window: true }))
      h.api.views.set("media-a", mediaView(mediaA)); h.api.images.set(proposal(1), { status: 200, bytes: IMAGE })
      await refresh(); await imageShown(h.page).waitFor()
      await reviewWithKeyboard(h)
      await attach(h.page).click()
      const view = mediaView(mediaA)
      ids.add(envelope(await sent(2), "attach_media_revision", mediaA, { expected_policy_sha256: "1".repeat(64), proposal_sha256: proposal(1),
        expected_packet_sha256: view.packet.packet_sha256, review: { decision: "accept",
          confirmations: Object.fromEntries(Object.keys(jointConfirmations).map((key) => [key, true])),
          reason: "Invented joint review note; checked image and text together." } }, { window: true }))
      const checksPayload = { expected_policy_sha256: "1".repeat(64), expected_renderer_profile_sha256: "2".repeat(64),
        expected_packet_sha256: view.packet.packet_sha256, expected_review_sha256: "3".repeat(64) }
      h.api.views.set("media-a", mediaView(mediaA, { status: "attached", review_current: true, checks_status: "not_requested" }))
      await refresh(); await h.page.getByText("Joint human review recorded. Run fresh checks before parking approval.").waitFor()
      await h.page.getByRole("button", { name: "Run fresh checks" }).click()
      ids.add(envelope(await sent(3), "request_revision_checks", mediaA, checksPayload, { window: true }))
      h.api.views.set("media-a", mediaView(mediaA, { status: "attached", review_current: true, checks_status: "pending",
        checks: { deterministic: "passed", safety: "pending", fact_check: "pending", critic: "pending" } }))
      await refresh(); await h.page.getByText("Checks are pending. The separate local worker runs one stage at a time.").waitFor()
      assert.equal(await h.page.getByRole("button", { name: /Run fresh checks|Park approval/ }).count(), 0)
      for (const outcome of ["failed", "unknown"]) {
        h.api.views.set("media-a", mediaView(mediaA, { status: "attached", review_current: true, checks_status: outcome,
          checks: { deterministic: "passed", safety: outcome, fact_check: "not_run", critic: "not_run" } }))
        await refresh(); await h.page.locator(".graphic-preview p[role=status]").getByText(outcome, { exact: true }).waitFor()
        assert.equal(await h.page.getByRole("button", { name: "Run fresh checks" }).count(), 1)
        assert.equal(await h.page.getByRole("button", { name: "Park approval locally" }).count(), 0)
      }
      // A revision change between checks: the next command must target only the new revision.
      const revised = revise(mediaA)
      h.api.views.set("media-a", mediaView(revised, { status: "attached", review_current: true, checks_status: "failed" }))
      await h.act("setDrafts", [revised, mediaB])
      await h.page.getByRole("button", { name: "Run fresh checks" }).waitFor(); await h.settle(2)
      await h.page.getByRole("button", { name: "Run fresh checks" }).click()
      ids.add(envelope(await sent(4), "request_revision_checks", revised, checksPayload, { window: true }))
      h.api.views.set("media-a", mediaView(revised, { status: "attached", review_current: true, checks_status: "passed",
        checks: { deterministic: "passed", safety: "passed", fact_check: "passed", critic: "passed" } }))
      await refresh(); await h.page.getByText("All four required checks passed for this text and graphic.").waitFor()
      await h.page.getByRole("button", { name: "Park approval locally" }).click()
      ids.add(envelope(await sent(5), "approve_media_revision", revised, { ...checksPayload,
        expected_check_completion_sha256: "4".repeat(64), reason: "Park the current jointly reviewed local text and graphic." }, { window: true }))
      h.api.views.set("media-a", mediaView(revised, { status: "attached", review_current: true, checks_status: "passed", parked: true }))
      await refresh(); await h.page.getByText("Approval parked for this text and graphic. Nothing will be published.").waitFor()
      await h.page.getByRole("button", { name: "Cancel parked approval" }).click()
      ids.add(envelope(await sent(6), "cancel_approval", revised, { reason: "Cancel the parked local text and graphic approval." }, { window: true }))
      const removal = { expected_proposal_sha256: proposal(1), requested_at: "2032-01-01T00:00:00.000Z", expires_at: "2032-01-01T00:05:00.000Z" }
      h.api.views.set("media-a", mediaView(revised, { status: "unavailable", code: "media_source_expired", packet: null, removal }))
      await refresh(); await h.page.getByRole("button", { name: "Remove graphic" }).click()
      ids.add(envelope(await sent(7), "remove_media_revision", revised, { expected_policy_sha256: "1".repeat(64),
        expected_proposal_sha256: proposal(1), confirmed: true, reason: "Remove this graphic from the local draft." }, { at: [removal.requested_at, removal.expires_at] }))
      assert.equal(ids.size, 7)
      assert.equal((await h.journal()).calls.filter((call) => call.name === "draftAct").length, 0)
    }))

    for (const width of [1280, 390, 320]) {
      await t.test(`reading, keyboard focus and no horizontal overflow at ${width}px`, () => scenario(`layout-${width}`, { drafts: [previewA, mediaA, longToken], selected: "preview-a",
        configure: (api) => {
          api.previews.set("preview-a", [{ status: 200, value: previewValue(previewA) }])
          const view = mediaView(mediaA)
          view.platform_description = { record: { description_sha256: hash("invented-description"), derivation: "full_raw_alt" },
            wire_text: view.packet.media.alt_text + "\n", status: "platform_api_unqualified" }
          api.views.set("media-a", view); api.images.set(proposal(1), { status: 200, bytes: IMAGE })
        } }, async (h) => {
        const problems = []
        await previewButton(h.page).click(); await figureTitle(h.page).waitFor()
        await h.page.locator(".graphic-preview details summary").focus(); await h.page.keyboard.press("Enter")
        await h.page.getByText(/^Invented complete graphic description for preview-a:/).waitFor()
        const summaryFocus = await h.page.evaluate(() => {
          const element = document.activeElement, style = getComputedStyle(element)
          return element.matches(":focus-visible") && style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0
        })
        assert.equal(summaryFocus, true, "preview description summary focus is not visible")
        await h.page.getByText("Preview only; not attached or approved.").waitFor()
        const overflow = () => h.page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth,
          // Diagnostic only: the first elements past the right edge (tag and class, no text).
          offenders: [...document.querySelectorAll("body *")].filter((node) => node.getBoundingClientRect().right > innerWidth + 1)
            .slice(0, 6).map((node) => `${node.tagName.toLowerCase()}.${String(node.className).split(" ")[0]}:${Math.round(node.getBoundingClientRect().right)}`) }))
        let measured = await overflow()
        assert.ok(measured.scroll <= measured.width, `preview overflow ${JSON.stringify(measured)}`)
        const shot = join(config.screens, `${width}-preview.png`)
        await h.page.screenshot({ path: shot, fullPage: true }); evidence.screenshots.push(shot)
        await h.queueItem("media-a").click(); await imageShown(h.page).waitFor()
        const focus = await reviewWithKeyboard(h)
        assert.ok(focus.every((row) => row.visible), `review focus not visible: ${JSON.stringify(focus)}`)
        await h.page.getByText("Human review and model checks are separate. Model cost remains unknown until reconciled. Publishing stays unavailable.").waitFor()
        // X-first, Bluesky deferred: the exact retained description is shown without presenting two active destinations.
        await h.page.getByText(/^Invented complete image description 1:/).first().waitFor({ state: "attached" })
        const copy = await h.page.locator('section[aria-label="Exact platform description"]').innerText()
        if (/Destinations: X and Bluesky/.test(copy)) problems.push("platform description presents X and Bluesky as active destinations")
        if (!/Bluesky rollout is deferred/.test(copy) || !/This local fixture review publishes nothing/.test(copy)) {
          problems.push("platform description does not state the Bluesky deferral and that local review publishes nothing")
        }
        measured = await overflow()
        assert.ok(measured.scroll <= measured.width, `media overflow ${JSON.stringify(measured)}`)
        const second = join(config.screens, `${width}-media.png`)
        await h.page.screenshot({ path: second, fullPage: true }); evidence.screenshots.push(second)
        // The already-identified 149-character unbroken token in the draft text itself.
        await h.queueItem("long-token").click()
        const draftText = h.page.locator(".draft-text")
        await draftText.waitFor()
        const reading = await draftText.evaluate((node) => {
          const selection = getSelection(); selection.removeAllRanges(); selection.selectAllChildren(node)
          const copied = selection.toString(); selection.removeAllRanges()
          const style = getComputedStyle(node)
          return { text: node.textContent, copied, nodeScroll: node.scrollWidth, nodeClient: node.clientWidth,
            pageScroll: document.documentElement.scrollWidth, width: innerWidth, whiteSpace: style.whiteSpace, wrap: style.overflowWrap }
        })
        evidence.layout.push({ width, token_length: LONG.length, ...reading, text: undefined, copied: undefined,
          text_exact: reading.text === longToken.text, copy_keeps_token: reading.copied.includes(LONG) })
        assert.equal(reading.text, longToken.text, "draft text changed")
        assert.ok(reading.copied.includes(LONG), "copying the draft text split the token")
        if (reading.pageScroll > reading.width || reading.nodeScroll > reading.nodeClient + 1) {
          problems.push(`draft text overflow ${JSON.stringify({ pageScroll: reading.pageScroll, width: reading.width, nodeScroll: reading.nodeScroll, nodeClient: reading.nodeClient })}`)
        }
        const third = join(config.screens, `${width}-long-token.png`)
        await h.page.screenshot({ path: third, fullPage: true }); evidence.screenshots.push(third)
        assert.deepEqual(problems, [])
      }, { width }))
    }

    await t.test("EditorMedia replacement and unmount revoke only owned image URLs", () => scenario("media-urls", { drafts: media, selected: "media-a",
      configure: (api) => {
        api.views.set("media-a", mediaView(mediaA)); api.views.set("media-b", mediaView(mediaB, {}, IMAGE, 2))
        api.images.set(proposal(1), { status: 200, bytes: IMAGE }); api.images.set(proposal(2), { status: 200, bytes: IMAGE })
      } }, async (h) => {
      await imageShown(h.page).waitFor()
      await h.queueItem("media-b").click(); await imageShown(h.page).waitFor(); await h.settle(4)
      const held = deferred()
      h.api.images.set(proposal(2), { status: 200, bytes: IMAGE, hold: held })
      await h.page.getByRole("button", { name: "Refresh graphic status" }).click(); await h.settle()
      await h.act("setMounted", false); held.release(); await h.settle(6)
      const urls = await h.liveImages()
      assert.equal(urls.live.length, 0, "unmounted media retained a Blob URL")
      assert.ok(urls.record.urls.every((row) => row.type === "image/png"))
      assert.equal(urls.record.revoked.length, urls.record.urls.length)
    }))
  } finally {
    await browser.close()
    writeFileSync(config.result, JSON.stringify({ ...evidence, SDK_calls: 0, database_calls: 0, hosted_or_human_acceptance: false,
      source_or_platform_qualification: false }, null, 2) + "\n", { flag: "wx", mode: 0o600 })
  }
  assert.ok(evidence.bytes_served <= 8 * 1024 * 1024, "bounded invented bytes")
  assert.deepEqual(evidence.page_errors, [])
  assert.deepEqual(evidence.denied, [])
  assert.deepEqual(evidence.mutations, [])
})
