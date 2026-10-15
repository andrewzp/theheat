import test from "node:test"
import assert from "node:assert/strict"
import { parseGistDocument, stringifyGistDocument, gistDraftNumericIdentity } from "../lib/lossless-gist.js"
import { updateDraftStore, writeStateStore } from "../lib/state-store.js"
import { draftIdentity, decisionRevision, invalidateText } from "../lib/draft-revisions.js"

const draft = (id, number = "500.0") => `{"id":"${id}","text":"Invented ${id}","status":"pending","created_at":"2026-01-01T00:00:00Z","review_context":{"two_bot":{"bundle":{"sample":${number},"record_sha256":"retained"}}}}`
const initial = `{"drafts":[${draft("aq")},${draft("fire", "91.0")}],"opaque":{"small":1e-7,"whole":1.0e3,"negative":-0.0,"precise":0.1234567890123456789}}`
const protectedFailure = { code: "state_evidence_preservation" }

async function store(raw, operation, { second = raw } = {}) {
  const oldFetch = globalThis.fetch
  const env = Object.fromEntries(["GIST_ID", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH"].map(key => [key, process.env[key]]))
  Object.assign(process.env, { GIST_ID: "invented-only", THEHEAT_STATE_BACKEND: "gist", THEHEAT_DB_PATH: "" })
  const writes = [], methods = []
  let gets = 0
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(url, "https://api.github.com/gists/invented-only")
    const method = options.method || "GET"
    methods.push(method)
    if (method === "GET") return Response.json({ files: { "state.json": { content: ++gets === 1 ? raw : second } } })
    assert.equal(method, "PATCH")
    writes.push(JSON.parse(options.body).files["state.json"].content)
    return Response.json({})
  }
  try { await operation(writes, methods); return writes }
  finally {
    globalThis.fetch = oldFetch
    for (const [key, value] of Object.entries(env)) { if (value === undefined) delete process.env[key]; else process.env[key] = value }
  }
}

test("unchanged source lexemes and unrelated precision survive real edit and generic writes", async () => {
  let raw = initial
  for (const text of ["First invented edit", "Second invented edit"]) {
    const writes = await store(raw, async (_, methods) => {
      const current = JSON.parse(raw).drafts.find(row => row.id === "aq")
      const expectedRevision = { ...draftIdentity(current), decision_revision: decisionRevision(current) }
      await updateDraftStore("aq", row => invalidateText(row, text), { expectedRevision })
      assert.deepEqual(methods, ["GET", "GET", "PATCH"])
    })
    raw = writes[0]
    assert.match(raw, /"sample":500\.0/)
    assert.match(raw, /"sample":91\.0/)
    assert.match(raw, /"opaque":\{"small":1e-7,"whole":1.0e3,"negative":-0\.0,"precise":0\.1234567890123456789\}/)
    const state = JSON.parse(raw)
    assert.equal(state.drafts.find(row => row.id === "aq").text, text)
    assert.equal(state.drafts.find(row => row.id === "fire").text, "Invented fire")
    for (const row of state.drafts.find(row => row.id === "aq").revision_history) assert.equal(row.review_context.two_bot.bundle.record_sha256, "retained")
  }
  const writes = await store(raw, () => writeStateStore({ errors: [{ msg: "Invented unrelated write" }] }))
  assert.match(writes[0], /"sample":500\.0/)
  assert.match(writes[0], /"sample":91\.0/)
})

test("draft correlation follows stable IDs through merge reorder", async () => {
  const writes = await store(initial, () => writeStateStore({ drafts: JSON.parse(initial).drafts.reverse().map(row => ({...row, updated_at: row.id === "aq" ? "2026-02-01T00:00:00Z" : "2026-01-01T00:00:00Z"})) }))
  const document = parseGistDocument(writes[0])
  assert.deepEqual(document.value.drafts.map(row => row.id), ["fire", "aq"])
  const source = (tree, id) => tree.children.get("drafts").children.find(node => node.value.id === id).children.get("review_context").raw
  for (const id of ["fire", "aq"]) assert.equal(source(document, id), source(parseGistDocument(initial), id))
})

test("numeric type drift at second read refuses before PATCH despite same revision", async () => {
  const second = initial.replace("500.0", "500")
  assert.deepEqual(draftIdentity(JSON.parse(initial).drafts[0]), draftIdentity(JSON.parse(second).drafts[0]))
  await store(initial, async writes => {
    await assert.rejects(updateDraftStore("aq", row => invalidateText(row, "Edited")), { status: 409 })
    assert.equal(writes.length, 0)
  }, {second})
})

for (const method of ["edit", "generic"]) test(`${method} cannot change or add retained evidence`, async () => {
  await store(initial, async writes => {
    const mutate = row => { row.review_context.two_bot.bundle.sample = 501; return row }
    const operation = method === "edit" ? updateDraftStore("aq", mutate) : writeStateStore({drafts: [mutate(JSON.parse(initial).drafts[0])]})
    await assert.rejects(operation, protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("updater cannot mutate the authoritative raw baseline through its state argument", async () => {
  await store(initial, async writes => {
    await assert.rejects(updateDraftStore("aq", (row, state) => {
      state.drafts[0].review_context.two_bot.bundle.sample = 501
      row.review_context.two_bot.bundle.sample = 501
      return row
    }), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("forged source history and new source-bearing drafts refuse", async () => {
  await store(initial, async writes => {
    await assert.rejects(updateDraftStore("aq", row => {
      row.revision_history = [{...structuredClone(row), review_context: {two_bot: {bundle: {sample: 501}}}}]
      return row
    }), protectedFailure)
    await assert.rejects(writeStateStore({drafts: [{...JSON.parse(initial).drafts[0], id: "unknown-source"}]}), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("ambiguous duplicate IDs refuse instead of selecting numeric evidence", async () => {
  await store(`{"drafts":[${draft("aq")},${draft("aq", "500")}]}`, async writes => {
    await assert.rejects(updateDraftStore("aq", row => row), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("already invalid retained hash is preserved without repair", async () => {
  const bad = initial.replaceAll("retained", "invalid-retained-hash")
  const writes = await store(bad, () => updateDraftStore("aq", row => invalidateText(row, "Still invalid")))
  assert.match(writes[0], /invalid-retained-hash/)
  assert.match(writes[0], /"sample":500\.0/)
})

for (const token of ["9007199254740993", "9007199254740993.0", "1e20", "1e400", "NaN", "Infinity"]) test(`unsafe ${token} blocks before PATCH`, async () => {
  await store(initial.replace("500.0", token), async writes => {
    await assert.rejects(updateDraftStore("aq", row => row), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

for (const raw of ['{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"x":01}', '{"x":1.}', '{"x":1e}', '{"x":true,}', '{"x":[1,]}', '{"x":"bad\nline"}', '{"x":null} trailing']) {
  test(`bounded parser refuses malformed or duplicate JSON ${JSON.stringify(raw)}`, () => assert.throws(() => parseGistDocument(raw), protectedFailure))
}

test("parser treats __proto__ and escaped delimiters as data", () => {
  const raw = '{"__proto__":{"x":500.0},"s":"bracket ] quote \\" slash \\\\"}'
  const parsed = parseGistDocument(raw)
  assert.equal(Object.getPrototypeOf(parsed.value), Object.prototype)
  assert.equal(Object.hasOwn(parsed.value, "__proto__"), true)
  assert.equal({}.x, undefined)
  assert.equal(stringifyGistDocument(parsed.value, parsed), raw)
})

test("size/depth and introduced invalid values refuse rather than normalize", () => {
  for (const raw of ['{"x":"' + "x".repeat(8 * 1024 * 1024) + '"}', '{"x":' + "[".repeat(65) + "0" + "]".repeat(65) + '}']) assert.throws(() => parseGistDocument(raw), {code:"state_evidence_limit"})
  const parsed = parseGistDocument('{"drafts":[],"n":1}')
  for (const n of [Infinity, NaN, 9007199254740992]) assert.throws(() => stringifyGistDocument({drafts: [], n}, parsed), protectedFailure)
  assert.equal(stringifyGistDocument({drafts: [], n: -0}, parsed), '{"drafts":[],"n":-0.0}')
})

test("ambiguous same-revision source spellings are never chosen by semantic hash", async () => {
  const history = [draft("aq", "500.0"), draft("aq", "500")]
  const raw = `{"drafts":[${draft("aq").slice(0,-1)},"content_revision":1,"revision_history":[${history.join(",")}]}]}`
  await store(raw, async writes => {
    await assert.rejects(updateDraftStore("aq", row => invalidateText(row, "Another edit")), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("generic stale source cannot restore an older revision from supplied history", async () => {
  const old = JSON.parse(draft("aq", "500.0"))
  const raw = `{"drafts":[${draft("aq", "501.0").slice(0,-1)},"content_revision":1,"revision_history":[${JSON.stringify(old)}]}]}`
  await store(raw, async writes => {
    await assert.rejects(writeStateStore({drafts:[old]}), protectedFailure)
    assert.equal(writes.length, 0)
  })
})

test("authorized rejection retention removes expired drafts and preserves retained source", async () => {
  const expired = draft("expired", "99.0").replace('"pending"', '"rejected"').replace('2026-01-01', '2000-01-01')
  const raw = initial.replace('],"opaque"', `,${expired}],"opaque"`)
  const writes = await store(raw, () => writeStateStore({errors:[]}))
  assert.deepEqual(JSON.parse(writes[0]).drafts.map(row => row.id).sort(), ["aq", "fire"])
  assert.match(writes[0], /"sample":500\.0/)
  assert.match(writes[0], /"sample":91\.0/)
})

test("removing retained source and boolean substitution refuse before PATCH", async () => {
  for (const mutate of [row => {delete row.review_context.two_bot.bundle}, row => {row.review_context.two_bot.bundle.sample = true}]) {
    await store(initial, async writes => {
      await assert.rejects(updateDraftStore("aq", row => {mutate(row); return row}), protectedFailure)
      assert.equal(writes.length, 0)
    })
  }
})

test("new undefined optional fields retain JSON omission semantics without null substitution", async () => {
  const writes = await store(initial, () => updateDraftStore("aq", row => ({...row,candidate_score:undefined})))
  assert.equal(Object.hasOwn(JSON.parse(writes[0]).drafts.find(row => row.id === "aq"), "candidate_score"), false)
  assert.match(writes[0], /"sample":500\.0/)
})
