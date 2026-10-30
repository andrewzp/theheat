// Invented in-memory transports only. The actual post-feedback and dashboard handlers run
// unchanged; the state Gist, the private feedback Gist and the workflow-run list are faked
// here, and every other external transport is refused and recorded.
import { draftIdentity, textHash } from "../../../lib/draft-revisions.js"
const key = Symbol.for("theheat.invented.w15.journey")
const posted = { id: "synthetic-post", event_id: "synthetic-event", type: "heat_record", status: "posted", publish_outcome: "confirmed",
  tweet_id: "1900000000000000001", text: "Invented: Fictionville reached 49.1C, its highest reading in the invented archive.",
  content_revision: 1, posted_at: "2026-10-10T19:00:00.000Z", created_at: "2026-10-10T18:00:00.000Z", city: "Fictionville",
  review_context: { source: "invented fixture only" } }
const pending = { id: "synthetic-draft", event_id: "synthetic-pending", type: "heat_record", status: "pending",
  text: "Invented pending copy about Fictionville's long warm spell, written for this journey only.", content_revision: 2,
  created_at: "2026-10-11T08:00:00.000Z", review_context: { source: "invented fixture only" } }
function initialState() {
  const receipt = { ...draftIdentity(posted), text: posted.text, text_sha256: textHash(posted.text), tweet_id: posted.tweet_id,
    phase: "confirmed", intent_id: "10a97d68-2e51-4998-92ed-f830863f7218", confirmed_at: "2026-10-10T19:00:00.000Z" }
  return { drafts: [structuredClone(posted), structuredClone(pending)], publish_ledger: { [posted.event_id]: receipt }, run_history: [] }
}
export const CORRECTION_REPORT = { candidates: [{ tweet_id: posted.tweet_id, claim: "49.1C", kind: "value", uncertainty: "Invented: provisional QC.",
  source_evidence: { retrieved_at: "2026-10-18T00:00:00Z", statement: "Invented table shows 48.7C." }, automatic_correction: false, deletion: false }], incomplete: [] }
export function fixtureStore(reset = false) {
  if (reset || !globalThis[key]) globalThis[key] = { state: initialState(), archive: {}, writes: 0, refused: [] }
  return globalThis[key]
}
export async function inventedFetch(url, options = {}) {
  const store = fixtureStore(), href = String(url)
  if (href === "https://api.github.com/gists/invented_w15_state") {
    if (options.method && options.method !== "GET") { store.refused.push(`${options.method} ${href}`); throw new Error("State writes are refused here") }
    return Response.json({ public: true, files: { "state.json": { content: JSON.stringify(store.state) } } })
  }
  if (href === "https://api.github.com/gists/invented_w15_feedback") {
    if (options.method === "PATCH") { Object.assign(store.archive, JSON.parse(options.body).files); store.writes++; return Response.json({}) }
    return Response.json({ public: false, files: store.archive })
  }
  if (href.startsWith("https://api.github.com/repos/andrewzp/theheat/actions/")) return Response.json({ workflow_runs: [], total_count: 0 })
  store.refused.push(href); throw new Error("External transport refused in invented journey")
}
export async function actualHandler(handler, request) {
  const previous = globalThis.fetch
  globalThis.fetch = inventedFetch
  try { return await handler(request) } finally { globalThis.fetch = previous }
}
