// The final-read re-confirmation of a review / approval / scheduling decision. Extracted
// unchanged from app/api/drafts/route.js so the legacy direct path (its confirmContext) and the
// P00c serialized consumer run byte-identical checks against the state they are about to write.
import { gistMediaCurrentness } from "./gist-media.js"
import { nwsSourceTiming } from "./nws-source-timing.js"
import { officialWarningValidation } from "./official-warning-validation.js"
import { nhcAdvisoryValidation } from "./nhc-advisory-validation.js"
import { dashboardEditorialPolicy } from "./editorial-policy.js"
import { dashboardAutomaticPolicy } from "./publication-control.js"

function fail(message, status = 409, code = "revision_conflict") {
  throw Object.assign(new Error(message), { status, code })
}

export function assertSavedSourceTiming(draft) {
  const timing = nwsSourceTiming(draft)
  if (timing.blocked) fail(timing.message, 409, "nws_source_review_required")
  const warning = officialWarningValidation(draft)
  if (warning.blocked) fail(warning.message, 409, "warning_source_review_required")
  const advisory = nhcAdvisoryValidation(draft)
  if (advisory.blocked) fail(advisory.message, 409, "nhc_advisory_source_review_required")
}

// New image families: explicit source recency at manual approval (the sender
// rechecks before upload). Historical previews stay inspectable; nothing changes.
export function assertMediaCurrent(draft) {
  const timing = gistMediaCurrentness(draft, Date.now())
  if (timing) fail(`${timing.message}. This image cannot be approved for posting; the draft is unchanged.`, 409, timing.code)
}

export function confirmDraftDecision(latestState, { runtimeReport = null } = {}, { action, draftId, checkedPolicySha, checkedAutomaticEpoch }) {
  const latestDraft = latestState.drafts?.find(draft => draft.id === draftId)
  if (!latestDraft) fail("This draft is no longer available.", 409, "draft_not_found")
  assertSavedSourceTiming(latestDraft)
  if (action === "approve") assertMediaCurrent(latestDraft)
  const current = dashboardEditorialPolicy(latestState, { runtimeReport })
  if (!current.policy || !checkedPolicySha || current.policy_sha256 !== checkedPolicySha) {
    fail("Editorial policy changed before this decision could be saved. Refresh and review again.", 409, "editorial_policy_changed")
  }
  if (action === "auto_approve") {
    const publication = dashboardAutomaticPolicy(latestState, { runtimeReport })
    if (!publication.enabled || publication.epoch !== checkedAutomaticEpoch) fail(publication.reason, 409, "automatic_publication_paused")
  }
}
