import { requireDashboardAuth } from "../../../lib/auth.js"
import { previewConfigured } from "../../../lib/draft-command-client.js"
import { decideReconciliation, inspectReconciliation, ReconciliationError } from "../../../lib/delivery-reconciliation.js"
import { fingerprint } from "../../../lib/draft-revisions.js"
import { readStateStore, writeStateStore } from "../../../lib/state-store.js"
export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store" }
const LIMIT = 16 * 1024

// Read-only inspection of every publish attempt and the actions it allows.
export async function GET(request) {
  const auth = requireDashboardAuth(request)
  if (auth) return auth
  try {
    return Response.json({ ...inspectReconciliation(await readStateStore(request)), writes_enabled: enabled() }, { headers })
  } catch {
    return Response.json({ code: "reconciliation_state_unavailable" }, { status: 503, headers })
  }
}

// Writes are an explicit operator capability, exact "1" only, default off.
function enabled() { return process.env.THEHEAT_DELIVERY_RECONCILIATION_ENABLED === "1" }

export async function POST(request) {
  const auth = requireDashboardAuth(request)
  if (auth) return auth
  if (!enabled()) return Response.json({ code: "delivery_reconciliation_disabled" }, { status: 503, headers })
  // The local preview authority has no reconciliation journal; the local CLI owns that path.
  if (previewConfigured()) return Response.json({ code: "local_reconciliation_uses_local_cli" }, { status: 503, headers })
  if (request.headers.get("content-type") !== "application/json") return Response.json({ code: "json_required" }, { status: 415, headers })
  let body
  try {
    const raw = await request.text()
    if (raw.length > LIMIT) return Response.json({ code: "reconciliation_request_too_large" }, { status: 413, headers })
    body = JSON.parse(raw)
  } catch { return Response.json({ code: "reconciliation_request_invalid" }, { status: 400, headers }) }
  try {
    const at = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")
    const state = await readStateStore(request)
    const { state: next, result } = decideReconciliation(state, body, { actor: "dashboard-operator", at })
    if (result.status !== "applied") return Response.json(result, { headers })
    // Second read: refuse if the attempt or its draft changed since the decision.
    const latest = await readStateStore(request)
    const eventId = body.event_id
    const draftOf = s => (s.drafts || []).find(d => (d?.event_id || d?.id) === eventId) ?? null
    if (fingerprint({ row: latest.publish_ledger?.[eventId] ?? null, draft: draftOf(latest) })
      !== fingerprint({ row: state.publish_ledger?.[eventId] ?? null, draft: draftOf(state) })) {
      return Response.json({ code: "revision_conflict" }, { status: 409, headers })
    }
    await writeStateStore({ publish_ledger: { [eventId]: next.publish_ledger[eventId] }, ...(result.action === "cancel" ? { drafts: [draftOf(next)] } : {}) })
    return Response.json(result, { headers })
  } catch (error) {
    if (error instanceof ReconciliationError) return Response.json({ code: error.code }, { status: 409, headers })
    return Response.json({ code: "reconciliation_write_unconfirmed" }, { status: 503, headers })
  }
}
