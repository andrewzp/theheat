import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync, mkdtempSync, rmSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"
import { mergeDrafts, readStateStore, writeStateStore, updateDraftStore, getStateBackend } from "../lib/state-store.js"

const cases = JSON.parse(readFileSync(new URL("../../tests/fixtures/draft_retention_contract.json", import.meta.url)))
const now = Date.parse("2026-09-08T00:00:00Z")
function expandGroups(example) {
  return example.groups.flatMap((group) => Array.from({ length: group.count }, (_, index) => {
    const row = { id: `${group.prefix}-${index}`, text: "Saved exact text", ...structuredClone(group.draft) }
    if (group.stepSeconds) row.created_at = new Date(Date.parse(row.created_at) + index * group.stepSeconds * 1000).toISOString()
    return row
  }))
}

for (const example of cases) {
  test(`shared retention: ${example.name}`, () => {
    const rows = expandGroups(example)
    const before = structuredClone(rows)
    const expected = example.keep.flatMap((group) => Array.from({ length: group.end - group.start }, (_, index) => `${group.prefix}-${group.start + index}`))
    const merged = mergeDrafts(rows.filter((_, i) => i % 2 === 0), rows.filter((_, i) => i % 2 === 1), 200, { now })
    assert.deepEqual(merged.map((row) => row.id).sort(), expected.sort())
    assert.deepEqual(rows, before)
  })
}

function gistResponse(state) {
  return { ok: true, status: 200, async json() { return { files: { "state.json": { content: JSON.stringify(state) } } } } }
}

function setEnvironment(t, values) {
  const saved = { ...process.env }
  Object.assign(process.env, values)
  t.after(() => {
    for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key]
    Object.assign(process.env, saved)
  })
}

test("editing a real Gist queue path preserves every protected draft over 200", async (t) => {
  setEnvironment(t, { THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "", GIST_ID: "mock", GITHUB_TOKEN: "mock" })
  const rows = expandGroups(cases[0]).filter((row) => row.status !== "rejected")
  let stored = { drafts: rows, publish_ledger: {} }
  let patches = 0
  t.mock.method(globalThis, "fetch", async (_url, options = {}) => {
    if (options.method === "PATCH") {
      patches++
      stored = JSON.parse(JSON.parse(options.body).files["state.json"].content)
    }
    return gistResponse(stored)
  })
  await updateDraftStore("approved-0", (row) => ({ ...row, text: "Edited revision", content_revision: 2 }))
  assert.equal(patches, 1)
  assert.equal(stored.drafts.length, rows.length)
  assert.equal(stored.drafts.find((row) => row.id === "approved-0").text, "Edited revision")
  for (const row of rows.filter((row) => row.id !== "approved-0")) {
    assert.deepEqual(stored.drafts.find((candidate) => candidate.id === row.id), row)
  }
})

test("explicit unsupported backend and SQLite without path fail before IO", async (t) => {
  t.mock.method(globalThis, "fetch", () => { throw new Error("Unexpected network") })
  setEnvironment(t, { THEHEAT_STATE_BACKEND: "sqlite-typo", THEHEAT_DB_PATH: "" })
  assert.throws(getStateBackend, /Unsupported state backend/)
  await assert.rejects(readStateStore(), /Unsupported state backend/)
  await assert.rejects(writeStateStore({}), /Unsupported state backend/)
  process.env.THEHEAT_STATE_BACKEND = "sqlite"
  await assert.rejects(readStateStore(), /THEHEAT_DB_PATH is not set/)
  await assert.rejects(updateDraftStore("x", (row) => row), /THEHEAT_DB_PATH is not set/)
})

test("configured Gist bootstrap failure refuses defaults and never writes a draft", async (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "heat-bootstrap-"))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  setEnvironment(t, { THEHEAT_STATE_BACKEND: "sqlite", THEHEAT_DB_PATH: path.join(directory, "state.sqlite"), GIST_ID: "mock", GITHUB_TOKEN: "mock" })
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status: 401, async text() { return "mock denied" } }))
  await assert.rejects(readStateStore(), /Failed to read state: 401/)
  await assert.rejects(writeStateStore({ drafts: [{ id: "new", status: "pending" }] }), /Failed to read state: 401/)
  await assert.rejects(updateDraftStore("new", (row) => row), /Failed to read state: 401/)
  const db = new DatabaseSync(process.env.THEHEAT_DB_PATH)
  try { assert.equal(db.prepare("SELECT COUNT(*) AS n FROM drafts").get().n, 0) } finally { db.close() }
})

test("invalid bootstrap payload rolls back instead of exposing empty state", async (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "heat-bootstrap-write-"))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  setEnvironment(t, { THEHEAT_STATE_BACKEND: "sqlite", THEHEAT_DB_PATH: path.join(directory, "state.sqlite"), GIST_ID: "mock", GITHUB_TOKEN: "mock" })
  t.mock.method(globalThis, "fetch", async () => gistResponse({ posted_events: ["duplicate", "duplicate"] }))
  await assert.rejects(readStateStore(), /UNIQUE constraint/)
  const db = new DatabaseSync(process.env.THEHEAT_DB_PATH)
  try { assert.equal(db.prepare("SELECT COUNT(*) AS n FROM metadata").get().n, 0) } finally { db.close() }
})

test("legacy table-only suppressions remain readable when metadata is absent", async (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), "heat-legacy-suppression-"))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  setEnvironment(t, { THEHEAT_STATE_BACKEND: "sqlite", THEHEAT_DB_PATH: path.join(directory, "state.sqlite"), GIST_ID: "", GITHUB_TOKEN: "" })
  const row = { id: "old", ts: "2026-09-08T12:00:00Z", stage: "review" }
  await writeStateStore({ suppressions: [row] })
  const db = new DatabaseSync(process.env.THEHEAT_DB_PATH)
  try { db.prepare("DELETE FROM metadata WHERE key = 'suppressions'").run() } finally { db.close() }
  assert.deepEqual((await readStateStore()).suppressions, [row])
})
