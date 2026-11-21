/** Within one projected receipt-backed post; no collection or quality verdict. */
export const METRIC_CHANGE_KEYS = ["likes", "retweets", "replies", "quotes", "impressions", "bookmarks"]
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const held = reason => ({ status: "unavailable", reason })

function instant(value) {
  if (typeof value !== "string") return null
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{6})Z$/.exec(value)
  if (!match || Number(value.slice(0, 4)) < 1) return null
  const milliseconds = Date.parse(match[1] + "Z")
  if (!Number.isFinite(milliseconds) || new Date(milliseconds).toISOString().slice(0, 19) !== match[1]) return null
  return BigInt(milliseconds) * 1000n + BigInt(match[2])
}

export function perPostMetricChange(post) {
  if (!object(post) || post.revision_status !== "recorded"
    || typeof post.tweet_id !== "string" || !/^[0-9]{1,30}$/.test(post.tweet_id)) return held("published_revision_unavailable")
  if (!Array.isArray(post.observations) || post.observations.some(row =>
    !object(row) || !["sample", "legacy"].includes(row.kind))) return held("history_unavailable")
  // Legacy snapshots do not establish the API source/time/age relation.
  const samples = post.observations.filter(row => row.kind === "sample")
  const timed = samples.map(row => ({ row, time: instant(row.collected_at) }))
  // An undated API observation cannot silently be treated as an older sample.
  if (timed.some(item => item.time === null)) return held("sample_order_unavailable")
  if (timed.length < 2) return { status: "insufficient_samples", sample_count: timed.length }
  timed.sort((a, b) => a.time > b.time ? -1 : a.time < b.time ? 1 : 0)
  const [latest, previous] = timed
  if (latest.time === previous.time || timed.slice(2).some(item => item.time === previous.time)
    || typeof latest.row.id !== "string"
    || typeof previous.row.id !== "string" || !latest.row.id || !previous.row.id
    || latest.row.id === previous.row.id) return held("latest_samples_conflict")
  const created = [latest, previous].map(item => instant(item.row.platform_created_at))
  for (let index = 0; index < 2; index++) {
    const { row, time } = [latest, previous][index], start = created[index]
    if (row.association !== "recorded" || row.age_status !== "recorded" || row.conflict !== false
      || start === null || time < start || !Number.isFinite(row.post_age_seconds)
      || row.post_age_seconds !== Number(time - start) / 1_000_000) return held("sample_time_or_age_unavailable")
  }
  if (created[0] !== created[1]) return held("different_post_time")
  if (latest.row.post_age_seconds <= previous.row.post_age_seconds) return held("sample_time_or_age_unavailable")
  const describe = item => ({ collected_at: item.row.collected_at, post_age_seconds: item.row.post_age_seconds })
  return { status: "comparable", previous: describe(previous), latest: describe(latest),
    metrics: METRIC_CHANGE_KEYS.map(key => {
      const before = count(previous.row.counts?.[key]), after = count(latest.row.counts?.[key])
      return { key, previous: before, latest: after, change: before === null || after === null ? null : after - before }
    }) }
}
