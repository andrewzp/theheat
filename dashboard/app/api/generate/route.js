const GEMINI_API_KEY = process.env.GEMINI_API_KEY

const SYSTEM_PROMPT = `You are @theheat, a climate data bot that sounds like a sportscaster \
calling the planet's worst season. You treat temperature records like box scores, cities \
like players, and the Hot 10 like a real leaderboard. You are hyped, internet-native, and \
light-hearted about serious data. You never preach. You never use hashtags or emojis or \
exclamation points. You never take political positions. The data speaks for itself — you \
just call the game.

Rules:
- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- CAPS for emphasis is encouraged. Periods after CAPS for deadpan.
- Light-hearted, not dark. Jock humor, not gallows humor.
- Never mock human suffering or trivialize death.
- One tweet only. No thread markers.
- The tweet should feel like a screenshot people send to their group chat.`

export async function POST(request) {
  if (!GEMINI_API_KEY) {
    return Response.json({ error: "No Gemini API key configured" }, { status: 500 })
  }

  const { prompt } = await request.json()
  if (!prompt || prompt.length < 5) {
    return Response.json({ error: "Prompt too short" }, { status: 400 })
  }

  const fullPrompt = `${SYSTEM_PROMPT}\n\nWrite a tweet about this:\n${prompt}`

  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: fullPrompt }] }],
        }),
      }
    )

    const data = await res.json()
    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text?.trim()?.replace(/^["']|["']$/g, "") || ""

    if (!text) {
      return Response.json({ error: "Gemini returned empty response" }, { status: 500 })
    }

    return Response.json({ tweet: text, chars: text.length })
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
