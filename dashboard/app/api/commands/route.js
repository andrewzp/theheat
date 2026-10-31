import { mutationOriginError, requireDashboardAuth } from "../../../lib/auth.js"
import { readJsonObject } from "../../../lib/request-json.js"
import { submitCommand, validateCommandRaw } from "../../../lib/gist-write-route.js"
import { submittedResponse } from "../../../lib/gist-route-submit.js"

// P00c: resubmit the SAME retained command after a lost/uncertain response. The exact canonical
// bytes are re-validated and dispatched again; admission and the consumer are idempotent by
// command id + digest, so a duplicate can never be applied twice. Route control is root-only.
export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (mutationOriginError(request)) return Response.json({ code: "command_origin_refused" }, { status: 403, headers })
  const { body, error } = await readJsonObject(request, { strict: true, maxBytes: 80 * 1024 })
  if (error) return error
  if (Object.keys(body).length !== 1 || typeof body.command !== "string") return Response.json({ code: "invalid_command" }, { status: 400, headers })
  try {
    const { command, expired } = validateCommandRaw(body.command)
    if (command.producer.kind === "gist_route_control") return Response.json({ code: "route_control_not_dashboard" }, { status: 403, headers })
    if (expired) return Response.json({ code: "expired", command_id: command.command_id }, { status: 409, headers })
    return submittedResponse(await submitCommand(body.command), headers)
  } catch (failure) {
    return Response.json({ code: typeof failure?.code === "string" ? failure.code : "invalid_command" }, { status: failure?.status || 400, headers })
  }
}
