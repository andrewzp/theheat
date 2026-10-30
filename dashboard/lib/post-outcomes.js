/** Read-only retained observations. No collection, attribution or billing authority. */
import { draftIdentity, fingerprint, textHash, mergePassiveMaps, publicationObservationStatus } from "./draft-revisions.js"
import { validUsageObservation } from "./usage-observations.js"

export const OUTCOME_METRICS = ["likes", "retweets", "replies", "quotes", "impressions", "bookmarks"]
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const postId = value => typeof value === "string" && /^[0-9]{1,30}$/.test(value)
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null
const nonblank = value => typeof value === "string" && value.trim().length > 0
const emptyContext = status => ({ status, type: null, source: null })

function contextKey(eventId, identity) {
  return fingerprint([eventId, identity.content_revision, identity.text_sha256, identity.evidence_sha256])
}

function retainedContexts(drafts) {
  const contexts = new Map(), pending = Array.isArray(drafts) ? [...drafts] : [], seen = new Set()
  while (pending.length) {
    const snapshot = pending.pop()
    if (!object(snapshot) || seen.has(snapshot)) continue
    seen.add(snapshot)
    if (Array.isArray(snapshot.revision_history)) pending.push(...snapshot.revision_history)
    // Ordinary text-edit history omits id/event/type. Never complete that
    // partial snapshot with today's draft fields, even when the text matches.
    if (!["id", "event_id", "type", "text", "content_revision"].every(key => Object.hasOwn(snapshot, key)) ||
        !nonblank(snapshot.id) || !nonblank(snapshot.event_id) || !nonblank(snapshot.type) ||
        (Object.hasOwn(snapshot, "revision_conflicts") &&
          (!Array.isArray(snapshot.revision_conflicts) || snapshot.revision_conflicts.length))) continue
    try {
      const identity = draftIdentity(snapshot), bundle = snapshot.review_context?.two_bot?.bundle
      const source = object(bundle) && nonblank(bundle.event_id) && nonblank(bundle.signal_kind) && bundle.event_id === snapshot.event_id
        ? { event_id: bundle.event_id, signal_kind: bundle.signal_kind, bundle_sha256: fingerprint(bundle) } : null
      contexts.set(contextKey(snapshot.event_id, identity), { type: snapshot.type, source })
    } catch { /* Malformed or incomplete evidence cannot establish context. */ }
  }
  return contexts
}

function publicationContext(rows, contexts, textConflict) {
  const identities = new Set()
  let unavailable = false
  for (const { event_id, receipt } of rows || []) {
    try {
      if (!nonblank(event_id) || receipt.phase !== "confirmed" || !nonblank(receipt.intent_id) ||
          !Number.isSafeInteger(receipt.content_revision) || receipt.content_revision < 1 ||
          !sha(receipt.text_sha256) || !sha(receipt.evidence_sha256) ||
          typeof receipt.text !== "string" || textHash(receipt.text) !== receipt.text_sha256 ||
          (Object.hasOwn(receipt, "attempt_conflicts") && !Array.isArray(receipt.attempt_conflicts))) {
        unavailable = true
        continue
      }
      identities.add(contextKey(event_id, receipt))
    } catch { unavailable = true }
  }
  if (textConflict || identities.size > 1) return emptyContext("conflict")
  if (unavailable || identities.size !== 1) return emptyContext("unknown")
  const context = contexts.get([...identities][0])
  return context ? { status: "recorded", ...context, source: context.source && { ...context.source } } : emptyContext("unknown")
}

