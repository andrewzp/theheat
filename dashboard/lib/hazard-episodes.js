// Physical-episode joins for the normal editor (W07.2/07.3/07.6). Reads the binding each
// draft already carries (review_context.physical_episode, written by the source runners
// and by `scripts/hazard_episodes.py publish`); there is no separate episode store.
// Mutations are per-draft evidence changes: the previous review context is kept in
// revision_history, review and approval are invalidated, delivered snapshots are refused.
// Report bytes never enter this view: a join names its retained report by SHA-256 only.
import { decisionRevision, draftIdentity, hasUnresolvedPublish, revokeApproval } from "./draft-revisions.js"

export const EPISODE_ACTIONS = Object.freeze(["remove_join", "split", "supersede"])
const SOURCE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$/
const MAX_RELATED = 20

const list = value => Array.isArray(value) ? value : []
const object = value => value && typeof value === "object" && !Array.isArray(value)

function fail(message, status = 409, code = "episode_command_refused") {
  throw Object.assign(new Error(message), { status, code })
}

export function parseEpisodeId(value) {
  const parts = typeof value === "string" ? value.split(":") : []
  if (parts[0] !== "ep1" || parts.length < 4) return null
  const [, hazard, issuer, ...rest] = parts
  return rest[0] === "anon"
    ? { hazard, issuer, anonymous: true, country: rest[1] ?? null, place: rest[2] ?? null, start_date: rest[3] ?? null }
    : { hazard, issuer, anonymous: false, source_event_id: rest.join(":") }
}

function binding(draft) {
  const value = draft?.review_context?.physical_episode
  return object(value) && typeof value.episode_id === "string" ? value : null
}

function delivered(draft, state) {
  return draft?.status === "posted" || draft?.publish_outcome === "unknown" || hasUnresolvedPublish(draft, state)
}

function separateReason(mine, other) {
  const a = parseEpisodeId(mine), b = parseEpisodeId(other)
  if (!a || !b) return "Separate: one episode identity cannot be read."
  if (a.hazard !== b.hazard) return "Separate: different hazards are never merged."
  if (a.issuer !== b.issuer) return `Separate: different issuers (${a.issuer} and ${b.issuer}); a join needs a shared identifier, or geometry and time overlap.`
  if (a.anonymous || b.anonymous) {
    if (a.country !== b.country) return "Separate: a different country."
    if (a.start_date !== b.start_date) return "Separate: a different start date."
    return "Separate: a different place."
  }
  return `Separate: a different ${a.issuer} source event ID. A matching name is never identity.`
}

function relationshipFor(own, episodeId, other) {
  return own.relationships?.find?.(row => list(row?.episodes).includes(episodeId) && list(row?.episodes).includes(other)) ?? null
}

export function episodeView(state, draftId) {
  const drafts = list(state?.drafts)
  const draft = drafts.find(row => row?.id === draftId)
  if (!draft) return null
  const own = binding(draft)
  const editable = ["pending", "approved"].includes(draft.status) && !delivered(draft, state)
  if (!own) {
    return { draft_id: draft.id, bound: false, editable: false, hold: draft.review_context?.physical_episode_hold ?? null,
      message: "No physical episode is bound to this draft. Episode binding is off, or the source supplied no identifier." }
  }
  const related = drafts.filter(row => row !== draft && binding(row)).map(row => ({ row, other: binding(row) }))
  const sameEpisode = related.filter(({ other }) => other.episode_id === own.episode_id).slice(0, MAX_RELATED)
    .map(({ row, other }) => ({ draft_id: row.id, status: row.status, source_revision: other.source_revision ?? null,
      update_of: other.update_of ?? null, eligibility: list(other.eligibility),
      why: `Joined: the same ${parseEpisodeId(own.episode_id)?.issuer ?? "issuer"} source event identity.` }))
  const hazard = parseEpisodeId(own.episode_id)?.hazard
  const separate = related.filter(({ other }) => other.episode_id !== own.episode_id && parseEpisodeId(other.episode_id)?.hazard === hazard)
    .slice(0, MAX_RELATED).map(({ row, other }) => {
      const relation = relationshipFor(own, own.episode_id, other.episode_id)
      return { draft_id: row.id, status: row.status, episode_id: other.episode_id,
        relationship: relation ? { decision: relation.decision, reason: relation.reason } : null,
        why: relation?.decision === "joined"
          ? `Joined by ${String(relation.reason).replaceAll("_", " ")}; human impacts are never combined.`
          : relation ? `Proposed only: ${String(relation.reason).replaceAll("_", " ")}.` : separateReason(own.episode_id, other.episode_id) }
    })
  const supersedeTargets = [...new Set(related.map(({ other }) => other.episode_id)
    .filter(id => id !== own.episode_id && parseEpisodeId(id)?.hazard === hazard))].sort()
  return {
    draft_id: draft.id, bound: true, editable,
    identity: { candidate_id: own.lineage?.candidate_id ?? draft.event_id ?? null, source_revision: own.source_revision ?? null,
      episode_id: own.episode_id, publication: { draft_id: draft.id, tweet_id: draft.tweet_id ?? null } },
    issuer: own.issuer ?? parseEpisodeId(own.episode_id)?.issuer ?? null, hazard, evidence_type: own.evidence_type ?? null,
    status: own.episode_status ?? "active", superseded_by: own.superseded_by ?? null,
    admission: { eligibility: list(own.eligibility), ignored_changes: list(own.ignored_changes), update_of: own.update_of ?? null },
    same_episode: sameEpisode, separate,
    relationships: list(own.relationships).map(row => ({ episodes: list(row?.episodes), decision: row?.decision, reason: row?.reason,
      contributors: list(row?.contributors), impacts_combined: row?.impacts_combined === true })),
    report_joins: list(own.report_joins).map(row => ({ join_id: row?.join_id, report_sha256: row?.report_sha256 ?? null,
      status: row?.status, reason: row?.reason, removed: row?.removed === true, removed_at: row?.removed_at ?? null,
      statement: row?.status === "matched" ? row?.claim?.text ?? null : null, attribution: row?.claim?.attribution ?? null,
      observation_type: row?.observation_type ?? null })),
    history: list(own.history), supersede_targets: supersedeTargets,
  }
}

