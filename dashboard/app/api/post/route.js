import { requireDashboardAuth } from "../../../lib/auth.js"

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  return Response.json({ error: "Untracked text cannot publish. Review a sourced draft in the workbench first.", code: "sourced_draft_required" },
    { status: 409, headers: { "Cache-Control": "no-store" } })
}
