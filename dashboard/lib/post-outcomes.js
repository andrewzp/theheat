/** Read-only retained observations. No collection, attribution or billing authority. */
import { fingerprint, textHash } from "./draft-revisions.js"

export const OUTCOME_METRICS = ["likes", "retweets", "replies", "quotes", "impressions", "bookmarks"]
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const postId = value => typeof value === "string" && /^[0-9]{1,30}$/.test(value)
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null

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
export function postOutcomes(rawState, { now = Date.now() } = {}) {
  const clock = now instanceof Date ? now.getTime() : now
  if (!Number.isFinite(clock) || !Number.isFinite(new Date(clock).getTime())) throw new TypeError("Outcome history requires a valid clock")
  const state = object(rawState) ? rawState : {}
  const clockMicroseconds = BigInt(Math.floor(clock * 1000))
  let inventoryKnown = Array.isArray(state.drafts) && state.drafts.every(object) && object(state.publish_ledger)
  const posts = new Map()
  const ensure = id => {
    if (!posts.has(id)) posts.set(id, { hashes: new Set(), texts: new Map(), conflict: false })
    return posts.get(id)
  }
  function text(post, value) {
    if (typeof value !== "string") return
    try { post.texts.set(textHash(value), value) } catch { /* Malformed text cannot establish a revision. */ }
  }
  const pending = object(state.publish_ledger) ? Object.values(state.publish_ledger) : []
  for (const draft of Array.isArray(state.drafts) ? state.drafts : []) {
    if (!object(draft)) continue
    if (postId(draft.tweet_id) && draft.status === "posted") ensure(draft.tweet_id)
    if (object(draft.published_revision)) pending.push(draft.published_revision)
  }
  const seen = new Set()
  while (pending.length) {
    const receipt = pending.pop()
    if (!object(receipt)) { inventoryKnown = false; continue }
    if (seen.has(receipt)) continue
    seen.add(receipt)
    if (postId(receipt.tweet_id) && receipt.phase !== "not_sent") {
      const post = ensure(receipt.tweet_id)
      if (sha(receipt.text_sha256)) post.hashes.add(receipt.text_sha256)
      text(post, receipt.text)
      if (sha(receipt.text_sha256) && typeof receipt.text === "string") {
        try { if (textHash(receipt.text) !== receipt.text_sha256) post.conflict = true } catch { post.conflict = true }
      }
    }
    if (Array.isArray(receipt.attempt_conflicts)) for (const child of receipt.attempt_conflicts) pending.push(child)
    else if (receipt.attempt_conflicts != null) inventoryKnown = false
  }
  const results = []
  for (const [tweet_id, post] of posts) {
    const row = object(state.tweet_metrics) && object(state.tweet_metrics[tweet_id]) ? state.tweet_metrics[tweet_id] : null
    const retained = new Map()
    function add(raw, kind, storageKey) {
      let key
      try { key = `${kind}:${fingerprint(raw)}` } catch { key = `${kind}:unreadable:${storageKey}` }
      if (retained.has(key)) return
      const item = observation(raw, kind, key, tweet_id, clockMicroseconds)
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
      history_status: observations.length ? "retained" : row ? "unreadable_or_empty" : "not_retained" })
  }
  results.sort((a, b) => a.tweet_id.localeCompare(b.tweet_id))
  return { status: results.length ? "retained" : inventoryKnown ? "no_retained_receipts" : "unknown", posts: results }
}
