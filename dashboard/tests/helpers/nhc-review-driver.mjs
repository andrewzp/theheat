// Cross-language journey driver: the actual draft handlers list, review and approve
// one imported NHC advisory draft. stdin/stdout carry invented test state only.
import assert from "node:assert/strict"
import { withWarningGist, body } from "./warning-gist-harness.js"
import { nhcAdvisoryForDisplay } from "../../lib/nhc-advisory-evidence.js"
let input = ""
for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
await withWarningGist(async t => {
  t.at(seed.now)
  const sourceBefore = structuredClone(t.get().review_context.two_bot.bundle)
  const listed = (await t.list())[0]
  assert.equal(listed.status, "pending"); assert.equal(listed.review_status, "needs_revalidation")
  assert.equal(nhcAdvisoryForDisplay(listed).status, "present")
  let result = await t.post(body(t.get(), "review", { reviewConfirmed: true,
    expectedPolicySha256: listed.editorial_policy.policy_sha256 }))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  result = await t.post(body(t.get(), "approve"))
  assert.equal(result.status, 200, JSON.stringify(result.body))
  assert.equal(t.dispatches.length, 1)
  assert.deepEqual(t.get().review_context.two_bot.bundle, sourceBefore)
  process.stdout.write(JSON.stringify({ raw_state: t.raw(), patches: t.patches.length, dispatches: t.dispatches }))
}, { seed })
