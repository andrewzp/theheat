// Explicit execution policy for existing mocked review/approval scenarios.
import * as revisions from "../../lib/draft-revisions.js"
import { EDITORIAL_POLICY_MANIFEST } from "../../lib/editorial-policy-manifest.js"
export * from "../../lib/draft-revisions.js"
export const policy = { schema_version: 1, execution_sha256: "a".repeat(64), source_sha256: EDITORIAL_POLICY_MANIFEST.source_sha256,
  models: { writer: "claude-sonnet-4-6", writer_provider: "anthropic", fact_check: "gemini-2.5-flash", critic: "gemini-2.5-pro", safety: "gemini-flash-latest" },
  flags: { critic_enabled: true, critic_revise_enabled: false, writer_samples: 1, safety_llm_enabled: false } }
export const reviewIsCurrent = (draft) => revisions.reviewIsCurrent(draft, policy)
export const approvalIsCurrent = (draft, mode = null) => revisions.approvalIsCurrent(draft, mode, policy)
export const initializeRevision = (draft) => revisions.initializeRevision(draft, policy)
export const recordModelReview = (draft) => revisions.recordModelReview(draft, policy)
export const recordHumanReview = (draft) => revisions.recordHumanReview(draft, policy)
export const authorizeDraft = (draft, mode, intent = null, epoch = null) => revisions.authorizeDraft(draft, mode, intent, epoch, policy)
export const projectDraft = (draft) => revisions.projectDraft(draft, policy)
export const runtimeRun = (at) => ({ started_at: at, runtime_inventory: { schema_version: 1, captured_at: at, editorial_policy: structuredClone(policy) } })
