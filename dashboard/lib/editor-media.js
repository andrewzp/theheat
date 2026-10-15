// Browser carries references and explicit human decisions, never check verdicts.
export const jointConfirmations = {
  text_matches_data: "The tweet matches the saved source facts.",
  graphic_matches_data: "The graphic matches those facts.",
  text_graphic_agree: "The tweet and graphic say the same thing.",
  qualifications_visible: "Forecast, date, measurement and scope qualifiers are visible.",
  alt_text_agrees: "The full image description agrees with the graphic and tweet.",
}

export const publishedConfirmations = {
  raster_labels_match: "I checked the original station, complete timestamp, dBZ scale and warning legend.",
  named_point_context_matches: "Oklahoma City is visibly labeled; this is point context, not the full warning footprint or impact proof.",
  unaltered_product_reuse_conditions_met: "The original marks and credits are preserved and the product reuse conditions are met.",
}

export function confirmationsFor(packet) {
  return packet?.schema_version === 2 ? { ...jointConfirmations, ...publishedConfirmations } : jointConfirmations
}

export function mediaCommand(view, action, review, now = new Date()) {
  const payload = { expected_policy_sha256: view.expected_policy_sha256 }
  if (["prepare_media_revision", "request_revision_checks", "approve_media_revision"].includes(action))
    payload.expected_renderer_profile_sha256 = view.expected_renderer_profile_sha256
  if (["attach_media_revision", "review_media_revision"].includes(action)) {
    payload.proposal_sha256 = view.preparation.proposal_sha256
    payload.expected_packet_sha256 = view.packet.packet_sha256
    payload.review = review
  } else if (["request_revision_checks", "approve_media_revision"].includes(action)) {
    payload.expected_packet_sha256 = view.packet.packet_sha256
    payload.expected_review_sha256 = view.expected_review_sha256
    if (action === "approve_media_revision") {
      payload.expected_check_completion_sha256 = view.expected_check_completion_sha256
      payload.reason = "Park the current jointly reviewed local text and graphic."
    }
  } else if (action === "remove_media_revision") {
    payload.expected_proposal_sha256 = view.removal.expected_proposal_sha256
    payload.confirmed = true
    payload.reason = "Remove this graphic from the local draft."
  } else if (action === "cancel_approval") {
    delete payload.expected_policy_sha256
    payload.reason = "Cancel the parked local text and graphic approval."
  } else if (action !== "prepare_media_revision") throw new Error("Unknown graphic action")
  return { command_id: crypto.randomUUID(), action,
    requested_at: action === "remove_media_revision" ? view.removal.requested_at : now.toISOString(),
    expires_at: action === "remove_media_revision" ? view.removal.expires_at : new Date(now.getTime() + 300000).toISOString(),
    targets: [structuredClone(view.target)], payload }
}

export function sameMediaTarget(view, draft) {
  const target = { draft_id: draft.id, ...draft.revision_identity }
  return view?.draft_id === draft.id && view?.publication_approved === false &&
    Object.keys(target).every(k => target[k] === view.target?.[k]) && Object.keys(view.target || {}).length === 5
}

export function mediaStatus(view) {
  if (view.parked) return "Approval parked for this text and graphic. Nothing will be published."
  if (view.status === "unavailable") return "Graphic unavailable for this saved revision. " + (view.code || "").replaceAll("_", " ")
  if (view.checks_status === "passed") return "All four required checks passed for this text and graphic."
  if (view.checks_status === "pending") return "Checks are pending. The separate local worker runs one stage at a time."
  if (view.review_current) return "Joint human review recorded. Run fresh checks before parking approval."
  if (view.status === "attached") return "Graphic attached. Review the current text, image and description together."
  if (view.status === "prepared") return "Graphic prepared. It is not attached or reviewed yet."
  return "Prepare a graphic from the saved source facts. No new source fetch or AI generation."
}

export async function retainedMediaBlob(view, signal) {
  const response = await fetch(`/api/editor-media?draftId=${encodeURIComponent(view.draft_id)}&proposal=${view.preparation.proposal_sha256}`,
    { cache:"no-store", redirect:"error", signal })
  if (!response.ok || response.headers.get("content-type") !== "image/png" || !response.body) throw new Error("The retained graphic is unavailable")
  const reader=response.body.getReader(),chunks=[]
  let size=0
  try {
    while (true) {
      if(signal.aborted) throw new Error("Graphic request cancelled")
      const {done,value}=await reader.read()
      if(done) break
      size+=value.length
      if(size>8*1024*1024) throw new Error("Graphic exceeds the local size limit")
      chunks.push(value)
    }
    const bytes=new Uint8Array(size)
    let offset=0
    for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length}
    if(signal.aborted || bytes.length<33 || ![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v)) throw new Error("Invalid retained PNG")
    return new Blob([bytes],{type:"image/png"})
  // Cleanup must not create a second, unhandled rejection after a failed read.
  } finally { void reader.cancel().catch(() => {}) }
}
