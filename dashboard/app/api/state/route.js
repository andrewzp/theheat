const GIST_ID = process.env.GIST_ID
const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = "andrewzp/theheat"

async function githubJson(url, headers) {
  const res = await fetch(url, { headers, cache: "no-store" })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }
  return res.json()
}

export async function GET() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  if (GITHUB_TOKEN) headers.Authorization = `token ${GITHUB_TOKEN}`

  const results = {}

  // Fetch bot state from Gist
  if (GIST_ID) {
    try {
      const gist = await githubJson(`https://api.github.com/gists/${GIST_ID}`, headers)
      results.state = JSON.parse(gist.files["state.json"].content)
    } catch (error) {
      results.state = null
      results.stateError = `Failed to fetch state Gist: ${error.message}`
    }
  }

  // Fetch recent workflow runs
  try {
    const data = await githubJson(
      `https://api.github.com/repos/${REPO}/actions/runs?per_page=10`,
      headers
    )
    results.runs = (data.workflow_runs || []).map((r) => ({
      id: r.id,
      status: r.status,
      conclusion: r.conclusion,
      created_at: r.created_at,
      updated_at: r.updated_at,
      event: r.event,
      html_url: r.html_url,
    }))
  } catch (error) {
    results.runs = []
    results.runsError = `Failed to fetch workflow runs: ${error.message}`
  }

  return Response.json(results)
}
