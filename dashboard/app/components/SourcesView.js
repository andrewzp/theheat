"use client"

import { formatDuration, timeAgo } from "../../lib/format.js"
import {
  sourceDiagnosticClass,
  sourceDiagnosticLabel,
} from "../../lib/source-diagnostic.js"

function formatTroubleshootingMetric(entry) {
  return [
    `observed ${entry.observed ?? 0}`,
    `promoted ${entry.promoted ?? 0}`,
    `drafted ${entry.drafted ?? 0}`,
    `latency ${entry.duration_ms ? formatDuration(entry.duration_ms) : "0ms"}`,
  ].join(" / ")
}

function TroubleshootingLog({ source }) {
  if (source.health === "healthy" || source.health === "idle") return null
  const entries = Array.isArray(source.troubleshooting_log)
    ? source.troubleshooting_log.slice(0, 3)
    : []
  if (entries.length === 0) return null
  return (
    <div className={`source-troubleshooting ${sourceDiagnosticClass(source.health)}`}>
      <div className="source-troubleshooting-title">Troubleshooting log</div>
      {entries.map((entry, index) => (
        <div className="source-troubleshooting-row" key={`${entry.at || "unknown"}-${index}`}>
          <div className="source-troubleshooting-meta">
            <strong>{entry.status || "unknown"}</strong>
            <span>{entry.at ? timeAgo(entry.at) : "unknown time"}</span>
            {entry.error_class && <code>{entry.error_class}</code>}
          </div>
          <div className="source-troubleshooting-diagnostic">
            {entry.diagnostic || "(no diagnostic recorded)"}
          </div>
          <div className="source-troubleshooting-metrics">
            {formatTroubleshootingMetric(entry)}
          </div>
        </div>
      ))}
    </div>
  )
}

export function SourcesView({ sources, stats }) {
  if (!sources || sources.length === 0) {
    return (
      <div className="card full">
        <h2>Source Health</h2>
        <p style={{ color: "#888" }}>No run history yet.</p>
      </div>
    )
  }
  return (
    <div className="card full">
      <div className="section-head">
        <div>
          <h2>Source Health</h2>
          <p style={{ color: "#888", fontSize: 12 }}>
            Aggregated over the last {stats?.runs_analyzed ?? 0} runs.
            {stats?.unhealthy_count > 0 && (
              <span style={{ color: "#f87171", marginLeft: 8 }}>
                {stats.unhealthy_count} unhealthy
              </span>
            )}
            {stats?.degraded_count > 0 && (
              <span style={{ color: "#fbbf24", marginLeft: 8 }}>
                {stats.degraded_count} degraded
              </span>
            )}
            {stats?.external_count > 0 && (
              <span style={{ color: "#fb923c", marginLeft: 8 }}>
                {stats.external_count} external (NASA/gov)
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="source-health-table" style={{ marginTop: 16 }}>
        <div className="source-row source-header">
          <span>Source</span>
          <span>Health</span>
          <span>Success rate</span>
          <span>Observed</span>
          <span>Drafted</span>
          <span>Latency</span>
          <span>Last run</span>
        </div>
        {sources.map((s) => (
          <div key={s.source} className="source-row">
            <span className="source-name">{s.source}</span>
            <span className={`badge source-${s.health}`}>
              {s.health}
              {s.served_via && (
                <span style={{ marginLeft: 6, fontWeight: 400, opacity: 0.85 }}>
                  · served via {s.served_via}
                </span>
              )}
            </span>
            <span className="source-rate">
              {s.success_rate != null ? `${Math.round(s.success_rate * 100)}%` : "—"}
              <span style={{ color: "#555", marginLeft: 8, fontSize: 11 }}>
                ({s.successes}/{s.active ?? s.runs}
                {s.skipped ? `, ${s.skipped} skipped` : ""})
              </span>
            </span>
            <span className="source-num">{s.total_observed}</span>
            <span className="source-num">{s.total_drafted}</span>
            <span className="source-num">{s.avg_duration_ms != null ? formatDuration(s.avg_duration_ms) : "—"}</span>
            <span className="source-time">
              {s.last_run_at ? timeAgo(s.last_run_at) : "—"}
              {s.last_run_status === "failed" && (
                <span style={{ color: "#f87171", marginLeft: 4 }}>(failed)</span>
              )}
            </span>
            {s.last_error && !s.served_via && (
              <div
                className={`source-diagnostic ${sourceDiagnosticClass(s.health)}`}
              >
                {sourceDiagnosticLabel(s.health)} ({s.last_error_at ? timeAgo(s.last_error_at) : "—"}): {s.last_error}
              </div>
            )}
            <TroubleshootingLog source={s} />
          </div>
        ))}
      </div>
    </div>
  )
}
