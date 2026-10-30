import { fixtureStore } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export function GET() { const store = fixtureStore(); return Response.json({ writes: store.writes, refused: store.refused, archive: store.archive }) }
export async function POST(request) {
  const { action } = await request.json()
  if (action !== "reset") return Response.json({ error: "Unknown invented control" }, { status: 400 })
  fixtureStore(true); return Response.json({ reset: true })
}
