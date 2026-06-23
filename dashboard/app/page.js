"use client"

import { useEffect, useState, useCallback } from "react"
import { AutomationStatusStrip } from "./components/AutomationStrip.js"
import { CredentialsCard } from "./components/CredentialsCard.js"
import { DraftWorkbench } from "./components/DraftWorkbench.js"
import { Hot10Card, Hot10Leaderboard } from "./components/Hot10Card.js"
import { PipelineView } from "./components/PipelineView.js"
import { RunsTable } from "./components/RunsTable.js"
import { SourcesView } from "./components/SourcesView.js"
import { SourceHealthContent } from "./health/page.js"
import { SuppressedView } from "./components/SuppressedView.js"
import { hot10IsStale, hot10StaleDays, timeAgo, todayTweetCount } from "../lib/format.js"
import "./dashboard.css"

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
  const stateBackend = data?.stateBackend
  const stateError = data?.stateError
  const runs = data?.runs || []
  const hot10 = state?.last_hot10 || {}
  const streaks = state?.streaks || {}
  const errors = state?.errors || []
  const credentialExpiry = state?.credential_expiry || {}
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
            {stateBackend && <span className="backend-pill">state: {stateBackend}</span>}
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
          <button
            className={`tab ${activeTab === "health" ? "active" : ""}`}
            onClick={() => setActiveTab("health")}
          >
            Health
            {sourcesStats?.unhealthy_count > 0 ? (
              <span className="tab-count alert">{sourcesStats.unhealthy_count}</span>
            ) : sourcesStats?.degraded_count > 0 ? (
              <span className="tab-count">{sourcesStats.degraded_count}</span>
            ) : null}
          </button>
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
        ) : activeTab === "health" ? (
          <SourceHealthContent embedded sources={sources} stats={sourcesStats} />
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
          <DraftWorkbench
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
              <Hot10Card hot10={hot10} hot10Stale={hot10Stale} hot10StaleAgeDays={hot10StaleAgeDays} />
              <CredentialsCard credentialExpiry={credentialExpiry} nowMs={Date.now()} />
            </div>

            <div className="grid">
              <Hot10Leaderboard hot10={hot10} />
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
            <RunsTable runs={runs} />

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
