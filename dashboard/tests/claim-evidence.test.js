import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ClaimEvidence } from "../app/components/ClaimEvidence.js"
import { claimEvidenceForDisplay } from "../lib/saved-claim-evidence.js"
import { projectDraft as unverifiedProjection } from "../lib/draft-revisions.js"
import { fingerprint, initializeRevision, invalidateText, policy, projectDraft, recordHumanReview, textHash } from "./helpers/review-policy.js"

function draft() {
  const d = { id: "invented-claim-desk", type: "temperature", event_id: "invented-source", status: "pending",
    text: "Invented model forecast: 40°C tomorrow.", review_context: { two_bot: {
      bundle: { event_id: "invented-source", signal_kind: "temperature", where: "Invented place", when: "2032-01-02",
        current_facts: [{ label: "forecast_maximum", value: 40, unit: "°C" },
          { label: "zero_is_a_value", value: 0, unit: "" }, { label: "absent_value", value: null }, { label: "flag", value: false }] },
      fact_check: { passed: true, failures: [], raw_response: "invented offline response",
        extracted_claims: [{ text: "40°C", kind: "number" }, { text: "tomorrow", kind: "date" }] },
      critic: { passed: true },
    } } }
  const two = d.review_context.two_bot
  two.reviewed_text_sha256 = textHash(d.text)
  two.reviewed_bundle_sha256 = fingerprint(two.bundle)
  two.reviewed_policy_sha256 = fingerprint(policy)
  return initializeRevision(d)
}
const render = (d, extra = {}) => renderToStaticMarkup(React.createElement(ClaimEvidence, { draft: d, ...extra }))

test("all ordinary draft projections retain bounded model analysis and shared input without mutating authority", () => {
  const d = draft(), before = structuredClone(d), projected = projectDraft(d)
  const view = claimEvidenceForDisplay(projected)
  assert.deepEqual(view.claims, { status: "bound", items: d.review_context.two_bot.fact_check.extracted_claims })
  assert.deepEqual(view.source.facts, d.review_context.two_bot.bundle.current_facts.map(row => ({ ...row, unit: row.unit ?? null })))
  assert.equal(view.source.when, "2032-01-02")
  assert.deepEqual(d, before)
  projected.claim_evidence.claims.items[0].text = "Changed display copy"
  assert.deepEqual(d, before)
})

test("historical matching analysis does not turn an unverified policy into a current review", () => {
  const projected = unverifiedProjection(draft())
  assert.equal(projected.review_status, "policy_unverified")
  assert.equal(projected.review_kind, null)
  assert.equal(projected.claim_evidence.claims.status, "bound")
  const html = render(projected)
  assert.ok(html.includes("not individual source citations or independent verification"))
  assert.ok(html.includes("Individual source links were not retained"))
  assert.ok(!html.includes("checks current") && !html.includes("passed"))
})

test("model claims cannot survive changed text, source, output, content revision or missing proof", () => {
  const changes = [
    d => { d.text += " Changed" },
    d => { d.review_context.two_bot.bundle.current_facts[0].value = 50 },
    d => { d.review_context.two_bot.fact_check.extracted_claims[0].text = "50°C" },
    d => { d.review_context.two_bot.critic.passed = false },
    d => { d.content_revision++ },
    d => { delete d.review_binding },
    d => { delete d.review_context.two_bot.reviewed_text_sha256 },
    d => { d.review_context.two_bot.required_checks_binding = {} },
    d => { d.revision_conflicts = ["conflicting source"] },
  ]
  for (const change of changes) {
    const d = draft(); change(d)
    const projected = projectDraft(d)
    assert.equal(projected.claim_evidence.claims.status, "unbound")
    assert.deepEqual(projected.claim_evidence.claims.items, [])
    assert.ok(!render(projected).includes("Saved model claims ·"))
  }
})

test("editing, saving, reverting and a new human review never inherit model claims", () => {
  const d = draft(), original = d.text, projected = projectDraft(d)
  assert.equal(claimEvidenceForDisplay(projected, { editing: true }).claims.status, "editing")
  assert.ok(!render(projected, { editing: true }).includes("Saved model claims ·"))
  assert.ok(render(projected, { editing: true }).includes("Saved source facts"))
  invalidateText(d, "An edited, invented sentence.")
  assert.equal(projectDraft(d).claim_evidence.claims.status, "missing")
  assert.equal(d.revision_history[0].review_context.two_bot.fact_check.extracted_claims.length, 2)
  invalidateText(d, original)
  recordHumanReview(d)
  const human = projectDraft(d)
  assert.equal(human.review_kind, "human")
  assert.equal(human.claim_evidence.claims.status, "missing")
})

