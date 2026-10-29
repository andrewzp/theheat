// Invented in-memory transport only. Actual draft route/state-store/revision
// handlers run unchanged; every attempted external transport is trapped here.
import fixture from "../../../../tests/fixtures/operator_claim_references.json" with { type: "json" }
import { initializeRevision } from "../../../lib/draft-revisions.js"
const key = Symbol.for("theheat.invented.claim.reference.journey")
export function fixtureStore() {
  if (!globalThis[key]) {
    const draft = id => initializeRevision({ id, event_id: id, type: fixture.bundle.signal_kind, status: "pending", text: fixture.text,
      created_at: "2032-01-02T00:00:00Z", review_context: { source: "Invented fixture", two_bot: { bundle: { ...structuredClone(fixture.bundle), event_id: id } } } })
    globalThis[key] = { state: { drafts: [draft("invented-reference"), draft("invented-other")], publish_ledger: {}, run_history: [] }, writes: 0, refused: [] }
  }
  return globalThis[key]
}
export async function inventedFetch(url, options = {}) {
  const store = fixtureStore()
  if (String(url) !== "https://api.github.com/gists/invented-claim-journey") {
    store.refused.push(String(url)); throw new Error("External transport refused in invented journey")
  }
  if (options.method === "PATCH") {
    store.state = JSON.parse(JSON.parse(options.body).files["state.json"].content); store.writes++
    return Response.json({})
  }
  return Response.json({ files: { "state.json": { content: JSON.stringify(store.state) } } })
}
export async function actualHandler(handler, request) {
  const previous = globalThis.fetch
  globalThis.fetch = inventedFetch
  try { return await handler(request) } finally { globalThis.fetch = previous }
}
