// Browser-safe exact command construction; one gesture retains this body for retry.
export function createDraftCommand(draft, action, payload = {}, now = new Date()) {
  const names = { edit: "edit_revision", review: "record_review", approve: "approve_revision",
    reject: "reject_revision", cancel_auto_approve: "cancel_approval", select_candidate: "select_candidate" }
  if (!names[action]) throw new Error("This action is unavailable in local preview.")
  const reason = "Local preview editorial action; no publication transport"
  const data = action === "edit" ? { text: payload.editedText }
    : action === "review" ? { confirmed: payload.reviewConfirmed, reason, expected_policy_sha256: payload.expectedPolicySha256 }
    : action === "select_candidate" ? { candidate_rank: payload.candidateRank,
      candidate_sha256: draft.candidates?.find((c) => c.rank === payload.candidateRank)?.command_sha256 }
    : { reason }
  return { command_id: crypto.randomUUID(), action: names[action], requested_at: now.toISOString(),
    expires_at: new Date(now.getTime() + 3600000).toISOString(),
    targets: [{ draft_id: draft.id, ...(payload.expectedRevision || draft.revision_identity) }], payload: data }
}


export function createCandidateCommand(candidate, action, now = new Date()) {
  if (action === "admit_checked_slate") {
    const keys = ["slate_id", "slate_sha256", "expected_state_version", "expected_policy_sha256", "expected_completion_set_sha256"]
    return { command_id: crypto.randomUUID(), action, requested_at: now.toISOString(),
      expires_at: new Date(now.getTime() + 3600000).toISOString(), targets: [],
      payload: Object.fromEntries(keys.map(key => [key, candidate[key]])) }
  }
  if (!["request_candidate_checks", "admit_checked_candidate"].includes(action)) throw new Error("Unknown candidate action")
  const originKeys = candidate.origin_kind === "synchronous_writer_v1" ? ["origin_kind", "generation_id"] : ["job_id", "custom_id"]
  const keys = ["admission_input_id", "admission_input_sha256", ...originKeys, "candidate_id", "expected_state_version", "expected_policy_sha256"]
  if (action === "admit_checked_candidate") keys.push("check_set_id", "expected_completion_sha256")
  return { command_id: crypto.randomUUID(), action, requested_at: now.toISOString(),
    expires_at: new Date(now.getTime() + 3600000).toISOString(), targets: [],
    payload: Object.fromEntries(keys.map((key) => [key, candidate[key]])) }
}

export function localCommandEndpoint(command) {
  return ["request_sourced_generation", "request_important_variants"].includes(command.action) ? "/api/generate" : "/api/drafts"
}
