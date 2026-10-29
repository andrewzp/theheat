import { previewResponse } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function POST(request) { return previewResponse(await request.json()) }
