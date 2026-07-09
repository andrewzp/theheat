function getDashboardUsername() {
  return process.env.DASHBOARD_USERNAME || ""
}

function getDashboardPassword() {
  return process.env.DASHBOARD_PASSWORD || ""
}

function decodeBasicPayload(value) {
  if (typeof atob === "function") {
    return atob(value)
  }
  return Buffer.from(value, "base64").toString("utf-8")
}

function unauthorizedResponse() {
  return new Response("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="theheat dashboard"',
    },
  })
}

function unconfiguredResponse() {
  return new Response("Dashboard authentication is not configured", {
    status: 503,
  })
}

export function verifyDashboardAuth(request) {
  // App-level HTTP Basic auth is an OPTIONAL second layer. Set DASHBOARD_AUTH_DISABLED=1
  // to turn it off intentionally and rely on Vercel Deployment Protection (Vercel
  // Authentication) as the sole gate. Without this explicit opt-out, unconfigured auth
  // still fails CLOSED in production (503 below) so a forgotten config never exposes the
  // dashboard — which can trigger runs and post tweets.
  if (process.env.DASHBOARD_AUTH_DISABLED === "1") {
    return { ok: true, response: null }
  }

  const dashboardUsername = getDashboardUsername()
  const dashboardPassword = getDashboardPassword()

  if (!dashboardUsername && !dashboardPassword) {
    if (process.env.NODE_ENV === "production") {
      return { ok: false, response: unconfiguredResponse() }
    }
    return { ok: true, response: null }
  }

  if (!dashboardUsername || !dashboardPassword) {
    return { ok: false, response: unconfiguredResponse() }
  }

  const header = request.headers.get("authorization") || ""
  if (!header.startsWith("Basic ")) {
    return { ok: false, response: unauthorizedResponse() }
  }

  try {
    const decoded = decodeBasicPayload(header.slice(6))
    const separator = decoded.indexOf(":")
    const username = separator === -1 ? decoded : decoded.slice(0, separator)
    const password = separator === -1 ? "" : decoded.slice(separator + 1)
    if (username === dashboardUsername && password === dashboardPassword) {
      return { ok: true, response: null }
    }
  } catch {
    return { ok: false, response: unauthorizedResponse() }
  }

  return { ok: false, response: unauthorizedResponse() }
}

export function requireDashboardAuth(request) {
  const result = verifyDashboardAuth(request)
  return result.ok ? null : result.response
}
