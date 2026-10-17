import { localCostEvidence } from "../../../lib/local-cost-evidence.js"
import { localCommandRequest, localDraftProjection, previewConfigured, previewError } from "../../../lib/draft-command-client.js"
import { dashboardEditorialPolicy } from "../../../lib/editorial-policy.js"
import { dashboardAutomaticPolicy } from "../../../lib/publication-control.js"
import { getStateBackend, readStateWithRuntimeReport } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"
import { buildSourceHealthPayload } from "../../../lib/source-health.js"
import { projectStateForDashboard } from "../../../lib/projection.js"
import { hasUnresolvedPublish, projectDraft } from "../../../lib/draft-revisions.js"
import { buildRuntimeConfig, dashboardDeployment } from "../../../lib/runtime-inventory.js"
import { buildProductHealth } from "../../../lib/product-health.js"
import { buildCostEvidence } from "../../../lib/cost-evidence.js"
import { nwsSourceTiming } from "../../../lib/nws-source-timing.js"

export const runtime = "nodejs"

const REPO = "andrewzp/theheat"
const DEFAULT_SUPPRESSION_LIMIT = 50
const MAX_SUPPRESSION_LIMIT = 200

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

function pendingDrafts(state, local = null, runtimeReport = null) {
  const now = Date.now()
  return (state?.drafts || [])
    .filter((d) => ["pending", "approved"].includes(d.status))
    .sort((a, b) => {
      const sourceDiff = local ? 0 : Number(nwsSourceTiming(a, now).blocked) - Number(nwsSourceTiming(b, now).blocked)
      if (sourceDiff) return sourceDiff
      const priorityA = (a.score?.total || 0) + (a.candidate_score?.total || 0) * 0.35
      const priorityB = (b.score?.total || 0) + (b.candidate_score?.total || 0) * 0.35
      const scoreDiff = priorityB - priorityA
      if (scoreDiff !== 0) return scoreDiff
      return new Date(b.created_at || 0) - new Date(a.created_at || 0)
    })
    .map((d) => {
      try {
        if (local) return localDraftProjection(d, state, local)
        return { ...projectDraft(d, dashboardEditorialPolicy(state, { runtimeReport }).policy), editorial_policy: dashboardEditorialPolicy(state, { runtimeReport }), automatic_publication: dashboardAutomaticPolicy(state, { runtimeReport }), publish_blocked: hasUnresolvedPublish(d, state), tweet_id: d.tweet_id ?? null }
      } catch (error) {
        return { ...d, text: typeof d.text === "string" ? d.text : "[Invalid draft text]", revision_identity: null, review_status: "conflict", review_kind: null, publish_blocked: true, review_error: error.message, tweet_id: d.tweet_id ?? null }
      }
    })
}

// Row 9: posted drafts joined to their captured engagement metrics, so the
// grading corpus can compare its A–F grades against what readers actually did.
// Only posted drafts that carry a tweet_id (the join key) are surfaced;
// metrics is null until the twitter_metrics lane has polled that tweet.
function postedDraftsWithMetrics(state) {
  const metrics = state?.tweet_metrics || {}
  return (state?.drafts || [])
    .filter((d) => d.status === "posted" && d.tweet_id)
    .sort((a, b) => new Date(b.posted_at || 0) - new Date(a.posted_at || 0))
    .map((d) => ({
      id: d.id,
      type: d.type ?? null,
      event_id: d.event_id ?? null,
      tweet_id: d.tweet_id,
      text: d.text ?? null,
      posted_at: d.posted_at ?? null,
      created_at: d.created_at ?? null,
      score: d.score ?? null,
      candidate_score: d.candidate_score ?? null,
      metrics: metrics[d.tweet_id] ?? null,
    }))
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
    drafts: { drafts: [], posted: [] },
    suppressions: { suppressions: [], stats: null },
    sourceHealth: { sources: [], stats: null },
    config: buildRuntimeConfig(),
    deployment: dashboardDeployment(),
    productHealth: null,
    costEvidence: buildCostEvidence(null),
    runs: [],
  }

  try {
    const local = previewConfigured() ? (await localCommandRequest(request, "/state")).payload : null
    const { state, runtimeReport } = local ? { state: local.state, runtimeReport: null } : await readStateWithRuntimeReport()
    results.local_preview = !!local
    if (local) { results.candidates = local.candidates || []; results.operator_role = local.role; results.operator_subject = local.operator_subject }
    if (local) results.localCostEvidence = localCostEvidence(local.local_cost)
    results.costEvidence = buildCostEvidence(state, {scenario: url.searchParams.get("cost_scenario")})
    results.state = projectStateForDashboard(state)
    results.stateBackend = local ? "local command preview" : getStateBackend()
    results.drafts = { drafts: pendingDrafts(state, local, runtimeReport), posted: postedDraftsWithMetrics(state) }
    results.suppressions = suppressionsPayload(state, { sourceFilter, sinceFilter, limit })
    results.sourceHealth = buildSourceHealthPayload(state)
    results.config = buildRuntimeConfig(state, { runtimeReport })
    results.productHealth = buildProductHealth(state, { runtimeReport })
  } catch (error) {
    if (previewConfigured()) return previewError(error)
    results.stateError = `Failed to fetch state store: ${error.message}`
  }

  try {
    results.runs = previewConfigured() ? [] : await workflowRuns()
  } catch (error) {
    results.runs = []
    results.runsError = `Failed to fetch workflow runs: ${error.message}`
  }

  return Response.json(results, { headers: { "Cache-Control": "private, no-store" } })
}
