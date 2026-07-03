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
const RUN_METRICS = [
  "duration_ms",
  "observed",
  "promoted",
  "triaged_in",
  "triaged_out",
  "writer_attempted",
  "drafted",
]
const TROUBLESHOOTING_LOG_LIMIT = 8

// How many of the most-recent runs define "now" for health classification.
// The cumulative counters span src/state.py's 7-day window, so a single bad
// day (e.g. a NASA 503 storm) can dominate them for days. Classifying on a
// recent sub-window keeps the badge honest: recovering sources stop being red,
// freshly-degrading sources stop hiding behind stale successes.
const RECENT_WINDOW = 5

// Mirror of scripts/source_health_sentinel.py classify_error. An upstream error
// (NASA/gov 5xx, timeouts, connection failures, 403/429 rate-limits) means the
// failure is external — not our bug — and renders as "external" (amber), not the
// red/yellow of a real defect. Earthdata 403 credential failures are checked
// before the upstream regex. our_bug = code/auth/moved-endpoint we must fix.
const OUR_BUG_RE = /\b(401|404|410)\b|Unauthorized|EARTHDATA_TOKEN|invalid token|token expired|expired token|credential|AttributeError|KeyError|TypeError|ValueError|IndexError|NameError|UnboundLocalError|ZeroDivisionError|RecursionError|JSONDecodeError|Expecting value|schema drift|missing required field|expected JSON object|could not parse|invalid literal|Not Found/i
const UPSTREAM_RE = /\b(403|429|50\d)\b|Server Error|Bad Gateway|Service Unavailable|Gateway Time|ReadTimeout|ConnectTimeout|Timeout|timed out|ConnectionError|Connection refused|Connection reset|Max retries|Network is unreachable|Name or service not known|Temporary failure in name resolution|HTTPSConnectionPool|HTTPConnectionPool|Forbidden|Too Many Requests/i
const EARTHDATA_CREDENTIAL_HOST_RE = /earthdata|urs\.earthdata|EDL|podaac/i
const HTTP_403_RE = /\b403\b/

// Mirror of scripts/source_health_sentinel.py parse_served_via. A run served by a
// redundancy witness (src/data/_witness.py) records status "degraded" with the
// diagnostic "served via <leg>". Surfacing the leg lets the dashboard render
// "firms — degraded (served via noaa_hms)" instead of treating it as an error, and
// warns the operator the primary is down even while backup drafts still flow.
const SERVED_VIA_RE = /served via (\S+)/

function parseServedVia(diagnostic) {
  if (!diagnostic) return null
  const m = SERVED_VIA_RE.exec(String(diagnostic))
  return m ? m[1] : null
}

function classifyError(lastError) {
  if (!lastError) return "none"
  const t = String(lastError).trim()
  if (!t || t === "-") return "none"
  if (OUR_BUG_RE.test(t)) return "our_bug"
  if (HTTP_403_RE.test(t) && EARTHDATA_CREDENTIAL_HOST_RE.test(t)) return "our_bug"
  if (UPSTREAM_RE.test(t)) return "upstream"
  return "unknown"
}

function classifyHealth(s) {
  // No runs OR no active attempts ever -> idle.
  const degradedRuns = s.degraded + s.partial_failures
  const active = s.successes + s.failures + degradedRuns
  if (s.runs === 0 || active === 0) return "idle"

  // Recent RUN window is all cadence skips -> idle. The source isn't attempting
  // right now, so it isn't currently failing — don't judge it on stale attempts
  // from days ago (matches the sentinel; fixes ice_mass showing red while idle).
  if (typeof s.recent_active === "number" && s.recent_active === 0) return "idle"

  const recentSuccessRate =
    typeof s.recent_active === "number" && s.recent_active > 0
      ? s.recent_successes / s.recent_active
      : null
  const rate = recentSuccessRate != null ? recentSuccessRate : s.successes / active

  // If we have a recent active window and every recent attempt succeeded, the
  // source recovered even if the 7-day cumulative counters still contain an old
  // degraded/failed row. Without a recent window (run_history fallback), keep the
  // cumulative guard.
  if (rate >= 1 && (recentSuccessRate != null || degradedRuns === 0)) return "healthy"

  const hasFailures = s.failures > 0 || s.partial_failures > 0
  // Hard failures caused by NASA/gov -> "external" (amber), not our red/yellow.
  if (hasFailures && classifyError(s.last_error) === "upstream") return "external"
  // Hard failures dominating -> unhealthy (red). Otherwise degraded (yellow):
  // partial/degraded runs, or a recovering source whose recent rate is back up.
  if (hasFailures && rate < 0.5) return "unhealthy"
  return "degraded"
}

