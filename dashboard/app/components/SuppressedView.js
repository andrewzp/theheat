"use client"

import { timeAgo } from "../../lib/format.js"

export function SuppressedView({ suppressions, stats, sourceFilter, setSourceFilter, stageFilter, setStageFilter }) {
  const sourceCounts = stats?.source_counts || {}
  const sourceEntries = Object.entries(sourceCounts).sort((a, b) => b[1] - a[1])
  const stageCounts = stats?.stage_counts || {}
  const stageEntries = Object.entries(stageCounts).sort((a, b) => b[1] - a[1])

  // Client-side stage filter applied on top of the server-side source filter.
  const visible = stageFilter
    ? suppressions.filter((s) => (s.stage || "unknown") === stageFilter)
    : suppressions

  return (
    <>
      <div className="grid">
        <div className="card">
          <h2>Last 24h</h2>
          <div className="stat">{stats?.last24h ?? 0}</div>
          <div className="stat-label">pipeline kills</div>
        </div>
        <div className="card">
          <h2>Last 7 Days</h2>
          <div className="stat">{stats?.last7d ?? 0}</div>
          <div className="stat-label">cumulative</div>
        </div>
      </div>

      <div className="grid">
        <div className="card">
          <h2>Top Source</h2>
          <div className="stat" style={{ fontSize: 20 }}>{stats?.top_source || "—"}</div>
          <div className="stat-label">most-suppressed loop</div>
        </div>
        <div className="card">
          <h2>Top Stage</h2>
          <div className="stat" style={{ fontSize: 20 }}>{stats?.top_stage || "—"}</div>
          <div className="stat-label">kill stage with most hits</div>
        </div>
      </div>

      {stageEntries.length > 0 && (
        <div className="card full" style={{ marginBottom: 16 }}>
          <h2>Filter by Stage</h2>
          <div className="streak-list">
            <span
              className={`streak-chip clickable ${!stageFilter ? "selected" : ""}`}
              onClick={() => setStageFilter("")}
            >
              all stages
            </span>
            {stageEntries.map(([stage, count]) => (
              <span
                key={stage}
                className={`streak-chip clickable supp-stage-chip ${stageFilter === stage ? "selected" : ""}`}
                onClick={() => setStageFilter(stageFilter === stage ? "" : stage)}
              >
                {stage} <span className="days">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {sourceEntries.length > 0 && (
        <div className="card full" style={{ marginBottom: 16 }}>
          <h2>Filter by Source</h2>
          <div className="streak-list">
            <span
              className={`streak-chip clickable ${!sourceFilter ? "selected" : ""}`}
              onClick={() => setSourceFilter("")}
            >
              all sources
            </span>
            {sourceEntries.map(([src, count]) => (
              <span
                key={src}
                className={`streak-chip clickable ${sourceFilter === src ? "selected" : ""}`}
                onClick={() => setSourceFilter(sourceFilter === src ? "" : src)}
              >
                {src} <span className="days">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="card full">
        <h2>Suppressed Signals ({visible.length})</h2>
        <p className="card-kicker">
          Signals killed at any pipeline stage — score gate, writer, fact-check, cooldown, dedup, cycle cap,
          or pipeline error. Stage pill (primary) shows where in the pipeline the kill happened; tight score
          gaps (0–5 below threshold) suggest the bar may be slightly high.
        </p>
        {visible.length > 0 ? (
          visible.map((s) => {
            const total = Number(s.score_total ?? 0)
            const threshold = Number(s.threshold ?? 0)
            const gap = threshold - total
            const tone = gap <= 5 ? "tight" : gap <= 15 ? "near" : "far"
            const stage = s.stage || "unknown"
            return (
              <div key={s.id} className="supp-item">
                <div className="supp-meta">
                  <span className="supp-time">{timeAgo(s.ts)}</span>
                  <span className={`supp-stage supp-stage--${stage.replace(/_/g, "-")}`}>{stage}</span>
                  <span className="draft-type">{s.source || "—"}</span>
                  {threshold > 0 && (
                    <span className={`supp-score ${tone}`}>
                      {total}/{threshold} <span className="supp-gap">−{gap}</span>
                    </span>
                  )}
                  {s.category && <span className="supp-cat">{s.category}</span>}
                </div>
                <div className="supp-summary">
                  {s.summary || s.event_id || "(no summary)"}
                </div>
                {Array.isArray(s.reasons) && s.reasons.length > 0 && (
                  <div className="supp-reasons">
                    {s.reasons.map((r, i) => (
                      <span key={`${s.id}-r-${i}`} className="supp-reason">{r}</span>
                    ))}
                  </div>
                )}
              </div>
            )
          })
        ) : (
          <div className="draft-empty">
            No suppressions logged yet. Once the bot runs with this build deployed, near-miss signals
            will appear here.
          </div>
        )}
      </div>
    </>
  )
}
