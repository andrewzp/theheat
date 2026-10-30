/** W09.4 Operations failure recovery: the exact affected attempt and whether an action can
 * spend or publish. Actual drafts route over an invented Gist (fake transports only); an
 * unknown or submitted attempt pauses every mutation and is never offered a retry.
 */
import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { RECOVERY_NOTE, publicationAttempt, publicationAttemptLines } from "../lib/publication-recovery.js"
import { body, withGist } from "./helpers/gist-hazard-harness.js"

// Compile the actual JSX Workbench with the installed Next compiler (same local loader as
// ghcn-candidate-status.test.js); no component substitutions.
const require = createRequire(import.meta.url)
const cache = new Map()
function component(filename) {
  if (filename.endsWith(".json")) return JSON.parse(readFileSync(filename, "utf8"))
  if (cache.has(filename)) return cache.get(filename).exports
  const module = { exports: {} }
  cache.set(filename, module)
  const code = transformSync(readFileSync(filename, "utf8"), {
    filename, jsc: { parser: { syntax: "ecmascript", jsx: true }, target: "es2022", transform: { react: { runtime: "automatic" } } },
    module: { type: "commonjs" },
  }).code
  const localRequire = name => name.startsWith(".") ? component(resolve(dirname(filename), name)) : require(name)
  new Function("require", "module", "exports", code)(localRequire, module, module.exports)
  return module.exports
}
const { DraftWorkbench } = component(fileURLToPath(new URL("../app/components/DraftWorkbench.js", import.meta.url)))

const row = (draft, extra = {}) => ({ content_revision: draft.content_revision, text_sha256: "a".repeat(64), evidence_sha256: "b".repeat(64),
  text: draft.text, intent_id: "invented-intent-unknown", tweet_id: null, phase: "unknown", at: "2032-01-02T03:04:05Z", ...extra })

test("the attempt view names phase, intent, version and receipt, and degrades to unreadable", () => {
  const draft = { id: "d", event_id: "e", content_revision: 3, text: "Invented." }
  assert.equal(publicationAttempt(draft, { publish_ledger: {} }), null)
  assert.deepEqual(publicationAttempt({ ...draft, publish_outcome: "submitted" }, { publish_ledger: {} }).phase, "submitted")
  const unknown = publicationAttempt(draft, { publish_ledger: { e: row(draft) } })
  assert.deepEqual(unknown, { status: "recorded", phase: "unknown", intent_id: "invented-intent-unknown", at: "2032-01-02T03:04:05Z",
    content_revision: 3, receipt: "none", conflicts: 0 })
  assert.deepEqual(publicationAttempt(draft, { publish_ledger: { e: { phase: "resent" } } }), { status: "unreadable" })
  assert.equal(publicationAttempt(draft, { publish_ledger: { e: row(draft, { intent_id: "<script>" }) } }).intent_id, null)
  const lines = publicationAttemptLines(unknown).join(" ")
  assert.match(lines, /intent invented-intent-unknown for version 3/)
  assert.match(lines, /outcome unknown/)
  assert.match(lines, /No platform receipt is recorded/)
  assert.doesNotMatch(lines + RECOVERY_NOTE, /try again|retry now|resend now/i)
})

test("the actual route projects the affected attempt and refuses every mutation while it is unresolved", async () => {
  await withGist("pm25", async t => {
    const state = t.state(), draft = state.drafts.find(d => d.id === t.primary)
    state.publish_ledger = { ...(state.publish_ledger || {}), [draft.event_id]: row(draft) }
    draft.publish_outcome = "unknown"
    t.replaceState(state)
    const projected = (await t.list()).find(d => d.id === t.primary)
    assert.equal(projected.publish_blocked, true)
    assert.equal(projected.publish_attempt.intent_id, "invented-intent-unknown")
    assert.equal(projected.publish_attempt.phase, "unknown")
    const before = t.raw(), writes = t.patches.length
    for (const [action, extra] of [["edit", { editedText: `${draft.text} Changed.` }], ["approve", {}], ["review", { reviewConfirmed: true }],
      ["attach_graphic", { expectedMediaSha256: "0".repeat(64) }], ["remove_graphic", {}], ["reject", {}]]) {
      const result = await t.post(body(t.get(), action, extra))
      assert.equal(result.status, 409, `${action}: ${JSON.stringify(result.body)}`)
    }
    assert.equal(t.patches.length, writes); assert.equal(t.raw(), before); assert.equal(t.dispatches.length, 0)
    assert.equal(t.previews.length, 0)
    // Rendered in the real Workbench: the attempt and the no-spend/no-publish note; no retry affordance.
    const html = renderToStaticMarkup(React.createElement(DraftWorkbench, { drafts: [projected], selectedDraftId: projected.id,
      setSelectedDraftId: () => {}, draftAct: () => {}, startEditing: () => {}, setEditText: () => {}, setEditingId: () => {} }))
    assert.match(html, /A publication attempt needs reconciliation/)
    assert.match(html, /Affected attempt: intent invented-intent-unknown/)
    assert.match(html, /Nothing on this page publishes, resends or spends for this draft/)
    assert.doesNotMatch(html, /Retry same action|Try again/)
  })
})
