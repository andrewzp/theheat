"use client"

import React, { useCallback, useEffect, useState } from "react"

const h = React.createElement
const REFRESH_INTERVAL_MS = 30000
const ERROR_MAX_LENGTH = 120

export function timeAgo(dateStr, now = Date.now()) {
  if (!dateStr) return "never"
  const then = new Date(dateStr).getTime()
  if (Number.isNaN(then)) return "never"
  const diff = now - then
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export function truncateError(text, max = ERROR_MAX_LENGTH) {
  if (!text || text.length <= max) return text || ""
  return `${text.slice(0, max - 1)}…`
}

export function successRateLabel(rate) {
  return rate == null ? "—" : `${Math.round(rate * 100)}%`
}

export function healthClass(health) {
  if (health === "unhealthy") return "unhealthy"
  if (health === "degraded") return "degraded"
  if (health === "healthy") return "healthy"
  return "idle"
}

export async function fetchSourceHealth(fetchImpl = fetch) {
  const response = await fetchImpl("/api/source-health")
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    throw new Error(payload?.error || `Source health request failed (${response.status})`)
  }
  if (payload?.error) {
    throw new Error(payload.error)
  }
  return {
    sources: Array.isArray(payload?.sources) ? payload.sources : [],
    stats: payload?.stats || null,
  }
}

function StatCard({ label, value, tone }) {
  return h(
    "div",
    { className: `stat-card ${tone || ""}` },
    h("div", { className: "stat-value" }, value ?? 0),
    h("div", { className: "stat-label" }, label)
  )
}

function HealthPill({ health }) {
  const safeHealth = health || "idle"
  return h("span", { className: `health-pill ${healthClass(safeHealth)}` }, safeHealth)
}

function CounterPill({ label, value, tone }) {
  return h(
    "span",
    { className: `counter-pill ${tone || ""}` },
    h("strong", null, value ?? 0),
    " ",
    label
  )
}

