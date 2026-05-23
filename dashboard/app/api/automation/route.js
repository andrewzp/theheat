import { requireDashboardAuth } from "../../../lib/auth.js"
import { getAutomationStatus } from "../../../lib/automation.js"

export const runtime = "nodejs"

const DEFAULT_AUTOMATION_CACHE_TTL_MS = 15000

let cachedStatus = null
let cachedAt = 0
let cachedPromise = null

function cacheTtlMs() {
  const raw = Number(process.env.THEHEAT_AUTOMATION_CACHE_TTL_MS)
  if (!Number.isFinite(raw) || raw < 0) return DEFAULT_AUTOMATION_CACHE_TTL_MS
  return raw
}

async function getCachedAutomationStatus() {
  const ttl = cacheTtlMs()
  if (ttl === 0) return getAutomationStatus()

  const now = Date.now()
  if (cachedStatus && now - cachedAt < ttl) {
    return cachedStatus
  }
  if (cachedPromise) {
    return cachedPromise
  }

  cachedPromise = getAutomationStatus()
    .then((status) => {
      cachedStatus = status
      cachedAt = Date.now()
      return status
    })
    .finally(() => {
      cachedPromise = null
    })
  return cachedPromise
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  try {
    const status = await getCachedAutomationStatus()
    return Response.json(status)
  } catch (e) {
    return Response.json({ error: e?.message || "automation status failed" }, { status: 500 })
  }
}