function writerContexts(rows) {
  const values = new Map()
  let unavailable = false, conflict = false
  for (const { event_id, receipt } of rows || []) {
    if (receipt.phase !== "confirmed" || !receipt.tweet_id || !Object.hasOwn(receipt, "publication_observations")) {
      unavailable = true; continue
    }
    if (Object.hasOwn(receipt, "attempt_conflicts") && (!Array.isArray(receipt.attempt_conflicts) || receipt.attempt_conflicts.some(row => !object(row)))) unavailable = true
    const maps = Object.entries(mergePassiveMaps(receipt.publication_observations))
    if (!maps.length) unavailable = true
    if (maps.length > 1) conflict = true
    for (const [digest, payload] of maps) {
      let status = "unknown"
      try { status = publicationObservationStatus(payload, event_id, receipt) } catch { /* Unreadable evidence stays unknown. */ }
      if (status === "conflict") conflict = true
      if (status === "unknown") unavailable = true
      const previous = values.get(digest)
      const rank = { recorded: 0, unknown: 1, conflict: 2 }
      if (!previous || rank[status] > rank[previous.status]) values.set(digest, { status, payload })
    }
  }
  if (values.size > 1) conflict = true
  const status = conflict ? "conflict" : unavailable || values.size !== 1 ? "unknown" : "recorded"
  const [digest, row] = values.entries().next().value || []
  if (status !== "recorded") return { status, variants: [...values].sort(([a], [b]) => a.localeCompare(b)).map(([sha256, item]) => ({ sha256, ...item })) }
  const payload = row.payload, writer = Object.values(mergePassiveMaps(payload.writer_observations))[0]
  return { status, sha256: digest, writer_reported_angle: writer.angle_chosen,
    text_comparison: writer.text_sha256 === payload.identity.text_sha256 ? "matches" : "differs",
    retained_different_text: Object.values(payload.text_observations).some(item => item.text_sha256 !== writer.text_sha256),
    history_scope: payload.history_scope, history_unavailable: payload.history_unavailable,
    actor_status: "unknown", source_relation: "matches", variants: [{ sha256: digest, status, payload }] }
}

function instant(value, latest) {
  if (typeof value !== "string") return null
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(value)
  if (!match || Number(value.slice(0, 4)) < 1 || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4]) > 59 || Number(match[7] || 0) > 23 || Number(match[8] || 0) > 59) return null
  const day = new Date(`${match[1]}T00:00:00Z`)
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== match[1]) return null
  const parsed = Date.parse(value.replace(/\.\d+(?=Z|[+-])/, ""))
  if (!Number.isFinite(parsed)) return null
  const fraction = (match[5] || "").padEnd(6, "0")
  const microseconds = BigInt(parsed) * 1000n + BigInt(fraction)
  if (microseconds > latest) return null
  return { microseconds, iso: new Date(parsed).toISOString().replace(".000Z", `.${fraction}Z`) }
}

function observation(raw, kind, key, tweetId, now) {
  const valid = object(raw) && (kind === "legacy" ? (!Object.hasOwn(raw, "tweet_id") || raw.tweet_id === tweetId) : (raw.schema_version === 1 && raw.tweet_id === tweetId && raw.source === "x_api.public_metrics"))
  const time = valid ? instant(kind === "legacy" ? raw.at : raw.sampled_at, now) : null
  const counts = valid && object(kind === "legacy" ? raw : raw.counts) ? (kind === "legacy" ? raw : raw.counts) : {}
  const posted = valid && kind === "sample" && raw.post_time_status === "recorded" && raw.post_time_basis === "x_api.created_at" && time !== null
    ? instant(raw.posted_at, time.microseconds) : null
  const age = posted === null ? null : Number(time.microseconds - posted.microseconds) / 1_000_000
  const ageMatches = age !== null && typeof raw.post_age_seconds === "number" && raw.post_age_seconds === age
  return {
    id: key, kind, association: valid ? "recorded" : "unusable",
    collected_at: time?.iso ?? null,
    post_age_seconds: ageMatches ? age : null,
    age_status: age !== null && !ageMatches ? "conflict" : ageMatches ? "recorded" : "unknown",
    counts: Object.fromEntries(OUTCOME_METRICS.map(field => [field, count(counts[field])])),
    conflict: false,
  }
}