function formatDurationMs(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return "0ms"
  if (n < 1000) return `${Math.round(n)}ms`
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s`
}

function troubleshootingMetricText(entry) {
  return [
    `observed ${entry.observed ?? 0}`,
    `promoted ${entry.promoted ?? 0}`,
    `drafted ${entry.drafted ?? 0}`,
    `latency ${formatDurationMs(entry.duration_ms)}`,
  ].join(" / ")
}

function TroubleshootingLog({ entries, now, health }) {
  if (health === "healthy" || health === "idle") return null
  if (!Array.isArray(entries) || entries.length === 0) return null
  return h(
    "div",
    { className: "troubleshooting-log" },
    h("div", { className: "troubleshooting-title" }, "Troubleshooting log"),
    entries.slice(0, 5).map((entry, index) =>
      h(
        "div",
        { className: "troubleshooting-row", key: `${entry.at || "unknown"}-${index}` },
        h(
          "div",
          { className: "troubleshooting-row-head" },
          h("strong", null, entry.status || "unknown"),
          h("span", null, entry.at ? timeAgo(entry.at, now) : "unknown time"),
          entry.error_class
            ? h("code", null, entry.error_class)
            : null
        ),
        h("p", { title: entry.diagnostic || "" }, entry.diagnostic || "(no diagnostic recorded)"),
        h("small", null, troubleshootingMetricText(entry))
      )
    )
  )
}

function SourceRow({ source, now }) {
  const lastError = source.last_error || ""
  const clippedError = truncateError(lastError)
  const troubleshootingLog = Array.isArray(source.troubleshooting_log)
    ? source.troubleshooting_log
    : []
  return h(
    "article",
    { className: `source-card ${healthClass(source.health)}`, "data-source": source.source },
    h(
      "div",
      { className: "source-main" },
      h(
        "div",
        { className: "source-title-block" },
        h("h2", { className: "source-title" }, source.source),
        h(
          "div",
          { className: "source-subline" },
          h("span", null, "last run "),
          h("strong", null, source.last_run_at ? timeAgo(source.last_run_at, now) : "—"),
          h("span", null, " / "),
          h("strong", null, source.last_run_status || "—")
        )
      ),
      h(
        "div",
        { className: "source-metrics" },
        h(HealthPill, { health: source.health }),
        h("span", { className: "rate-pill" }, successRateLabel(source.success_rate))
      )
    ),
    h(
      "div",
      { className: "counter-row" },
      h(CounterPill, { label: "success", value: source.successes, tone: "success" }),
      h(CounterPill, { label: "degraded", value: source.degraded + source.partial_failures, tone: "degraded" }),
      h(CounterPill, { label: "failed", value: source.failures, tone: "failed" }),
      h(CounterPill, { label: "skipped", value: source.skipped, tone: "skipped" })
    ),
    lastError
      ? h(
          "div",
          { className: "last-error", title: lastError },
          h("span", null, "last error"),
          h("strong", null, clippedError)
        )
      : null,
    h(TroubleshootingLog, { entries: troubleshootingLog, now, health: source.health })
  )
}

export function SourceHealthContent({
  sources = [],
  stats = null,
  loading = false,
  error = "",
  refreshing = false,
  lastUpdated = null,
  onRefresh = null,
  now = Date.now(),
  embedded = false,
}) {
  const hasSources = sources.length > 0

  // The body (stats grid + list) is identical standalone and embedded; only the
  // chrome (header + the standalone-only tab nav + global page styles) differs.
  // Embedded mode renders inside the main control panel, which already provides
  // the header + the shared tab nav — so emitting them here is what dropped the
  // rest of the navigation when Health was a separate /health route.
  const bodyChildren = [
    h(
      "section",
      { className: "stats-grid", "aria-label": "Source health counts", key: "stats" },
      h(StatCard, { label: "unhealthy", value: stats?.unhealthy_count ?? 0, tone: "unhealthy" }),
      h(StatCard, { label: "degraded", value: stats?.degraded_count ?? 0, tone: "degraded" }),
      h(StatCard, { label: "healthy", value: stats?.healthy_count ?? 0, tone: "healthy" }),
      h(StatCard, { label: "idle", value: stats?.idle_count ?? 0, tone: "idle" })
    ),
    error
      ? h("div", { className: "status-banner error", role: "alert", key: "err" }, `Source health unavailable: ${error}`)
      : null,
    loading
      ? h("div", { className: "loading", key: "loading" }, "loading...")
      : hasSources
      ? h(
          "section",
          { className: "source-list", "aria-label": "Source health list", key: "list" },
          sources.map((source) => h(SourceRow, { key: source.source, source, now }))
        )
      : h(
          "div",
          { className: "empty-state", key: "empty" },
          "Source health data not yet available. The next alerts cron will populate this view."
        ),
  ]

  if (embedded) {
    return h(
      React.Fragment,
      null,
      h("style", { dangerouslySetInnerHTML: { __html: styles } }),
      h(
        "div",
        { className: "health-embedded" },
        h(
          "p",
          { className: "health-kicker" },
          `Aggregated over the last ${stats?.runs_analyzed ?? 0} runs.`
        ),
        ...bodyChildren
      )
    )
  }

  return h(
    React.Fragment,
    null,
    h("style", { dangerouslySetInnerHTML: { __html: globalStyles + styles } }),
    h(
      "main",
      { className: "health-shell" },
      h(
        "header",
        { className: "health-header" },
        h(
          "div",
          null,
          h("h1", null, "@theheat ", h("span", null, "source health")),
          h(
            "p",
            { className: "health-kicker" },
            `Aggregated over the last ${stats?.runs_analyzed ?? 0} runs.`
          )
        ),
        h(
          "div",
          { className: "header-actions" },
          lastUpdated && !error
            ? h("span", { className: "refresh-meta" }, `updated ${timeAgo(lastUpdated, now)}`)
            : null,
          h(
            "button",
            {
              type: "button",
              className: `refresh-btn${refreshing ? " is-refreshing" : ""}`,
              onClick: onRefresh || undefined,
              disabled: refreshing || !onRefresh,
            },
            refreshing ? "refreshing…" : "refresh"
          )
        )
      ),
      h(
        "nav",
        { className: "health-tabs", "aria-label": "Dashboard navigation" },
        h("a", { className: "tab-link", href: "/" }, "Dashboard"),
        h("a", { className: "tab-link active", href: "/health" }, "Health")
      ),
      ...bodyChildren
    )
  )
}

export default function SourceHealthPage() {
  const [sources, setSources] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState("")
  const [lastUpdated, setLastUpdated] = useState(null)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError("")
    try {
      const result = await fetchSourceHealth()
      setSources(result.sources)
      setStats(result.stats)
      setLastUpdated(new Date().toISOString())
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [load])

  return h(SourceHealthContent, {
    sources,
    stats,
    loading,
    error,
    refreshing,
    lastUpdated,
    onRefresh: load,
  })
}

// Global page chrome — only injected by the standalone /health route. Embedded
// mode (inside the control panel) skips these so it doesn't restyle the panel.
const globalStyles = `
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "SF Mono", "Fira Code", "Consolas", monospace;
  background: #0a0a0a;
  color: #e0e0e0;
}
`

// Component styles — injected in both modes (the .stat-card / .source-card etc.
// classes live only here, not in the panel's global CSS).
const styles = `
.health-embedded { margin-top: 4px; }
.health-shell {
  max-width: 1040px;
  margin: 0 auto;
  padding: 24px 16px 40px;
}
.health-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #222;
}
.health-header h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #ff4d00;
}
.health-header h1 span {
  color: #666;
  font-size: 14px;
  font-weight: 400;
}
.health-kicker {
  margin: 6px 0 0;
  color: #666;
  font-size: 12px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.refresh-meta {
  color: #555;
  font-size: 11px;
}
.refresh-btn {
  min-width: 96px;
  background: none;
  border: 1px solid #333;
  color: #888;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}
.refresh-btn:hover {
  border-color: #555;
  color: #ccc;
}
.refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.refresh-btn.is-refreshing {
  border-color: #ff4d00;
  color: #ff4d00;
  opacity: 1;
}
.health-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  border-bottom: 1px solid #222;
}
.tab-link {
  color: #666;
  padding: 10px 14px;
  border-bottom: 2px solid transparent;
  text-decoration: none;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: -1px;
}
.tab-link:hover {
  color: #ccc;
}
.tab-link.active {
  color: #ff4d00;
  border-bottom-color: #ff4d00;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.stat-card {
  background: #111;
  border: 1px solid #222;
  border-radius: 8px;
  padding: 16px;
}
.stat-value {
  font-size: 30px;
  line-height: 1;
  font-weight: 700;
  color: #ff4d00;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  margin-top: 7px;
  color: #666;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.stat-card.unhealthy .stat-value { color: #f87171; }
.stat-card.degraded .stat-value { color: #facc15; }
.stat-card.healthy .stat-value { color: #4ade80; }
.stat-card.idle .stat-value { color: #888; }
.status-banner {
  margin-bottom: 16px;
  padding: 10px 12px;
  border-radius: 4px;
  font-size: 12px;
  border: 1px solid;
}
.status-banner.error {
  background: #2a0a0a;
  color: #f87171;
  border-color: #4a1a1a;
}
.source-list {
  display: grid;
  gap: 10px;
}
.source-card {
  background: #111;
  border: 1px solid #222;
  border-radius: 8px;
  padding: 14px;
}
.source-card.unhealthy { border-color: #4a1a1a; }
.source-card.degraded { border-color: #4a3a1a; }
.source-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: start;
}
.source-title {
  margin: 0;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}
.source-subline {
  margin-top: 6px;
  color: #666;
  font-size: 12px;
}
.source-subline strong {
  color: #aaa;
  font-weight: 600;
}
.source-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
}
.health-pill,
.rate-pill,
.counter-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  white-space: nowrap;
}
.health-pill {
  text-transform: uppercase;
}
.health-pill.healthy {
  background: #0a2a0a;
  color: #4ade80;
  border: 1px solid #1a4a1a;
}
.health-pill.degraded {
  background: #2a1a0a;
  color: #facc15;
  border: 1px solid #4a3a1a;
}
.health-pill.unhealthy {
  background: #2a0a0a;
  color: #f87171;
  border: 1px solid #4a1a1a;
}
.health-pill.idle {
  background: #1a1a1a;
  color: #888;
  border: 1px solid #333;
}
.rate-pill {
  background: #1a1a1a;
  color: #ccc;
  border: 1px solid #333;
  font-variant-numeric: tabular-nums;
}
.counter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}
.counter-pill {
  background: #1a1a1a;
  color: #888;
  border: 1px solid #2a2a2a;
}
.counter-pill strong {
  color: #ccc;
  font-variant-numeric: tabular-nums;
}
.counter-pill.success strong { color: #4ade80; }
.counter-pill.degraded strong { color: #facc15; }
.counter-pill.failed strong { color: #f87171; }
.last-error {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  margin-top: 12px;
  padding: 8px 10px;
  background: #1a1010;
  border: 1px solid #3a1010;
  border-radius: 4px;
  color: #f87171;
  font-size: 12px;
}
.last-error span {
  color: #a85555;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 10px;
}
.last-error strong {
  min-width: 0;
  color: #f87171;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.troubleshooting-log {
  margin-top: 12px;
  display: grid;
  gap: 8px;
}
.troubleshooting-title {
  color: #666;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.8px;
  text-transform: uppercase;
}
.troubleshooting-row {
  padding: 8px 10px;
  background: #151515;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
}
.troubleshooting-row-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 5px;
}
.troubleshooting-row-head strong {
  color: #f87171;
  font-size: 11px;
  text-transform: uppercase;
}
.troubleshooting-row-head span {
  color: #666;
  font-size: 11px;
}
.troubleshooting-row-head code {
  color: #fb923c;
  background: #20140a;
  border: 1px solid #3a2410;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 10px;
}
.troubleshooting-row p {
  margin: 0;
  color: #ccc;
  font-size: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.troubleshooting-row small {
  display: block;
  margin-top: 5px;
  color: #777;
  font-size: 10px;
}
.empty-state,
.loading {
  padding: 28px 0;
  color: #555;
  font-size: 13px;
  font-style: italic;
}
@media (max-width: 720px) {
  .health-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .source-main {
    grid-template-columns: 1fr;
  }
  .source-metrics {
    justify-content: flex-start;
  }
}
@media (max-width: 460px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .last-error {
    grid-template-columns: 1fr;
  }
}
`
