import { mutationOriginError, requireDashboardAuth } from "../../../lib/auth.js"
import { readJsonObject } from "../../../lib/request-json.js"
import { activeRouteActivation, parseCommandRaw, readRouteRecord, submitCommand } from "../../../lib/gist-write-route.js"
import { openEnvelope, requireSealKey } from "../../../lib/gist-command-seal.js"
import { sessionActorSubject, submittedResponse } from "../../../lib/gist-route-submit.js"

// P00c: resubmit the SAME retained command after a lost/uncertain response (ROUTE-CONTRACT-v2 §1).
// Only an exact sealed envelope this server issued is accepted: it must open under the server key
// (authentic, unaltered, every public field bound), name the current session subject and the
// currently active route activation, and be unexpired. It is re-dispatched byte-for-byte; admission
// and the consumer are idempotent by command id + digest. Route control is root-only.
export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }
const refuse = (code, status) => Response.json({ code }, { status, headers })

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (mutationOriginError(request)) return refuse("command_origin_refused", 403)
  const { body, error } = await readJsonObject(request, { strict: true, maxBytes: 80 * 1024 })
  if (error) return error
  if (Object.keys(body).length !== 1 || typeof body.command !== "string") return refuse("invalid_command", 400)
  try {
    const parsed = parseCommandRaw(body.command)
    if (parsed.kind !== "sealed") {
      return parsed.command.producer?.kind === "gist_route_control" ? refuse("route_control_not_dashboard", 403) : refuse("plaintext_command_refused", 400)
    }
    openEnvelope(parsed, requireSealKey())
    if (parsed.envelope.actor_subject !== sessionActorSubject(request)) return refuse("command_actor_mismatch", 403)
    if (parsed.expired) return Response.json({ code: "expired", command_id: parsed.envelope.command_id }, { status: 409, headers })
    if (activeRouteActivation(await readRouteRecord()) !== parsed.envelope.route_activation) return refuse("route_generation_not_current", 409)
    return submittedResponse(await submitCommand(body.command), headers)
  } catch (failure) {
    return refuse(typeof failure?.code === "string" ? failure.code : "invalid_command", failure?.status || 400)
  }
}
