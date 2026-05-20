const HEALTH_METRIC_TOTALS = [
  "total_duration_ms",
  "avg_duration_ms",
  "max_duration_ms",
  "total_observed",
  "total_promoted",
  "total_triaged_in",
  "total_triaged_out",
  "total_writer_attempted",
  "total_drafted",
]

function classifyHealth(s) {
  // No runs OR every run was a skip (e.g. drought on a non-Friday) -> idle.
  // Skipped is a deliberate "this source isn't due today," not a failure.
  const degradedRuns = s.degraded + s.partial_failures
  const active = s.successes + s.failures + degradedRuns
  if (s.runs === 0 || active === 0) return "idle"

  const successRate = s.successes / active

  // Most recent run failed: at minimum "degraded", "unhealthy" if the
  // pattern is consistent.
  if (s.last_run_status === "failed" || s.last_run_status === "partial_failure") {
    return successRate < 0.5 ? "unhealthy" : "degraded"
  }
  if (s.last_run_status === "degraded") return "degraded"
  if (s.failures / active >= 0.5) return "unhealthy"
  if (degradedRuns > 0 || successRate < 0.95) return "degraded"
  return "healthy"
}

function numberOrZero(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function addDerivedFields(s) {
  const active = s.successes + s.failures + s.degraded + s.partial_failures
  return {
    ...s,
    success_rate: active > 0 ? s.successes / active : null,
    health: classifyHealth(s),
  }
}

function aggregateFromSourceHealth(sourceHealth) {
  return Object.entries(sourceHealth || {}).map(([source, health]) => {
    const runs = Array.isArray(health?.runs) ? health.runs : []
    const lastRun = runs.length > 0 ? runs[runs.length - 1] : null
    const row = {
      source,
      runs: runs.length,
      successes: numberOrZero(health?.success),
      failures: numberOrZero(health?.failed),
      degraded: numberOrZero(health?.degraded),
      partial_failures: 0,
      skipped: numberOrZero(health?.skipped),
      last_error: health?.last_error || null,
      last_error_at: health?.last_error_ts || null,
      last_run_at: lastRun?.ts || null,
      last_run_status: lastRun?.status || null,
    }
    for (const key of HEALTH_METRIC_TOTALS) {
      row[key] = health?.[key] ?? (key === "avg_duration_ms" ? null : 0)
    }
    return addDerivedFields(row)
  })
}

function aggregateFromRunHistory(history) {
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
          total_duration_ms: 0,
          avg_duration_ms: null,
          max_duration_ms: 0,
          total_observed: 0,
          total_promoted: 0,
          total_triaged_in: 0,
          total_triaged_out: 0,
          total_writer_attempted: 0,
          total_drafted: 0,
          last_error: null,
          last_error_at: null,
          last_run_at: null,
          last_run_status: null,
        })
      }
      const agg = bySource.get(key)
      agg.runs += 1
      const durationMs = Number(s.duration_ms) || 0
      agg.total_duration_ms += durationMs
      agg.max_duration_ms = Math.max(agg.max_duration_ms, durationMs)
      agg.total_observed += Number(s.observed) || 0
      agg.total_promoted += Number(s.promoted) || 0
      agg.total_triaged_in += Number(s.triaged_in) || 0
      agg.total_triaged_out += Number(s.triaged_out) || 0
      agg.total_writer_attempted += Number(s.writer_attempted) || 0
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

  return [...bySource.values()].map((s) => ({
    ...s,
    avg_duration_ms: s.runs > 0 ? Math.round(s.total_duration_ms / s.runs) : null,
  })).map(addDerivedFields)
}

export function buildSourceHealthPayload(state, { runsLimit = 20 } = {}) {
  const durableHealth = state?.source_health && Object.keys(state.source_health).length > 0
  const history = durableHealth
    ? []
    : (Array.isArray(state?.run_history) ? state.run_history : []).slice(0, runsLimit)
  const order = { unhealthy: 0, degraded: 1, healthy: 2, idle: 3 }
  const rawSources = durableHealth
    ? aggregateFromSourceHealth(state.source_health)
    : aggregateFromRunHistory(history)
  const sources = rawSources.sort((a, b) => {
    const cmp = (order[a.health] ?? 9) - (order[b.health] ?? 9)
    if (cmp !== 0) return cmp
    return a.source.localeCompare(b.source)
  })

  return {
    sources,
    stats: {
      runs_analyzed: durableHealth
        ? Math.max(0, ...sources.map((s) => s.runs || 0))
        : history.length,
      unhealthy_count: sources.filter((s) => s.health === "unhealthy").length,
      degraded_count: sources.filter((s) => s.health === "degraded").length,
      healthy_count: sources.filter((s) => s.health === "healthy").length,
      idle_count: sources.filter((s) => s.health === "idle").length,
    },
  }
}
