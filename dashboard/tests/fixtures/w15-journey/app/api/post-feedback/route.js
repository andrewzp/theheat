import { GET as readFeedback, POST as saveFeedback } from "../../../../../../app/api/post-feedback/route.js"
import { actualHandler } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET(request) { return actualHandler(readFeedback, request) }
export async function POST(request) { return actualHandler(saveFeedback, request) }
