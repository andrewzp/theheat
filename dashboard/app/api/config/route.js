import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

// Defaults must mirror src/config.py. The dashboard reads the same env
// vars the Python pipeline reads, so an override on either side is
// reflected here. If the python defaults change, update both this file
// and src/config.py in the same commit.
const CHEAP_MODEL_DEFAULT = "gemini-2.5-flash"
const WRITER_MODEL_DEFAULT = "claude-sonnet-4-6"

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }

  const cheap = process.env.THEHEAT_CHEAP_MODEL || CHEAP_MODEL_DEFAULT
  const writer = process.env.THEHEAT_WRITER_MODEL || WRITER_MODEL_DEFAULT

  return Response.json({
    writer_model: writer,
    fact_check_model: process.env.THEHEAT_FACT_CHECK_MODEL || cheap,
    claim_extract_model: process.env.THEHEAT_CLAIM_EXTRACT_MODEL || cheap,
    voice_gen_model: process.env.GEMINI_MODEL || cheap,
    evaluator_enabled: (process.env.EVALUATOR_ENABLED || "true").toLowerCase() !== "false",
    shadow_ab_enabled: process.env.THEHEAT_SHADOW_AB_ENABLED === "1",
  })
}
