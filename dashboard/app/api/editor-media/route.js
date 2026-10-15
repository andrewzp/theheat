import { requireDashboardAuth } from "../../../lib/auth.js"
import { localCommandRequest, previewConfigured, previewError } from "../../../lib/draft-command-client.js"

export const runtime = "nodejs"
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" }

export async function GET(request) {
  const auth = requireDashboardAuth(request)
  if (auth) return auth
  if (!previewConfigured()) return Response.json({ code: "editor_media_unavailable" }, { status: 503, headers })
  try {
    const query = new URL(request.url).searchParams
    const draft = query.get("draftId"), proposal = query.get("proposal"), original = query.get("original"), delivery = query.get("deliveryIntent")
    if (!/^[A-Za-z0-9_.:-]{1,200}$/.test(draft || "") || [...query.keys()].some(k => !["draftId", "proposal", "original", "deliveryIntent"].includes(k)) ||
        query.getAll("draftId").length !== 1 || query.getAll("proposal").length > 1 || query.getAll("original").length > 1 ||
        query.getAll("deliveryIntent").length > 1 || (delivery !== null &&
          (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(delivery) || proposal !== null || original !== null ||
           request.body || request.headers.has("range") || request.headers.has("transfer-encoding") ||
           (request.headers.has("content-length") && request.headers.get("content-length") !== "0"))) ||
        (original !== null && (original !== "1" || proposal === null)) ||
        (proposal !== null && !/^[a-f0-9]{64}$/.test(proposal))) {
      return Response.json({ code: "invalid_media_reference" }, { status: 400, headers })
    }
    const path = `/drafts/${draft}/media${delivery ? `/delivery/${delivery}` : proposal ? `/${proposal}/${original ? "original.gif" : "preview.png"}` : ""}`
    const result = await localCommandRequest(request, path)
    return result.bytes ? new Response(result.bytes, { headers: { ...headers, "Content-Type": result.mimeType || "image/png" } })
      : Response.json(result.payload, { headers })
  } catch (error) { return previewError(error) }
}
