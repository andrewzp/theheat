const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

export async function POST(request) {
  if (!GITHUB_TOKEN) {
    return Response.json({ error: "No GitHub token configured" }, { status: 500 })
  }

  const { mode } = await request.json()
  if (!["alerts", "leaderboard", "both"].includes(mode)) {
    return Response.json({ error: "Invalid mode" }, { status: 400 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `token ${GITHUB_TOKEN}`,
        Accept: "application/vnd.github.v3+json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { mode },
      }),
    }
  )

  if (res.ok || res.status === 204) {
    return Response.json({ ok: true, mode })
  }

  const text = await res.text()
  return Response.json({ error: text }, { status: res.status })
}
