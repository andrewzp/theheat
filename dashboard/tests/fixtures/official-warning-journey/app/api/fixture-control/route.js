import { fixtureStore, reset, expire } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export function GET() {
  const store = fixtureStore()
  return Response.json({ state: JSON.parse(store.raw), writes: store.writes, dispatches: store.dispatches, refused: store.refused })
}
export async function POST(request) {
  const { action } = await request.json()
  if (action === "reset") reset()
  else if (action === "expire") expire()
  else return Response.json({ error: "Unknown invented control" }, { status: 400 })
  return Response.json({ changed: true })
}
