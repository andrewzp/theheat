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
    headers: { "Cache-Control": "no-store" },
  })
}

function verifyProtectedDeployment(request) {
  // VERCEL_URL is the generated deployment hostname, whose outer Vercel
  // authentication gate is verified during release. Production aliases can be
  // public on Hobby plans, so they must never serve dashboard data directly.
  const hostname = (process.env.VERCEL_URL || "").toLowerCase()
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app$/.test(hostname)) {
    return { ok: false, response: unconfiguredResponse() }
  }

  const requestedUrl = new URL(request.url)
  const rawHost = (request.headers.get("host") || "").toLowerCase()
  // Forwarded headers can influence a framework's request URL. Requiring the
  // raw Host as well prevents either representation alone granting access.
  if (requestedUrl.hostname === hostname && rawHost === hostname) {
    return { ok: true, response: null }
  }

  const destination = new URL(`https://${hostname}`)
  if (requestedUrl.hostname !== hostname && (request.method === "GET" || request.method === "HEAD")) {
    // Assign path/query separately so a path beginning // cannot change origin.
    destination.pathname = requestedUrl.pathname
    destination.search = requestedUrl.search
    return {
      ok: false,
      response: new Response(null, {
        status: 307,
        headers: { Location: destination.href, "Cache-Control": "no-store" },
      }),
    }
  }

  return {
    ok: false,
    response: Response.json({
      error: "Sign in at the protected dashboard address before making changes.",
      code: "sign_in_required",
      signInUrl: destination.href,
    }, { status: 403, headers: { "Cache-Control": "no-store" } }),
  }
}

export function verifyDashboardAuth(request) {
  // Disabling Basic auth in production relies on the verified outer Vercel gate
  // at the generated deployment URL. Missing platform configuration fails closed.
  if (process.env.DASHBOARD_AUTH_DISABLED === "1") {
    return process.env.NODE_ENV === "production"
      ? verifyProtectedDeployment(request)
      : { ok: true, response: null }
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
