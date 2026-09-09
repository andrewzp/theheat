import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { draftIdentity, hasUnresolvedPublish } from "../lib/draft-revisions.js"
import { mergeDrafts, mergePublishLedger, readStateStore, updateDraftStore, writeStateStore } from "../lib/state-store.js"

const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/draft_merge_contract.json", import.meta.url)))

for (const example of cases) {
  test(`shared draft merge: ${example.name}`, () => {
    for (const [current, incoming] of [[example.current, example.incoming], [example.incoming, example.current]]) {
      const before = structuredClone([current, incoming])
      const row = mergeDrafts([current], [incoming])[0]
      for (const [key, value] of Object.entries(example.expected)) assert.deepEqual(row[key], value, key)
      for (const key of example.absent) assert.equal(Object.hasOwn(row, key), false, key)
      assert.equal(Boolean(row.revision_history?.length), example.history)
      assert.equal(Boolean(row.revision_conflicts?.length), example.conflict)
      assert.deepEqual([current, incoming], before)
    }
  })
}

test("equal timestamp divergent edits display deterministically", () => {
  const first = { id: "d1", text: "A", content_revision: 2, status: "pending" }
  const second = { ...first, text: "B" }
  assert.equal(mergeDrafts([first], [second])[0].text, mergeDrafts([second], [first])[0].text)
})

test("same-attempt confirmation dominates a stale submission", () => {
  const submitted = { intent_id: "i1", at: "2026-09-08T12:00:00Z", phase: "submitted", tweet_id: null }
  const confirmed = { ...submitted, phase: "confirmed", tweet_id: "t1" }
  assert.deepEqual(mergePublishLedger({ e1: confirmed }, { e1: submitted }).e1, confirmed)
  assert.deepEqual(mergePublishLedger({ e1: submitted }, { e1: confirmed }).e1, confirmed)
})

test("reconciled receipt preserves attempt start and resolves submission", () => {
  const submitted = { id: "d1", text: "40°C", content_revision: 1, status: "pending", publish_outcome: "submitted", last_publish_attempt_at: "2026-09-08T12:00:00Z", updated_at: "2026-09-08T12:00:00Z" }
  const confirmed = { ...submitted, status: "posted", publish_outcome: "confirmed", tweet_id: "t1", posted_at: "2026-09-08T12:01:00Z", updated_at: "2026-09-08T13:00:00Z" }
  const row = mergeDrafts([submitted], [confirmed])[0]
  assert.equal(row.publish_outcome, "confirmed")
  assert.equal(row.last_publish_attempt_at, submitted.last_publish_attempt_at)
})

test("different attempts and older receipts remain independently visible", () => {
  const draft = { id: "d1", event_id: "e1", text: "B", content_revision: 2 }
  const confirmed = { intent_id: "i1", at: "2026-09-08T12:00:00Z", phase: "confirmed", tweet_id: "t1", text: "A" }
  const unknown = { intent_id: "i2", at: "2026-09-08T13:00:00Z", phase: "unknown", text: "B" }
  const ledger = mergePublishLedger({ e1: confirmed }, { e1: unknown })
  assert.equal(ledger.e1.tweet_id, "t1")
  assert.deepEqual(ledger.e1.attempt_conflicts, [unknown])
  assert.equal(hasUnresolvedPublish(draft, { publish_ledger: ledger }), true)
  assert.deepEqual(mergePublishLedger(ledger, { e1: confirmed }), ledger)
})

test("draft cap cannot discard an unresolved publication attempt", () => {
  const unknown = { id: "unknown", text: "A", status: "rejected", created_at: "2000-01-01T00:00:00Z", publish_outcome: "unknown", last_publish_attempt_at: "2000-01-01T00:00:00Z" }
  const recent = Array.from({ length: 201 }, (_, i) => ({ id: `d${i}`, text: "B", status: "pending", created_at: "2026-09-08T12:00:00Z" }))
  assert.ok(mergeDrafts([unknown], recent).some((row) => row.id === "unknown"))
})

function gistResponse(state) {
  return { ok: true, status: 200, async json() { return { files: { "state.json": { content: JSON.stringify(state) } } } } }
}

for (const change of ["text", "approval", "attempt"]) {
  test(`Gist observed ${change} change rejects a stale mutation without PATCH`, async (t) => {
    process.env.THEHEAT_STATE_BACKEND = "gist"
    process.env.THEHEAT_DB_PATH = ""
    process.env.GIST_ID = "mock_gist"
    process.env.GITHUB_TOKEN = "mock_token"
    const draft = { id: "d1", event_id: "e1", text: "40°C", content_revision: 1, status: "approved", approval_binding: { mode: "manual" } }
    const initial = { drafts: [draft], publish_ledger: {} }
    const latest = structuredClone(initial)
    if (change === "text") Object.assign(latest.drafts[0], { text: "50°C", content_revision: 2 })
    else if (change === "approval") delete latest.drafts[0].approval_binding
    else latest.publish_ledger.e1 = { intent_id: "other", phase: "submitted" }
    let calls = 0
    t.mock.method(globalThis, "fetch", async (_url, options = {}) => {
      assert.equal(options.method, undefined, "a stale mutation must not PATCH")
      return gistResponse(++calls === 1 ? initial : latest)
    })
    await assert.rejects(updateDraftStore("d1", (row) => ({ ...row, status: "pending" }), { expectedRevision: draftIdentity(draft) }),
      (error) => error.status === 409 && error.code === "revision_conflict")
    assert.equal(calls, 2)
  })
}

test("SQLite preserves nested contract fields and rolls back rejected revisions", async () => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "theheat-p02-state-"))
  process.env.THEHEAT_STATE_BACKEND = "sqlite"
  process.env.THEHEAT_DB_PATH = path.join(tmp, "state.sqlite")
  process.env.GIST_ID = ""
  process.env.GITHUB_TOKEN = ""
  const draft = { id: "d1", event_id: "e1", text: "40°C", content_revision: 2, status: "pending", revision_history: [{ content_revision: 1, text: "30°C" }], revision_conflicts: [{ content_revision: 2, text: "41°C" }], publish_outcome: "unknown" }
  draft.review_binding = { ...draftIdentity(draft), kind: "human" }
  const ledger = { e1: { intent_id: "i1", phase: "unknown", ...draftIdentity(draft), text: draft.text, attempt_conflicts: [{ intent_id: "old", tweet_id: "receipt" }] } }
  try {
    await writeStateStore({ drafts: [draft], publish_ledger: ledger })
    const loaded = await readStateStore()
    assert.deepEqual(loaded.drafts, [draft])
    assert.equal(loaded.publish_ledger.e1.tweet_id, "receipt")
    assert.equal(loaded.publish_ledger.e1.attempt_conflicts[0].phase, "unknown")
    await assert.rejects(updateDraftStore("d1", (row) => row, { expectedRevision: draftIdentity({ ...draft, content_revision: 1 }) }), { status: 409 })
    const updated = await updateDraftStore("d1", (row) => ({ ...row, post_error: "Still blocked" }), { expectedRevision: draftIdentity(draft) })
    assert.equal(updated.draft.post_error, "Still blocked")
    assert.deepEqual((await readStateStore()).drafts[0].revision_history, draft.revision_history)
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
})
