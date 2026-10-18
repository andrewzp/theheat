import { requireDashboardAuth } from "../../../lib/auth.js"
import { previewConfigured } from "../../../lib/local-preview-boundary.js"
import { FeedbackError, readPostFeedback, savePostFeedback } from "../../../lib/post-feedback.js"

export const runtime = "nodejs"
const headers = { "Cache-Control":"private, no-store" }
const response = (body, status = 200) => Response.json(body, { status, headers })
function unavailable() {
  return previewConfigured() || process.env.THEHEAT_DB_PATH || (process.env.THEHEAT_STATE_BACKEND && process.env.THEHEAT_STATE_BACKEND !== "gist")
}
function errorResponse(error) {
  return response({ code:error instanceof FeedbackError ? error.code : "feedback_store_unavailable" }, error instanceof FeedbackError ? error.status : 503)
}
async function input(request) {
  if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || !request.body) throw new FeedbackError("invalid_feedback", 400)
  const reader = request.body.getReader(), chunks = []
  let size = 0, timer
  const deadline = new Promise((_, reject) => { timer = setTimeout(() => reject(new FeedbackError("invalid_feedback", 400)), 5000) })
  try {
    while (true) {
      const {done, value} = await Promise.race([reader.read(), deadline])
      if (done) break
      size += value.byteLength
      if (size > 8192) throw new FeedbackError("invalid_feedback", 400)
      chunks.push(Buffer.from(value))
    }
    return JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(Buffer.concat(chunks)))
  } catch { throw new FeedbackError("invalid_feedback", 400) }
  finally { clearTimeout(timer); void reader.cancel().catch(() => {}) }
}
export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (unavailable()) return response({code:"feedback_gist_only"}, 503)
  try { return response(await readPostFeedback(new URL(request.url).searchParams.get("request_id"))) }
  catch (error) { return errorResponse(error) }
}
export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (unavailable()) return response({code:"feedback_gist_only"}, 503)
  // Require the browser's exact same-origin signal even with Basic authentication.
  // Proxy/forwarded headers cannot grant another origin access to this write.
  if (request.headers.get("origin") !== new URL(request.url).origin ||
      (request.headers.get("sec-fetch-site") && request.headers.get("sec-fetch-site") !== "same-origin")) return response({code:"feedback_origin_refused"}, 403)
  try { return response(await savePostFeedback(await input(request))) }
  catch (error) { return errorResponse(error) }
}
