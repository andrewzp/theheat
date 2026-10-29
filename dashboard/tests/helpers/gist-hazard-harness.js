/** Invented Gist harness for the new hazard image families. The actual drafts route,
 * revision/lossless writers and the real Python PNG preview run; the only fetches are
 * the explicitly intercepted Gist, preview and workflow-dispatch requests below.
 * Shared by the route tests and the cross-language fake-X journey.
 */
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import path from "node:path"
import { importFresh } from "./import-fresh.js"
import { policy, runtimeRun } from "./review-policy.js"
import { draftIdentity, fingerprint } from "../../lib/draft-revisions.js"
import { validGistMedia } from "../../lib/gist-media.js"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }

export const FAMILIES = (process.env.THEHEAT_GIST_HAZARD_FAMILIES || "pm25,modis,viirs").split(",")
const root = path.resolve(new URL("../../..", import.meta.url).pathname)
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const digest = bytes => createHash("sha256").update(bytes).digest("hex")
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const fixtureCode = trap + `
value=json.load(sys.stdin)
if value['family'] in ('crw','radar','cone'):
    from tests.gist_store_helpers import CLOCKS, saved_state
else:
    from tests.gist_hazard_helpers import CLOCKS, saved_state
state=saved_state(value['family'],runtime=value['runtime'])
print(json.dumps(dict(raw_state=json.dumps(state,ensure_ascii=False),clocks=CLOCKS[value['family']],
  raw_bundle=json.dumps(state['drafts'][0]['review_context']['two_bot']['bundle'],ensure_ascii=False))))
`
const renderCode = trap + `
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin)
state=json.loads(value['raw_state'])
sys.stdout.buffer.write(build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
`
export function pythonJSON(code, input) {
  const result = spawnSync(python, ["-c", code], { cwd: root, input: JSON.stringify(input), encoding: "utf8", timeout: 60000,
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-gist-test", LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
      PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*",
      // The invented local media store for store-backed families (never a credential).
      ...(process.env.THEHEAT_MEDIA_STORE ? { THEHEAT_MEDIA_STORE: process.env.THEHEAT_MEDIA_STORE } : {}) },
    maxBuffer: 16 * 1024 * 1024 })
  assert.equal(result.status, 0, JSON.stringify({ stderr: result.stderr?.slice(-4000), signal: result.signal }))
  return JSON.parse(result.stdout)
}
const fixtures = {}
// The invented bot report is re-stamped textually whenever the invented clock moves;
// re-serializing the whole state would change retained source number spellings.
const SENTINEL = "2000-01-01T00:00:00.000Z"
function inventedFixture(family, editorialPolicy = null) {
  // A journey into the Python sender passes Python's own current policy, as the
  // deployed bot's runtime report would; route-only tests use the fixed test policy.
  const runtime = runtimeRun(SENTINEL)
  if (editorialPolicy) runtime.runtime_inventory.editorial_policy = structuredClone(editorialPolicy)
  const key = `${family}:${fingerprint(runtime)}`
  fixtures[key] ??= pythonJSON(fixtureCode, { family, runtime })
  return structuredClone(fixtures[key])
}
export const revision = draft => ({ ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 })
export const body = (draft, action, extra = {}) => ({ draftId: draft.id, action, expectedRevision: revision(draft), ...extra })