// Mirror of the media-attachment invalidation in draft-revisions.js for an evidence change.
function invalidateEvidence(draft, change) {
  const previous = {}
  for (const key of ["text", "review_context", "review_binding", "approval_binding", "revision_conflicts", "decision_revision", "media_attachment", "media_review_binding"]) {
    if (Object.hasOwn(draft, key)) previous[key] = structuredClone(draft[key])
  }
  Object.assign(previous, draftIdentity(draft), { invalidated_at: new Date().toISOString() })
  if (previous.content_revision >= Number.MAX_SAFE_INTEGER || decisionRevision(draft) >= Number.MAX_SAFE_INTEGER - 1) fail("Revision exhausted", 422, "invalid_draft_data")
  if (Object.hasOwn(draft, "revision_history") && !Array.isArray(draft.revision_history)) fail("Invalid revision history", 422, "invalid_draft_data")
  draft.revision_history ??= []
  draft.revision_history.push(previous)
  draft.content_revision = previous.content_revision + 1
  draft.status = "pending"
  revokeApproval(draft)
  for (const key of ["review_binding", "media_review_binding", "revision_conflicts", "candidate_score", "selected_candidate_rank"]) delete draft[key]
  if (draft.review_context?.two_bot) draft.review_context.two_bot = Object.fromEntries(Object.entries(draft.review_context.two_bot).filter(([key]) => ["bundle", "signal_kind"].includes(key)))
  change(draft.review_context.physical_episode)
  draft.episode_invalidated = true
  return draft
}

export function applyEpisodeCommand(draft, command, { state, actor = "dashboard", now = new Date().toISOString() } = {}) {
  if (!EPISODE_ACTIONS.includes(command?.action)) fail("Unknown episode action.", 400, "invalid_episode_action")
  const own = binding(draft)
  if (!own) fail("No physical episode is bound to this draft.", 409, "episode_unbound")
  if (!["pending", "approved"].includes(draft.status) || delivered(draft, state)) {
    fail("A delivered or unreconciled draft keeps its snapshot; it cannot be changed.", 409, "draft_delivered")
  }
  const entry = { action: command.action, at: now, by: actor, from_episode: own.episode_id }
  if (command.action === "remove_join") {
    const join = list(own.report_joins).find(row => row?.join_id === command.joinId)
    if (!join || join.removed === true) fail("That report join is not active on this draft.", 409, "report_join_unknown")
    return invalidateEvidence(draft, value => {
      const target = value.report_joins.find(row => row?.join_id === command.joinId)
      // The join row and its report hash stay; only the match is withdrawn from the writer's support.
      Object.assign(target, { removed: true, removed_at: now, removed_by: actor })
      value.history = [...list(value.history), { ...entry, join_id: command.joinId, report_sha256: join.report_sha256 ?? null }]
    })
  }
  const parsed = parseEpisodeId(own.episode_id)
  if (command.action === "split") {
    if (typeof command.newSourceId !== "string" || !SOURCE_ID.test(command.newSourceId)) fail("Name the new episode with a source identifier (letters, digits, . _ : -).", 400, "episode_split_target")
    const next = `ep1:${parsed.hazard}:${parsed.issuer}:${command.newSourceId}`
    const known = new Set(list(state?.drafts).map(row => binding(row)?.episode_id).filter(Boolean))
    if (next === own.episode_id || known.has(next)) fail("That episode already exists; use supersede to point at it.", 409, "episode_split_target")
    if (own.historical_hold && !/^[a-f0-9]{64}$/.test(command.evidencePacketSha256 ?? "")) fail("This incident stays held until its missing evidence packet is supplied.", 409, "historical_hold")
    return invalidateEvidence(draft, value => {
      value.history = [...list(value.history), { ...entry, to_episode: next, origin_source_revision: own.source_revision ?? null }]
      value.split_from = own.episode_id
      value.episode_id = next
      // Joins and relationships were made against the old episode; they stay in revision history only.
      value.relationships = []
      value.report_joins = []
    })
  }
  const target = command.supersededBy
  const valid = typeof target === "string" && target !== own.episode_id && parseEpisodeId(target)?.hazard === parsed.hazard
    && list(state?.drafts).some(row => binding(row)?.episode_id === target)
  if (!valid) fail("Choose an existing episode of the same hazard.", 409, "episode_supersede_target")
  if (own.historical_hold) fail("This incident stays held until its missing evidence packet is supplied.", 409, "historical_hold")
  return invalidateEvidence(draft, value => {
    value.history = [...list(value.history), { ...entry, superseded_by: target }]
    value.episode_status = "superseded"
    value.superseded_by = target
  })
}
