// Fixture-only boundary: the assessment was produced by the real scripts/theheat_evaluation.py
// match-coverage on invented input (by the launcher); the local preview server is not started here.
import { readFileSync } from "node:fs"
export const dynamic = "force-dynamic"
export function GET() {
  const assessment = JSON.parse(readFileSync(process.env.THEHEAT_W15_ASSESSMENT, "utf8"))
  return Response.json({ assessment, currentness: "current", ready: false, reports: [] }, { headers: { "Cache-Control": "private, no-store" } })
}
