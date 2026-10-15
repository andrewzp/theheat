import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { transformSync } from "next/dist/build/swc/index.js"
import { createCandidateCommand } from "../lib/draft-command-request.js"

// Compile the actual JSX component and its local imports, using the already
// installed Next compiler. This loader is local to this test, with no hooks or
// production component substitutions.
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
const row = { admission_input_id: "a".repeat(64), admission_input_sha256: "b".repeat(64), origin_kind: "synchronous_writer_v1",
  generation_id: "gss_" + "c".repeat(64), candidate_id: "d".repeat(64), expected_state_version: 1,
  expected_policy_sha256: "e".repeat(64), check_set_id: "f".repeat(64), expected_completion_sha256: "1".repeat(64),
  required_checks_completed: false, status: "checks_recorded", stages: { deterministic: "passed", safety: "passed", fact_check: "passed", critic: "passed" },
  text: "Invented station reached its archive maximum.", source: { where: "Invented station", facts: [] } }
function html(candidate, changes = {}) {
  return renderToStaticMarkup(createElement(DraftWorkbench, { drafts: [], localCandidates: [candidate], localRole: "editor", botRuns: [], ...changes }))
}
test("recorded checks request fresh validation without claiming approval", () => {
  const rendered = html(row)
  assert.match(rendered, /Checks recorded; source validation required/)
  assert.match(rendered, /Validate and add to local drafts/)
  assert.doesNotMatch(rendered, /Required checks completed/)
  for (const changes of [{ localRole: "viewer" }, { pendingCommand: { command: {} } }, { editingId: "other" }]) {
    assert.match(html(row, changes), /disabled=""[^>]*>Validate and add to local drafts/)
  }
  for (const status of ["checks_pending", "checks_blocked", "stale"]) assert.doesNotMatch(html({ ...row, status }), /Validate and add to local drafts/)
  assert.match(html({ ...row, status: "checks_completed", required_checks_completed: true }), /Add to local drafts/)
  const request = createCandidateCommand({ ...row, raw: "forbidden", source: { verdict: true } }, "admit_checked_candidate")
  assert.equal(request.action, "admit_checked_candidate")
  assert.deepEqual(Object.keys(request.payload).sort(), ["admission_input_id", "admission_input_sha256", "candidate_id", "check_set_id", "expected_completion_sha256", "expected_policy_sha256", "expected_state_version", "generation_id", "origin_kind"].sort())
})

test("saved candidate checks are historical while unadmitted conflicts stay visible", () => {
  const saved = html({ ...row, status: "admitted", saved_draft_id: "draft-invented", reason: "candidate_state_conflict" })
  assert.match(saved, /role="status">Saved to local drafts<\/p>/)
  assert.match(saved, /These candidate checks are historical/)
  assert.match(saved, /Open the saved draft for its current review status/)
  assert.match(saved, /<summary>Earlier candidate validation<\/summary><p>candidate_state_conflict<\/p>/)
  assert.match(saved, />Open saved draft<\/button>/)
  assert.doesNotMatch(saved, />Check candidate<|>Add to local drafts<|>Validate and add to local drafts</)

  for (const status of ["stale", "checks_blocked"]) {
    const blocked = html({ ...row, status, reason: "candidate_state_conflict" })
    assert.match(blocked, /role="status">[^<]* — candidate_state_conflict<\/p>/)
    assert.doesNotMatch(blocked, /These candidate checks are historical|Earlier candidate validation|>Open saved draft</)
    assert.doesNotMatch(blocked, />Check candidate<|>Add to local drafts<|>Validate and add to local drafts</)
  }
})