/** Receipt identity and historical text are independent of today's draft text. */
// W15.6: what is still unknown about a delivered post, named rather than implied.
function evidenceNeeded(row) {
  const needed = []
  if (row.revision_status !== "recorded") needed.push("published_revision")
  if (row.publication_context?.status !== "recorded") needed.push("published_type_and_source")
  if (!row.observations.length) needed.push("metric_observation")
  else if (!row.observations.some(item => item.age_status === "recorded")) needed.push("platform_creation_time")
  return needed
}

// Optional supplied joins. Absent inputs are "not_loaded", distinct from "none recorded".
function feedbackFor(tweetId, records) {
  if (!Array.isArray(records)) return { status: "not_loaded" }
  const mine = records.filter(r => object(r) && object(r.target) && r.target.tweet_id === tweetId)
  const opinions = mine.filter(r => r.kind === "dashboard_editorial_opinion").length
  const tags = Object.fromEntries(["concise", "useful", "confusing", "incorrect"].map(tag => [tag, 0]))
  for (const r of mine) if (r.kind === "dashboard_revision_feedback" && Array.isArray(r.tags)) for (const tag of r.tags) if (Object.hasOwn(tags, tag)) tags[tag]++
  return { status: mine.length ? "recorded" : "none_recorded", editorial_opinions: opinions, revision_tags: tags, category: "human_feedback" }
}
function correctionsFor(tweetId, report) {
  if (!object(report) || !Array.isArray(report.candidates)) return { status: "not_loaded" }
  const candidates = report.candidates.filter(c => object(c) && c.tweet_id === tweetId && c.automatic_correction === false && c.deletion === false)
    .map(c => ({ claim: c.claim, kind: c.kind, uncertainty: c.uncertainty, source_retrieved_at: c.source_evidence?.retrieved_at ?? null,
      source_statement: c.source_evidence?.statement ?? null, action: "editor_review_only" }))
  const incomplete = (Array.isArray(report.incomplete) ? report.incomplete : []).filter(r => object(r) && r.tweet_id === tweetId)
    .map(r => (Array.isArray(r.needed) ? r.needed : []))
  return { status: candidates.length ? "candidates" : incomplete.length ? "evidence_needed" : "none_supplied", candidates, incomplete }
}

// The coverage class/region a delivered post was logged under, joined only by the
// receipt's exact event ID. One distinct class/region is required; the log is
// output geography, never a recall denominator or evidence of worldwide coverage.
const COVERAGE_TEXT = /^[^\u0000-\u001f]{1,80}$/
function coverageFor(eventIds, log) {
  if (!Array.isArray(log)) return { status: "not_loaded", rows: 0 }
  const matches = log.filter(row => object(row) && eventIds.has(row.event_id))
  if (!matches.length) return { status: "not_recorded", rows: 0 }
  const readable = matches.filter(row => ["cls", "continent", "country"].every(key => typeof row[key] === "string" && COVERAGE_TEXT.test(row[key])))
  const distinct = new Map(readable.map(row => [JSON.stringify([row.cls, row.continent, row.country]), row]))
  if (readable.length !== matches.length) return { status: "unknown", rows: matches.length }
  if (distinct.size !== 1) return { status: "conflict", rows: matches.length }
  const row = [...distinct.values()][0]
  return { status: "recorded", rows: matches.length, coverage_class: row.cls, continent: row.continent, country: row.country,
    date: typeof row.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(row.date) ? row.date : null,
    scope: "output_geography_not_recall" }
}

