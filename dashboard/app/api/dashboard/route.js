import { getStateBackend, readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { buildSourceHealthPayload } from "../../../lib/source-health.js"

export const runtime = "nodejs"

const REPO = "andrewzp/theheat"
const DEFAULT_SUPPRESSION_LIMIT = 50
const MAX_SUPPRESSION_LIMIT = 200
const CHEAP_MODEL_DEFAULT = "gemini-2.5-flash"
const WRITER_MODEL_DEFAULT = "claude-sonnet-4-6"

function parseLimit(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_SUPPRESSION_LIMIT
  return Math.min(Math.floor(parsed), MAX_SUPPRESSION_LIMIT)
}

function tsValue(s) {
  if (!s?.ts) return 0
  const parsed = Date.parse(s.ts)
  return Number.isFinite(parsed) ? parsed : 0
}

function pendingDrafts(state) {
  return (state?.drafts || [])
    .filter((d) => d.status === "pending")
    .sort((a, b) => {
      const priorityA = (a.score?.total || 0) + (a.candidate_score?.total || 0) * 0.35
      const priorityB = (b.score?.total || 0) + (b.candidate_score?.total || 0) * 0.35
      const scoreDiff = priorityB - priorityA
      if (scoreDiff !== 0) return scoreDiff
      return new Date(b.created_at || 0) - new Date(a.created_at || 0)
    })
}

function suppressionsPayload(state, { sourceFilter, sinceFilter, limit }) {
  const all = Array.isArray(state?.suppressions) ? state.suppressions : []
  const sinceMs = sinceFilter ? Date.parse(sinceFilter) : NaN
  const filtered = all.filter((s) => {
    if (sourceFilter && s.source !== sourceFilter) return false
    if (Number.isFinite(sinceMs) && tsValue(s) < sinceMs) return false
    return true
  })

  filtered.sort((a, b) => tsValue(b) - tsValue(a))
  const suppressions = filtered.slice(0, limit)
  const now = Date.now()
  const day = 24 * 60 * 60 * 1000
  const sourceCounts = {}
  const stageCounts = {}
  for (const s of filtered) {
    const sourceKey = s.source || "unknown"
    sourceCounts[sourceKey] = (sourceCounts[sourceKey] || 0) + 1
    const stageKey = s.stage || "unknown"
    stageCounts[stageKey] = (stageCounts[stageKey] || 0) + 1
  }

  return {
    suppressions,
    stats: {
      total: filtered.length,
      last24h: filtered.filter((s) => now - tsValue(s) < day).length,
      last7d: filtered.filter((s) => now - tsValue(s) < 7 * day).length,
      top_source: Object.entries(sourceCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || null,
      source_counts: sourceCounts,
      top_stage: Object.entries(stageCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || null,
      stage_counts: stageCounts,
    },
  }
}

function modelConfig() {
  const cheap = process.env.THEHEAT_CHEAP_MODEL || CHEAP_MODEL_DEFAULT
  const writer = process.env.THEHEAT_WRITER_MODEL || WRITER_MODEL_DEFAULT
  return {
    writer_model: writer,
    fact_check_model: process.env.THEHEAT_FACT_CHECK_MODEL || cheap,
    claim_extract_model: process.env.THEHEAT_CLAIM_EXTRACT_MODEL || cheap,
    voice_gen_model: process.env.GEMINI_MODEL || cheap,
    evaluator_enabled: (process.env.EVALUATOR_ENABLED || "true").toLowerCase() !== "false",
    shadow_ab_enabled: process.env.THEHEAT_SHADOW_AB_ENABLED === "1",
  }
}

async function githubJson(url, headers) {
  const res = await fetch(url, { headers, cache: "no-store" })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }
  return res.json()
}

async function workflowRuns() {
  const headers = { Accept: "application/vnd.github.v3+json" }
  if (process.env.GITHUB_TOKEN) headers.Authorization = `token ${process.env.GITHUB_TOKEN}`
  const data = await githubJson(
    `https://api.github.com/repos/${REPO}/actions/runs?per_page=10`,
    headers
  )
  return (data.workflow_runs || []).map((r) => ({
    id: r.id,
    status: r.status,
    conclusion: r.conclusion,
    created_at: r.created_at,
    updated_at: r.updated_at,
    event: r.event,
    html_url: r.html_url,
  }))
}

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  const url = new URL(request.url)
  const sourceFilter = url.searchParams.get("source")
  const sinceFilter = url.searchParams.get("since")
  const limit = parseLimit(url.searchParams.get("limit"))

  const results = {
    state: null,
    stateBackend: getStateBackend(),
    drafts: { drafts: [] },
    suppressions: { suppressions: [], stats: null },
    sourceHealth: { sources: [], stats: null },
    config: modelConfig(),
    runs: [],
  }

  try {
    const state = await readStateStore()
    results.state = state
    results.stateBackend = getStateBackend()
    results.drafts = { drafts: pendingDrafts(state) }
    results.suppressions = suppressionsPayload(state, { sourceFilter, sinceFilter, limit })
    results.sourceHealth = buildSourceHealthPayload(state)
  } catch (error) {
    results.stateError = `Failed to fetch state store: ${error.message}`
  }

  try {
    results.runs = await workflowRuns()
  } catch (error) {
    results.runs = []
    results.runsError = `Failed to fetch workflow runs: ${error.message}`
  }

  return Response.json(results)
}
