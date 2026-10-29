import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { importFresh } from "./helpers/import-fresh.js"
import { createDraftCommand } from "../lib/draft-command-request.js"
import { draftIdentity, initializeRevision, invalidateText, projectDraft } from "../lib/draft-revisions.js"
import { parseGistDocument, stringifyGistDocument } from "../lib/lossless-gist.js"
const fixture = JSON.parse(readFileSync(new URL("../../tests/fixtures/operator_claim_references.json", import.meta.url)))
function draft(id = fixture.bundle.event_id) {
  return initializeRevision({ id, event_id: fixture.bundle.event_id, type: fixture.bundle.signal_kind, text: fixture.text, status: "pending",
    review_context: { source: "Invented fixture", two_bot: { bundle: structuredClone(fixture.bundle) } } })
}
const expected = d => ({ ...draftIdentity(d), decision_revision: d.decision_revision })

test("paired references-only, omitted, remove, changed and reverted edits preserve exact history and media", () => {
  const d = draft(); d.media_attachment = { invented: "retained recipe" }; d.media_review_binding = { old: "joint decision" }
  d.review_binding = { old: "review" }; d.approval_binding = { old: "approval" }; d.publish_intent_id = "invented-intent"
  d.review_context.two_bot.fact_check = { passed: null, unknown: true }
  const before = structuredClone(d)
  invalidateText(d, d.text, fixture.items)
  assert.equal(d.content_revision, before.content_revision + 1)
  assert.equal(d.decision_revision, before.decision_revision + 1)
  for (const key of ["review_binding", "approval_binding", "publish_intent_id", "media_review_binding"]) assert.ok(!Object.hasOwn(d, key))
  assert.deepEqual(d.media_attachment, before.media_attachment)
  assert.deepEqual(d.review_context.two_bot, { bundle: fixture.bundle })
  const saved = structuredClone(d)
  invalidateText(d, d.text); assert.deepEqual(d, saved)
  invalidateText(d, d.text, fixture.items); assert.deepEqual(d, saved)
  invalidateText(d, d.text, [])
  assert.ok(!Object.hasOwn(d.review_context, "operator_claim_references"))
  assert.equal(projectDraft(d).operator_claim_reference_history.at(-1).operator_claim_reference_view.status, "saved")
  invalidateText(d, d.text, fixture.items)
  invalidateText(d, d.text + ".")
  invalidateText(d, fixture.text)
  assert.equal(projectDraft(d).operator_claim_reference_view.status, "missing")
  assert.deepEqual(d.review_context.two_bot.bundle, fixture.bundle)
})

test("reference edits preserve exact Gist numeric source spellings and immutable history", () => {
  const raw = JSON.stringify({ drafts: [draft()] }).replace('"value":40', '"value":40.0')
  const document = parseGistDocument(raw), state = structuredClone(document.value)
  invalidateText(state.drafts[0], fixture.text, fixture.items)
  const saved = stringifyGistDocument(state, document)
  assert.ok(saved.includes('"value":40.0'))
  assert.equal((saved.match(/"value":40\.0/g) || []).length, 2)
  for (const change of [d => d.content_revision--, d => d.review_binding = { forged: true }, d => delete d.revision_history,
    d => d.review_context.two_bot.fact_check = { passed: true }, d => d.auto_approve_requested_at = "2032-01-01T00:00:00Z",
    d => d.review_context.operator_claim_references.items[0].sources[0].value_sha256 = "f".repeat(64),
    d => d.revision_history[0].review_context.two_bot.bundle.current_facts[0].value = 99]) {
    const changed = structuredClone(state); change(changed.drafts[0])
    assert.throws(() => stringifyGistDocument(changed, document), { code: "state_evidence_preservation" })
  }
  const persisted = parseGistDocument(saved), edited = structuredClone(persisted.value)
  invalidateText(edited.drafts[0], fixture.text, [])
  const historical = edited.drafts[0].revision_history[1]
  historical.review_context.operator_claim_references.items[0].claim.text = "forged historical connection"
  assert.throws(() => stringifyGistDocument(edited, persisted), { code: "state_evidence_preservation" })
})

async function withStore(run, hooks = {}) {
  const env = { ...process.env }, original = globalThis.fetch
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "fixture", DASHBOARD_PASSWORD: "invented", THEHEAT_STATE_BACKEND: "gist", GIST_ID: "invented-reference-store" })
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  let state = { drafts: [draft()], publish_ledger: {}, run_history: [] }, writes = 0, reads = 0
  globalThis.fetch = async (url, request = {}) => {
    assert.equal(new URL(url).hostname, "api.github.com")
    assert.ok(!String(url).includes("dispatches"), "edits must never dispatch publication")
    if (request.method === "PATCH") {
      state = JSON.parse(JSON.parse(request.body).files["state.json"].content); writes++
      return Response.json({})
    }
    hooks.onRead?.(state, ++reads)
    return Response.json({ files: { "state.json": { content: JSON.stringify(state) } } })
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    const headers = { "Content-Type": "application/json", authorization: "Basic " + Buffer.from("fixture:invented").toString("base64") }
    const postRaw = async body => {
      const response = await route.POST(new Request("http://localhost/api/drafts", { method: "POST", headers, body }))
      return { status: response.status, body: await response.json() }
    }
    const post = body => postRaw(JSON.stringify(body))
    await run({ state: () => state, writes: () => writes, post, postRaw,
      get: async () => (await route.GET(new Request("http://localhost/api/drafts", { headers }))).json() })
  } finally {
    globalThis.fetch = original
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(env, key)) delete process.env[key]
    Object.assign(process.env, env)
  }
}
function edit(d, more = {}) { return { action: "edit", draftId: d.id, editedText: d.text, expectedRevision: expected(d), ...more } }