function numberOrZero(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function normalizedProblemStatus(status) {
  if (status === "partial_failure") return "partial_failure"
  if (status === "degraded") return "degraded"
  if (status === "failed") return "failed"
  return null
}

function troubleshootingEntry(row, at) {
  const status = normalizedProblemStatus(row?.status)
  if (!status) return null
  const diagnostic = String(row?.error || row?.note || "").trim()
  const entry = {
    at: at || row?.ts || null,
    status,
    diagnostic: diagnostic || "(no diagnostic recorded)",
    error_class: row?.error_class || (diagnostic ? classifyError(diagnostic) : "none"),
  }
  for (const key of RUN_METRICS) {
    entry[key] = numberOrZero(row?.[key])
  }
  return entry
}

function buildTroubleshootingLogFromRuns(runs, getTimestamp) {
  return (Array.isArray(runs) ? runs : [])
    .map((row) => troubleshootingEntry(row, getTimestamp(row)))
    .filter(Boolean)
    .sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")))
    .slice(0, TROUBLESHOOTING_LOG_LIMIT)
}

function addDerivedFields(s) {
  // active = runs that actually attempted the fetch (skips excluded). This is
  // the denominator for both success_rate AND the displayed "(N/M)" fraction —
  // using s.runs (which includes skips) made the fraction contradict the % for
  // cadence-gated sources (e.g. ice_mass: "33% (1/10)" instead of "33% (1/3)").
  const active = s.successes + s.failures + s.degraded + s.partial_failures
  const health = classifyHealth(s)
  const latestRunSucceeded = s.last_run_status === "success"
  const showDiagnostic =
    health !== "healthy" &&
    health !== "idle" &&
    (!latestRunSucceeded || health === "unhealthy")
  const lastError = showDiagnostic ? s.last_error : null
  const lastErrorAt = showDiagnostic ? s.last_error_at : null
  return {
    ...s,
    last_error: lastError,
    last_error_at: lastErrorAt,
    active,
    success_rate: active > 0 ? s.successes / active : null,
    health,
    troubleshooting_log: Array.isArray(s.troubleshooting_log)
      ? s.troubleshooting_log
      : [],
    // Only meaningful while degraded — a recovered primary (back to healthy)
    // clears the stale "served via" diagnostic so it can't masquerade.
    served_via: health === "degraded" ? parseServedVia(lastError) : null,
  }
}

function aggregateFromSourceHealth(sourceHealth) {
  return Object.entries(sourceHealth || {}).map(([source, health]) => {
    const runs = Array.isArray(health?.runs) ? health.runs : []
    const lastRun = runs.length > 0 ? runs[runs.length - 1] : null

    // Recent sub-window: active attempts within the last RECENT_WINDOW actual
    // runs (runs is oldest-first per src/state.py:record_source_health). We look
    // at the recent RUN window INCLUDING skips — if it's all skips the source is
    // idle (not attempting now), not "failing" on stale attempts from days ago.
    let recentSuccesses = 0
    let recentActive = 0
    for (const r of runs.slice(-RECENT_WINDOW)) {
      const st = r?.status
      if (st === "success") {
        recentSuccesses += 1
        recentActive += 1
      } else if (st === "failed" || st === "degraded" || st === "partial_failure") {
        recentActive += 1
      }
    }

    const row = {
      source,
      runs: runs.length,
      successes: numberOrZero(health?.success),
      failures: numberOrZero(health?.failed),
      degraded: numberOrZero(health?.degraded),
      partial_failures: 0,
      skipped: numberOrZero(health?.skipped),
      recent_successes: recentSuccesses,
      recent_active: recentActive,
      last_error: health?.last_error || null,
      last_error_at: health?.last_error_ts || null,
      last_run_at: lastRun?.ts || null,
      last_run_status: lastRun?.status || null,
      troubleshooting_log: buildTroubleshootingLogFromRuns(runs, (r) => r?.ts || null),
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
          troubleshooting_log: [],
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
      const logEntry = troubleshootingEntry(s, runStartedAt)
      if (logEntry) {
        agg.troubleshooting_log.push(logEntry)
      }
    }
  }

  return [...bySource.values()].map((s) => ({
    ...s,
    troubleshooting_log: s.troubleshooting_log
      .sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")))
      .slice(0, TROUBLESHOOTING_LOG_LIMIT),
    avg_duration_ms: s.runs > 0 ? Math.round(s.total_duration_ms / s.runs) : null,
  })).map(addDerivedFields)
}

// ---------------------------------------------------------------------------
// coverageWatch — JS mirror of scripts/source_health_sentinel.py coverage_watch
// Constants MUST stay in sync with the Python implementation.
// ---------------------------------------------------------------------------

// MUST match scripts/source_health_sentinel.py
export const COVERAGE_WINDOW_DAYS = 21
export const COVERAGE_MIN_EVENTS = 20
export const COVERAGE_CONCENTRATION = 0.85
export const COVERAGE_DATA_FLOOR = 5
const COVERAGE_WATCHED_CLASSES = ["heat"]

function botIsDrafting(runHistory) {
  return (runHistory || []).some((r) => r && (r.mode === "alerts" || r.mode === "both"))
}

export function coverageWatch(coverageLog, runHistory, now = new Date()) {
  const cutoff = new Date(now.getTime() - COVERAGE_WINDOW_DAYS * 86400000).toISOString().slice(0, 10)
  const drafting = botIsDrafting(runHistory)
  const findings = []
  for (const cls of COVERAGE_WATCHED_CLASSES) {
    const recs = (coverageLog || []).filter((r) => r && r.cls === cls && String(r.date || "") >= cutoff)
    const n = recs.length
    if (n < COVERAGE_DATA_FLOOR) {
      if (drafting) findings.push({ cls, kind: "no_data", dominant: "—", share: 0, events: n, distribution: {} })
      continue
    }
    if (n < COVERAGE_MIN_EVENTS) {
      findings.push({ cls, kind: "insufficient_data", dominant: "—", share: 0, events: n, distribution: {} })
      continue
    }
    for (const axis of ["country", "continent"]) {
      const counts = {}
      for (const r of recs) { const k = String(r[axis] || "Unknown"); counts[k] = (counts[k] || 0) + 1 }
      const [dominant, top] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
      if (dominant !== "Unknown" && top / n >= COVERAGE_CONCENTRATION) {
        findings.push({ cls, kind: "mono_regional", dominant, share: Math.round((top / n) * 1000) / 1000,
          events: n, distribution: counts })
        break
      }
    }
  }
  return findings
}

// ---------------------------------------------------------------------------
// writerWatch — JS mirror of scripts/source_health_sentinel.py writer_watch
// Constants MUST stay in sync with the Python implementation.
// ---------------------------------------------------------------------------

// MUST match scripts/source_health_sentinel.py
export const WRITER_WATCH_WINDOW_HOURS = 24

// Strict ISO timestamp parse mirroring Python's _parse_ts rejections: full
// ISO shape required, and invalid calendar/clock parts are REJECTED — bare
// Date.parse silently normalizes them (2026-02-31 -> Mar 3), which would make
// the JS mirror count a malformed row Python skips. Returns epoch ms or NaN.
const TS_SHAPE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/
function parseTsStrict(ts) {
  const m = TS_SHAPE.exec(String(ts || ""))
  if (!m) return NaN
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number)
  const daysInMonth = new Date(Date.UTC(y, mo, 0)).getUTCDate()
  if (mo < 1 || mo > 12 || d < 1 || d > daysInMonth) return NaN
  if (h > 23 || mi > 59 || s > 59) return NaN
  return Date.parse(m[0])
}

export function writerWatch(suppressions, runHistory, now = new Date()) {
  if (!botIsDrafting(runHistory)) return []
  // Parse timestamps rather than comparing strings — a malformed ts must be
  // SKIPPED, not lexically treated as "recent" (mirrors the Python _parse_ts
  // behavior and avoids string-format cutoff mismatches).
  const cutoffMs = now.getTime() - WRITER_WATCH_WINDOW_HOURS * 3600000
  const rows = (suppressions || []).filter((r) => {
    if (!r || r.stage !== "budget_exhausted") return false
    const t = parseTsStrict(r.ts)
    return !Number.isNaN(t) && t >= cutoffMs
  })
  if (rows.length === 0) return []
  const lastTs = rows.map((r) => String(r.ts || "")).sort().at(-1)
  return [{ kind: "budget_exhausted", count: rows.length, last_ts: lastTs }]
}

export function buildSourceHealthPayload(state, { runsLimit = 20 } = {}) {
  const durableHealth = state?.source_health && Object.keys(state.source_health).length > 0
  const history = durableHealth
    ? []
    : (Array.isArray(state?.run_history) ? state.run_history : []).slice(0, runsLimit)
  const order = { unhealthy: 0, degraded: 1, external: 2, healthy: 3, idle: 4 }
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
      external_count: sources.filter((s) => s.health === "external").length,
      healthy_count: sources.filter((s) => s.health === "healthy").length,
      idle_count: sources.filter((s) => s.health === "idle").length,
    },
    coverage: coverageWatch(state?.coverage_log, state?.run_history, new Date()),
    writer: writerWatch(state?.suppressions, state?.run_history, new Date()),
  }
}
