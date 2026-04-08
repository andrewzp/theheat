const GIST_ID = process.env.GIST_ID
const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

export async function GET() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) headers.Authorization = `token ${GITHUB_TOKEN}`

  const results = {}

  // Fetch bot state from Gist
  if (GIST_ID) {
    try {
      const res = await fetch(`https://api.github.com/gists/${GIST_ID}`, {
        headers,
        next: { revalidate: 60 },
      })
      const gist = await res.json()
      results.state = JSON.parse(gist.files["state.json"].content)
    } catch {
      results.state = null
      results.stateError = "Failed to fetch state Gist"
    }
  }

  // Fetch recent workflow runs
  try {
    const res = await fetch(
      `https://api.github.com/repos/${REPO}/actions/runs?per_page=10`,
      { headers, next: { revalidate: 60 } }
    )
    const data = await res.json()
    results.runs = (data.workflow_runs || []).map((r) => ({
      id: r.id,
      status: r.status,
      conclusion: r.conclusion,
      created_at: r.created_at,
      updated_at: r.updated_at,
      event: r.event,
      html_url: r.html_url,
    }))
  } catch {
    results.runs = []
  }

  return Response.json(results)
}