export async function withGist(family, run, options = {}) {
  const values = inventedFixture(family, options.editorialPolicy)
  let patches = [], previews = [], dispatches = [], reads = 0
  const originalFetch = globalThis.fetch, originalNow = Date.now
  const keys = ["NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "GIST_ID", "GITHUB_TOKEN", "VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]
  const previous = Object.fromEntries(keys.map(k => [k, process.env[k]]))
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented-reviewer", DASHBOARD_PASSWORD: "invented-password",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "invented-gist-hazard-route", GITHUB_TOKEN: "invented-not-a-real-token" })
  for (const key of ["VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]) delete process.env[key]
  const clock = { current: Date.parse(values.clocks[0]), expired: Date.parse(values.clocks[1]) }
  let now = clock.current, stamp = new Date(now - 60000).toISOString()
  let rawState = values.raw_state.split(SENTINEL).join(stamp)
  Date.now = () => now
  const headers = { "Content-Type": "application/json", Host: "localhost:3000", Authorization: `Basic ${Buffer.from("invented-reviewer:invented-password").toString("base64")}` }
  const state = () => JSON.parse(rawState)
  const primary = `invented-${family}`
  const get = (id = primary) => state().drafts.find(d => d.id === id)
  const replaceState = value => { rawState = typeof value === "string" ? value : JSON.stringify(value) }
  const render = request => pythonJSON(renderCode, { raw_state: rawState, request,
    policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
  globalThis.fetch = async (url, request = {}) => {
    url = String(url)
    if (url === "http://localhost:3000/api/graphic_preview") {
      const requestBody = JSON.parse(request.body)
      assert.equal(request.method, "POST"); assert.equal(request.redirect, "error")
      assert.equal(request.headers.Origin, "http://localhost:3000")
      assert.equal(request.headers.authorization, headers.Authorization)
      assert.equal(requestBody.format, "png")
      previews.push(requestBody)
      if (options.previewFailure) return new Response("invented refused preview", { status: 422 })
      const response = render(requestBody)
      assert.equal(response.png_sha256, digest(Buffer.from(response.png_base64, "base64")))
      options.changePreview?.(response)
      return new Response(JSON.stringify(response), { headers: { "Content-Type": "application/json" } })
    }
    if (url === "https://api.github.com/gists/invented-gist-hazard-route") {
      if (request.method === "PATCH") {
        const patch = JSON.parse(request.body)
        assert.deepEqual(Object.keys(patch.files), ["state.json"])
        rawState = patch.files["state.json"].content
        patches.push(rawState)
        assert.ok(!rawState.includes('"png_base64"') && !rawState.includes("iVBORw0KGgo"), "PNG bytes must never be stored in Gist")
        return new Response("{}")
      }
      assert.ok(!request.method || request.method === "GET")
      reads++
      options.onRead?.({ state, get, replaceState, raw: () => rawState, reads })
      return new Response(JSON.stringify({ files: { "state.json": { content: rawState } } }))
    }
    if (url === "https://api.github.com/repos/andrewzp/theheat/actions/workflows/bot.yml/dispatches") {
      assert.equal(request.method, "POST")
      dispatches.push(JSON.parse(request.body))
      return new Response(null, { status: 204 })
    }
    assert.fail(`Unexpected external request: ${url}`)
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    async function post(value) {
      const response = await route.POST(new Request("http://localhost:3000/api/drafts", { method: "POST", headers, body: JSON.stringify(value) }))
      return { status: response.status, body: await response.json() }
    }
    async function list() {
      const response = await route.GET(new Request("http://localhost:3000/api/drafts", { headers }))
      return (await response.json()).drafts
    }
    const preview = (draft, retained = options.retainedInput) => render({ draft_id: draft.id, expected_revision: revision(draft),
      expected_policy_source_sha256: manifest.identity.policy_source_sha256, expected_preview_runtime_sha256: manifest.runtime_sha256, format: "png",
      ...(retained ? { retained_input_sha256: retained } : {}) })
    const at = value => {
      now = typeof value === "number" ? value : Date.parse(value)
      const next = new Date(now - 60000).toISOString()
      rawState = rawState.split(stamp).join(next); stamp = next
    }
    await run({ post, list, state, get, replaceState, raw: () => rawState, patches, previews, dispatches, preview, clock, at,
      primary, secondary: `${primary}-secondary`, rawBundle: values.raw_bundle, retainedInput: options.retainedInput ?? null })
  } finally {
    globalThis.fetch = originalFetch; Date.now = originalNow
    for (const key of keys) { if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key] }
  }
}

const retainedBody = t => t.retainedInput ? { retainedInputSha256: t.retainedInput } : {}
export const attestationsFor = preview => preview.schema_version === 5
  ? { publishedAttestations: Object.fromEntries(preview.inspection.required_attestations.map(row => [row.name, true])) } : {}
export async function attach(t, id = t.primary) {
  const original = t.get(id), preview = t.preview(original)
  const result = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256, ...retainedBody(t) }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  assert.equal(validGistMedia(t.get(id)), true)
  return { original, preview, attached: t.get(id) }
}
export async function joint(t, id = t.primary) {
  const current = t.get(id), preview = t.preview(current)
  const result = await t.post(body(current, "review", { reviewConfirmed: true, mediaReviewConfirmed: true,
    expectedMediaSha256: preview.media_descriptor_sha256, expectedPolicySha256: fingerprint(policy), ...attestationsFor(preview) }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  return t.get(id)
}
