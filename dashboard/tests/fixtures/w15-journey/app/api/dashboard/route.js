import { GET as readDashboard } from "../../../../../../app/api/dashboard/route.js"
import { actualHandler } from "../../../fixture-store.js"
export const dynamic = "force-dynamic"
export async function GET(request) { return actualHandler(readDashboard, request) }