test("real Gist edit/GET handlers save, refresh, remove and retain historical references without dispatch", async () => {
  await withStore(async ({ post, state, get }) => {
    const initial = structuredClone(state().drafts[0])
    const saved = await post(edit(initial, { operator_claim_references: fixture.items }))
    assert.equal(saved.status, 200, JSON.stringify(saved.body))
    assert.equal(saved.body.draft.operator_claim_reference_view.status, "saved")
    assert.deepEqual(state().drafts[0].review_context.operator_claim_references, fixture.saved)
    assert.equal((await get()).drafts[0].operator_claim_reference_view.status, "saved")
    const current = structuredClone(state().drafts[0])
    assert.equal((await post(edit(current))).status, 200)
    assert.equal(state().drafts[0].content_revision, current.content_revision)
    const removed = await post(edit(current, { operator_claim_references: [] }))
    assert.equal(removed.status, 200)
    assert.equal(removed.body.draft.operator_claim_reference_view.status, "missing")
    assert.equal(removed.body.draft.operator_claim_reference_history.at(-1).operator_claim_reference_view.status, "saved")
  })
})

test("bad pointers/digests and current publication uncertainty fail before any Gist write", async () => {
  await withStore(async ({ post, state, writes }) => {
    const initial = structuredClone(state())
    for (const change of [items => items[0].sources[0].pointer = "/current_facts/64", items => items[0].sources[0].value_sha256 = "a".repeat(64), items => items[0].claim.text = "stale quote"]) {
      const items = structuredClone(fixture.items); change(items)
      assert.equal((await post(edit(state().drafts[0], { operator_claim_references: items }))).status, 422)
      assert.deepEqual(state(), initial); assert.equal(writes(), 0)
    }
    state().drafts[0].publish_outcome = "unknown"
    assert.equal((await post(edit(state().drafts[0], { operator_claim_references: fixture.items }))).status, 409)
    assert.equal(writes(), 0)
  })
})

test("duplicate or escaped-equivalent JSON reference keys are refused before a Gist write", async () => {
  await withStore(async ({ postRaw, state, writes }) => {
    const body = JSON.stringify(edit(state().drafts[0], { operator_claim_references: fixture.items }))
    const before = structuredClone(state())
    for (const duplicate of ['"pointer":"/current_facts/1","pointer":"/current_facts/0"', '"pointer":"/current_facts/1","\\u0070ointer":"/current_facts/0"']) {
      const raw = body.replace('"pointer":"/current_facts/0"', duplicate)
      assert.equal((await postRaw(raw)).status, 400)
      assert.equal(writes(), 0); assert.deepEqual(state(), before)
    }
  })
})

test("stale source or decision between Gist reads preserves the newer record", async () => {
  for (const change of [d => d.review_context.two_bot.bundle.current_facts[0].value = 99, d => d.decision_revision++]) {
    await withStore(async ({ post, state, writes }) => {
      const result = await post(edit(state().drafts[0], { operator_claim_references: fixture.items }))
      assert.equal(result.status, 409); assert.equal(writes(), 0)
      assert.ok(!Object.hasOwn(state().drafts[0].review_context, "operator_claim_references"))
    }, { onRead(state, n) { if (n === 2) change(state.drafts[0]) } })
  }
})

test("local command construction preserves explicit references and omission without digest injection", () => {
  const d = projectDraft(draft())
  const command = createDraftCommand(d, "edit", { editedText: d.text, operator_claim_references: fixture.items })
  assert.deepEqual(command.payload, { text: d.text, operator_claim_references: fixture.items })
  command.payload.operator_claim_references[0].claim.text = "changed copy"
  assert.notEqual(command.payload.operator_claim_references[0].claim.text, fixture.items[0].claim.text)
  assert.ok(!Object.hasOwn(createDraftCommand(d, "edit", { editedText: d.text }).payload, "operator_claim_references"))
})

test("actual preview route forwards the optional reference command before Gist handling", async () => {
  const env = { ...process.env }, original = globalThis.fetch, calls = []
  Object.assign(process.env, { NODE_ENV: "test", DASHBOARD_AUTH_DISABLED: "1", THEHEAT_LOCAL_COMMAND_URL: "http://127.0.0.1:3999" })
  for (const key of ["GIST_ID", "GITHUB_TOKEN", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD"]) delete process.env[key]
  const command = createDraftCommand(projectDraft(draft()), "edit", { editedText: fixture.text, operator_claim_references: fixture.items })
  const raw = JSON.stringify(command)
  globalThis.fetch = async (url, request) => {
    calls.push(String(url)); assert.equal(Buffer.from(request.body).toString(), raw)
    return Response.json({ status: "accepted", command_id: command.command_id }, { status: 202 })
  }
  try {
    const route = await importFresh("app/api/drafts/route.js")
    const response = await route.POST(new Request("http://127.0.0.1:3033/api/drafts", { method: "POST", headers: { host: "127.0.0.1:3033", origin: "http://127.0.0.1:3033", "Content-Type": "application/json", authorization: "Basic " + Buffer.from("editor:invented-editor").toString("base64") }, body: raw }))
    assert.equal(response.status, 202)
    assert.deepEqual(calls, ["http://127.0.0.1:3999/commands"])
  } finally {
    globalThis.fetch = original
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(env, key)) delete process.env[key]
    Object.assign(process.env, env)
  }
})
