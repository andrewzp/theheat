/** Read-only recorded X receipts. Never an approval, quota or live platform check. */
import { postOutcomes, retainedInstant } from "./post-outcomes.js"

const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const postId = value => typeof value === "string" && /^[0-9]{1,30}$/.test(value)
const DAY = 86_400_000n * 1000n
const MAX_ROWS = 10_000

export function postingEvidence(rawState, { now = Date.now() } = {}) {
  const clock = now instanceof Date ? now.getTime() : now
  if (!Number.isFinite(clock) || !Number.isFinite(new Date(clock).getTime())) throw new TypeError("Posting cadence requires a valid clock")
  const latest = BigInt(Math.floor(clock * 1000))
  const date = new Date(clock).toISOString().slice(0, 10)
  const start = BigInt(Date.parse(`${date}T00:00:00Z`)) * 1000n
  const state = object(rawState) ? rawState : {}
  // Resolve actual retained observation associations once. A supplied label or
  // caller-provided "passed" projection cannot substitute for this consumer.
  const outcomes = postOutcomes(state, { now: clock })
  let known = Array.isArray(state.drafts) && object(state.publish_ledger)
  let invalidIds = 0, visitedRows = 0
  const receipts = new Map(), seen = new WeakSet(), pending = []

  function enqueue(row, kind, path = new Set()) {
    if (pending.length + visitedRows >= MAX_ROWS) { known = false; return }
    pending.push({ row, kind, path })
  }
  for (const row of Array.isArray(state.drafts) ? state.drafts : []) enqueue(row, "draft")
  for (const row of object(state.publish_ledger) ? Object.values(state.publish_ledger) : []) enqueue(row, "ledger")
  while (pending.length) {
    const { row, kind, path } = pending.pop()
    visitedRows++
    if (!object(row) || path.has(row) || path.size > 32) { known = false; continue }
    if (seen.has(row)) continue
    seen.add(row)
    const next = new Set(path).add(row)
    if (row.published_revision != null) enqueue(row.published_revision, "ledger", next)
    if (row.attempt_conflicts != null) {
      if (!Array.isArray(row.attempt_conflicts)) known = false
      else for (const child of row.attempt_conflicts) enqueue(child, "ledger", next)
    }
    if (kind === "draft" && row.status !== "posted") continue
    if (row.tweet_id == null || row.tweet_id === "") continue
    if (!postId(row.tweet_id)) { invalidIds++; known = false; continue }
    // A contradictory not-sent row is not a new receipt. Its confirmed children
    // are inspected independently and cannot be erased by the parent's status.
    if (kind === "ledger" && row.phase === "not_sent") { known = false; continue }
    if (!receipts.has(row.tweet_id)) receipts.set(row.tweet_id, { times: new Map(), invalid: false })
    const receipt = receipts.get(row.tweet_id)
    const value = kind === "draft" ? row.posted_at
      : row.confirmed_at ?? (["confirmed", "posted"].includes(row.phase) ? row.at : undefined)
    // An absent time can be supplied by another copy. An explicit bad time is
    // retained as uncertainty, never silently replaced by a later good spelling.
    if (value == null || value === "") continue
    const time = retainedInstant(value, latest)
    if (!time) receipt.invalid = true
    else receipt.times.set(time.microseconds.toString(), time)
  }

  for (const post of outcomes.posts) {
    const receipt = receipts.get(post.tweet_id)
    if (!receipt) continue
    const platform = new Map()
    let conflict = false
    for (const observation of post.observations) {
      if (observation.age_status === "conflict") conflict = true
      if (observation.association !== "recorded" || observation.age_status !== "recorded") continue
      const time = retainedInstant(observation.platform_created_at, latest)
      if (time) platform.set(time.microseconds.toString(), time)
    }
    // Supported platform creation times describe publication, unlike local
    // acknowledgement times. They may resolve local date disagreements.
    // Disagreeing platform observations remain alternatives, never first-wins.
    if (platform.size) {
      receipt.times = platform
      receipt.invalid = conflict
    }
  }

  function window(lower) {
    let count = 0, unknown = 0
    for (const receipt of receipts.values()) {
      if (receipt.invalid || !receipt.times.size) { unknown++; continue }
      const inside = [...receipt.times.values()].map(time => time.microseconds >= lower)
      if (inside.every(Boolean)) count++
      else if (inside.some(Boolean)) unknown++
    }
    const complete = known && unknown === 0
    return { status: complete ? "recorded" : !known && count === 0 ? "unknown" : "partial",
      minimum_count: count, uncertain_receipt_count: unknown,
      target_met: count >= 4 ? true : complete ? false : null }
  }

  const dated = [...receipts].filter(([, row]) => !row.invalid && row.times.size === 1)
    .map(([tweet_id, row]) => ({ tweet_id, time: [...row.times.values()][0] }))
    .sort((a, b) => a.time.microseconds < b.time.microseconds ? 1 : a.time.microseconds > b.time.microseconds ? -1 : a.tweet_id.localeCompare(b.tweet_id))
  const last = dated[0]
  const undated = [...receipts.values()].filter(row => row.invalid || row.times.size !== 1).length
  const at = last ? last.time.microseconds % 1000n === 0n
    ? new Date(Number(last.time.microseconds / 1000n)).toISOString() : last.time.iso : null
  const cadence = { schema_version: 1, target_per_day: 4, date_utc: date, as_of: new Date(clock).toISOString(),
    inventory_known: known, retained_receipt_count: receipts.size, invalid_id_records: invalidIds,
    uncertain_time_receipts: undated, today: window(start), last_24h: window(latest - DAY),
    latest_dated_receipt: last ? { status: "recorded", tweet_id: last.tweet_id, at,
      age_hours: Number(latest - last.time.microseconds) / 3_600_000_000,
      evidence: "retained_publication_receipt", uncertain_time_receipts: undated }
      : { status: "unknown", at: null, age_hours: null, uncertain_time_receipts: undated },
    notes: ["Recorded X post IDs only; drafts, posted flags and send attempts are not posts. Supported platform creation dates take precedence; otherwise dates describe saved local confirmations. This is retained evidence, not a complete platform history or a live check.",
      "The four-post goal does not change publication, selection or spending limits. Missing or conflicting times remain uncertain; no newest date is chosen."] }
  return { cadence, outcomes }
}

export function postingCadence(rawState, options) { return postingEvidence(rawState, options).cadence }
