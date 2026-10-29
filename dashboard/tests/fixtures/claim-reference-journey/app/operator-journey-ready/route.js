export const dynamic = "force-dynamic"
export function GET() { return Response.json({ token: process.env.THEHEAT_OPERATOR_JOURNEY_TOKEN }) }
