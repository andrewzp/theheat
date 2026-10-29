import { fixtureStore } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET() {
  const store = fixtureStore()
  return Response.json({ writes: store.writes, previews: store.previews, refused: store.refused, state: JSON.parse(store.raw), lastRequest: store.lastRequest })
}
export async function POST(request) {
  const { action } = await request.json(), store = fixtureStore()
  if (action === "reset") { store.raw = store.seed; store.previewRefused = false; store.writes = 0; store.previews = 0; store.refused = [] }
  else if (action === "refuse_preview") store.previewRefused = true
  else return Response.json({ error: "Unknown invented control" }, { status: 400 })
  return Response.json({ changed: true })
}
