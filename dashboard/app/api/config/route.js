import { requireDashboardAuth } from "../../../lib/auth.js"
import { readStateWithRuntimeReport } from "../../../lib/state-store.js"
import { buildRuntimeConfig } from "../../../lib/runtime-inventory.js"

export const runtime = "nodejs"

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }

  try {
    const { state, runtimeReport } = await readStateWithRuntimeReport()
    return Response.json(buildRuntimeConfig(state, { runtimeReport }), { headers: { "Cache-Control": "no-store" } })
  } catch {
    return Response.json({ ...buildRuntimeConfig(), error: "Bot runtime inventory is unavailable because state could not be read." }, { status: 503 })
  }
}
