// Fixture-only join: the actual postOutcomes consumer with the feedback the actual route saved
// and an invented review-only correction report (the production dashboard does not load either).
import { postOutcomes } from "../../../../../../lib/post-outcomes.js"
import { CORRECTION_REPORT, fixtureStore } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export function GET() {
  const store = fixtureStore()
  // One saved record per archive file, exactly as the actual route wrote it.
  const feedbackRecords = Object.values(store.archive).flatMap(file => { try { const value = JSON.parse(file.content); return value && typeof value === "object" ? [value] : [] } catch { return [] } })
  return Response.json(postOutcomes(store.state, { now: Date.parse("2026-10-20T00:00:00Z"), feedbackRecords, correctionReport: CORRECTION_REPORT }))
}
