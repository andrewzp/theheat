"use client"

import { useEffect, useState, useCallback } from "react"
import { AutomationStatusStrip } from "./components/AutomationStrip.js"
import { RunStatus, SourceStatusBadge } from "./components/Badge.js"
import { formatDuration, hot10IsStale, hot10StaleDays, timeAgo, todayTweetCount } from "../lib/format.js"
import "./dashboard.css"

function formatUtcStamp(dateStr) {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return ""
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mm = String(d.getUTCMinutes()).padStart(2, "0")
  return `${hh}:${mm} UTC`
}

function draftOutcomeLabel(draft) {
  if (draft?.status === "posted") return "posted"
  if (draft?.status === "approved") return "approved"
  if (draft?.status === "rejected") return "rejected"
  if (draft?.auto_approve_at) return "auto-queued"
  return draft?.status || "pending"
}

function draftOutcomeTone(draft) {
  if (draft?.status === "posted") return "success"
  if (draft?.status === "approved") return "running"
  if (draft?.status === "rejected") return "failure"
  return "neutral"
}

function clipText(text, max = 96) {
  if (!text || text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

function countdownText(dateStr) {
  if (!dateStr) return ""
  const diff = new Date(dateStr).getTime() - Date.now()
  if (diff <= 0) return "due now"
  const mins = Math.ceil(diff / 60000)
  if (mins < 60) return `auto in ${mins}m`
  const hrs = Math.floor(mins / 60)
  const rem = mins % 60
  return `auto in ${hrs}h ${rem}m`
}

function delayLabel(minutes) {
  if (!minutes) return "manual"
  if (minutes < 60) return `${minutes}m`
  const hrs = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem ? `${hrs}h ${rem}m` : `${hrs}h`
}

function policySummary(draft) {
  const policy = draft?.approval_policy
  if (!policy) return "policy pending"
  if (policy.mode === "manual_only") return "review only"
  if (draft?.auto_approve_at) return countdownText(draft.auto_approve_at)
  if (policy.recommended_delay_minutes) return `auto ${delayLabel(policy.recommended_delay_minutes)}`
  return "manual review"
}

function findDraftRun(draft, botRuns) {
  const runId = draft?.review_context?.run_id
  if (!runId) return null
  return (botRuns || []).find((run) => run.id === runId) || null
}

function findDraftSourceRun(draft, botRuns) {
  const run = findDraftRun(draft, botRuns)
  if (!run) return null
  const sourceKey = draft?.review_context?.source_key
  if (!sourceKey) return null
  return (run.sources || []).find((s) => s.source === sourceKey) || null
}

function ScoreMeter({ label, value, inverse = false }) {
  const safeValue = Number.isFinite(value) ? value : 0
  const fillValue = inverse ? Math.max(8, 100 - safeValue) : safeValue
  return (
    <div className="score-meter">
      <div className="score-meter-head">
        <span>{label}</span>
        <span>{safeValue}</span>
      </div>
      <div className="score-meter-track">
        <div className={`score-meter-fill ${inverse ? "inverse" : ""}`} style={{ width: `${fillValue}%` }} />
      </div>
    </div>
  )
}

function WorkbenchView({
  drafts,
  selectedDraftId,
  setSelectedDraftId,
  editingId,
  setEditingId,
  editText,
  setEditText,
  draftAct,
  draftAction,
  draftFeedback,
  botRuns,
}) {
  const selectedDraft = drafts.find((d) => d.id === selectedDraftId) || drafts[0] || null
  const selectedDraftRun = findDraftRun(selectedDraft, botRuns)
  const selectedDraftSourceRun = findDraftSourceRun(selectedDraft, botRuns)
  const selectedCandidate =
    selectedDraft?.candidates?.find((c) => c.text === selectedDraft?.text) ||
    selectedDraft?.candidates?.[0]

  return (
    <div className="card full desk-panel">
      <div className="section-head">
        <div>
          <h2>Draft Workbench</h2>
          <p className="card-kicker">
            Review the queue with source facts, score context, alternate copy, and approval policy in one place.
          </p>
        </div>
        <span className="backend-pill">{drafts.length} pending drafts</span>
      </div>

      {drafts.length > 0 ? (
        <div className="draft-desk">
          <div className="draft-queue">
            {drafts.map((draft) => (
              <button
                key={draft.id}
                type="button"
                className={`queue-item ${selectedDraft?.id === draft.id ? "selected" : ""}`}
                onClick={() => {
                  setSelectedDraftId(draft.id)
                  setEditingId(null)
                  setEditText("")
                }}
              >
                <div className="queue-item-head">
                  <span className="draft-type">{draft.type}</span>
                  <span className="queue-score">
                    S {draft.score?.total ?? "—"} · C {draft.candidate_score?.total ?? "—"}
                  </span>
                </div>
                <div className="queue-text">{clipText(draft.text, 118)}</div>
                <div className="queue-meta">
                  <span>{timeAgo(draft.created_at)}</span>
                  <span>{policySummary(draft)}</span>
                </div>
              </button>
            ))}
          </div>

          <div className="draft-workbench">
            {selectedDraft && (
              <>
                <div className="draft-meta">
                  <span className="draft-type">{selectedDraft.type}</span>
                  <span className="draft-time">
                    {selectedDraft.review_context?.source || "draft queue"}
                    {" · "}
                    {timeAgo(selectedDraft.created_at)}
                  </span>
                </div>

                <div className="draft-status-row">
                  <span className="workbench-pill">
                    signal {selectedDraft.score?.total ?? "—"}
                    {selectedDraft.score?.label ? ` · ${selectedDraft.score.label}` : ""}
                  </span>
                  <span className="workbench-pill">
                    copy {selectedDraft.candidate_score?.total ?? "—"}
                    {selectedCandidate?.source ? ` · ${selectedCandidate.source}` : ""}
                  </span>
                  {selectedDraft.auto_approve_at ? (
                    <span className="workbench-pill alert">{countdownText(selectedDraft.auto_approve_at)}</span>
                  ) : selectedDraft.approval_policy?.mode === "manual_only" ? (
                    <span className="workbench-pill">manual only</span>
                  ) : (
                    <span className="workbench-pill">
                      {selectedDraft.approval_policy?.recommended_delay_minutes
                        ? `recommended ${delayLabel(selectedDraft.approval_policy.recommended_delay_minutes)}`
                        : "manual approval"}
                    </span>
                  )}
                  {selectedDraft.review_context?.run_mode && (
                    <span className="workbench-pill">{selectedDraft.review_context.run_mode}</span>
                  )}
                </div>

                {editingId === selectedDraft.id ? (
                  <>
                    <textarea
                      className="draft-edit-area"
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      rows={4}
                    />
                    <div className={`draft-chars ${editText.length > 280 ? "over" : ""}`}>
                      {editText.length}/280
                    </div>
                  </>
                ) : (
                  <>
                    <div className="draft-text">{selectedDraft.text}</div>
                    <div className="draft-chars">{selectedDraft.text.length}/280</div>
                  </>
                )}

                {(selectedDraft.score?.reasons?.length > 0 ||
                  selectedDraft.candidate_score?.reasons?.length > 0) && (
                  <div className="draft-reason-block">
                    {selectedDraft.score?.reasons?.length > 0 && (
                      <div className="draft-reason-line">
                        <strong>Signal:</strong> {selectedDraft.score.reasons.join(" · ")}
                      </div>
                    )}
                    {selectedDraft.candidate_score?.reasons?.length > 0 && (
                      <div className="draft-reason-line">
                        <strong>Copy:</strong> {selectedDraft.candidate_score.reasons.join(" · ")}
                      </div>
                    )}
                  </div>
                )}

                {selectedDraft.review_context?.shadow_two_bot?.text && (
                  <div className="shadow-two-bot">
                    <div className="shadow-label">SHADOW (TWO-BOT)</div>
                    <div className="shadow-text">{selectedDraft.review_context.shadow_two_bot.text}</div>
                    <div className="shadow-meta">
                      <span>{selectedDraft.review_context.shadow_two_bot.text.length}/280</span>
                      {selectedDraft.review_context.shadow_two_bot.angle_chosen && (
                        <span>angle: {selectedDraft.review_context.shadow_two_bot.angle_chosen}</span>
                      )}
                      {selectedDraft.review_context.shadow_two_bot.writer_model && (
                        <span>writer: {selectedDraft.review_context.shadow_two_bot.writer_model}</span>
                      )}
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() =>
                          navigator.clipboard?.writeText(selectedDraft.review_context.shadow_two_bot.text)
                        }
                      >
                        copy
                      </button>
                    </div>
                  </div>
                )}

                <div className="workbench-grid">
                  <div className="workbench-panel">
                    <h3>Why This Exists</h3>
                    <div className="workbench-headline">
                      {selectedDraft.review_context?.headline || "Pending draft awaiting review"}
                    </div>
                    {selectedDraft.review_context?.facts?.length > 0 ? (
                      <div className="fact-list">
                        {selectedDraft.review_context.facts.map((fact) => (
                          <div key={`${selectedDraft.id}-${fact.label}`} className="fact-row">
                            <span className="fact-label">{fact.label}</span>
                            <span className="fact-value">{fact.value}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty">no structured source facts saved</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Signal Score</h3>
                    {selectedDraft.score ? (
                      <>
                        <ScoreMeter label="severity" value={selectedDraft.score.severity} />
                        <ScoreMeter label="novelty" value={selectedDraft.score.novelty} />
                        <ScoreMeter label="timeliness" value={selectedDraft.score.timeliness} />
                        <ScoreMeter label="confidence" value={selectedDraft.score.confidence} />
                        <ScoreMeter label="shareability" value={selectedDraft.score.shareability} />
                        <ScoreMeter label="sensitivity" value={selectedDraft.score.sensitivity} inverse />
                      </>
                    ) : (
                      <div className="empty">no signal score available</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Copy Score</h3>
                    {selectedDraft.candidate_score ? (
                      <>
                        <ScoreMeter label="clarity" value={selectedDraft.candidate_score.clarity} />
                        <ScoreMeter label="context" value={selectedDraft.candidate_score.context} />
                        <ScoreMeter label="voice" value={selectedDraft.candidate_score.voice} />
                        <ScoreMeter label="punch" value={selectedDraft.candidate_score.punch} />
                      </>
                    ) : (
                      <div className="empty">single-candidate draft</div>
                    )}
                  </div>

                  <div className="workbench-panel">
                    <h3>Approval Policy</h3>
                    <div className="workbench-headline">
                      {selectedDraft.approval_policy?.mode === "armed_auto"
                        ? "Policy armed this draft automatically."
                        : selectedDraft.approval_policy?.mode === "suggested_auto"
                        ? "Policy recommends a timed auto-approval."
                        : "Policy requires explicit human approval."}
                    </div>
                    <div className="fact-list">
                      <div className="fact-row">
                        <span className="fact-label">Policy key</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.key || "—"}</span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Mode</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.mode || "—"}</span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Recommended window</span>
                        <span className="fact-value">
                          {selectedDraft.approval_policy?.recommended_delay_minutes
                            ? delayLabel(selectedDraft.approval_policy.recommended_delay_minutes)
                            : "manual only"}
                        </span>
                      </div>
                      <div className="fact-row">
                        <span className="fact-label">Why</span>
                        <span className="fact-value">{selectedDraft.approval_policy?.reason || "—"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="workbench-panel">
                    <h3>Run Trace</h3>
                    <div className="run-trace">
                      <div className="trace-line">
                        <span>workflow run</span>
                        <strong>{selectedDraftRun?.id || selectedDraft.review_context?.run_id || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>source slot</span>
                        <strong>{selectedDraft.review_context?.source_key || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>source status</span>
                        <strong>{selectedDraftSourceRun?.status || "—"}</strong>
                      </div>
                      <div className="trace-line">
                        <span>observed / promoted</span>
                        <strong>
                          {selectedDraftSourceRun
                            ? `${selectedDraftSourceRun.observed} / ${selectedDraftSourceRun.promoted}`
                            : "—"}
                        </strong>
                      </div>
                      <div className="trace-line">
                        <span>source duration</span>
                        <strong>
                          {selectedDraftSourceRun ? formatDuration(selectedDraftSourceRun.duration_ms) : "—"}
                        </strong>
                      </div>
                      <div className="trace-line">
                        <span>event id</span>
                        <strong>{selectedDraft.event_id || "manual"}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {selectedDraft.candidates?.length > 1 && (
                  <div className="candidate-list">
                    {selectedDraft.candidates
                      .filter((c) => c.text !== selectedDraft.text)
                      .slice(0, 3)
                      .map((c) => (
                        <div key={`${selectedDraft.id}-${c.rank}`} className="candidate-item">
                          <div className="candidate-head">
                            <span>
                              alt #{c.rank} · copy {c.score?.total || 0} · {c.source}
                            </span>
                            <button
                              type="button"
                              className="btn sm"
                              disabled={!!draftAction}
                              onClick={() =>
                                draftAct(selectedDraft.id, "select_candidate", { candidateRank: c.rank })
                              }
                            >
                              Use This
                            </button>
                          </div>
                          <div className="candidate-text">{c.text}</div>
                          {c.score?.reasons?.length > 0 && (
                            <div className="candidate-meta">{c.score.reasons.join(" · ")}</div>
                          )}
                        </div>
                      ))}
                  </div>
                )}

                <div className="draft-actions">
                  {editingId === selectedDraft.id ? (
                    <>
                      <button
                        type="button"
                        className="btn approve sm"
                        disabled={draftAction === selectedDraft.id || editText.length > 280}
                        onClick={() => draftAct(selectedDraft.id, "edit", { editedText: editText })}
                      >
                        Save
                      </button>
                      <button type="button" className="btn sm" onClick={() => setEditingId(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn approve sm"
                        disabled={!!draftAction}
                        onClick={() => draftAct(selectedDraft.id, "approve")}
                      >
                        {draftAction === selectedDraft.id ? "..." : "Approve + Post"}
                      </button>
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => {
                          setEditingId(selectedDraft.id)
                          setEditText(selectedDraft.text)
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn reject sm"
                        disabled={!!draftAction}
                        onClick={() => draftAct(selectedDraft.id, "reject")}
                      >
                        Reject
                      </button>
                      {selectedDraft.auto_approve_at ? (
                        <button
                          type="button"
                          className="btn sm"
                          disabled={!!draftAction}
                          onClick={() => draftAct(selectedDraft.id, "cancel_auto_approve")}
                        >
                          Cancel {countdownText(selectedDraft.auto_approve_at)}
                        </button>
                      ) : selectedDraft.approval_policy?.can_auto_approve === false ? (
                        <button type="button" className="btn sm" disabled>
                          Review Only
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn sm"
                          disabled={!!draftAction}
                          onClick={() =>
                            draftAct(selectedDraft.id, "auto_approve", {
                              delayMinutes: selectedDraft.approval_policy?.recommended_delay_minutes,
                            })
                          }
                        >
                          Auto {delayLabel(selectedDraft.approval_policy?.recommended_delay_minutes || 30)}
                        </button>
                      )}
                    </>
                  )}
                </div>
                {draftFeedback && (
                  <div className={`draft-feedback ${draftFeedback.type}`} role="alert">
                    {draftFeedback.text}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="draft-empty">
          No drafts waiting. Trigger a run on the Pipeline tab or compose one manually.
        </div>
      )}
    </div>
  )
}

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

function PipelineView({ run, runs, config, drafts, trigger, triggering, triggerResult }) {
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

function SourcesView({ sources, stats }) {
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
            <span className={`badge source-${s.health}`}>{s.health}</span>
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
            {s.last_error && (
              <div
                className="source-error"
                style={{
                  gridColumn: "1 / -1",
                  color: "#f87171",
                  fontSize: 11,
                  marginTop: 4,
                  paddingLeft: 12,
                }}
              >
                last error ({s.last_error_at ? timeAgo(s.last_error_at) : "—"}): {s.last_error}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SuppressedView({ suppressions, stats, sourceFilter, setSourceFilter, stageFilter, setStageFilter }) {
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

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(null)
  const [triggerResult, setTriggerResult] = useState(null)

  // Drafts
  const [drafts, setDrafts] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState("")
  const [draftAction, setDraftAction] = useState(null)
  const [selectedDraftId, setSelectedDraftId] = useState(null)
  const [draftFeedback, setDraftFeedback] = useState(null)

  // Compose
  const [composePrompt, setComposePrompt] = useState("")
  const [composeTweet, setComposeTweet] = useState("")
  const [generating, setGenerating] = useState(false)
  const [posting, setPosting] = useState(false)
  const [composeStatus, setComposeStatus] = useState(null)

  // Suppressed signals
  const [suppressions, setSuppressions] = useState([])
  const [suppressionsStats, setSuppressionsStats] = useState(null)
  const [suppressionsSourceFilter, setSuppressionsSourceFilter] = useState("")
  const [suppressionsStageFilter, setSuppressionsStageFilter] = useState("")

  const [sources, setSources] = useState([])
  const [sourcesStats, setSourcesStats] = useState(null)

  // Model config
  const [modelConfig, setModelConfig] = useState(null)

  // Tabs
  const [activeTab, setActiveTab] = useState("dashboard")

  // Refresh state for the refresh button + auto-refresh interval.
  //   refreshing: true while a fetch is in-flight (drives "refreshing…" label
  //     and disabled state on the button — prior version showed no feedback at
  //     all so users couldn't tell the click did anything).
  //   lastUpdated: timestamp of the most recent successful fetchData run.
  //   refreshError: surfaces the last network/parse failure to the operator
  //     (prior version swallowed errors into console.error only).
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [refreshError, setRefreshError] = useState(null)

  // Automation status strip — separate from dashboard data so a dashboard
  // fetch failure doesn't suppress automation refresh, and vice versa.
  const [automation, setAutomation] = useState(null)
  const [automationError, setAutomationError] = useState(null)

  const fetchData = useCallback(async () => {
    setRefreshing(true)
    setRefreshError(null)
    try {
      const dashboardUrl = suppressionsSourceFilter
        ? `/api/dashboard?limit=50&source=${encodeURIComponent(suppressionsSourceFilter)}`
        : "/api/dashboard?limit=50"
      const dashboardRes = await fetch(dashboardUrl)
      if (!dashboardRes.ok) {
        throw new Error(`dashboard refresh failed: ${dashboardRes.status}`)
      }
      const payload = await dashboardRes.json()
      setData({
        state: payload.state,
        stateBackend: payload.stateBackend,
        stateError: payload.stateError,
        runs: payload.runs || [],
        runsError: payload.runsError,
      })
      setDrafts(payload.drafts?.drafts || [])
      setSuppressions(payload.suppressions?.suppressions || [])
      setSuppressionsStats(payload.suppressions?.stats || null)
      setModelConfig(payload.config || null)
      setSources(payload.sourceHealth?.sources || [])
      setSourcesStats(payload.sourceHealth?.stats || null)
      setLastUpdated(new Date().toISOString())
    } catch (e) {
      console.error(e)
      setRefreshError(e?.message || String(e))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }

    // Automation status — independent of dashboard fetch. A failure here is
    // non-fatal and must NOT suppress the dashboard state set above. Sits
    // outside the dashboard try/catch by design (Codex flagged the nested
    // version as the cause of automation going stale during dashboard outages).
    try {
      const automationRes = await fetch("/api/automation")
      if (automationRes.ok) {
        const automationPayload = await automationRes.json()
        setAutomation(automationPayload)
        setAutomationError(null)
      } else {
        setAutomationError(`/api/automation ${automationRes.status}`)
      }
    } catch (err) {
      setAutomationError(err?.message || String(err))
    }
  }, [suppressionsSourceFilter])

  useEffect(() => {
    fetchData()
    const refreshIfVisible = () => {
      if (document.visibilityState === "hidden") return
      fetchData()
    }
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") fetchData()
    }
    const interval = setInterval(refreshIfVisible, 30000)
    document.addEventListener("visibilitychange", handleVisibilityChange)
    return () => {
      clearInterval(interval)
      document.removeEventListener("visibilitychange", handleVisibilityChange)
    }
  }, [fetchData])

  async function trigger(mode) {
    setTriggering(mode)
    setTriggerResult(null)
    try {
      const res = await fetch("/api/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      })
      const result = await res.json()
      setTriggerResult(result.ok ? `Triggered ${mode}` : `Error: ${result.error}`)
      setTimeout(fetchData, 5000)
    } catch (e) {
      setTriggerResult(`Error: ${e.message}`)
    } finally {
      setTriggering(null)
    }
  }

  async function draftAct(draftId, action, payload = {}) {
    // Backward-compat: if a string is passed (legacy 'edit' callers), treat as editedText
    if (typeof payload === "string") payload = { editedText: payload }
    setDraftAction(draftId)
    setDraftFeedback(null)
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, draftId, ...payload }),
      })
      const result = await res.json()
      if (!res.ok || result.ok === false) {
        setDraftFeedback({ type: "error", text: result.error || "Draft action failed" })
        return
      }
      setEditingId(null)
      setEditText("")
      setDraftFeedback({
        type: "success",
        text: result.action ? `${result.action.replaceAll("_", " ")}.` : "Draft updated.",
      })
      await fetchData()
    } catch (e) {
      console.error(e)
      setDraftFeedback({ type: "error", text: e.message })
    } finally {
      setDraftAction(null)
    }
  }

  async function generateTweet() {
    setGenerating(true)
    setComposeStatus(null)
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: composePrompt }),
      })
      const result = await res.json()
      if (result.tweet) {
        setComposeTweet(result.tweet)
      } else {
        setComposeStatus(`Error: ${result.error}`)
      }
    } catch (e) {
      setComposeStatus(`Error: ${e.message}`)
    } finally {
      setGenerating(false)
    }
  }

  async function postComposed() {
    if (!composeTweet.trim()) return
    setPosting(true)
    setComposeStatus(null)
    try {
      const res = await fetch("/api/post", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tweet: composeTweet.trim() }),
      })
      const result = await res.json()
      if (result.ok) {
        setComposeStatus("Sent to post queue")
        setComposeTweet("")
        setComposePrompt("")
        setTimeout(fetchData, 5000)
      } else {
        setComposeStatus(`Error: ${result.error}`)
      }
    } catch (e) {
      setComposeStatus(`Error: ${e.message}`)
    } finally {
      setPosting(false)
    }
  }

  const state = data?.state
  const stateError = data?.stateError
  const runs = data?.runs || []
  const hot10 = state?.last_hot10 || {}
  const streaks = state?.streaks || {}
  const errors = state?.errors || []
  const nowIso = new Date().toISOString()
  const todayCount = todayTweetCount(state?.daily_tweet_count, nowIso)
  const hot10Stale = hot10IsStale(hot10.date, nowIso)
  const hot10StaleAgeDays = hot10StaleDays(hot10.date, nowIso)

  const sortedStreaks = Object.entries(streaks)
    .sort((a, b) => b[1].consecutive_days - a[1].consecutive_days)
    .slice(0, 10)

  // Latest internal bot run for Source Health / Funnel / Timeline.
  // Prefer the most recent `alerts` mode run because it sweeps every data
  // source; `auto_publish_due` is a single-source bookkeeping run that
  // would otherwise hide the rest of the pipeline. Fall back to any
  // multi-source run, then to whatever's most recent.
  const runHistory = state?.run_history || []
  const latestRichRun =
    runHistory.find((r) => r.mode === "alerts" && (r.sources || []).length > 0) ||
    runHistory.find((r) => (r.sources || []).length > 1) ||
    runHistory.find((r) => (r.sources || []).length > 0) ||
    runHistory[0] ||
    null
  const newestRunStartedAt = runHistory.reduce((newest, run) => {
    const startedAt = run?.started_at
    if (!startedAt) return newest
    if (!newest) return startedAt
    return new Date(startedAt).getTime() > new Date(newest).getTime() ? startedAt : newest
  }, null)

  return (
    <>

      <AutomationStatusStrip status={automation} error={automationError} />

      <div className="dash">
        <header>
          <h1
            role="button"
            tabIndex={0}
            title="Back to dashboard"
            aria-label="@theheat control panel — back to dashboard"
            onClick={() => {
              setActiveTab("dashboard")
              window.scrollTo({ top: 0, behavior: "smooth" })
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                setActiveTab("dashboard")
                window.scrollTo({ top: 0, behavior: "smooth" })
              }
            }}
          >
            @theheat <span>control panel</span>
          </h1>
          <div className="refresh-group">
            {refreshError && (
              <span className="refresh-error" title={refreshError}>
                refresh failed
              </span>
            )}
            {lastUpdated && !refreshError && (
              <span className="refresh-meta">
                updated {timeAgo(lastUpdated)}
                {newestRunStartedAt ? ` / data: ${timeAgo(newestRunStartedAt)}` : ""}
              </span>
            )}
            <button
              className={`refresh-btn${refreshing ? " is-refreshing" : ""}`}
              onClick={fetchData}
              disabled={refreshing}
            >
              {refreshing ? "refreshing…" : "refresh"}
            </button>
          </div>
        </header>

        <div className="tabs">
          <button
            className={`tab ${activeTab === "dashboard" ? "active" : ""}`}
            onClick={() => setActiveTab("dashboard")}
          >
            Dashboard
          </button>
          <button
            className={`tab ${activeTab === "pipeline" ? "active" : ""}`}
            onClick={() => setActiveTab("pipeline")}
          >
            Pipeline
            {latestRichRun?.failure_count > 0 ? (
              <span className="tab-count alert">{latestRichRun.failure_count}</span>
            ) : null}
          </button>
          <button
            className={`tab ${activeTab === "workbench" ? "active" : ""}`}
            onClick={() => setActiveTab("workbench")}
          >
            Workbench
            {drafts.length > 0 ? <span className="tab-count">{drafts.length}</span> : null}
          </button>
          <button
            className={`tab ${activeTab === "suppressed" ? "active" : ""}`}
            onClick={() => setActiveTab("suppressed")}
          >
            Suppressed
            {suppressionsStats?.last24h ? (
              <span className="tab-count">{suppressionsStats.last24h}</span>
            ) : null}
          </button>
          <button
            className={`tab ${activeTab === "sources" ? "active" : ""}`}
            onClick={() => setActiveTab("sources")}
          >
            Sources
            {sourcesStats?.unhealthy_count > 0 ? (
              <span className="tab-count alert">{sourcesStats.unhealthy_count}</span>
            ) : sourcesStats?.degraded_count > 0 ? (
              <span className="tab-count">{sourcesStats.degraded_count}</span>
            ) : null}
          </button>
          <a className="tab" href="/health">
            Health
            {sourcesStats?.unhealthy_count > 0 ? (
              <span className="tab-count alert">{sourcesStats.unhealthy_count}</span>
            ) : sourcesStats?.degraded_count > 0 ? (
              <span className="tab-count">{sourcesStats.degraded_count}</span>
            ) : null}
          </a>
        </div>

        {stateError && (
          <div className="state-error-banner" role="alert">
            state read failed: {stateError}
          </div>
        )}

        {loading ? (
          <div className="loading">loading...</div>
        ) : activeTab === "suppressed" ? (
          <SuppressedView
            suppressions={suppressions}
            stats={suppressionsStats}
            sourceFilter={suppressionsSourceFilter}
            setSourceFilter={setSuppressionsSourceFilter}
            stageFilter={suppressionsStageFilter}
            setStageFilter={setSuppressionsStageFilter}
          />
        ) : activeTab === "sources" ? (
          <SourcesView sources={sources} stats={sourcesStats} />
        ) : activeTab === "pipeline" ? (
          <PipelineView
            run={latestRichRun}
            runs={runHistory}
            config={modelConfig}
            drafts={drafts}
            trigger={trigger}
            triggering={triggering}
            triggerResult={triggerResult}
          />
        ) : activeTab === "workbench" ? (
          <WorkbenchView
            drafts={drafts}
            selectedDraftId={selectedDraftId}
            setSelectedDraftId={setSelectedDraftId}
            editingId={editingId}
            setEditingId={setEditingId}
            editText={editText}
            setEditText={setEditText}
            draftAct={draftAct}
            draftAction={draftAction}
            draftFeedback={draftFeedback}
            botRuns={runHistory}
          />
        ) : (
          <>
            {/* DRAFTS — primary view */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Drafts to Review ({drafts.length})</h2>
              {drafts.length > 0 ? (
                drafts.map((d) => (
                  <div key={d.id} className={`draft-item ${editingId === d.id ? "highlight" : ""}`}>
                    <div className="draft-meta">
                      <span className="draft-type">{d.type}</span>
                      <span className="draft-time">{timeAgo(d.created_at)}</span>
                    </div>

                    {editingId === d.id ? (
                      <>
                        <textarea
                          className="draft-edit-area"
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          rows={3}
                        />
                        <div className={`draft-chars ${editText.length > 280 ? "over" : ""}`}>
                          {editText.length}/280
                        </div>
                        <div className="draft-actions">
                          <button
                            className="btn approve sm"
                            disabled={draftAction === d.id || editText.length > 280}
                            onClick={() => draftAct(d.id, "edit", editText)}
                          >
                            Save
                          </button>
                          <button className="btn sm" onClick={() => setEditingId(null)}>
                            Cancel
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="draft-text">{d.text}</div>
                        <div className="draft-chars">{d.text.length}/280</div>
                        <div className="draft-actions">
                          <button
                            className="btn approve sm"
                            disabled={!!draftAction}
                            onClick={() => draftAct(d.id, "approve")}
                          >
                            {draftAction === d.id ? "..." : "Approve + Post"}
                          </button>
                          <button
                            className="btn sm"
                            onClick={() => { setEditingId(d.id); setEditText(d.text) }}
                          >
                            Edit
                          </button>
                          <button
                            className="btn reject sm"
                            disabled={!!draftAction}
                            onClick={() => draftAct(d.id, "reject")}
                          >
                            Reject
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))
              ) : (
                <div className="draft-empty">
                  No drafts waiting. Trigger a run below or compose one manually.
                </div>
              )}
            </div>

            {/* Generate Drafts */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Generate Drafts</h2>
              <div className="trigger-bar">
                <button
                  className="btn primary"
                  disabled={!!triggering}
                  onClick={() => trigger("both")}
                >
                  {triggering === "both" ? "..." : "Run Both"}
                </button>
                <button className="btn" disabled={!!triggering} onClick={() => trigger("alerts")}>
                  {triggering === "alerts" ? "..." : "Alerts Only"}
                </button>
                <button className="btn" disabled={!!triggering} onClick={() => trigger("leaderboard")}>
                  {triggering === "leaderboard" ? "..." : "Leaderboard Only"}
                </button>
                {triggerResult && <span className="trigger-result">{triggerResult}</span>}
              </div>
            </div>

            {/* Compose */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Compose Tweet</h2>
              <div className="compose">
                <textarea
                  className="compose-input"
                  placeholder="Describe the data (e.g. 'Phoenix hit 122F today, old record 121F from 2024')..."
                  value={composePrompt}
                  onChange={(e) => setComposePrompt(e.target.value)}
                  rows={2}
                />
                <button className="btn" disabled={generating || !composePrompt.trim()} onClick={generateTweet}>
                  {generating ? "generating..." : "Generate Preview"}
                </button>
                {composeTweet && (
                  <div className="preview-box">
                    <div className="preview-label">
                      PREVIEW
                      <span className={`char-count ${composeTweet.length > 280 ? "over" : ""}`}>
                        {composeTweet.length}/280
                      </span>
                    </div>
                    <textarea
                      className="preview-tweet"
                      value={composeTweet}
                      onChange={(e) => setComposeTweet(e.target.value)}
                      rows={3}
                    />
                    <div className="preview-actions">
                      <button
                        className="btn approve"
                        disabled={posting || !composeTweet.trim() || composeTweet.length > 280}
                        onClick={postComposed}
                      >
                        {posting ? "..." : "Approve + Post"}
                      </button>
                      <button className="btn" disabled={generating} onClick={generateTweet}>
                        Regenerate
                      </button>
                      <button className="btn" onClick={() => { setComposeTweet(""); setComposeStatus(null) }}>
                        Discard
                      </button>
                    </div>
                  </div>
                )}
                {composeStatus && <div className="compose-status">{composeStatus}</div>}
              </div>
            </div>

            {/* Stats */}
            <div className="grid">
              <div className="card">
                <h2>Tweets Today</h2>
                <div className="stat">{todayCount}</div>
                <div className="stat-label">of 10 daily cap</div>
              </div>
              <div className="card">
                <h2>Last Hot 10</h2>
                <div className="stat stat-with-chip">
                  <span>{hot10.date || "—"}</span>
                  {hot10Stale && (
                    <span className="badge running hot10-stale-chip">(stale {hot10StaleAgeDays}d)</span>
                  )}
                </div>
                <div className="stat-label">
                  {hot10.date ? timeAgo(hot10.date + "T12:00:00Z") : "no data yet"}
                </div>
              </div>
            </div>

            <div className="grid">
              <div className="card">
                <h2>Hot 10 Leaderboard</h2>
                {hot10.cities?.length > 0 ? (
                  <ul className="hot10-list">
                    {hot10.cities.map((city, i) => (
                      <li key={city}>
                        <span className="rank">{i + 1}.</span>
                        <span className="city">{city}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="empty">no leaderboard data yet</div>
                )}
              </div>
              <div className="card">
                <h2>Streaks</h2>
                {sortedStreaks.length > 0 ? (
                  <div className="streak-list">
                    {sortedStreaks.map(([city, s]) => (
                      <span className="streak-chip" key={city}>
                        {city} <span className="days">{s.consecutive_days}d</span>
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="empty">no active streaks</div>
                )}
              </div>
            </div>

            {/* Recent GitHub Workflow Runs (cron sanity check) */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Recent Runs</h2>
              {runs.length > 0 ? (
                <table className="runs-table">
                  <thead>
                    <tr><th>Status</th><th>Trigger</th><th>When</th><th>Link</th></tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id}>
                        <td><RunStatus conclusion={r.conclusion} status={r.status} /></td>
                        <td>{r.event === "schedule" ? "cron" : r.event}</td>
                        <td>{timeAgo(r.created_at)}</td>
                        <td><a href={r.html_url} target="_blank" rel="noopener">logs</a></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="empty">no runs yet</div>
              )}
            </div>

            {/* Errors */}
            <div className="card full">
              <h2>Recent Errors</h2>
              {errors.length > 0 ? (
                <ul className="error-list">
                  {errors.slice(-10).reverse().map((e, i) => (
                    <li key={i}>
                      <span className="error-source">{e.source}</span>
                      <span className="error-ts">{timeAgo(e.ts)}</span>
                      <span className="error-msg">{e.msg}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty">no errors. suspicious.</div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  )
}
