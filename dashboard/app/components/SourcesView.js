"use client"

import { formatDuration, timeAgo } from "../../lib/format.js"
import { SourceHistoryDates, SourceHistorySnapshot } from "./SourceHistoryTime.js"
import { SourceContractDetails } from "./SourceContractDetails.js"
import { RainfallReadiness } from "./RainfallReadiness.js"
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

export function SourcesView({ sources, stats, trace = null }) {
  if (!sources || sources.length === 0) {
    return (
      <div className="card full">
        <h2>Saved source runs</h2>
        <p className="source-history-note">No saved runs are available. Current source availability is unverified.</p>
      </div>
    )
  }
  return (
    <div className="card full">
      <div className="section-head">
        <div>
          <h2>Saved source runs</h2>
          <p className="source-history-note">
            Past collection results, not a live source check. Current availability is unverified.
            A successful run does not establish current data or event coverage.
          </p>
          <SourceHistorySnapshot asOf={stats?.as_of} />
          {trace?.counts && (
            <p className="source-history-note" data-testid="selection-trace">
              Coverage to selection (retained only; not recall):{" "}
              {Object.entries(trace.counts).map(([key, n]) => `${key.replaceAll("_", " ")} ${n}`).join(" · ")}
              {trace.not_fetched_sources?.length ? `. Not fetched last run: ${trace.not_fetched_sources.join(", ")}` : ""}
            </p>
          )}
          {trace?.source_gaps?.length > 0 && (
            <ul className="source-history-note" data-testid="source-gaps" aria-label="Source gaps in the latest run">
              {trace.source_gaps.map(gap => (
                <li key={gap.source} data-gap-state={gap.state}>
                  <strong>{gap.source}</strong>: {gap.reason}{gap.detail ? ` — ${gap.detail}` : ""}. Next: {gap.next_action}
                </li>
              ))}
            </ul>
          )}
          <p className="source-history-note">
            Up to {stats?.runs_analyzed ?? 0} retained runs per source; dates describe collection, not measurement.
            {stats?.unhealthy_count > 0 && (
              <span style={{ color: "#f87171", marginLeft: 8 }}>
                {stats.unhealthy_count} recorded unhealthy
              </span>
            )}
            {stats?.degraded_count > 0 && (
              <span style={{ color: "#fbbf24", marginLeft: 8 }}>
                {stats.degraded_count} recorded degraded
              </span>
            )}
            {stats?.external_count > 0 && (
              <span style={{ color: "#fb923c", marginLeft: 8 }}>
                {stats.external_count} recorded external issues
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="source-health-table" style={{ marginTop: 16 }}>
        <div className="source-row source-header">
          <span>Source</span>
          <span>Recorded status</span>
          <span>Recorded success</span>
          <span>Observed</span>
          <span>Drafted</span>
          <span>Latency</span>
          <span>Recorded timing</span>
        </div>
        {sources.map((s) => (
          <div key={s.source} className="source-row">
            <span className="source-name" data-label="Source">{s.source}</span>
            <span data-label="Recorded status" className={`badge source-${s.health === "healthy" || s.health === "idle" ? "recorded" : s.health}`}>
              recorded {s.health}
              {s.served_via && (
                <span style={{ marginLeft: 6, fontWeight: 400, opacity: 0.85 }}>
                  · served via {s.served_via}
                </span>
              )}
            </span>
            <span className="source-rate" data-label="Recorded success">
              {s.success_rate != null ? `${Math.round(s.success_rate * 100)}%` : "—"}
              <span style={{ color: "#555", marginLeft: 8, fontSize: 11 }}>
                ({s.successes}/{s.active ?? s.runs}
                {s.skipped ? `, ${s.skipped} skipped` : ""})
              </span>
            </span>
            <span className="source-num" data-label="Observed">{s.total_observed}</span>
            <span className="source-num" data-label="Drafted">{s.total_drafted}</span>
            <span className="source-num" data-label="Latency">{s.avg_duration_ms != null ? formatDuration(s.avg_duration_ms) : "—"}</span>
            <div className="source-time"><SourceHistoryDates timing={s.history_time} /></div>
            <SourceContractDetails contract={s.source_contract} />
            {s.outcome && s.outcome.state !== "unknown" && (
              <div className="source-outcome" data-outcome={s.outcome.state}>
                <strong>{s.outcome.label}</strong>{s.outcome.detail ? ` — ${s.outcome.detail}` : ""}. Next: {s.outcome.next_action}
                {s.coverage_row?.universe?.checked != null && (
                  <span> Checked {s.coverage_row.universe.usable ?? "unknown"} of {s.coverage_row.universe.checked} {s.coverage_row.universe.label}; not global recall.</span>
                )}
              </div>
            )}
            {Array.isArray(s.incidents) && s.incidents.some(row => row.state !== "qualified") && (
              <ul className="source-incidents" aria-label={`${s.source} product incidents`}>
                {s.incidents.filter(row => row.state !== "qualified").map(row => (
                  <li key={row.key} data-incident-state={row.state}>
                    <strong>{row.product_id}</strong> ({row.region}, {row.window}): {row.label}
                    {row.text ? ` — ${row.text}` : ""}
                    {row.first_failure ? ` First retained failure ${timeAgo(row.first_failure)}; ${row.failures} failed attempt(s).` : ""}
                    {row.recovered_at ? ` Recovered ${timeAgo(row.recovered_at)} by a qualified result.` : ""}
                  </li>
                ))}
              </ul>
            )}
            <RainfallReadiness source={s.source} readiness={s.rainfall_readiness} />
            {s.access_health && (
              <div className="source-outcome" data-access-stage={s.access_health.stage} data-testid={`${s.source}-access-health`}>
                <strong>Access and last good data</strong> — {s.access_health.public_text}
                {s.access_health.backoff ? ` ${s.access_health.backoff.consecutive_refusals} consecutive refusal(s); no request inside the backoff.` : ""}
                {" "}An empty or model-served feed is not current coverage.
              </div>
            )}
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
