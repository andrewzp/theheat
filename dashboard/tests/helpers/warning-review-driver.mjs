// Cross-language driver: stdin/out are invented test state only.
import assert from "node:assert/strict"
import { withWarningGist, body } from "./warning-gist-harness.js"
let input = ""
for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
await withWarningGist(async t => {
  const sourceBefore = structuredClone(t.get().review_context.two_bot.bundle)
  const text = "Example Island faces possible dangerous winds tonight, Invented Warning Agency warns."
  let result = await t.post(body(t.get(), "edit", { editedText: text,
    operator_claim_references: [{ claim: { start: 0, end: 14, text: "Example Island" }, sources: [{ pointer: "/current_facts/2" }] }] }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  const listed = (await t.list())[0]
  result = await t.post(body(t.get(), "review", { reviewConfirmed: true,
    expectedPolicySha256: listed.editorial_policy.policy_sha256 }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  result = await t.post(body(t.get(), "approve"))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  assert.equal(t.dispatches.length, 1)
  assert.deepEqual(t.get().review_context.two_bot.bundle, sourceBefore)
  process.stdout.write(JSON.stringify({ raw_state: t.raw(), text, patches: t.patches.length,
    dispatches: t.dispatches, source_preserved: true }))
}, { seed })
