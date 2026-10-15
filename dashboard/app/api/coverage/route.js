import { requireDashboardAuth } from "../../../lib/auth.js"
import { acceptLocalCommand, localCommandRequest, previewConfigured, previewError } from "../../../lib/draft-command-client.js"

export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }
function unavailable() {
  return previewConfigured() ? null : Response.json({ error: "Coverage evidence is not configured.", code: "coverage_unavailable" }, { status: 503, headers })
}
export async function GET(request) {
  const error = requireDashboardAuth(request) || unavailable()
  if (error) return error
  try {
    const { payload } = await localCommandRequest(request, "/coverage")
    return Response.json(payload, { headers })
  } catch (error) { return previewError(error) }
}
export async function POST(request) {
  const error = requireDashboardAuth(request) || unavailable()
  if (error) return error
  return acceptLocalCommand(request, "evaluate_reference_coverage")
}
