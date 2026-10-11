import { requireDashboardAuth } from "../../../lib/auth.js"
import { acceptLocalCommand, localCommandRequest, previewConfigured, previewError } from "../../../lib/draft-command-client.js"

export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }
function unavailable() {
  if (process.env.THEHEAT_PRODUCTION_PAUSED === "1") return Response.json({ error: "Data collection and draft generation are paused. Existing drafts remain available for review.", code: "production_paused" }, { status: 503, headers })
  if (!previewConfigured()) return Response.json({ error: "Sourced generation is not configured. Existing drafts remain available for review.", code: "sourced_generation_unavailable" }, { status: 503, headers })
  return null
}
export async function GET(request) {
  const error = requireDashboardAuth(request) || unavailable()
  if (error) return error
  try {
    const { payload } = await localCommandRequest(request, "/generation")
    return Response.json(payload, { headers })
  } catch (error) { return previewError(error) }
}
export async function POST(request) {
  const error = requireDashboardAuth(request) || unavailable()
  if (error) return error
  return acceptLocalCommand(request, "request_sourced_generation")
}
