import { GET as readEpisodes } from "../../../../../../app/api/episodes/route.js"
import { actualHandler } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET(request) { return actualHandler(readEpisodes, request) }
