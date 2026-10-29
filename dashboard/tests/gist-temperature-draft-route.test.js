/** Invented Gist boundary; real Python PNG qualification, route and lossless state writers.
 * No source/model/platform requests: the only fetches are explicitly intercepted below.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import path from "node:path"
import { importFresh } from "./helpers/import-fresh.js"
import { policy, runtimeRun } from "./helpers/review-policy.js"
import { draftIdentity, fingerprint, reviewIsCurrent, approvalIsCurrent } from "../lib/draft-revisions.js"
import { prepareGistTemperatureMedia, validGistTemperatureMedia } from "../lib/gist-temperature-media.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const root = path.resolve(process.cwd(), "..")
const python = process.env.THEHEAT_TEST_PYTHON || "python3"
const digest = bytes => createHash("sha256").update(bytes).digest("hex")
const fixtureCode = `
import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from tests.dashboard_graphic_helpers import saved_temperature_preview
value=json.load(sys.stdin)
state,request=saved_temperature_preview()
draft=state['drafts'][0]
draft.update(content_revision=1,decision_revision=0,event_id=draft['review_context']['two_bot']['bundle']['event_id'],created_at=value['now'])
state.update(run_history=[value['runtime']],publish_ledger={},errors=[])
other=dict(draft,id='invented-secondary')
state['drafts'].append(other)
print(json.dumps(dict(raw_state=json.dumps(state,ensure_ascii=False),raw_bundle=json.dumps(draft['review_context']['two_bot']['bundle'],ensure_ascii=False))))
`
const renderCode = `
import json,sys,socket
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
value=json.load(sys.stdin)
state=json.loads(value['raw_state'])
body=build_preview(value['request'],policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget())
sys.stdout.buffer.write(body)
`
function pythonJSON(code, input) {
  const result = spawnSync(python, ["-c", code], { cwd: root, input: JSON.stringify(input), encoding: "utf8", timeout: 30000,
    env: { PATH: process.env.PATH, HOME: "/nonexistent-invented-gist-test", LC_ALL: "C", LANG: "C", NETRC: "/dev/null",
      PYTHON_DOTENV_DISABLED: "1", PYTHONDONTWRITEBYTECODE: "1", NO_PROXY: "*", no_proxy: "*" } })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}
let fixture
function inventedFixture() {
  fixture ??= pythonJSON(fixtureCode, { now: new Date().toISOString(), runtime: runtimeRun(new Date().toISOString()) })
  return structuredClone(fixture)
}
function revision(draft) { return { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 } }
function body(draft, action, extra = {}) { return { draftId: draft.id, action, expectedRevision: revision(draft), ...extra } }

async function withGist(run, options = {}) {
  const values = inventedFixture()
  let rawState = values.raw_state, patches = [], previews = [], dispatches = [], reads = 0
  const originalFetch = globalThis.fetch
  const keys = ["NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "GIST_ID", "GITHUB_TOKEN", "VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]
  const previous = Object.fromEntries(keys.map(k => [k, process.env[k]]))
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented-reviewer", DASHBOARD_PASSWORD: "invented-password",
    THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "invented-gist-media-route", GITHUB_TOKEN: "invented-not-a-real-token" })
  for (const key of ["VERCEL", "VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"]) delete process.env[key]
  const headers = { "Content-Type": "application/json", Host: "localhost:3000", Authorization: `Basic ${Buffer.from("invented-reviewer:invented-password").toString("base64")}` }
  const state = () => JSON.parse(rawState)
  const get = (id = "invented-station") => state().drafts.find(d => d.id === id)
  function replaceState(value) { rawState = typeof value === "string" ? value : JSON.stringify(value) }
  globalThis.fetch = async (url, request = {}) => {
    url = String(url)
    if (url === "http://localhost:3000/api/graphic_preview") {
      const requestBody = JSON.parse(request.body)
      assert.equal(request.method, "POST"); assert.equal(request.redirect, "error")
      assert.equal(request.headers.Origin, "http://localhost:3000")
      assert.equal(request.headers.authorization, headers.Authorization)
      assert.equal(requestBody.format, "png")
      previews.push(requestBody)
      options.onPreview?.({ state, get, replaceState, previews })
      if (options.previewFailure) return new Response("invented refused preview", { status: 409 })
      const response = pythonJSON(renderCode, { raw_state: rawState, request: requestBody,
        policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
      assert.equal(response.png_sha256, digest(Buffer.from(response.png_base64, "base64")))
      options.changePreview?.(response)
      return new Response(JSON.stringify(response), { headers: { "Content-Type": "application/json" } })
    }
    if (url === "https://api.github.com/gists/invented-gist-media-route") {
      if (request.method === "PATCH") {
        const patch = JSON.parse(request.body)
        assert.deepEqual(Object.keys(patch.files), ["state.json"])
        rawState = patch.files["state.json"].content
        patches.push(rawState)
        assert.ok(!rawState.includes('"png_base64"'), "PNG bytes must never be stored in Gist")
        options.onPatch?.({ state, get, replaceState, patches })
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
    const preview = draft => pythonJSON(renderCode, { raw_state: rawState, request: { draft_id: draft.id, expected_revision: revision(draft),
      expected_policy_source_sha256: manifest.identity.policy_source_sha256, expected_preview_runtime_sha256: manifest.runtime_sha256, format: "png" },
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
    await run({ post, state, get, replaceState, raw: () => rawState, patches, previews, dispatches, preview, rawBundle: values.raw_bundle })
  } finally {
    globalThis.fetch = originalFetch
    for (const key of keys) { if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key] }
  }
}
async function attach(t) {
  const original = t.get(), preview = t.preview(original)
  const result = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  assert.equal(validGistTemperatureMedia(t.get()), true)
  return { original, preview, attached: t.get() }
}
async function joint(t) {
  const current = t.get(), preview = t.preview(current)
  const result = await t.post(body(current, "review", { reviewConfirmed: true, mediaReviewConfirmed: true,
    expectedMediaSha256: preview.media_descriptor_sha256, expectedPolicySha256: fingerprint(policy) }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  return t.get()
}

test("real PNG -> lossless Gist attach -> joint review -> manual approval preserves exact recipe and source", async () => {
  await withGist(async t => {
    const { original, preview, attached } = await attach(t)
    assert.equal(attached.content_revision, original.content_revision + 1)
    assert.equal(attached.decision_revision, original.decision_revision + 1)
    assert.deepEqual(attached.media_attachment, preview.media_descriptor)
    assert.equal(reviewIsCurrent(attached, policy), false)
    assert.ok(t.raw().includes(t.rawBundle), "original source numeric tokens must be retained")
    assert.ok(attached.revision_history.some(row => row.content_revision === original.content_revision
      && fingerprint(row.review_context?.two_bot?.bundle) === fingerprint(original.review_context.two_bot.bundle)))
    const unreviewed = await t.post(body(attached, "approve"))
    assert.equal(unreviewed.status, 409); assert.equal(t.dispatches.length, 0)
    const reviewed = await joint(t)
    assert.equal(reviewed.review_binding.kind, "human_media")
    assert.equal(reviewed.review_binding.media_sha256, fingerprint(preview.media_descriptor))
    assert.equal(reviewIsCurrent(reviewed, policy), true)
    const approved = await t.post(body(reviewed, "approve"))
    assert.equal(approved.status, 200, JSON.stringify(approved.body))
    const saved = t.get()
    assert.equal(approvalIsCurrent(saved, "manual", policy), true)
    assert.deepEqual(saved.media_attachment, preview.media_descriptor)
    assert.equal(t.dispatches.length, 1)
    assert.equal(t.dispatches[0].inputs.publish_intent_id, saved.publish_intent_id)
    assert.equal(t.dispatches[0].inputs.tweet_text, original.text)
    assert.equal((await t.post(body(saved, "approve"))).status, 409)
    assert.equal(t.dispatches.length, 1)
  })
})

test("repeated attach is idempotent; removal changes revision and retains exact prior attachment in history", async () => {
  await withGist(async t => {
    const { preview, attached } = await attach(t)
    assert.equal((await t.post(body(attached, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))).status, 200)
    assert.equal(t.get().content_revision, attached.content_revision)
    assert.equal(t.get().revision_history.length, attached.revision_history.length)
    await joint(t)
    const reviewed = t.get(), removed = await t.post(body(reviewed, "remove_graphic"))
    assert.equal(removed.status, 200, JSON.stringify(removed.body))
    assert.equal(Object.hasOwn(t.get(), "media_attachment"), false)
    assert.equal(t.get().content_revision, reviewed.content_revision + 1)
    assert.equal(reviewIsCurrent(t.get(), policy), false)
    assert.ok(t.get().revision_history.some(row => row.content_revision === reviewed.content_revision
      && row.text === reviewed.text && row.review_binding?.kind === "human_media"
      && fingerprint(row.media_attachment) === fingerprint(preview.media_descriptor)))
    assert.ok(t.raw().includes(t.rawBundle))
    const revisionBefore = revision(t.get())
    assert.equal((await t.post(body(t.get(), "remove_graphic"))).status, 200)
    assert.deepEqual(revision(t.get()), revisionBefore)
    assert.equal(t.dispatches.length, 0)
  })
})

for (const failure of ["missing_checkbox", "missing_hash", "stale_hash", "text_only"]) test(`joint media review refuses ${failure} without write or dispatch`, async () => {
  await withGist(async t => {
    const { preview } = await attach(t)
    const before = t.raw(), count = t.patches.length
    const extra = { reviewConfirmed: true, mediaReviewConfirmed: true, expectedMediaSha256: preview.media_descriptor_sha256, expectedPolicySha256: fingerprint(policy) }
    if (failure === "missing_checkbox" || failure === "text_only") delete extra.mediaReviewConfirmed
    if (failure === "missing_hash") delete extra.expectedMediaSha256
    if (failure === "stale_hash") extra.expectedMediaSha256 = "0".repeat(64)
    const result = await t.post(body(t.get(), "review", extra))
    assert.equal(result.status, 409, JSON.stringify(result.body))
    assert.equal(t.raw(), before); assert.equal(t.patches.length, count); assert.equal(t.dispatches.length, 0)
  })
})

for (const change of ["png", "alt", "draft", "policy", "renderer", "extra_descriptor", "unknown_kind"]) test(`attach rejects changed ${change} response through actual route`, async () => {
  await withGist(async t => {
    const original = t.get(), preview = t.preview(original), before = t.raw()
    const result = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
    assert.equal(result.status, 409, JSON.stringify(result.body)); assert.equal(t.raw(), before)
    assert.equal(t.patches.length, 0); assert.equal(t.dispatches.length, 0)
  }, { changePreview(value) {
    if (change === "png") value.png_base64 = Buffer.from("invented changed bytes").toString("base64")
    if (change === "alt") value.alt_text += " changed"
    if (change === "draft") value.draft_id = "invented-secondary"
    if (change === "policy") value.policy_source_sha256 = "0".repeat(64)
    if (change === "renderer") value.media_descriptor.renderer.implementation_sha256 = "0".repeat(64)
    if (change === "extra_descriptor") value.media_descriptor.url = "https://example.invalid/arbitrary.png"
    if (change === "unknown_kind") value.media_descriptor.kind = "experimental_pg_image"
  } })
})

test("preview refusal and stale draft revision never write an attachment", async () => {
  await withGist(async t => {
    const before = t.raw(), original = t.get(), preview = t.preview(original)
    assert.equal((await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))).status, 409)
    assert.equal(t.raw(), before); assert.equal(t.dispatches.length, 0)
  }, { previewFailure: true })
  await withGist(async t => {
    const original = t.get(), preview = t.preview(original)
    assert.equal((await t.post(body(original, "edit", { editedText: "Invented changed station wording." }))).status, 200)
    const before = t.raw()
    assert.equal((await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))).status, 409)
    assert.equal(t.raw(), before); assert.equal(t.dispatches.length, 0)
  })
})

test("draft switch rechecks the selected draft even when both retained source recipes are identical", async () => {
  await withGist(async t => {
    const preview = t.preview(t.get()), other = t.get("invented-secondary"), before = t.raw()
    // The preview transport returns a real image for the selected second draft,
    // but the client must name exactly its own descriptor/revision, not reuse an old result.
    const result = await t.post(body(other, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
    // Identical retained source recipes can legitimately have the same digest;
    // exact selected draft/revision binding is independently checked by the helper.
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().media_attachment, undefined)
    assert.equal(validGistTemperatureMedia(t.get("invented-secondary")), true)
    assert.notEqual(t.raw(), before)
  })
})

for (const action of ["attach_graphic", "remove_graphic", "review", "approve"]) test(`${action} preserves unresolved send fences and never writes or dispatches`, async () => {
  await withGist(async t => {
    const preview = t.preview(t.get())
    const state = t.state(), selected = state.drafts[0]
    state.publish_ledger[selected.event_id] = { phase: "unknown", publish_intent_id: "invented-unknown-attempt" }
    t.replaceState(state)
    const before = t.raw()
    const result = await t.post(body(t.get(), action, { reviewConfirmed: true, mediaReviewConfirmed: true,
      expectedPolicySha256: fingerprint(policy), expectedMediaSha256: preview.media_descriptor_sha256 }))
    assert.equal(result.status, 409); assert.equal(result.body.code, "publication_unresolved")
    assert.equal(t.raw(), before); assert.equal(t.patches.length, 0); assert.equal(t.previews.length, 0); assert.equal(t.dispatches.length, 0)
  })
})

test("source numeric-token change at confirmation is refused without overwriting the changed Gist", async () => {
  let changed
  await withGist(async t => {
    const preview = t.preview(t.get())
    const result = await t.post(body(t.get(), "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
    assert.equal(result.status, 409, JSON.stringify(result.body))
    assert.equal(t.patches.length, 0); assert.equal(t.dispatches.length, 0)
    assert.equal(t.raw(), changed)
  }, { onRead({ reads, raw, replaceState }) {
    if (reads !== 2) return
    const original = raw()
    changed = original.replace('"lat": 40.0', '"lat": 40')
    assert.notEqual(changed, original, "fixture must retain an actual numeric spelling distinction")
    replaceState(changed)
  } })
})

test("legacy zero revision draft can attach using its explicit projected revision", async () => {
  await withGist(async t => {
    // Preserve the original source JSON and only remove the revision field.
    const raw = t.raw().replace('"content_revision": 1, ', '')
    assert.notEqual(raw, t.raw())
    t.replaceState(raw)
    const preview = t.preview(t.get())
    const result = await t.post(body(t.get(), "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256 }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.equal(t.get().content_revision, 1)
    assert.equal(validGistTemperatureMedia(t.get()), true)
    assert.ok(t.raw().includes(t.rawBundle))
  })
})

test("editing reviewed media invalidates review and stale approval cannot dispatch", async () => {
  await withGist(async t => {
    await attach(t); const reviewed = await joint(t)
    assert.equal((await t.post(body(reviewed, "edit", { editedText: "Invented changed text needs a new joint review." }))).status, 200)
    assert.equal(reviewIsCurrent(t.get(), policy), false)
    assert.equal((await t.post(body(reviewed, "approve"))).status, 409)
    assert.equal((await t.post(body(t.get(), "approve"))).status, 409)
    assert.equal(t.dispatches.length, 0)
    assert.ok(t.get().revision_history.some(row => row.content_revision === reviewed.content_revision
      && row.text === reviewed.text && row.review_binding?.kind === "human_media"))
  })
})

test("caller-supplied media and encoded bytes cannot replace the server-derived descriptor", async () => {
  await withGist(async t => {
    const original = t.get(), preview = t.preview(original)
    const result = await t.post(body(original, "attach_graphic", { expectedMediaSha256: preview.media_descriptor_sha256,
      media_attachment: { kind: "arbitrary", url: "https://example.invalid/pixel", png_sha256: "0".repeat(64) },
      png_base64: Buffer.from("invented caller bytes").toString("base64") }))
    assert.equal(result.status, 200, JSON.stringify(result.body))
    assert.deepEqual(t.get().media_attachment, preview.media_descriptor)
    assert.ok(!t.raw().includes("example.invalid")); assert.equal(t.dispatches.length, 0)
  })
})

for (const [url, host, destination] of [
  ["http://localhost:3388/api/drafts", "127.0.0.1:3388", "http://127.0.0.1:3388"],
  ["http://127.0.0.1:3388/api/drafts", "localhost:3388", "http://localhost:3388"],
  ["http://localhost:3388/api/drafts", "localhost:3388", "http://localhost:3388"],
  ["http://localhost:3388/api/drafts", "127.0.0.1:3389", null],
  ["http://localhost:3388/api/drafts", "example.invalid:3388", null],
  ["http://example.invalid:3388/api/drafts", "127.0.0.1:3388", null],
  ["https://localhost:3388/api/drafts", "127.0.0.1:3388", null],
  ["http://localhost:3388/api/drafts", "127.0.0.1:3388@example.invalid", null],
]) test(`preview origin confines Next normalization ${url} / ${host}`, async () => {
  const previous = process.env.VERCEL; delete process.env.VERCEL
  const calls = []
  try {
    const request = new Request(url, { method: "POST", headers: { Host: host, authorization: "Basic invented" } })
    await assert.rejects(prepareGistTemperatureMedia(request, { id: "invented-origin", text: "Invented text." }, "a".repeat(64), async (url, options) => {
      calls.push(String(url)); assert.equal(options.headers.authorization, "Basic invented")
      assert.equal(options.headers.Origin, destination)
      return new Response("invented refused response", { status: 409 })
    }))
    assert.deepEqual(calls, destination ? [`${destination}/api/graphic_preview`] : [])
  } finally { if (previous === undefined) delete process.env.VERCEL; else process.env.VERCEL = previous }
})

for (const invalid of [null, false, { kind: "unsupported_invented_attachment" }]) test(`present broken attachment ${JSON.stringify(invalid)} can be removed through the actual lossless route`, async () => {
  await withGist(async t => {
    await attach(t)
    const expected = JSON.stringify(t.get().media_attachment), raw = t.raw().replace(expected, JSON.stringify(invalid))
    assert.notEqual(raw, t.raw(), "replace the actual stored descriptor only")
    t.replaceState(raw)
    const before = t.get(), previewCount = t.previews.length
    assert.equal((await t.post(body(before, "approve"))).status, 409)
    assert.equal((await t.post(body(before, "remove_graphic"))).status, 200)
    assert.equal(Object.hasOwn(t.get(), "media_attachment"), false)
    assert.equal(t.previews.length, previewCount, "recovery must not require a usable PNG")
    assert.ok(t.get().revision_history.some(row => Object.hasOwn(row, "media_attachment") && fingerprint(row.media_attachment) === fingerprint(invalid)))
    assert.equal(t.dispatches.length, 0)
    assert.ok(t.raw().includes(t.rawBundle))
  })
})
