import { localPreviewConfiguration as configuration, localPreviewError, previewConfigured } from "./local-preview-boundary.js"
export { previewConfigured }
import { fingerprint, hasUnresolvedPublish, projectDraft } from "./draft-revisions.js"
// Local preview transport only. No production backend selection or fallback.
const LIMIT = 128 * 1024
const headers = { "Cache-Control": "private, no-store" }

function fail(code, status = 503) {
  throw Object.assign(new Error(code), { code, status })
}

async function boundedBody(body, maxBytes, signal) {
  if (!body) fail("invalid_command_body", 400)
  const reader = body.getReader()
  const chunks = []
  let size = 0
  const cancel = () => { void reader.cancel() }
  signal.addEventListener("abort", cancel, { once: true })
  try {
    while (true) {
      if (signal.aborted) fail("local_authority_timeout")
      const { done, value } = await reader.read()
      if (signal.aborted) fail("local_authority_timeout")
      if (done) break
      size += value.byteLength
      if (size > maxBytes) fail("command_too_large", 413)
      chunks.push(value)
    }
    const bytes = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
    return bytes
  } finally {
    signal.removeEventListener("abort", cancel)
    void reader.cancel()
  }
}

export async function localCommandRequest(request, path, { method = "GET", raw } = {}) {
  const config = configuration(request)
  if (!/^\/(?:state|generation|reports|commands(?:\/[a-f0-9-]{36}(?:\/abandon)?)?|drafts\/[A-Za-z0-9_.:-]{1,200}\/media(?:\/[a-f0-9]{64}\/preview\.png)?)$/.test(path)) fail("invalid_command_route", 400)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8000)
  try {
    const response = await fetch(`${config.destination.origin}${path}`, {
      method, headers: { Authorization: config.authorization, Origin: config.origin,
        ...(raw ? { "Content-Type": "application/json" } : {}) }, body: raw,
      signal: controller.signal, redirect: "error", cache: "no-store",
    })
    const bytes = await boundedBody(response.body, 8 * 1024 * 1024, controller.signal)
    if (response.ok && path.endsWith("/preview.png")) {
      if (response.headers.get("content-type") !== "image/png" || bytes.length < 33 ||
          ![137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => bytes[i] === v)) fail("invalid_media_response")
      return { status: response.status, bytes }
    }
    const payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes))
    if (!response.ok) throw Object.assign(new Error(payload.error || "Local authority unavailable"), {
      status: response.status, code: payload.code || "local_authority_unavailable",
    })
    return { status: response.status, payload }
  } catch (error) {
    if (error.status) throw error
    fail("local_authority_unavailable_retry_same_command")
  } finally { clearTimeout(timer) }
}

export const previewError = localPreviewError

export async function acceptLocalCommand(request, expectedAction = null, recoveryId = null) {
  try {
    const config = configuration(request)
    if (request.headers.get("origin") !== config.origin) fail("local_preview_origin_refused", 403)
    if (request.headers.get("content-type") !== "application/json") fail("json_required", 415)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 5000)
    let raw
    try { raw = await boundedBody(request.body, LIMIT, controller.signal) }
    finally { clearTimeout(timer) }
    if (expectedAction) {
      let parsed
      try { parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)) }
      catch { fail("invalid_command_body", 400) }
      if (parsed?.action !== expectedAction) fail("sourced_generation_command_required", 400)
    }
    // Preserve raw bytes: Python rejects duplicate JSON keys before parsing any
    // identity/action. Next must never silently normalize a hostile request.
    const path = recoveryId === null ? "/commands" : `/commands/${recoveryId}/abandon`
    const { status, payload } = await localCommandRequest(request, path, { method: "POST", raw })
    return Response.json(payload, { status, headers })
  } catch (error) { return previewError(error) }
}

export function localDraftProjection(draft, state, local) {
  const policy = local.editorial_policy
  return { ...projectDraft(draft, policy), local_preview: true, operator_role: local.role,
    editorial_policy: { status: "recorded", policy, policy_sha256: fingerprint(policy), reason: "Current local command authority policy" },
    automatic_publication: { enabled: false, reason: "Local preview has no publication transport" },
    publish_blocked: hasUnresolvedPublish(draft, state), tweet_id: draft.tweet_id ?? null,
    candidates: draft.candidates?.map((candidate) => ({ ...candidate, command_sha256: fingerprint(candidate) })),
    parked_intent: draft.status === "approved" ? draft.publish_intent_id : null }
}
