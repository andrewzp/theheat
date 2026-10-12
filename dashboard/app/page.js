"use client"
import SourcedGeneration from "./components/SourcedGeneration.js"

import { useEffect, useState, useCallback, useRef } from "react"
import { AutomationStatusStrip } from "./components/AutomationStrip.js"
import { CredentialsCard } from "./components/CredentialsCard.js"
import { DraftWorkbench } from "./components/DraftWorkbench.js"
import { Hot10Card, Hot10Leaderboard } from "./components/Hot10Card.js"
import { PipelineView } from "./components/PipelineView.js"
import { RunsTable } from "./components/RunsTable.js"
import { SourcesView } from "./components/SourcesView.js"
import { SourceHealthContent } from "./health/page.js"
import { ProductHealthPanel } from "./components/ProductHealthPanel.js"
import { CostPanel } from "./components/CostPanel.js"
import { COST_SCENARIO } from "../lib/usage-cost-contract.js"
import { SuppressedView } from "./components/SuppressedView.js"
import { hot10IsStale, hot10StaleDays, timeAgo, todayTweetCount } from "../lib/format.js"
import { draftReviewControls, draftTextLength, revisionKey } from "../lib/draft-review-ui.js"
import { createDraftCommand, createCandidateCommand } from "../lib/draft-command-request.js"
import { recoveryKey, saveCommandReference, readCommandReference, clearCommandReference, withCommandReference, abandonmentBody } from "../lib/local-command-recovery.js"
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
  const [editingRevision, setEditingRevision] = useState(null)
  const [draftAction, setDraftAction] = useState(null)
  const [selectedDraftId, setSelectedDraftId] = useState(null)
  const [draftFeedback, setDraftFeedback] = useState(null)
  const [pendingCommand, setPendingCommand] = useState(null)
  const pendingCommandRef = useRef(null)
  const recoveredScope = useRef(null)
  const recoveryScope = useRef(null)
  const previewSeen = useRef(false)

  // Compose

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
      const dashboardRes = await fetch(`${dashboardUrl}&cost_scenario=${encodeURIComponent(COST_SCENARIO.scenario)}`)
      const payload = await dashboardRes.json()
      if (payload.local_preview === true) previewSeen.current = true
      if (!dashboardRes.ok) {
        throw new Error(payload.error || `dashboard refresh failed: ${dashboardRes.status}`)
      }
      previewSeen.current = payload.local_preview === true
      setData({
        state: payload.state,
        candidates: payload.candidates || [],
        operator_role: payload.operator_role,
        operator_subject: payload.operator_subject,
        local_preview: payload.local_preview === true,
        stateBackend: payload.stateBackend,
        stateError: payload.stateError,
        runs: payload.runs || [],
        runsError: payload.runsError,
        productHealth: payload.productHealth,
        costEvidence: payload.costEvidence,
        deployment: payload.deployment,
      })
      // Show the review queue in time order (newest first) — the API returns
      // drafts in insertion order, which reads as jumbled. created_at is ISO 8601,
      // so a string compare is chronological.
      setDrafts(
        [...(payload.drafts?.drafts || [])].sort((a, b) =>
          (b.created_at || "").localeCompare(a.created_at || "")
        )
      )
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

    if (previewSeen.current) {
      setAutomation(null)
      setAutomationError("Local preview: collection and publication are unavailable.")
      return
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

  useEffect(() => {
    const key = data?.local_preview ? recoveryKey(window.location.origin, data.operator_subject) : null
    recoveryScope.current = key
    if (!key || recoveredScope.current === key) return
    recoveredScope.current = key
    const saved = readCommandReference(window.sessionStorage, key)
    pendingCommandRef.current = saved
    setPendingCommand(saved)
    setDraftAction(saved?.draftId || null)
    if (!saved) return
    const control = new AbortController()
    fetch(`/api/drafts?commandId=${encodeURIComponent(saved.command.command_id)}`, { cache:"no-store", signal:control.signal })
      .then(async response => {
        const value = await response.json()
        if (!response.ok) throw new Error("The previous action is unresolved. Check its result before creating another action.")
        if (control.signal.aborted || recoveryScope.current !== key || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
        const command = value.recoverable_command
        if (command?.command_id === saved.command.command_id && command.payload && command.targets) {
          const recovered = await withCommandReference({ ...saved, command })
          if (control.signal.aborted || recoveryScope.current !== key || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
          saveCommandReference(window.sessionStorage, key, recovered)
          pendingCommandRef.current = recovered
          setPendingCommand(recovered)
        }
        setDraftFeedback({ type:"pending", draftId:saved.draftId, text:"Recovered the previous local action. Check its result; no action was repeated." })
      }).catch(error => {
        if (!control.signal.aborted && recoveryScope.current === key && pendingCommandRef.current?.command.command_id === saved.command.command_id)
          setDraftFeedback({ type:"error", draftId:saved.draftId, text:error.message })
      })
    return () => control.abort()
  }, [data?.local_preview, data?.operator_subject])

  async function trigger(mode) {
    if (data?.local_preview) { setTriggerResult("Collection is unavailable in local preview."); return }
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

  async function submitLocalCommand(saved) {
    if (!saved.command.payload) return checkLocalCommand()
    if (pendingCommandRef.current && pendingCommandRef.current.command.command_id !== saved.command.command_id) return
    pendingCommandRef.current = saved
    setPendingCommand(saved)
    setDraftAction(saved.draftId)
    const scope = recoveryScope.current
    let sent = false
    try {
      saved = await withCommandReference(saved)
      if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
      if (!saveCommandReference(window.sessionStorage, scope, saved)) throw new Error("Cannot retain the action reference in this browser; submission was not sent")
      pendingCommandRef.current = saved
      setPendingCommand(saved)
      sent = true
      const response = await fetch("/api/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(saved.command) })
      const result = await response.json()
      if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
      if (!response.ok) {
        throw new Error(result.error || "Local authority unavailable")
      }
      setDraftFeedback({ type: "pending", draftId: saved.draftId, text: "Accepted and waiting for the local consumer. Your edit is preserved." })
    } catch (error) {
      if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
      if (!sent) {
        pendingCommandRef.current = null
        setPendingCommand(null); setDraftAction(null)
        clearCommandReference(window.sessionStorage, scope)
      }
      setDraftFeedback({ type: "error", draftId: saved.draftId, text: `${error.message}. Check the result or retry the same action. Your edit is preserved.` })
    }
  }

  async function checkLocalCommand(abandon = false) {
    const saved = pendingCommandRef.current
    if (!saved) return
    const scope = recoveryScope.current
    try {
      const body = abandon === true ? abandonmentBody(saved) : null
      if (abandon === true && !body) throw new Error("This legacy reference has no fingerprint. Inspect its retained result before closing it")
      const response = body ? await fetch(`/api/local-command-recovery?commandId=${encodeURIComponent(saved.command.command_id)}`, {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) })
        : await fetch(`/api/drafts?commandId=${encodeURIComponent(saved.command.command_id)}`, { cache: "no-store" })
      const payload = await response.json()
      if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
      if (!response.ok) throw new Error(payload.error || "Local authority unavailable")
      let reference = saved
      if (payload.recoverable_command?.command_id === saved.command.command_id) {
        const recovered = await withCommandReference({ ...saved, command:payload.recoverable_command })
        if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
        saveCommandReference(window.sessionStorage, recoveryScope.current, recovered)
        pendingCommandRef.current = recovered
        setPendingCommand(recovered)
        reference = recovered
      }
      if (payload.receipt?.command_id !== saved.command.command_id || !reference.request_sha256 ||
          payload.submission_reference?.request_sha256 !== reference.request_sha256 ||
          payload.submission_reference?.original_action !== reference.original_action) throw new Error("The result does not match this operator's submission reference")
      if (payload.status === "pending") {
        setDraftFeedback({ type: "pending", draftId: saved.draftId, text: "Still waiting for the local consumer. Your edit is preserved." })
        return
      }
      const result = payload.result
      if (!result || result.command_id !== saved.command.command_id || result.actor_subject !== data.operator_subject ||
          !["applied", "unchanged", "rejected"].includes(result.status)) throw new Error("Unrecognized command result")
      const abandoned = result.code === "submission_abandoned"
      const rejected = result.status === "rejected"
      setDraftFeedback({ type: rejected ? "error" : "success", draftId: saved.draftId,
        text: abandoned ? "The previous submission was never accepted and is now closed. Nothing was changed."
          : rejected ? `${result.message} Your edit is preserved.`
          : result.publish_intent_id ? "Approved locally. The intent is parked; nothing will be published."
          : saved.action === "review" ? "Human review recorded for this exact version."
          : saved.action === "edit" ? "Saved. Review this version against its sources before approval." : "Local command completed." })
      if (!rejected && result.candidate?.draft_id) setSelectedDraftId(result.candidate.draft_id)
      if (!rejected && !abandoned) { setEditingId(null); setEditText(""); setEditingRevision(null) }
      setPendingCommand(null)
      pendingCommandRef.current = null
      clearCommandReference(window.sessionStorage, recoveryScope.current)
      setDraftAction(null)
      await fetchData()
    } catch (error) {
      if (scope !== recoveryScope.current || pendingCommandRef.current?.command.command_id !== saved.command.command_id) return
      setDraftFeedback({ type: "error", draftId: saved.draftId, text: `${error.message}. The same action is retained for retry; your edit is preserved.` })
    }
  }

  async function draftAct(draftId, action, payload = {}) {
    // Backward-compat: if a string is passed (legacy 'edit' callers), treat as editedText
    if (typeof payload === "string") payload = { editedText: payload }
    const expectedRevision = payload.expectedRevision || (action === "edit"
      ? editingRevision
      : drafts.find((draft) => draft.id === draftId)?.revision_identity)
    if (data?.local_preview) {
      if (pendingCommand) return
      try {
        const draft = drafts.find((item) => item.id === draftId)
        const command = createDraftCommand(draft, action, { ...payload, expectedRevision })
        return await submitLocalCommand({ command, draftId, action })
      } catch (error) { setDraftFeedback({ type: "error", draftId, text: error.message }); return }
    }
    setDraftAction(draftId)
    setDraftFeedback(null)
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, draftId, ...payload, expectedRevision }),
      })
      const result = await res.json()
      if (!res.ok || result.ok === false) {
        setDraftFeedback({ type: "error", draftId, text: result.error || "Draft action failed" })
        if (res.status === 409 || action === "approve") await fetchData()
        return
      }
      setEditingId(null)
      setEditText("")
      setEditingRevision(null)
      setDraftFeedback({
        type: "success",
        draftId,
        text: action === "edit" || action === "select_candidate"
          ? (result.draft?.review_status === "passed" ? "Text unchanged; current review retained." : "Saved. Previous approval was cancelled. Review this version against its sources before posting.")
          : action === "review" ? "Human review recorded for this version. You can now approve it for posting."
          : result.action ? `${result.action.replaceAll("_", " ")}.` : "Draft updated.",
      })
      await fetchData()
    } catch (e) {
      console.error(e)
      setDraftFeedback({
        type: "error",
        draftId,
        text: `Unable to confirm whether this action completed.${editingId === draftId ? " Your edit is preserved." : ""} Check the refreshed draft before retrying.`,
      })
      await fetchData()
    } finally {
      setDraftAction(null)
    }
  }

  function startEditing(draft) {
    setEditingId(draft.id)
    setEditText(draft.text)
    setEditingRevision(draft.revision_identity)
    setDraftFeedback(null)
  }

  function acceptLatestEditRevision(draft) {
    if (draft.id === editingId && revisionKey(draft.revision_identity) !== revisionKey(editingRevision)) {
      setEditingRevision(draft.revision_identity)
      setDraftFeedback({ type: "success", draftId: draft.id, text: "Your edit is kept. Saving will replace the latest text shown above." })
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
        {data?.local_preview && (
          <div className="card full" role="status">
            <strong>Invented local preview</strong>
            <p>Use invented retained sources for explicit local draft generation. Approvals are parked. Production collection, drafting and publishing remain paused.</p>
            {pendingCommand && (
              <div className="draft-actions">
                <button className="btn sm" type="button" onClick={checkLocalCommand}>Check result</button>
                {pendingCommand.command.payload && <button className="btn sm" type="button" onClick={() => submitLocalCommand(pendingCommand)}>Retry same action</button>}
                {abandonmentBody(pendingCommand) ? <button className="btn sm" type="button" disabled={data.operator_role === "viewer"} onClick={() => checkLocalCommand(true)}>Resolve missing submission</button>
                  : !pendingCommand.command.payload && <p>Legacy reference: inspect its retained result before closing it. A missing fingerprint prevents safe closure.</p>}
                {draftFeedback && <p role="status">{draftFeedback.text}</p>}
              </div>
            )}
          </div>
        )}
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

        {!loading && ["dashboard", "health"].includes(activeTab) && (
          <>
          <ProductHealthPanel health={data?.productHealth} config={modelConfig} deployment={data?.deployment} stale={Boolean(refreshError)} />
          <CostPanel evidence={data?.costEvidence} stale={Boolean(refreshError)} loading={loading} />
          </>
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
          <SourceHealthContent embedded sources={sources} stats={sourcesStats} error={stateError || ""} />
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
            localCandidates={data?.candidates || []}
            localRole={data?.operator_role}
            candidateAct={(candidate, action) => submitLocalCommand({ command: createCandidateCommand(candidate, action), draftId: candidate.admission_input_id, action })}
            refreshCandidates={fetchData}
            selectedDraftId={selectedDraftId}
            setSelectedDraftId={setSelectedDraftId}
            editingId={editingId}
            setEditingId={setEditingId}
            editText={editText}
            setEditText={setEditText}
            editingRevision={editingRevision}
            startEditing={startEditing}
            acceptLatestEditRevision={acceptLatestEditRevision}
            draftAct={draftAct}
            draftAction={draftAction}
            draftFeedback={draftFeedback}
            pendingCommand={pendingCommand}
            submitLocalCommand={submitLocalCommand}
            checkLocalCommand={checkLocalCommand}
            retryLocalCommand={() => pendingCommand && submitLocalCommand(pendingCommand)}
            botRuns={runHistory}
          />
        ) : (
          <>
            {/* DRAFTS — primary view */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>{data?.local_preview ? "Local drafts" : "Drafts awaiting publication"} ({drafts.length})</h2>
              {drafts.length > 0 ? (
                drafts.map((d) => {
                  const controls = draftReviewControls(d)
                  return (
                    <div key={d.id} className="draft-item">
                      <div className="draft-meta">
                        <span className="draft-type">{d.type}</span>
                        <span className="draft-time">{timeAgo(d.created_at)}</span>
                        <span className="workbench-pill">
                          {d.publish_blocked ? "publication needs reconciliation" : d.status === "approved" ? (d.local_preview ? "local intent parked" : "awaiting publication") : controls.needsReview ? "review needed" : d.review_kind === "human" ? "human reviewed" : "model checks current"}
                        </span>
                      </div>
                      <div className="draft-text">{d.text}</div>
                      <div className="draft-chars">{draftTextLength(d.text)}/280</div>
                      <div className="draft-actions">
                        <button
                          type="button"
                          className="btn approve sm"
                          disabled={!!draftAction || !controls.canApprove || editingId === d.id}
                          onClick={() => draftAct(d.id, "approve")}
                        >
                          {draftAction === d.id ? "..." : d.local_preview ? "Approve locally" : "Approve + Post"}
                        </button>
                        <button
                          type="button"
                          className="btn sm"
                          onClick={() => {
                            setSelectedDraftId(d.id)
                            if (editingId !== d.id) {
                              setEditingId(null)
                              setEditText("")
                              setEditingRevision(null)
                            }
                            setActiveTab("workbench")
                          }}
                        >
                          Review / Edit
                        </button>
                        <button
                          type="button"
                          className="btn reject sm"
                          disabled={!!draftAction || !controls.canEdit}
                          onClick={() => draftAct(d.id, "reject")}
                        >
                          Reject
                        </button>
                      </div>
                      {draftFeedback?.draftId === d.id && (
                        <div className={`draft-feedback ${draftFeedback.type}`} role="alert">{draftFeedback.text}</div>
                      )}
                    </div>
                  )
                })
              ) : (
                <div className="draft-empty">
                  No drafts waiting. Trigger a run below or try a writing preview.
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

            <SourcedGeneration onRefresh={fetchData} readOnly={data?.operator_role === "viewer"} />

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
