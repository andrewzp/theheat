import { NextResponse } from "next/server.js"

import { verifyDashboardAuth } from "./lib/auth.js"

export function middleware(request) {
  const result = verifyDashboardAuth(request)
  if (!result.ok) {
    return result.response
  }
  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)"],
}
