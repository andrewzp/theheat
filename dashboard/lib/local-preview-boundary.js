// Browser/Edge-safe configuration guard, shared by middleware and API handlers.
// A configured local preview never enters a legacy producer or remote read.
export function previewConfigured() {
  return Object.hasOwn(process.env, "THEHEAT_LOCAL_COMMAND_URL")
}

function refuse(code, status = 503) {
  throw Object.assign(new Error(code), { code, status })
}

export function localPreviewConfiguration(request) {
  const value = process.env.THEHEAT_LOCAL_COMMAND_URL
  if (process.env.NODE_ENV === "production" || process.env.THEHEAT_ENVIRONMENT === "production"
      || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(value || "")) refuse("local_preview_configuration_refused")
  const destination = new URL(value)
  if (Number(destination.port) > 65535) refuse("local_preview_configuration_refused")
  for (const [key, value] of Object.entries(process.env)) {
    if (key.startsWith("PG") || (value && (/(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$/.test(key)
        || /^(?:AWS_|TWITTER_|BLUESKY_|X_API_)/.test(key)) && key !== "DASHBOARD_PASSWORD")) refuse("local_preview_credentials_refused")
  }
  if (!request) refuse("local_preview_authenticated_request_required")
  const incoming = new URL(request.url)
  const host = request.headers.get("host") || ""
  // Next middleware canonicalizes a loopback URL to localhost. Bind the
  // browser origin to the raw numeric Host, requiring the same explicit port
  // and a loopback URL as a second check. Forwarded headers are never authority.
  if (!/^127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(host) || incoming.protocol !== "http:"
      || !["127.0.0.1", "localhost"].includes(incoming.hostname) || !incoming.port
      || incoming.port !== host.split(":")[1]) refuse("local_preview_origin_refused", 403)
  const browserOrigin = `http://${host}`
  const origin = request.headers.get("origin")
  if (origin && origin !== browserOrigin) refuse("local_preview_origin_refused", 403)
  const authorization = request.headers.get("authorization") || ""
  if (!authorization.startsWith("Basic ") || authorization.length > 2048) refuse("local_preview_sign_in_required", 401)
  return { destination, authorization, origin: browserOrigin }
}

export function localPreviewError(error) {
  return Response.json({ ok: false, local_preview: true, error: error.message, code: error.code }, {
    status: error.status || 503, headers: { "Cache-Control": "private, no-store",
      ...(error.status === 401 ? { "WWW-Authenticate": 'Basic realm="theheat local preview"' } : {}) },
  })
}

export function localPreviewGuard(request) {
  if (!previewConfigured()) return null
  try {
    localPreviewConfiguration(request)
    const path = new URL(request.url).pathname
    if (path.startsWith("/api/")) {
      const methods = { "/api/drafts": ["GET", "POST"], "/api/dashboard": ["GET"], "/api/generate": ["GET", "POST"], "/api/reports": ["GET", "POST"], "/api/editor-media": ["GET"], "/api/local-command-recovery": ["POST"] }[path]
      if (!methods) refuse("local_preview_route_unavailable")
      if (!methods.includes(request.method)) refuse("local_preview_method_refused", 405)
    }
    return null
  } catch (error) { return localPreviewError(error) }
}
