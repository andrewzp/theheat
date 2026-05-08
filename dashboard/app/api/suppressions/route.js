import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

const DEFAULT_LIMIT = 50
const MAX_LIMIT = 200

function parseLimit(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_LIMIT
  return Math.min(Math.floor(parsed), MAX_LIMIT)
}

function tsValue(s) {
  if (!s?.ts) return 0
  const parsed = Date.parse(s.ts)
  return Number.isFinite(parsed) ? parsed : 0
}

// GET — return recent suppressions (newest first), with optional filters.
export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  try {
    const url = new URL(request.url)
    const sourceFilter = url.searchParams.get("source")
    const sinceFilter = url.searchParams.get("since")
    const limit = parseLimit(url.searchParams.get("limit"))

    const state = await readStateStore()
    const all = Array.isArray(state.suppressions) ? state.suppressions : []

    const sinceMs = sinceFilter ? Date.parse(sinceFilter) : NaN
    const filtered = all.filter((s) => {
      if (sourceFilter && s.source !== sourceFilter) return false
      if (Number.isFinite(sinceMs) && tsValue(s) < sinceMs) return false
      return true
    })

    filtered.sort((a, b) => tsValue(b) - tsValue(a))
    const suppressions = filtered.slice(0, limit)

    // Aggregate stats over the FULL (filtered) set, not just the page.
    const now = Date.now()
    const day = 24 * 60 * 60 * 1000
    const last24h = filtered.filter((s) => now - tsValue(s) < day).length
    const last7d = filtered.filter((s) => now - tsValue(s) < 7 * day).length

    const sourceCounts = {}
    const stageCounts = {}
    for (const s of filtered) {
      const sourceKey = s.source || "unknown"
      sourceCounts[sourceKey] = (sourceCounts[sourceKey] || 0) + 1

      const stageKey = s.stage || "unknown"
      stageCounts[stageKey] = (stageCounts[stageKey] || 0) + 1
    }
    const topSource = Object.entries(sourceCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || null
    const topStage = Object.entries(stageCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || null

    return Response.json({
      suppressions,
      stats: {
        total: filtered.length,
        last24h,
        last7d,
        top_source: topSource,
        source_counts: sourceCounts,
        top_stage: topStage,
        stage_counts: stageCounts,
      },
    })
  } catch (e) {
    return Response.json({ suppressions: [], stats: null, error: e.message }, { status: 500 })
  }
}
