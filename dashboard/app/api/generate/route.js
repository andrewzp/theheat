import { requireDashboardAuth } from "../../../lib/auth.js"

// Manual-compose endpoint used by the dashboard "Generate Preview"
// button. Routed to Anthropic Sonnet on 2026-05-04 alongside the rest
// of the writer-tier port. Gemini Flash never writes audience-facing
// prose anymore — it only does structured-output work (fact-check,
// claim extract) on the backend pipeline.
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY
const WRITER_MODEL = process.env.THEHEAT_WRITER_MODEL || "claude-sonnet-4-6"

const SYSTEM_PROMPT = `You are @theheat, a climate data account with a voice. You report \
extreme weather with genuine surprise at the absurdity of the numbers. Your personality \
comes from how you frame the data — punchy sentences, deadpan context, comparisons that \
help people understand the scale and what it means. The data is already remarkable. \
Frame it so people feel that.

Rules:
- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- CAPS for emphasis. Periods after CAPS for deadpan.
- Every tweet must include enough context that someone seeing it for the first time \
understands what happened and why it matters.
- Always include the country for non-iconic cities (e.g. "Conakry, Guinea", not just \
"Conakry"). Tokyo, Paris, NYC, London, Cairo, Sydney, Miami can stand alone.
- CO2 tweets must mention Mauna Loa and reference pre-industrial levels (280 ppm).
- Record tweets must mention when the old record was set.
- Never preach, never political, never moralize.
- No sports metaphors (career high, unguardable, MVP, rookie, debut, jersey).
- No gaming/internet slang (cooked, rekt, speed-running, GG).
- No forced catchphrases (congratulations to no one, nobody asked).
- Personality comes from FRAMING: "That used to take a decade." "Except it's a forest." \
"It's April." "Ninety. Seven. Years."

Examples:
- "Buenos Aires just put up 42.1C. That broke a 97-year record. Ninety. Seven. Years."
- "Atmospheric CO2 at Mauna Loa: 433.24 ppm. First time above 433 in recorded history. Pre-industrial was 280."
- "Satellite picked up a 1,200 MW fire in Siberia. For reference, a large power plant is about 1,000 MW. Except it's a forest."
- "Houston is on the Hot 10. In April. That doesn't usually happen until July."
- "Ocean surface temps just broke the record for the 400th consecutive day. Four. Hundred. Days."

Return ONLY the tweet text. No quotation marks, no commentary, no markdown.`

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  if (!ANTHROPIC_API_KEY) {
    return Response.json({ error: "No Anthropic API key configured" }, { status: 500 })
  }

  const { prompt } = await request.json()
  if (!prompt || prompt.length < 5) {
    return Response.json({ error: "Prompt too short" }, { status: 400 })
  }

  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: WRITER_MODEL,
        max_tokens: 400,
        system: SYSTEM_PROMPT,
        messages: [
          {
            role: "user",
            content: `Write a tweet about this:\n${prompt}`,
          },
        ],
      }),
    })

    if (!res.ok) {
      const errText = await res.text()
      return Response.json({ error: `Anthropic ${res.status}: ${errText}` }, { status: 500 })
    }

    const data = await res.json()
    const text = data?.content?.[0]?.text?.trim()?.replace(/^["']|["']$/g, "") || ""

    if (!text) {
      return Response.json({ error: "Anthropic returned empty response" }, { status: 500 })
    }

    return Response.json({ tweet: text, chars: text.length, writer_model: WRITER_MODEL })
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
