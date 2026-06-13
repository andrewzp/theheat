"use client"

import { useState } from "react"
import { formatDuration, timeAgo } from "../../lib/format.js"
import { SourceStatusBadge } from "./Badge.js"
import { clipText, draftOutcomeLabel, draftOutcomeTone, formatUtcStamp } from "./shared.js"

function PipelineHero() {
  return (
    <div className="card full hero-card" style={{ marginBottom: 16 }}>
      <div className="hero-eyebrow">Live Ops</div>
      <h1 className="hero-headline">Operational truth, not workflow vibes.</h1>
      <p className="hero-sub">
        Source health, funnel quality, queue state, and publishing outcomes — measured in signal
        quality, not just cron completion.
      </p>
    </div>
  )
}

function RichSourceRow({ source }) {
  const [expanded, setExpanded] = useState(false)
  const details = source.details
  const hasFunnel = details?.pipeline_metrics &&
    Object.values(details.pipeline_metrics).some((v) => typeof v === "number" && v > 0)
  const hasEvents = Array.isArray(details?.events) && details.events.length > 0
  const expandable = hasFunnel || hasEvents
  return (
    <div className="source-row">
      <div className="source-head">
        <strong>{source.source}</strong>
        <SourceStatusBadge status={source.status} />
        {expandable && (
          <button
            type="button"
            className="expand-btn"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? "▼ hide" : "▶ details"}
          </button>
        )}
      </div>
      <div className="source-meta">
        <span>{source.observed ?? 0} observed</span>
        <span>{source.promoted ?? 0} promoted</span>
        <span className={source.drafted > 0 ? "drafted-num" : ""}>{source.drafted ?? 0} drafted</span>
        <span>{formatDuration(source.duration_ms)} latency</span>
      </div>
      {source.note && <div className="source-note">{source.note}</div>}
      {source.error && <div className="source-error">{source.error}</div>}
      {expandable && expanded && (
        <div className="source-detail">
          {hasFunnel && <SourceFunnelInline metrics={details.pipeline_metrics} provider={details.provider} />}
          {hasEvents && <EventsTableInline events={details.events} />}
        </div>
      )}
    </div>
  )
}

function SourceFunnelInline({ metrics, provider }) {
  const stages = [
    { key: "stations_active", label: "Stations active" },
    { key: "stations_with_obs", label: "Stations with fresh obs" },
    { key: "stations_checked", label: "Stations checked" },
    { key: "raw_signals", label: "Raw signals fired" },
    { key: "bundles_after_dedup", label: "Bundles (post-dedup)" },
    { key: "country_records", label: "Country records" },
    { key: "drafted", label: "Drafted" },
  ]
  const present = stages.filter((s) => typeof metrics[s.key] === "number")
  const max = Math.max(...present.map((s) => metrics[s.key] || 0), 1)
  if (present.length === 0) return null
  return (
    <div className="inline-funnel">
      <div className="inline-funnel-title">{provider ? `${provider} funnel` : "pipeline funnel"}</div>
      {present.map((s) => {
        const value = metrics[s.key] || 0
        const pct = (value / max) * 100
        return (
          <div className="inline-funnel-row" key={s.key}>
            <span className="inline-funnel-label">{s.label}</span>
            <div className="inline-funnel-track">
              <div className="inline-funnel-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="inline-funnel-val">{value.toLocaleString()}</span>
          </div>
        )
      })}
    </div>
  )
}

