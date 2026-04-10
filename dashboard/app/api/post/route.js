import { requireDashboardAuth } from "../../../lib/auth.js"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

export async function POST(request) {
  const authError = requireDashboardAuth(request)
  if (authError) {
    return authError
  }
  if (!GITHUB_TOKEN) {
    return Response.json({ error: "No GitHub token configured" }, { status: 500 })
  }

  const { tweet } = await request.json()
  if (!tweet || tweet.length < 5 || tweet.length > 280) {
    return Response.json({ error: "Tweet must be 5-280 characters" }, { status: 400 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `token ${GITHUB_TOKEN}`,
        Accept: "application/vnd.github.v3+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { mode: "manual_tweet", tweet_text: tweet },
      }),
    }
  )

  if (res.ok || res.status === 204) {
    return Response.json({ ok: true })
  }

  const text = await res.text()
  return Response.json({ error: text }, { status: res.status })
}
