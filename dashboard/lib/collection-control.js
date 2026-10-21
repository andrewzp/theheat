// Presentation/request fence only. The server remains the authority for a run.
export const COLLECTION_STATUS_MAX_AGE_MS = 60_000
const MODES = new Set(["alerts", "leaderboard", "both"])

export function collectionAvailability(observation, now = Date.now()) {
  const blocked = message => ({ allowed: false, message })
  if (!observation) return blocked("Checking collection and draft-generation settings…")
  if (observation.localPreview) return blocked("Live collection is unavailable in this local preview.")
  if (observation.failed || !observation.dashboardReady) return blocked("Collection status is unavailable. Refresh before starting a run.")
  if (!Number.isFinite(now) || !Number.isFinite(observation.observedAt)
      || now < observation.observedAt || now - observation.observedAt >= COLLECTION_STATUS_MAX_AGE_MS)
    return blocked("Collection settings need a refresh before starting a run.")
  if (observation.dashboardPaused === true || observation.collectionPause === "configured")
    return blocked("Collection and draft generation are paused. Existing drafts remain available for review.")
  if (observation.dashboardPaused !== false || observation.collectionPause !== "not_configured")
    return blocked("Collection settings are unverified. Refresh before starting a run.")
  return { allowed: true, message: "Collection is not paused in the reported settings. Provider access remains unverified." }
}

export function createCollectionControl({ clock = () => Date.now() } = {}) {
  let epoch = 0
  let observation = null
  let busy = false
  return {
    begin() { observation = null; return ++epoch },
    complete(ticket, { status, error, dashboardReady = false, localPreview = false } = {}) {
      if (ticket !== epoch) return false
      observation = Object.freeze({ observedAt: clock(), dashboardReady: dashboardReady === true,
        localPreview: localPreview === true, failed: error != null,
        dashboardPaused: typeof status?.dashboard_generation_pause === "boolean" ? status.dashboard_generation_pause : null,
        collectionPause: status?.collection_pause?.status })
      return true
    },
    observation() { return observation },
    async request(mode, { fetcher = globalThis.fetch, onStart, onFinish } = {}) {
      const availability = collectionAvailability(observation, clock())
      if (!availability.allowed || busy || !MODES.has(mode)) return { ok: false, attempted: false,
        error: !availability.allowed ? availability.message : busy ? "A run is already being requested." : "Choose a supported collection mode." }
      busy = true
      try {
        onStart?.()
        const response = await fetcher("/api/trigger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) })
        const value = await response.json()
        return { ok: response.ok && value.ok === true, attempted: true,
          error: typeof value.error === "string" ? value.error : "Collection request was not accepted." }
      } finally { busy = false; onFinish?.() }
    },
  }
}
