import { requireDashboardAuth } from "../../../../lib/auth.js"
import { commandStatus } from "../../../../lib/gist-write-route.js"

// P00c: result of one serialized-route command: applied | refused(code) | pending | unknown.
// Read-only (state Gist, feedback Gist, admitted-artifact listing); success is never synthesized.
export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }

export async function GET(request, context) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  const { id } = await context.params
  const digest = new URL(request.url).searchParams.get("digest")
  try {
    return Response.json(await commandStatus(id, { digest: /^[a-f0-9]{64}$/.test(digest || "") ? digest : null }), { headers })
  } catch (error) {
    return Response.json({ code: typeof error?.code === "string" ? error.code : "command_status_unavailable" },
      { status: error?.status || 503, headers })
  }
}
