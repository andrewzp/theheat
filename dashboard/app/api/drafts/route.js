const GIST_ID = process.env.GIST_ID
const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

function gistHeaders() {
  const h = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) h.Authorization = `token ${GITHUB_TOKEN}`
  return h
}

async function readState() {
  const res = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
    headers: gistHeaders(),
    cache: "no-store",
  })
  const gist = await res.json()
  return JSON.parse(gist.files["state.json"].content)
}

async function writeState(state) {
  await fetch(`https://api.github.com/gists/${GIST_ID}`, {
    method: "PATCH",
    headers: { ...gistHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      files: { "state.json": { content: JSON.stringify(state, null, 2) } },
    }),
  })
}

// GET — return pending drafts
export async function GET() {
  try {
    const state = await readState()
    const drafts = (state.drafts || []).filter((d) => d.status === "pending")
    return Response.json({ drafts })
  } catch (e) {
    return Response.json({ drafts: [], error: e.message })
  }
}

// POST — approve, reject, or edit a draft
export async function POST(request) {
  const { action, draftId, editedText } = await request.json()

  if (!["approve", "reject", "edit"].includes(action)) {
    return Response.json({ error: "Invalid action" }, { status: 400 })
  }

  try {
    const state = await readState()
    const drafts = state.drafts || []
    const draft = drafts.find((d) => d.id === draftId)

    if (!draft) {
      return Response.json({ error: "Draft not found" }, { status: 404 })
    }

    if (action === "reject") {
      draft.status = "rejected"
      await writeState(state)
      return Response.json({ ok: true, action: "rejected" })
    }

    if (action === "edit") {
      if (!editedText || editedText.length > 280) {
        return Response.json({ error: "Invalid text" }, { status: 400 })
      }
      draft.text = editedText
      await writeState(state)
      return Response.json({ ok: true, action: "edited" })
    }

    if (action === "approve") {
      // Trigger GitHub Actions to post the tweet
      const res = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/bot.yml/dispatches`,
        {
          method: "POST",
          headers: { ...gistHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            ref: "main",
            inputs: { mode: "manual_tweet", tweet_text: draft.text },
          }),
        }
      )

      if (res.ok || res.status === 204) {
        draft.status = "approved"
        draft.approved_at = new Date().toISOString()
        await writeState(state)
        return Response.json({ ok: true, action: "approved" })
      }

      return Response.json({ error: "Failed to trigger workflow" }, { status: 500 })
    }
  } catch (e) {
    return Response.json({ error: e.message }, { status: 500 })
  }
}
