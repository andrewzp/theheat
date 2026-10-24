// Ownership marker for scripts/operator_media_journey.mjs: returns the per-run
// token that only the launcher's own spawned server received in its env.
export const dynamic = "force-dynamic"

export function GET() {
  return Response.json({ token: process.env.THEHEAT_OPERATOR_JOURNEY_TOKEN || null },
    { headers: { "Cache-Control": "no-store" } })
}
