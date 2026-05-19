import { readStateStore } from "../../../lib/state-store.js"
import { requireDashboardAuth } from "../../../lib/auth.js"

export const runtime = "nodejs"

const DEFAULT_RUNS = 20

function classifyHealth(s) {
  // No runs OR every run was a skip (e.g. drought on a non-Friday) → idle.
  // Skipped is a deliberate "this source isn't due today," not a failure.
  const degradedRuns = s.degraded + s.partial_failures
  const active = s.successes + s.failures + degradedRuns
  if (s.runs === 0 || active === 0) return "idle"

  const successRate = s.successes / active

  // Most recent run failed — at minimum "degraded", "unhealthy" if pattern is consistent
  if (s.last_run_status === "failed" || s.last_run_status === "partial_failure") {
    return successRate < 0.5 ? "unhealthy" : "degraded"
  }
  if (s.last_run_status === "degraded") return "degraded"
  if (s.failures / active >= 0.5) return "unhealthy"
  if (degradedRuns > 0 || successRate < 0.95) return "degraded"
  return "healthy"
}

// GET — return per-source health rollup over the last N runs.
//
// Aggregates `bot_state.run_history` (capped at 20 by finalize_run) into a
// per-source view: success rate, total observed/promoted/drafted, last
// error, last run status. Sorted worst-first so dashboard surfaces problem
// sources at a glance.
export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  try {
    const url = new URL(request.url)
    const requested = Number(url.searchParams.get("runs"))
    const runsLimit = Number.isFinite(requested) && requested > 0
      ? Math.min(Math.floor(requested), DEFAULT_RUNS)
      : DEFAULT_RUNS

    const state = await readStateStore()
    const history = (Array.isArray(state.run_history) ? state.run_history : []).slice(0, runsLimit)

    // run_history is newest-first per src/state.py:finalize_run, so the FIRST
    // occurrence of a source across the iteration is its most-recent run.
    const bySource = new Map()
    for (const run of history) {
      const runStartedAt = run.started_at || null
      const sources = Array.isArray(run.sources) ? run.sources : []
      for (const s of sources) {
        const key = s.source
        if (!key) continue
        if (!bySource.has(key)) {
          bySource.set(key, {
            source: key,
            runs: 0,
            successes: 0,
            failures: 0,
            degraded: 0,
            partial_failures: 0,
            skipped: 0,
            total_observed: 0,
            total_promoted: 0,
            total_drafted: 0,
            last_error: null,
            last_error_at: null,
            last_run_at: null,
            last_run_status: null,
          })
        }
        const agg = bySource.get(key)
        agg.runs += 1
        agg.total_observed += Number(s.observed) || 0
        agg.total_promoted += Number(s.promoted) || 0
        agg.total_drafted += Number(s.drafted) || 0

        if (s.status === "success") agg.successes += 1
        else if (s.status === "failed") agg.failures += 1
        else if (s.status === "degraded") agg.degraded += 1
        else if (s.status === "partial_failure") agg.partial_failures += 1
        else if (s.status === "skipped") agg.skipped += 1

        if (agg.last_run_at == null) {
          agg.last_run_at = runStartedAt
          agg.last_run_status = s.status || null
        }
        // Capture the latest actionable error for ANY problem status, not
        // just "failed". Codex review of PR #70 flagged that
        // `partial_failure` (e.g. auto_publish_due hitting a per-draft rate
        // limit) was being classified as a problem but leaving last_error
        // null — hiding the actual rate-limit / downstream failure message
        // the operator needs to see. Same applies to "degraded" runs
        // whose note carries the diagnostic ("provider:ghcn
        // diff_dates_missing:4").
        const isProblemStatus =
          s.status === "failed" ||
          s.status === "partial_failure" ||
          s.status === "degraded"
        const diagnostic = s.error || s.note || null
        if (agg.last_error_at == null && isProblemStatus && diagnostic) {
          agg.last_error_at = runStartedAt
          agg.last_error = diagnostic
        }
      }
    }

    const order = { unhealthy: 0, degraded: 1, healthy: 2, idle: 3 }
    const sources = [...bySource.values()]
      .map((s) => {
        // success_rate denominator is active runs (success + problem),
        // not including skipped — matches the health classifier.
        const active = s.successes + s.failures + s.degraded + s.partial_failures
        return {
          ...s,
          success_rate: active > 0 ? s.successes / active : null,
          health: classifyHealth(s),
        }
      })
      .sort((a, b) => {
        const cmp = (order[a.health] ?? 9) - (order[b.health] ?? 9)
        if (cmp !== 0) return cmp
        // Within same health bucket, sort alphabetically for stable display
        return a.source.localeCompare(b.source)
      })

    return Response.json({
      sources,
      stats: {
        runs_analyzed: history.length,
        unhealthy_count: sources.filter((s) => s.health === "unhealthy").length,
        degraded_count: sources.filter((s) => s.health === "degraded").length,
        healthy_count: sources.filter((s) => s.health === "healthy").length,
        idle_count: sources.filter((s) => s.health === "idle").length,
      },
    })
  } catch (e) {
    return Response.json({ sources: [], stats: null, error: e.message }, { status: 500 })
  }
}
