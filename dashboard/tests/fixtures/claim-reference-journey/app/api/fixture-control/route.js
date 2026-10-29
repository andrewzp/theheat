import { fixtureStore } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET() {
  const store = fixtureStore()
  return Response.json({ writes: store.writes, refused: store.refused, state: store.state })
}
export async function POST(request) {
  const { action } = await request.json(), store = fixtureStore()
  if (action !== "change_source") return Response.json({ error: "Unknown invented control" }, { status: 400 })
  store.state.drafts.find(d => d.id === "invented-reference").review_context.two_bot.bundle.current_facts[0].value++
  return Response.json({ changed: true })
}
