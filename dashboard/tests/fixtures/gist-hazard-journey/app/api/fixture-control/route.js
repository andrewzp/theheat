import { fixtureStore, setClock } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET() {
  const store = fixtureStore()
  return Response.json({ writes: store.writes, previews: store.previews, refused: store.refused, dispatches: store.dispatches,
    clock: store.now, state: JSON.parse(store.raw) })
}
export async function POST(request) {
  const { action, family, when } = await request.json(), store = fixtureStore()
  if (action === "reset") Object.assign(store, { raw: store.seed, stamp: store.seedStamp, previewRefused: false, writes: 0,
    previews: 0, refused: [], dispatches: [] })
  else if (action === "refuse_preview") store.previewRefused = true
  else if (action === "clock" && store.clocks[family] && ["current", "expired"].includes(when)) setClock(store.clocks[family][when === "current" ? 0 : 1])
  else return Response.json({ error: "Unknown invented control" }, { status: 400 })
  return Response.json({ changed: true, clock: store.now })
}
