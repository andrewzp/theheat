const DAY_MS = 24 * 60 * 60 * 1000

function dayStampMs(dateStr) {
  if (!dateStr) return Number.NaN
  return new Date(`${dateStr}T12:00:00Z`).getTime()
}

export function todayTweetCount(dailyMap, nowIso) {
  const now = new Date(nowIso)
  if (Number.isNaN(now.getTime())) return 0
  const todayKey = now.toISOString().slice(0, 10)
  return dailyMap?.[todayKey] ?? 0
}

export function timeAgo(dateStr) {
  if (!dateStr) return "never"
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export function formatDuration(ms) {
  if (ms === undefined || ms === null) return "—"
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function hot10IsStale(dateStr, nowIso) {
  const stampMs = dayStampMs(dateStr)
  const nowMs = new Date(nowIso).getTime()
  if (!Number.isFinite(stampMs) || !Number.isFinite(nowMs)) return false
  return nowMs - stampMs > DAY_MS
}

export function hot10StaleDays(dateStr, nowIso) {
  const stampMs = dayStampMs(dateStr)
  const nowMs = new Date(nowIso).getTime()
  if (!Number.isFinite(stampMs) || !Number.isFinite(nowMs)) return 0
  const ageMs = nowMs - stampMs
  if (ageMs <= DAY_MS) return 0
  return Math.max(1, Math.floor(ageMs / DAY_MS))
}
