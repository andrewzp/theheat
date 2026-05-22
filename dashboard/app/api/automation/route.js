import { requireDashboardAuth } from "../../../lib/auth.js"
import { getAutomationStatus } from "../../../lib/automation.js"

export const runtime = "nodejs"

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  try {
    const status = await getAutomationStatus()
    return Response.json(status)
  } catch (e) {
    return Response.json({ error: e?.message || "automation status failed" }, { status: 500 })
  }
}