// Model responses attributed to a delivered post's exact receipt event (the
// attempt join written by src/two_bot/usage_ledger.py). Rows without an
// attribution, unjoined or operation-only rows are never assigned to a post.
// The window is bounded and older rows carry no attribution, so absence is
// "not_joined", not zero; token counts are usage, never a charge.
function costFor(eventIds, window) {
  const rows = object(window) && Array.isArray(window.observations) ? window.observations : null
  if (rows === null) return { status: "not_loaded", charge: "unknown" }
  const joined = rows.filter(row => validUsageObservation(row) && Object.hasOwn(row, "attribution")
    && row.attribution.status === "joined_attempt" && eventIds.has(row.attribution.event_id))
  if (!joined.length) return { status: "not_joined", charge: "unknown" }
  const stages = {}
  for (const row of joined) {
    const stage = stages[row.stage ?? "unknown"] ??= { responses: 0, usage_present: 0, providers: [] }
    stage.responses += 1
    stage.usage_present += row.usage_status === "present" ? 1 : 0
    if (!stage.providers.includes(row.provider)) stage.providers.push(row.provider)
  }
  for (const stage of Object.values(stages)) stage.providers.sort()
  return { status: "joined", responses: joined.length, attempts: new Set(joined.map(row => row.attribution.attempt)).size,
    by_stage: stages, charge: "unknown", scope: "retained_window_all_attempts_for_event",
    window_truncated: window.truncated === true }
}

