import { hasUnresolvedPublish, reviewIsCurrent } from "./draft-revisions.js"
import { buildRuntimeConfig } from "./runtime-inventory.js"

const HOUR = 3600000
const DAY = 24 * HOUR
const METRIC_FIELDS = ["likes", "retweets", "replies"]
const INTERNAL_SOURCES = new Set(["twitter_metrics", "budget", "triage", "billing"])
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value)
const rows = (value) => Array.isArray(value) ? value.filter(object) : []
const entries = (value) => object(value) ? Object.entries(value) : []
const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : null
const identifier = (value) => typeof value === "string" && value.trim() ? value.trim() : null
const draftInventoryKnown = (state) => Array.isArray(state.drafts) && state.drafts.every(object)
const validAttempt = (row) => object(row) && (row.attempt_conflicts == null || (Array.isArray(row.attempt_conflicts) && row.attempt_conflicts.every(validAttempt)))
const ledgerInventoryKnown = (state) => object(state.publish_ledger) && Object.values(state.publish_ledger).every(validAttempt)

// Date.parse normalizes invalid calendar dates. Reject those, ambiguous local
// clocks and future rows instead of making corrupt telemetry look recent.
function timestamp(value, now) {
  if (typeof value !== "string") return null
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.exec(value)
  if (!match) return null
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number)
  const calendar = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00Z`)
  if (year < 1 || !Number.isFinite(calendar.getTime()) || calendar.toISOString().slice(0, 10) !== value.slice(0, 10)) return null
  if (month > 12 || day > 31 || hour > 23 || minute > 59 || second > 59) return null
  const parsed = Date.parse(match[7] ? value : `${value}Z`)
  return Number.isFinite(parsed) && parsed <= now ? parsed : null
}

function dayStart(day, now) {
  return typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day) ? timestamp(`${day}T00:00:00Z`, now) : null
}

function milestone(candidates, now) {
  const latest = candidates.filter((row) => row.time !== null).sort((a, b) => b.time - a.time)[0]
  if (!latest) return { status: "unknown", at: null, age_hours: null }
  const { time, ...details } = latest
  return { status: "recorded", at: new Date(time).toISOString(), age_hours: (now - time) / HOUR, ...details }
}

function sourceRows(state, now) {
  const result = []
  for (const [source, health] of entries(state.source_health)) {
    for (const row of rows(health?.runs)) result.push({ ...row, source, time: timestamp(row.ts, now), evidence: "source_health" })
  }
  for (const run of rows(state.run_history)) {
    for (const row of rows(run.sources)) result.push({ ...row, time: timestamp(run.ended_at || run.started_at, now), evidence: "run_history", timestamp_precision: "run" })
  }
  return result.filter((row) => row.time !== null).sort((a, b) => b.time - a.time)
}

function attempts(row) {
  if (!object(row)) return []
  return [row, ...rows(row.attempt_conflicts).flatMap(attempts)]
}

function unresolvedLedger(row) {
  if (!validAttempt(row)) return true
  return attempts(row).some((attempt) => !identifier(attempt.tweet_id) && attempt.phase !== "not_sent")
}

function receiptPosts(state, drafts, now) {
  const posts = new Map()
  function add(tweetId, postedAt, eligibleAt, details, collectorSupported = true) {
    const tweet_id = identifier(tweetId)
    if (!tweet_id) return
    const time = timestamp(postedAt, now)
    const eligibility_time = timestamp(eligibleAt, now)
    const previous = posts.get(tweet_id)
    posts.set(tweet_id, {
      ...details, tweet_id,
      collector_supported: collectorSupported || previous?.collector_supported === true,
      time: previous?.time != null && (time === null || previous.time > time) ? previous.time : time,
      eligibility_time: previous?.eligibility_time != null && (eligibility_time === null || previous.eligibility_time > eligibility_time) ? previous.eligibility_time : eligibility_time,
    })
  }
  for (const draft of drafts) add(draft.tweet_id, draft.posted_at || draft.last_publish_attempt_at, draft.posted_at || draft.last_publish_attempt_at, { id: draft.id ?? null, evidence: "draft_receipt" })
  for (const [event_id, row] of entries(state.publish_ledger)) {
    // The current collector reads only the top-level ledger row and draft IDs.
    // Conflict receipts remain real publication evidence, but are not silently
    // advertised as IDs that this collector knows how to fetch.
    for (const attempt of attempts(row)) add(attempt.tweet_id, attempt.confirmed_at || attempt.at, attempt === row ? attempt.at : null, { event_id, evidence: "publish_ledger" }, attempt === row)
  }
  return [...posts.values()]
}

function queueHealth(state, drafts, now) {
  const draftsKnown = draftInventoryKnown(state)
  const inventoryKnown = draftsKnown && ledgerInventoryKnown(state)
  const waiting = []
  const draftEvents = new Set()
  let pending = 0
  let approved = 0
  for (const draft of drafts) {
    const eventId = draft.event_id || draft.id
    if (eventId) draftEvents.add(eventId)
    let unresolved = false
    try { unresolved = hasUnresolvedPublish(draft, state) } catch { unresolved = true }
    if (eventId && Object.hasOwn(object(state.publish_ledger) ? state.publish_ledger : {}, eventId) && unresolvedLedger(state.publish_ledger[eventId])) unresolved = true
    if (draft.status === "pending") pending += 1
    if (draft.status === "approved") approved += 1
    if (!["pending", "approved"].includes(draft.status) && !unresolved) continue
    const dates = [draft.created_at, ...(unresolved ? [draft.last_publish_attempt_at, ...attempts(state.publish_ledger?.[eventId]).map((row) => row.at)] : [])]
      .map((at) => timestamp(at, now)).filter((at) => at !== null)
    waiting.push({ unresolved, time: dates.length ? Math.min(...dates) : null })
  }
  for (const [event_id, row] of entries(state.publish_ledger)) {
    if (draftEvents.has(event_id) || !unresolvedLedger(row)) continue
    const dates = attempts(row).map((attempt) => timestamp(attempt.at, now)).filter((at) => at !== null)
    waiting.push({ unresolved: true, time: dates.length ? Math.min(...dates) : null })
  }
  const knownDates = waiting.map((row) => row.time).filter((at) => at !== null)
  const oldest = knownDates.length ? Math.min(...knownDates) : null
  return {
    status: inventoryKnown ? "recorded" : "unknown",
    waiting_count: inventoryKnown ? waiting.length : null,
    pending_count: draftsKnown ? pending : null, approved_count: draftsKnown ? approved : null,
    unresolved_publish_count: inventoryKnown ? waiting.filter((row) => row.unresolved).length : null,
    oldest_waiting_at: oldest === null ? null : new Date(oldest).toISOString(),
    oldest_waiting_age_hours: oldest === null ? null : (now - oldest) / HOUR,
    unknown_age_count: inventoryKnown ? waiting.filter((row) => row.time === null).length : null,
    notes: ["Counts cover retained drafts and orphan ledger events; unknown publication never ages out. Missing or malformed collections yield unknown counts, not an empty queue. Approval status alone does not establish a current review or permission to post."],
  }
}

function writerHealth(state, now) {
  const calls = []
  for (const [day, bucket] of entries(state.llm_usage)) {
    const time = dayStart(day, now)
    if (time === null) continue
    for (const [key, aggregate] of entries(bucket)) {
      const [stage, ...modelParts] = key.split("|")
      const recorded = count(aggregate?.calls)
      if (stage !== "writer" || recorded === null || recorded === 0 || !modelParts.join("|")) continue
      calls.push({ day, time, model: modelParts.join("|"), calls: recorded })
    }
  }
  calls.sort((a, b) => b.time - a.time)
  const failures = rows(state.suppressions)
    .filter((row) => ["budget_exhausted", "billing_cycle_abort", "pipeline_error"].includes(row.stage))
    .map((row) => ({ time: timestamp(row.ts, now), stage: row.stage, reasons: Array.isArray(row.reasons) ? row.reasons.filter((reason) => typeof reason === "string") : [] }))
    .sort((a, b) => (b.time ?? -Infinity) - (a.time ?? -Infinity))
  const latest = calls[0]
  const failure = failures.find((row) => row.time === null) ?? failures[0]
  // Daily call totals cannot establish whether a call preceded a same-day error.
  // Unordered errors likewise cannot be dismissed as recovered.
  const failed = failure && (failure.time === null || !latest || latest.time <= failure.time)
  return {
    status: failed ? "failed" : latest ? "calls_recorded" : "unknown",
    last_recorded_call_day: latest?.day ?? null,
    last_recorded_call_count: latest ? calls.filter((row) => row.day === latest.day).reduce((sum, row) => sum + row.calls, 0) : null,
    models: latest ? [...new Set(calls.filter((row) => row.day === latest.day).map((row) => row.model))].sort() : [],
    last_failure: failure ? { at: failure.time === null ? null : new Date(failure.time).toISOString(), stage: failure.stage, reasons: failure.reasons } : null,
    notes: ["Usage records successful writer responses by UTC day, not exact call times or accepted drafts. Same-day calls cannot prove recovery after an error; a green workflow never establishes provider credit recovery.", "The usage ledger retains at most 45 day buckets, excludes non-state-writing replays and can undercount concurrent writers. Errors come from at most 100 retained pipeline suppression rows; pipeline errors may occur after the writer."],
  }
}

function metricsHealth(state, posts, sources, now) {
  const inventoryKnown = draftInventoryKnown(state) && ledgerInventoryKnown(state)
  const runtime = buildRuntimeConfig(state, { now })
  const collectionEnabled = runtime.status === "recorded" && typeof runtime.flags.metrics_enabled === "boolean" ? runtime.flags.metrics_enabled : null
  // The collector selects at most 50 unique IDs from a 30-day lookback.
  const eligible = posts.filter((post) => post.eligibility_time !== null && post.eligibility_time >= now - 30 * DAY)
    .sort((a, b) => b.eligibility_time - a.eligibility_time).slice(0, 50)
  const undated = posts.filter((post) => post.time === null).length
  const unknownEligibility = posts.filter((post) => post.collector_supported && post.eligibility_time === null).length
  const sampled = eligible.map((post) => {
    const row = object(state.tweet_metrics) ? state.tweet_metrics[post.tweet_id] : null
    const time = row?.latest_sample_conflict === true ? null : timestamp(row?.at, now)
    return { time, values: Object.fromEntries(METRIC_FIELDS.map((field) => [field, time === null ? null : count(row?.[field])])) }
  })
  const complete = sampled.filter((row) => METRIC_FIELDS.every((field) => row.values[field] !== null)).length
  const anyRecorded = sampled.some((row) => METRIC_FIELDS.some((field) => row.values[field] !== null))
  const sampleDates = sampled.filter((row) => Object.values(row.values).some((value) => value !== null)).map((row) => row.time)
  const lastSample = sampleDates.length ? Math.max(...sampleDates) : null
  const collector = sources.find((row) => row.source === "twitter_metrics")
  const failedAfterSample = collector && (["failed", "partial_failure"].includes(collector.status) || (collector.status === "skipped" && /credential|access|auth/i.test(collector.note || collector.error || ""))) && (lastSample === null || collector.time >= lastSample)
  let status = "unknown"
  if (!inventoryKnown) status = "unknown"
  else if (!eligible.length) status = unknownEligibility ? "unknown" : "inactive"
  else if (failedAfterSample) status = "unavailable"
  else if (complete === eligible.length) status = "recorded"
  else if (anyRecorded) status = "partial"
  else if (collector?.status === "success") status = "unavailable"
  return {
    status, collection_enabled: collectionEnabled, lookback_days: 30, max_ids_per_collection: 50,
    eligible_post_count: inventoryKnown ? eligible.length : null, receipt_backed_post_count: inventoryKnown ? posts.length : null,
    undated_receipt_count: inventoryKnown ? undated : null, recorded_post_count: inventoryKnown ? complete : null,
    collector_unseen_receipt_count: inventoryKnown ? posts.filter((post) => !post.collector_supported).length : null,
    missing_post_count: inventoryKnown ? eligible.length - complete : null,
    last_sample_at: lastSample === null ? null : new Date(lastSample).toISOString(),
    totals: Object.fromEntries(METRIC_FIELDS.map((field) => [field, inventoryKnown && sampled.length && sampled.every((row) => row.values[field] !== null) ? sampled.reduce((sum, row) => sum + row.values[field], 0) : null])),
    last_collector: collector ? { at: new Date(collector.time).toISOString(), status: collector.status ?? null, error: collector.error ?? null, note: collector.note ?? null } : null,
    notes: ["Inactive means no retained receipt-backed post is eligible for the collector's 30-day window; it requires present draft and ledger collections and does not prove credentials or collection work. Missing collections or undated receipts have unknown eligibility.", "Missing or conflicting latest fields remain null; recorded zero is data. Totals use the latest unconflicted snapshot of eligible retained receipts only. New samples preserve collection time and post age when the platform creation time is available; historical samples are not yet presented here. Old stored metrics do not establish current collection, a fixed-age comparison or causal lift."],
  }
}

/** A read-only evidence projection. Workflow success and generation memory are not product outcomes. */
export function buildProductHealth(rawState, { now = Date.now() } = {}) {
  const clock = now instanceof Date ? now.getTime() : now
  if (!Number.isFinite(clock) || !Number.isFinite(new Date(clock).getTime())) throw new TypeError("Product health requires a valid clock")
  const state = object(rawState) ? rawState : {}
  const drafts = rows(state.drafts)
  const sources = sourceRows(state, clock)
  const posts = receiptPosts(state, drafts, clock)
  return {
    generated_at: new Date(clock).toISOString(),
    milestones: {
      source_observed: milestone(sources.filter((row) => identifier(row.source) && !INTERNAL_SOURCES.has(row.source) && count(row.observed) > 0).map((row) => ({ time: row.time, source: row.source, observed: row.observed, reported_status: row.status ?? null, evidence: row.evidence, timestamp_precision: row.timestamp_precision ?? "source" })), clock),
      draft_created: milestone(drafts.map((draft) => ({ time: timestamp(draft.created_at, clock), id: draft.id ?? null })), clock),
      draft_reviewed: milestone(drafts.filter((draft) => { try { return reviewIsCurrent(draft) } catch { return false } }).map((draft) => ({ time: timestamp(draft.review_binding.reviewed_at, clock), id: draft.id ?? null, review_kind: draft.review_binding.kind })), clock),
      post_confirmed: milestone(posts.map(({ eligibility_time, ...post }) => post), clock),
    },
    queue: queueHealth(state, drafts, clock),
    writer: writerHealth(state, clock),
    metrics: metricsHealth(state, posts, sources, clock),
    notes: ["These are latest retained observations, not a complete account history or a health guarantee. Source observations require a positive recorded count; success without an observation count does not establish that input arrived. Source-health rows retain a 7-day window and at most 10 runs per source; run history retains at most 20 runs.", "A current review is bound to the exact retained text and evidence; it is not independent scientific validation. A draft or legacy generation-memory text is not a publication. Only an explicit tweet ID establishes a stored publication receipt; this projection does not re-verify the platform.", "Missing, malformed and future timestamps cannot establish freshness. Retention can hide earlier successes and failures; absence of telemetry is unknown, not a recorded zero."],
  }
}