function EventsTableInline({ events }) {
  const visible = events.slice(0, 12)
  return (
    <div className="inline-events">
      <div className="inline-events-title">
        Events evaluated ({events.length}{events.length > 12 ? " — top 12 shown" : ""})
      </div>
      {visible.map((ev, i) => {
        const decTone = ev.decision === "drafted" ? "success" : ev.decision === "rejected" ? "failure" : "neutral"
        return (
          <div className="inline-event-row" key={ev.event_id || `${ev.station_id}-${i}`}>
            <span className={`badge ${decTone}`}>{(ev.decision || "—").replace(/_/g, " ")}</span>
            <span className="inline-event-station">
              <strong>{ev.station_name || ev.city || "—"}</strong>
              {ev.station_id ? <span className="inline-event-id"> ({ev.station_id})</span> : null}
            </span>
            <span className="inline-event-meta">
              {[ev.country, ev.signal_date, ev.type ? ev.type.replace(/_/g, " ") : null, typeof ev.score === "number" ? `score ${ev.score}` : null].filter(Boolean).join(" · ")}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function FunnelStagesCard({ run, drafts }) {
  const sources = run?.sources || []
  const totalObserved = sources.reduce((sum, s) => sum + (s.observed || 0), 0)
  const totalPromoted = sources.reduce((sum, s) => sum + (s.promoted || 0), 0)
  const candidatesCount = (drafts || []).reduce((sum, d) => sum + (d.candidates?.length || 1), 0)
  const queueLen = (drafts || []).length
  const stages = [
    { label: "Observations ingested", value: totalObserved, desc: "raw payloads normalized into canonical facts", tone: "success" },
    { label: "Events created", value: totalPromoted, desc: "duplicates clustered and low-confidence items suppressed", tone: "success" },
    { label: "Draft candidates generated", value: candidatesCount, desc: "3-5 variants per high-scoring event when available", tone: "success" },
    { label: "Queue-ready drafts", value: queueLen, desc: "best candidates that survived quality gates and policy rules", tone: queueLen > 0 ? "running" : "neutral" },
  ]
  return (
    <div className="card full">
      <h2>Funnel</h2>
      {stages.map((s) => (
        <div className="source-row" key={s.label}>
          <div className="source-head">
            <strong>{s.label}</strong>
            <span className={`badge ${s.tone}`}>{s.value.toLocaleString()}</span>
          </div>
          <div className="source-meta">
            <span>{s.desc}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function SourceHealthRichCard({ run }) {
  const sources = run?.sources || []
  return (
    <div className="card full">
      <h2>Source Health</h2>
      {sources.length > 0 ? (
        sources.map((s, i) => <RichSourceRow key={`${s.source}-${i}`} source={s} />)
      ) : (
        <div className="empty">No source telemetry yet.</div>
      )}
    </div>
  )
}

function RunTimelineRichCard({ run, drafts }) {
  if (!run) return null
  const sources = run.sources || []
  const autoQueued = (drafts || []).filter((d) => !!d.auto_approve_at).length
  const manualOnly = (drafts || []).filter((d) => d.approval_policy?.can_auto_approve === false).length
  const sourceTone = (status) => (status === "success" ? "success" : status === "failed" ? "failure" : "running")
  const rows = [
    {
      key: `${run.id}-start`,
      time: run.started_at,
      tone: run.failure_count ? "failure" : "success",
      label: "run started",
      text: `${run.mode || "run"} created ${run.id} and opened ${sources.length || run.source_count || 0} source slots.`,
    },
    ...sources
      .filter((s) => s.observed || s.promoted || s.drafted || s.note || s.error)
      .slice(0, 4)
      .map((s) => ({
        key: `${run.id}-${s.source}`,
        time: run.ended_at || run.started_at,
        tone: sourceTone(s.status),
        label: s.source,
        text: s.error
          ? `${s.source} failed after ${formatDuration(s.duration_ms)}. ${s.error}`
          : `${s.observed ?? 0} observations, ${s.promoted ?? 0} promoted, ${s.drafted ?? 0} drafts in ${formatDuration(s.duration_ms)}.`,
      })),
    {
      key: `${run.id}-queue`,
      time: run.ended_at || run.started_at,
      tone: autoQueued ? "running" : "success",
      label: "queue updated",
      text: `${(drafts || []).length} drafts are waiting. ${autoQueued} timed auto-approvals and ${manualOnly} manual-only reviews remain in the queue.`,
    },
  ]
  return (
    <div className="card full">
      <h2>Run Timeline</h2>
      {rows.length > 0 ? (
        rows.map((entry) => (
          <div className="timeline-row" key={entry.key}>
            <div className="timeline-head">
              <strong>{formatUtcStamp(entry.time)}</strong>
              <span className={`badge ${entry.tone}`}>{entry.label}</span>
            </div>
            <p className="timeline-text">{entry.text}</p>
          </div>
        ))
      ) : (
        <div className="empty">No run timeline yet.</div>
      )}
    </div>
  )
}

function PublishingOutcomesCard({ drafts }) {
  const recent = [...(drafts || [])]
    .sort(
      (a, b) =>
        new Date(b.updated_at || b.posted_at || b.created_at || 0) -
        new Date(a.updated_at || a.posted_at || a.created_at || 0)
    )
    .slice(0, 5)
  return (
    <div className="card full">
      <h2>Recent Publishing Outcomes</h2>
      {recent.length > 0 ? (
        recent.map((d) => (
          <div className="outcome-row" key={`outcome-${d.id}`}>
            <div className="outcome-head">
              <strong>{`${d.type || "draft"} / ${draftOutcomeLabel(d)}`}</strong>
              <span className={`badge ${draftOutcomeTone(d)}`}>{draftOutcomeLabel(d)}</span>
            </div>
            <div className="outcome-meta">
              <span>{clipText(d.text, 80)}</span>
              <span className="outcome-time">{timeAgo(d.updated_at || d.posted_at || d.created_at)}</span>
              {d.post_error && <span className="outcome-err">{d.post_error}</span>}
            </div>
          </div>
        ))
      ) : (
        <div className="empty">No publishing outcomes yet.</div>
      )}
    </div>
  )
}

function CommandDeckCard({ trigger, triggering, triggerResult }) {
  return (
    <div className="card full">
      <h2>Command Deck</h2>
      <p className="card-kicker">
        Trigger the pipeline, watch the queue, and keep manual intervention close without leaving the run view.
      </p>
      <div className="trigger-bar">
        <button className="btn primary" disabled={!!triggering} onClick={() => trigger("both")}>
          {triggering === "both" ? "Running..." : "Run Both"}
        </button>
        <button className="btn" disabled={!!triggering} onClick={() => trigger("alerts")}>
          {triggering === "alerts" ? "Running..." : "Alerts Only"}
        </button>
        <button className="btn" disabled={!!triggering} onClick={() => trigger("leaderboard")}>
          {triggering === "leaderboard" ? "Running..." : "Leaderboard Only"}
        </button>
      </div>
      {triggerResult && (
        <div className={`status-banner ${triggerResult.startsWith("Error") ? "error" : "success"}`}>
          {triggerResult}
        </div>
      )}
    </div>
  )
}

function ModelConfigCard({ config }) {
  if (!config) return null
  const rows = [
    { label: "writer", value: config.writer_model },
    { label: "fact-check", value: config.fact_check_model },
    { label: "claim-extract", value: config.claim_extract_model },
    { label: "voice-gen", value: config.voice_gen_model },
    { label: "evaluator", value: config.evaluator_enabled ? "enabled" : "disabled" },
    { label: "shadow A/B", value: config.shadow_ab_enabled ? "enabled" : "disabled" },
  ]
  return (
    <div className="card full" style={{ marginBottom: 16 }}>
      <h2>Model Config</h2>
      <div className="model-grid">
        {rows.map((r) => (
          <div className="model-row" key={r.label}>
            <span>{r.label}</span>
            <strong>{r.value}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

function RunSummaryStats({ run, drafts }) {
  if (!run) return null
  const sources = run.sources || []
  const succeeded = sources.filter((s) => s.status === "success").length
  const skipped = sources.filter((s) => s.status === "skipped").length
  // Skipped lanes are intentionally idle (Mondays-only, Fridays-only,
  // 1st-of-month, "already ran today" caps). They are not failures.
  const healthy = succeeded + skipped
  const total = sources.length || 1
  const totalObserved = sources.reduce((sum, s) => sum + (s.observed || 0), 0)
  const totalPromoted = sources.reduce((sum, s) => sum + (s.promoted || 0), 0)
  const failures = run.failure_count ?? sources.filter((s) => s.status === "failed").length
  const pendingDrafts = (drafts || []).length
  return (
    <div className="grid stats-grid">
      <div className="card">
        <h2>Current Run</h2>
        <div className="stat">{Math.round((healthy / total) * 100)}%</div>
        <div className="stat-label">
          {healthy} of {sources.length} sources healthy
          {skipped > 0 ? ` · ${skipped} scheduled idle` : ""}
        </div>
      </div>
      <div className="card">
        <h2>Signals</h2>
        <div className="stat">{totalObserved.toLocaleString()}</div>
        <div className="stat-label">{totalPromoted.toLocaleString()} promoted, {run.drafted_count ?? 0} drafted</div>
      </div>
      <div className="card">
        <h2>Failures</h2>
        <div className={`stat ${failures > 0 ? "alert" : ""}`}>{failures}</div>
        <div className="stat-label">{failures > 0 ? "source failure" : "no source failures"}</div>
      </div>
      <div className="card">
        <h2>Queue</h2>
        <div className="stat">{pendingDrafts}</div>
        <div className="stat-label">drafts waiting for review</div>
      </div>
    </div>
  )
}

export function PipelineView({ run, runs, config, drafts, trigger, triggering, triggerResult }) {
  return (
    <>
      <PipelineHero />
      <RunSummaryStats run={run} drafts={drafts} />
      <div className="grid">
        <SourceHealthRichCard run={run} />
        <FunnelStagesCard run={run} drafts={drafts} />
      </div>
      <RunTimelineRichCard run={run} drafts={drafts} />
      <div className="grid">
        <PublishingOutcomesCard drafts={drafts} />
        <CommandDeckCard trigger={trigger} triggering={triggering} triggerResult={triggerResult} />
      </div>
      <ModelConfigCard config={config} />
    </>
  )
}