export function postOutcomes(rawState, { now = Date.now(), feedbackRecords = null, correctionReport = null } = {}) {
  const clock = now instanceof Date ? now.getTime() : now
  if (!Number.isFinite(clock) || !Number.isFinite(new Date(clock).getTime())) throw new TypeError("Outcome history requires a valid clock")
  const state = object(rawState) ? rawState : {}
  const clockMicroseconds = BigInt(Math.floor(clock * 1000))
  let inventoryKnown = Array.isArray(state.drafts) && state.drafts.every(object) && object(state.publish_ledger)
  const posts = new Map(), receipts = new Map(), contexts = retainedContexts(state.drafts)
  const ensure = id => {
    if (!posts.has(id)) posts.set(id, { hashes: new Set(), texts: new Map(), conflict: false })
    return posts.get(id)
  }
  function text(post, value) {
    if (typeof value !== "string") return
    try { post.texts.set(textHash(value), value) } catch { /* Malformed text cannot establish a revision. */ }
  }
  const pending = object(state.publish_ledger) ? Object.entries(state.publish_ledger).map(([event_id, receipt]) => ({ event_id, receipt })) : []
  for (const draft of Array.isArray(state.drafts) ? state.drafts : []) {
    if (!object(draft)) continue
    if (postId(draft.tweet_id) && draft.status === "posted") ensure(draft.tweet_id)
    if (object(draft.published_revision)) pending.push({ event_id: draft.event_id || draft.id, receipt: draft.published_revision })
  }
  const seen = new Map()
  while (pending.length) {
    const { event_id, receipt } = pending.pop()
    if (!object(receipt)) { inventoryKnown = false; continue }
    if (!seen.has(receipt)) seen.set(receipt, new Set())
    if (seen.get(receipt).has(event_id)) continue
    seen.get(receipt).add(event_id)
    if (postId(receipt.tweet_id)) {
      if (!receipts.has(receipt.tweet_id)) receipts.set(receipt.tweet_id, [])
      receipts.get(receipt.tweet_id).push({ event_id, receipt })
    }
    if (postId(receipt.tweet_id) && receipt.phase !== "not_sent") {
      const post = ensure(receipt.tweet_id)
      if (sha(receipt.text_sha256)) post.hashes.add(receipt.text_sha256)
      text(post, receipt.text)
      if (sha(receipt.text_sha256) && typeof receipt.text === "string") {
        try { if (textHash(receipt.text) !== receipt.text_sha256) post.conflict = true } catch { post.conflict = true }
      }
    }
    if (Array.isArray(receipt.attempt_conflicts)) for (const child of receipt.attempt_conflicts) pending.push({ event_id, receipt: child })
    else if (receipt.attempt_conflicts != null) inventoryKnown = false
  }
  const results = []
  for (const [tweet_id, post] of posts) {
    const row = object(state.tweet_metrics) && object(state.tweet_metrics[tweet_id]) ? state.tweet_metrics[tweet_id] : null
    const retained = new Map()
    const writerContext = writerContexts(receipts.get(tweet_id))
    function add(raw, kind, storageKey) {
      let key
      try { key = `${kind}:${fingerprint(raw)}` } catch { key = `${kind}:unreadable:${storageKey}` }
      if (retained.has(key)) return
      const item = observation(raw, kind, key, tweet_id, clockMicroseconds)
      if (object(raw) && Object.hasOwn(raw, "publication_context_sha256")) {
        item.writer_context_status = writerContext.status === "conflict" ? "conflict"
          : item.association === "recorded" && kind === "sample" && writerContext.status === "recorded" && raw.publication_context_sha256 === writerContext.sha256 ? "recorded" : "unknown"
        item.publication_context_sha256 = sha(raw.publication_context_sha256) ? raw.publication_context_sha256 : null
      }
      retained.set(key, item)
      if (item.association === "recorded" && kind === "sample") {
        if (raw.published_revision_status === "conflict") post.conflict = true
        if (raw.published_revision_status === "recorded" && sha(raw.published_text_sha256)) post.hashes.add(raw.published_text_sha256)
      }
    }
    if (row) {
      if (object(row.samples)) for (const [key, raw] of Object.entries(row.samples)) add(raw, "sample", key)
      if (object(row.legacy_rows)) for (const [key, raw] of Object.entries(row.legacy_rows)) add(raw, "legacy", key)
      if (!Object.hasOwn(row, "samples") && !Object.hasOwn(row, "legacy_rows")) add(row, "legacy", "flat")
    }
    // Recover only text whose bytes match the retained published fingerprint.
    // No editorial metadata or authorship is inferred from the current draft.
    for (const draft of Array.isArray(state.drafts) ? state.drafts : []) {
      if (!object(draft) || draft.tweet_id !== tweet_id) continue
      text(post, draft.text)
      for (const revision of Array.isArray(draft.revision_history) ? draft.revision_history : []) {
        if (object(revision)) text(post, revision.text)
      }
    }
    const observations = [...retained.values()].sort((a, b) =>
      (a.collected_at === null) - (b.collected_at === null) || (a.collected_at || "").localeCompare(b.collected_at || "") || a.id.localeCompare(b.id))
    const times = new Map()
    for (const item of observations) {
      if (item.collected_at !== null) times.set(item.collected_at, (times.get(item.collected_at) || 0) + 1)
    }
    for (const item of observations) item.conflict = item.collected_at !== null && times.get(item.collected_at) > 1
    const conflict = post.conflict || post.hashes.size > 1
    const hash = !conflict && post.hashes.size === 1 ? [...post.hashes][0] : null
    results.push({ tweet_id, revision_status: conflict ? "conflict" : hash ? "recorded" : "unknown",
      published_text_sha256: hash, text: hash ? post.texts.get(hash) ?? null : null, observations,
      publication_context: publicationContext(receipts.get(tweet_id), contexts, conflict),
      writer_context: conflict ? { status: "conflict", variants: writerContext.variants } : writerContext,
      history_status: observations.length ? "retained" : row ? "unreadable_or_empty" : "not_retained",
      retained_text_versions: post.texts.size })
    const last = results.at(-1)
    last.evidence_needed = evidenceNeeded(last)
    last.feedback = feedbackFor(tweet_id, feedbackRecords)
    last.corrections = correctionsFor(tweet_id, correctionReport)
    last.generation_usage = costFor(new Set((receipts.get(tweet_id) || []).map(row => row.event_id).filter(nonblank)), state.llm_usage_observations)
    last.coverage = coverageFor(new Set((receipts.get(tweet_id) || []).map(row => row.event_id).filter(nonblank)), state.coverage_log)
  }
  results.sort((a, b) => a.tweet_id.localeCompare(b.tweet_id))
  return { status: results.length ? "retained" : inventoryKnown ? "no_retained_receipts" : "unknown", posts: results }
}
