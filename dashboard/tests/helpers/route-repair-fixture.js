// OFFLINE FIXTURE (P00c v2 repair proofs): the REAL Next handlers, the REAL Python admission CLI
// (child process, no key) and the REAL Node consumer over the in-process whole-file Gist model.
// Invented data and an invented test seal key only; no network, credentials or GitHub.
import { execFileSync } from "node:child_process"
import { mkdtempSync, readdirSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { createHash } from "node:crypto"
import { importFresh } from "./import-fresh.js"
import { installMemoryGist, ROUTE_ACTIVATION, routeConsumerEnv, routeEnv, routeRecord, TEST_SEAL_KEY } from "./route-memory-gist.js"
import { policy, runtimeRun, initializeRevision, draftIdentity, textHash, fingerprint } from "./review-policy.js"
import { consumeGistCommands } from "../../lib/gist-command-consumer.js"
import { ROUTE_FILE, RESULTS_FILE } from "../../lib/gist-write-route.js"

export const ROOT = fileURLToPath(new URL("../../..", import.meta.url))
// The non-secret repository variables the admit job receives (configured key ids).
export const ADMISSION_KIDS = { THEHEAT_COMMAND_SEAL_KID: "k-test", THEHEAT_ROUTE_CONTROL_KID: "k-ctl-test" }
export const sha = text => createHash("sha256").update(text, "utf8").digest("hex")
export const auth = { authorization: `Basic ${Buffer.from("reviewer:invented-pass").toString("base64")}` }
export const identity = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
export const entry = (raw, extra = {}) => ({ raw, admission: { command_id: JSON.parse(raw).command_id, digest: sha(raw) }, source: "test", ...extra })

export function seed(count = 2, mutate = () => {}) {
  const drafts = Array.from({ length: count }, (_, index) => {
    const id = `draft_route_${index + 1}`
    const draft = { id, event_id: `event_${id}`, type: "hot10", status: "pending", text: `Invented City ${index + 1} reached 40°C today.`,
      created_at: "2026-10-30T12:00:00Z", score: { total: 60 }, approval_policy: { can_auto_approve: true, recommended_delay_minutes: 30 },
      review_context: { source: "invented observations", two_bot: { bundle: { event_id: `event_${id}`, headline_value: 40 },
        fact_check: { passed: true, extracted_claims: [{ kind: "measurement", value: 40 }] }, critic: { passed: true } } } }
    const proof = draft.review_context.two_bot
    proof.reviewed_text_sha256 = textHash(draft.text)
    proof.reviewed_policy_sha256 = fingerprint(policy)
    proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
    return initializeRevision(draft)
  })
  const state = { drafts, publish_ledger: {}, errors: [], run_history: [runtimeRun(new Date().toISOString())] }
  mutate(state)
  return state
}

// Route ACTIVE by default: variable serialized + active record + dashboard seal key.
export async function withRoute(initial, run, { variable = "serialized", record = routeRecord(), key = TEST_SEAL_KEY, gist: options = {} } = {}) {
  const restore = routeEnv({ ...(variable ? { THEHEAT_GIST_WRITE_ROUTE: variable } : {}), ...(key ? { THEHEAT_COMMAND_SEAL_KEY: key } : {}) })
  const gist = installMemoryGist({ ...options, gists: { routestategist: { "state.json": JSON.stringify(initial), ...(record ? { [ROUTE_FILE]: record } : {}) },
    routefeedbackgist: {} } })
  try { return await run(gist) } finally { gist.restore(); restore() }
}

export async function post(route, body, extra = {}) {
  const handler = await importFresh(route)
  const response = await handler.POST(new Request("http://localhost/api/x", { method: "POST",
    headers: { ...auth, "Content-Type": "application/json", origin: "http://localhost", "sec-fetch-site": "same-origin", ...extra }, body: JSON.stringify(body) }))
  return { status: response.status, body: await response.json() }
}

export async function commandStatus(id, digest = null) {
  const handler = await importFresh("app/api/commands/[id]/route.js")
  const response = await handler.GET(new Request(`http://localhost/api/commands/${id}${digest ? `?digest=${digest}` : ""}`, { headers: auth }), { params: Promise.resolve({ id }) })
  return { status: response.status, body: await response.json() }
}

// The REAL Python admission CLI on the exact dispatched bytes (it holds no key).
export function admit(raw) {
  const out = path.join(mkdtempSync(path.join(tmpdir(), "route-repair-")), "artifact")
  const stdout = execFileSync(process.env.THEHEAT_TEST_PYTHON || "python3", ["-m", "src.commands.gist_commands", "admit", "--out", out], { cwd: ROOT,
    env: { PATH: process.env.PATH, LC_ALL: "C", TZ: "UTC", PYTHONDONTWRITEBYTECODE: "1", THEHEAT_COMMAND_INPUT: raw, ...ADMISSION_KIDS }, encoding: "utf8" })
  const result = JSON.parse(stdout)
  const files = result.admitted ? Object.fromEntries(readdirSync(out).map(name => [name, readFileSync(path.join(out, name), "utf8")])) : {}
  return { result, files }
}

export async function consume(entries, env = {}, options = {}) {
  const keys = [...Object.keys(routeConsumerEnv), ...Object.keys(env)]
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  Object.assign(process.env, routeConsumerEnv, env)
  for (const [key, value] of Object.entries(env)) if (value === undefined) delete process.env[key]
  try { return await consumeGistCommands(entries, options) } finally {
    for (const key of keys) { if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key] }
  }
}

export async function withConsumerEnv(env, run) {
  const keys = [...Object.keys(routeConsumerEnv), ...Object.keys(env)]
  const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
  Object.assign(process.env, routeConsumerEnv, env)
  try { return await run() } finally { for (const key of keys) { if (saved[key] === undefined) delete process.env[key]; else process.env[key] = saved[key] } }
}

export const stateOf = gist => JSON.parse(gist.store.routestategist["state.json"])
export const byId = (gist, id) => stateOf(gist).drafts.find(draft => draft.id === id)
export const resultsDoc = (gist, id = "routestategist") => JSON.parse(gist.store[id][RESULTS_FILE] ?? '{"schema_version":1,"results":{}}')
export { ROUTE_ACTIVATION, routeRecord, TEST_SEAL_KEY }
