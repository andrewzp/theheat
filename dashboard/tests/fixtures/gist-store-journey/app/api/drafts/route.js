import { GET as readDrafts, POST as editDraft } from "../../../../../../app/api/drafts/route.js"
import { actualHandler } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET(request) { return actualHandler(readDrafts, request) }
export async function POST(request) { return actualHandler(editDraft, request) }
