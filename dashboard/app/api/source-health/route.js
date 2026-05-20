import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { buildSourceHealthPayload } from "../../../lib/source-health.js"

export const runtime = "nodejs"

const DEFAULT_RUNS = 20

// GET — return per-source health rollup.
//
// Newer state reads source_health first so duration/funnel metrics survive
// past the short run_history cap. Older state falls back to run_history
// aggregation. Sorted worst-first so dashboard surfaces problem sources.
export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  try {
    const url = new URL(request.url)
    const requested = Number(url.searchParams.get("runs"))
    const runsLimit = Number.isFinite(requested) && requested > 0
      ? Math.min(Math.floor(requested), DEFAULT_RUNS)
      : DEFAULT_RUNS

    const state = await readStateStore()
    return Response.json(buildSourceHealthPayload(state, { runsLimit }))
  } catch (e) {
    return Response.json({ sources: [], stats: null, error: e.message }, { status: 500 })
  }
}
