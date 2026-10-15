import { requireDashboardAuth } from "../../../lib/auth.js"
import { acceptLocalCommand, previewConfigured } from "../../../lib/draft-command-client.js"
export const runtime = "nodejs"
export async function POST(request) {
  const auth = requireDashboardAuth(request)
  if (auth) return auth
  const query = new URL(request.url).searchParams
  const id = query.get("commandId")
  if (!previewConfigured()) return Response.json({ code:"local_recovery_unavailable" }, { status:503 })
  if (query.size !== 1 || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id || "")) {
    return Response.json({ code:"invalid_submission_reference" }, { status:400 })
  }
  return acceptLocalCommand(request, "abandon_submission", id)
}
