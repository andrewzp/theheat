// OFFLINE FIXTURE (P00c proofs): print an invented state document with N pending drafts and
// each draft's exact revision identity, built with the production revision helpers.
import { policy, runtimeRun, initializeRevision, draftIdentity, textHash, fingerprint } from "./review-policy.js"

const count = Number(process.argv[2] || 2)
const at = new Date().toISOString()
const drafts = Array.from({ length: count }, (_, index) => {
  const id = `draft_route_${index + 1}`
  const draft = { id, event_id: `event_${id}`, type: "hot10", status: "pending", text: `Invented City ${index + 1} reached 40°C today.`,
    created_at: "2026-10-30T12:00:00Z", score: { total: 60 },
    approval_policy: { can_auto_approve: true, recommended_delay_minutes: 30 },
    review_context: { source: "invented observations", two_bot: { bundle: { event_id: `event_${id}`, headline_value: 40 },
      fact_check: { passed: true, extracted_claims: [{ kind: "measurement", value: 40 }] }, critic: { passed: true } } } }
  const proof = draft.review_context.two_bot
  proof.reviewed_text_sha256 = textHash(draft.text)
  proof.reviewed_policy_sha256 = fingerprint(policy)
  proof.reviewed_bundle_sha256 = fingerprint(proof.bundle)
  return initializeRevision(draft)
})
const state = { drafts, publish_ledger: {}, errors: [], run_history: [runtimeRun(at)] }
const identities = Object.fromEntries(drafts.map(d => [d.id, { ...draftIdentity(d), decision_revision: d.decision_revision ?? 0 }]))
process.stdout.write(JSON.stringify({ state, identities }) + "\n")
