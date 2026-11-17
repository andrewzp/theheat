import { requireDashboardAuth } from "../../../lib/auth.js"
import { collectGistBackupManifest, GistBackupError } from "../../../lib/gist-backup.js"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const maxDuration = 60
const headers = { "Cache-Control": "private, no-store", "Content-Disposition": 'attachment; filename="theheat-backup-descriptors.json"' }

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError
  if (request.method !== "GET") return methodRefused(request)
  if (new URL(request.url).search) return Response.json({ error: "Backup arguments are not supported", code: "backup_arguments_refused" }, { status: 400, headers })
  try { return Response.json(await collectGistBackupManifest(), { headers }) }
  catch (error) {
    return Response.json({ error: "Complete backup descriptors are unavailable",
      code: error instanceof GistBackupError ? error.code : "backup_metadata_unavailable" }, { status: 503, headers })
  }
}

function methodRefused(request) {
  return requireDashboardAuth(request) || Response.json({ code: "backup_read_only" },
    { status: 405, headers: { ...headers, Allow: "GET" } })
}
export const HEAD = methodRefused
export const POST = methodRefused
export const PUT = methodRefused
export const PATCH = methodRefused
export const DELETE = methodRefused
export const OPTIONS = methodRefused