test("wrong event/type and malformed, oversized or sparse source facts do not become a partial source packet", () => {
  const changes = [
    b => { b.event_id = "different-event" }, b => { b.signal_kind = "fire" }, b => { delete b.where },
    b => { b.current_facts[0].value = { invented: 40 } },
    b => { b.current_facts = Array(2) }, b => { b.current_facts = Array.from({ length: 65 }, () => ({ label: "x", value: 0 })) },
    b => { b.current_facts = Array.from({ length: 16 }, () => ({ label: "x", value: "🌡".repeat(500) })) },
  ]
  for (const change of changes) {
    const d = draft(); change(d.review_context.two_bot.bundle)
    const source = projectDraft(d).claim_evidence.source
    assert.equal(source.status, "unreadable")
    assert.deepEqual(source.facts, [])
  }
  const nonfinite = draft(); nonfinite.review_context.two_bot.bundle.current_facts[0].value = Infinity
  assert.throws(() => projectDraft(nonfinite), /finite numbers/)
})

test("malformed claims are never coerced, truncated, guessed from facts or partly displayed", () => {
  for (const raw of ["40°C", [null], [{ text: 40, kind: "number" }], [{ text: "40", kind: "number", source: "guessed" }],
    [{ text: "x".repeat(2049), kind: "number" }], Array(2), Array.from({ length: 33 }, () => ({ text: "40", kind: "number" })),
    Array.from({ length: 20 }, () => ({ text: "🌡".repeat(300), kind: "number" }))]) {
    const d = draft(); d.review_context.two_bot.fact_check.extracted_claims = raw
    const result = projectDraft(d).claim_evidence.claims
    assert.equal(result.status, "unreadable")
    assert.deepEqual(result.items, [])
  }
  const empty = draft(); empty.review_context.two_bot.fact_check.extracted_claims = []
  initializeRevision(empty)
  assert.ok(render(projectDraft(empty)).includes("does not establish that the text contains no factual claims"))
})

test("client refuses stale projections and validates bounded display rows again", () => {
  const d = projectDraft(draft())
  for (const key of ["content_revision", "text_sha256", "evidence_sha256"]) {
    const changed = structuredClone(d)
    changed.revision_identity[key] = key === "content_revision" ? 2 : "f".repeat(64)
    assert.equal(claimEvidenceForDisplay(changed).claims.status, "unavailable")
  }
  const corrupt = structuredClone(d); corrupt.claim_evidence.claims.items = [null]
  assert.equal(claimEvidenceForDisplay(corrupt).claims.status, "unreadable")
  corrupt.claim_evidence.source.facts[0].value = {}
  assert.equal(claimEvidenceForDisplay(corrupt).source.status, "unreadable")
  assert.equal(claimEvidenceForDisplay({}).claims.status, "unavailable")
})

test("actual component escapes retained text, preserves zero/missing values and exposes no review/post action", () => {
  const d = draft(), two = d.review_context.two_bot
  two.fact_check.extracted_claims[0].text = '<img src=x onerror="alert(1)">'
  two.bundle.current_facts[0].value = "https://invalid.example/"
  two.reviewed_bundle_sha256 = fingerprint(two.bundle)
  initializeRevision(d)
  const html = render(projectDraft(d), { sourceHold: "Source update needed; review and approval held." })
  assert.ok(html.includes("&lt;img") && !html.includes("<img"))
  assert.ok(!html.includes("href="))
  for (const phrase of ["Source update needed", "Not supplied", "false", ">0<", "Saved source time: 2032-01-02"])
    assert.ok(html.includes(phrase), phrase)
  assert.equal((html.match(/<details/g) || []).length, 2)
  assert.equal((html.match(/<button/g) || []).length, 1)
  assert.ok(html.includes("Compare with shared source facts"))
  assert.ok(!html.includes("<input") && !html.includes("<form"))
})
