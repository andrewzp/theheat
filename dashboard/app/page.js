"use client"

import { useEffect, useState, useCallback } from "react"

function timeAgo(dateStr) {
  if (!dateStr) return "never"
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function RunStatus({ conclusion, status }) {
  if (status === "in_progress") return <span className="badge running">RUNNING</span>
  if (status === "partial_failure") return <span className="badge neutral">PARTIAL</span>
  if (status === "skipped") return <span className="badge neutral">SKIPPED</span>
  if (conclusion === "success") return <span className="badge success">OK</span>
  if (conclusion === "failure") return <span className="badge failure">FAIL</span>
  if (status === "success") return <span className="badge success">OK</span>
  if (status === "failed") return <span className="badge failure">FAIL</span>
  return <span className="badge neutral">{conclusion || status}</span>
}

function formatDuration(ms) {
  if (!ms && ms !== 0) return "—"
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
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

function clipText(text, max = 96) {
  if (!text || text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
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

function findDraftRun(draft, botRuns) {
  const runId = draft?.review_context?.run_id
  if (!runId) return null
  return botRuns.find((run) => run.id === runId) || null
}

function findDraftSourceRun(draft, botRuns) {
  const run = findDraftRun(draft, botRuns)
  const sourceKey = draft?.review_context?.source_key
  if (!run || !sourceKey) return null
  return run.sources?.find((source) => source.source === sourceKey) || null
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

  // Compose
  const [composePrompt, setComposePrompt] = useState("")
  const [composeTweet, setComposeTweet] = useState("")
  const [generating, setGenerating] = useState(false)
  const [posting, setPosting] = useState(false)
  const [composeStatus, setComposeStatus] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const [stateRes, draftsRes] = await Promise.all([
        fetch("/api/state"),
        fetch("/api/drafts"),
      ])
      setData(await stateRes.json())
      const d = await draftsRes.json()
      setDrafts(d.drafts || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  useEffect(() => {
    if (!drafts.length) {
      setSelectedDraftId(null)
      return
    }
    if (!drafts.some((draft) => draft.id === selectedDraftId)) {
      setSelectedDraftId(drafts[0].id)
    }
  }, [drafts, selectedDraftId])

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
    setDraftAction(draftId)
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, draftId, ...payload }),
      })
      await res.json()
      setEditingId(null)
      setEditText("")
      await fetchData()
    } catch (e) {
      console.error(e)
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
  const runs = data?.runs || []
  const botRuns = state?.run_history || []
  const hot10 = state?.last_hot10 || {}
  const streaks = state?.streaks || {}
  const errors = state?.errors || []
  const latestCountDate = state?.daily_tweet_count
    ? Object.keys(state.daily_tweet_count).sort().at(-1)
    : null
  const todayCount = latestCountDate
    ? state.daily_tweet_count[latestCountDate] || 0
    : 0

  const sortedStreaks = Object.entries(streaks)
    .sort((a, b) => b[1].consecutive_days - a[1].consecutive_days)
    .slice(0, 10)
  const latestBotRun = botRuns[0]
  const latestSourceRuns = latestBotRun?.sources || []
  const failedSourceRuns = latestSourceRuns.filter((source) => source.status === "failed")
  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) || drafts[0] || null
  const selectedDraftRun = findDraftRun(selectedDraft, botRuns)
  const selectedDraftSourceRun = findDraftSourceRun(selectedDraft, botRuns)
  const selectedCandidate = selectedDraft?.candidates?.find((candidate) => candidate.text === selectedDraft?.text)
    || selectedDraft?.candidates?.[0]

  return (
    <>
      <style jsx global>{`
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          font-family: "SF Mono", "Fira Code", "Consolas", monospace;
          background: #0a0a0a;
          color: #e0e0e0;
          min-height: 100vh;
        }
        .dash { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
        header {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid #222;
        }
        h1 { font-size: 20px; font-weight: 600; color: #ff4d00; }
        h1 span { color: #666; font-weight: 400; font-size: 14px; margin-left: 8px; }
        .refresh-btn {
          background: none; border: 1px solid #333; color: #888;
          padding: 6px 12px; border-radius: 4px; cursor: pointer;
          font-family: inherit; font-size: 12px;
        }
        .refresh-btn:hover { border-color: #555; color: #ccc; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
        @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
        .card {
          background: #111; border: 1px solid #222; border-radius: 8px; padding: 16px;
        }
        .card h2 {
          font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
          color: #666; margin-bottom: 12px;
        }
        .card.full { grid-column: 1 / -1; }
        .stat { font-size: 28px; font-weight: 700; color: #ff4d00; }
        .stat-label { font-size: 12px; color: #666; margin-top: 4px; }

        /* Drafts */
        .draft-item {
          background: #0a0a0a; border: 1px solid #222; border-radius: 6px;
          padding: 14px; margin-bottom: 10px;
        }
        .draft-item.highlight { border-color: #ff4d00; }
        .draft-desk {
          display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 16px;
        }
        @media (max-width: 860px) {
          .draft-desk { grid-template-columns: 1fr; }
        }
        .draft-queue {
          display: grid; gap: 10px; align-content: start;
        }
        .queue-item {
          width: 100%; text-align: left; background: #0a0a0a; border: 1px solid #222;
          border-radius: 8px; padding: 12px; color: inherit; cursor: pointer;
        }
        .queue-item:hover { border-color: #3a3a3a; }
        .queue-item.selected {
          border-color: #ff4d00;
          box-shadow: 0 0 0 1px rgba(255, 77, 0, 0.18);
        }
        .queue-item-head {
          display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 8px;
        }
        .queue-score { color: #666; font-size: 10px; letter-spacing: 0.8px; text-transform: uppercase; }
        .queue-text {
          color: #ededed; font-size: 13px; line-height: 1.45; margin-bottom: 8px;
        }
        .queue-meta {
          display: flex; justify-content: space-between; gap: 8px; color: #555; font-size: 10px;
        }
        .draft-workbench {
          background: linear-gradient(180deg, rgba(26, 26, 26, 0.78), rgba(10, 10, 10, 0.88));
          border: 1px solid #242424; border-radius: 10px; padding: 16px;
        }
        .draft-meta {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 8px; font-size: 11px;
        }
        .draft-type {
          background: #1a1a1a; color: #888; padding: 2px 8px;
          border-radius: 3px; text-transform: uppercase; letter-spacing: 0.5px;
        }
        .draft-time { color: #444; }
        .draft-text { font-size: 15px; line-height: 1.5; color: #fff; margin-bottom: 10px; }
        .draft-chars { font-size: 11px; color: #666; margin-bottom: 10px; }
        .draft-chars.over { color: #f87171; }
        .draft-actions { display: flex; gap: 8px; }
        .draft-status-row {
          display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px;
        }
        .workbench-pill {
          display: inline-flex; align-items: center; gap: 6px;
          background: #141414; border: 1px solid #2a2a2a; border-radius: 999px;
          padding: 5px 10px; font-size: 10px; letter-spacing: 0.8px; text-transform: uppercase; color: #888;
        }
        .workbench-grid {
          display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 14px 0;
        }
        @media (max-width: 860px) {
          .workbench-grid { grid-template-columns: 1fr; }
        }
        .workbench-panel {
          background: #0c0c0c; border: 1px solid #1d1d1d; border-radius: 8px; padding: 12px;
        }
        .workbench-panel h3 {
          font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: #666; margin-bottom: 10px;
        }
        .workbench-headline {
          color: #fff; font-size: 14px; line-height: 1.4; margin-bottom: 10px;
        }
        .fact-list { display: grid; gap: 8px; }
        .fact-row {
          display: flex; justify-content: space-between; gap: 10px; padding-bottom: 6px; border-bottom: 1px solid #171717;
        }
        .fact-row:last-child { border-bottom: none; padding-bottom: 0; }
        .fact-label { color: #666; font-size: 11px; }
        .fact-value { color: #e3e3e3; font-size: 11px; text-align: right; }
        .draft-reason-block { display: grid; gap: 4px; margin-bottom: 10px; }
        .draft-reason-line { font-size: 11px; color: #666; }
        .draft-reason-line strong { color: #888; font-weight: 600; }
        .candidate-list {
          display: grid; gap: 8px; margin: 12px 0; padding-top: 12px; border-top: 1px solid #1a1a1a;
        }
        .candidate-item {
          background: #111; border: 1px solid #222; border-radius: 6px; padding: 10px;
        }
        .candidate-head {
          display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 6px;
          font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: 0.8px;
        }
        .candidate-text { color: #d8d8d8; font-size: 13px; line-height: 1.45; margin-bottom: 8px; }
        .candidate-meta { color: #555; font-size: 10px; }
        .score-meter { margin-bottom: 10px; }
        .score-meter:last-child { margin-bottom: 0; }
        .score-meter-head {
          display: flex; justify-content: space-between; gap: 8px; color: #777; font-size: 10px;
          text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 4px;
        }
        .score-meter-track {
          height: 6px; border-radius: 999px; background: #161616; overflow: hidden;
        }
        .score-meter-fill {
          height: 100%; border-radius: 999px; background: linear-gradient(90deg, #ff4d00, #ff8a3d);
        }
        .score-meter-fill.inverse {
          background: linear-gradient(90deg, #4ade80, #facc15);
        }
        .run-trace { display: grid; gap: 8px; }
        .trace-line {
          display: flex; justify-content: space-between; gap: 10px; color: #777; font-size: 11px;
        }
        .trace-line strong { color: #ddd; font-weight: 600; }
        .draft-edit-area {
          width: 100%; background: #111; border: 1px solid #333; border-radius: 4px;
          color: #fff; font-family: inherit; font-size: 14px; padding: 10px;
          resize: vertical; margin-bottom: 8px;
        }
        .draft-edit-area:focus { outline: none; border-color: #ff4d00; }
        .draft-empty { color: #333; font-size: 13px; font-style: italic; padding: 20px 0; }

        /* Buttons */
        .trigger-bar { display: flex; gap: 8px; align-items: center; }
        .btn {
          background: #1a1a1a; border: 1px solid #333; color: #e0e0e0;
          padding: 8px 16px; border-radius: 4px; cursor: pointer;
          font-family: inherit; font-size: 12px; font-weight: 600;
        }
        .btn:hover { border-color: #ff4d00; color: #ff4d00; }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .btn.primary { background: #ff4d00; border-color: #ff4d00; color: #000; }
        .btn.primary:hover { background: #ff6620; }
        .btn.approve { background: #0a2a0a; border-color: #4ade80; color: #4ade80; }
        .btn.approve:hover { background: #0f3a0f; }
        .btn.reject { background: #1a1010; border-color: #666; color: #888; }
        .btn.sm { padding: 5px 10px; font-size: 11px; }
        .trigger-result { font-size: 12px; color: #4ade80; }

        /* Compose */
        .compose { display: flex; flex-direction: column; gap: 10px; }
        .compose-input {
          background: #0a0a0a; border: 1px solid #333; border-radius: 4px;
          color: #e0e0e0; font-family: inherit; font-size: 13px; padding: 10px;
          resize: vertical;
        }
        .compose-input:focus { outline: none; border-color: #ff4d00; }
        .preview-box {
          background: #0a0a0a; border: 1px solid #ff4d00; border-radius: 6px; padding: 12px;
        }
        .preview-label {
          font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
          color: #ff4d00; margin-bottom: 8px; display: flex; justify-content: space-between;
        }
        .char-count { color: #4ade80; }
        .char-count.over { color: #f87171; }
        .preview-tweet {
          background: transparent; border: none; color: #fff; font-family: inherit;
          font-size: 15px; line-height: 1.5; width: 100%; resize: vertical;
          padding: 0; margin-bottom: 10px;
        }
        .preview-tweet:focus { outline: none; }
        .preview-actions { display: flex; gap: 8px; }
        .compose-status { font-size: 12px; color: #4ade80; }

        /* Tables / lists */
        .hot10-list { list-style: none; }
        .hot10-list li {
          display: flex; justify-content: space-between; padding: 4px 0;
          border-bottom: 1px solid #1a1a1a; font-size: 13px;
        }
        .hot10-list li:last-child { border-bottom: none; }
        .rank { color: #666; width: 24px; }
        .city { flex: 1; }
        .streak-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .streak-chip { background: #1a1a1a; padding: 4px 10px; border-radius: 4px; font-size: 12px; }
        .streak-chip .days { color: #ff4d00; font-weight: 600; }
        .runs-table { width: 100%; font-size: 12px; }
        .runs-table th { text-align: left; color: #444; font-weight: 400; padding: 4px 8px 8px 0; }
        .runs-table td { padding: 6px 8px 6px 0; border-top: 1px solid #1a1a1a; }
        .runs-table a { color: #888; text-decoration: none; }
        .runs-table a:hover { color: #ff4d00; }
        .badge {
          display: inline-block; padding: 2px 8px; border-radius: 3px;
          font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
        }
        .badge.success { background: #0a2a0a; color: #4ade80; }
        .badge.failure { background: #2a0a0a; color: #f87171; }
        .badge.running { background: #1a1a0a; color: #facc15; }
        .badge.neutral { background: #1a1a1a; color: #888; }
        .error-list { list-style: none; max-height: 200px; overflow-y: auto; }
        .error-list li { font-size: 12px; padding: 6px 0; border-bottom: 1px solid #1a1a1a; }
        .error-source { color: #f87171; font-weight: 600; }
        .error-ts { color: #444; margin-left: 8px; }
        .error-msg { color: #888; display: block; margin-top: 2px; }
        .run-summary {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;
        }
        @media (max-width: 720px) { .run-summary { grid-template-columns: 1fr 1fr; } }
        .run-stat {
          background: #0a0a0a; border: 1px solid #222; border-radius: 6px; padding: 12px;
        }
        .run-stat-label {
          color: #666; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;
        }
        .run-stat-value { color: #fff; font-size: 18px; font-weight: 700; }
        .source-run-list { display: grid; gap: 10px; }
        .source-run {
          background: #0a0a0a; border: 1px solid #222; border-radius: 6px; padding: 12px;
        }
        .source-run-head {
          display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px;
        }
        .source-run-name { color: #fff; font-size: 13px; text-transform: uppercase; letter-spacing: 0.8px; }
        .source-run-meta { display: flex; flex-wrap: wrap; gap: 10px; color: #666; font-size: 11px; }
        .source-run-error { color: #f87171; font-size: 11px; margin-top: 6px; }
        .source-run-note { color: #888; font-size: 11px; margin-top: 6px; }
        .empty { color: #333; font-size: 13px; font-style: italic; }
        .loading { text-align: center; color: #333; padding: 60px; font-size: 14px; }
      `}</style>

      <div className="dash">
        <header>
          <h1>@theheat <span>control panel</span></h1>
          <button className="refresh-btn" onClick={fetchData}>refresh</button>
        </header>

        {loading ? (
          <div className="loading">loading...</div>
        ) : (
          <>
            {/* DRAFTS — primary view */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Draft Workbench ({drafts.length})</h2>
              {drafts.length > 0 ? (
                <div className="draft-desk">
                  <div className="draft-queue">
                    {drafts.map((draft) => (
                      <button
                        key={draft.id}
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
                            <span className="workbench-pill">{countdownText(selectedDraft.auto_approve_at)}</span>
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

                        {(selectedDraft.score?.reasons?.length > 0 || selectedDraft.candidate_score?.reasons?.length > 0) && (
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
                                <strong>{selectedDraftSourceRun ? formatDuration(selectedDraftSourceRun.duration_ms) : "—"}</strong>
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
                              .filter((candidate) => candidate.text !== selectedDraft.text)
                              .slice(0, 3)
                              .map((candidate) => (
                                <div key={`${selectedDraft.id}-${candidate.rank}`} className="candidate-item">
                                  <div className="candidate-head">
                                    <span>
                                      alt #{candidate.rank} · copy {candidate.score?.total || 0} · {candidate.source}
                                    </span>
                                    <button
                                      className="btn sm"
                                      disabled={!!draftAction}
                                      onClick={() => draftAct(selectedDraft.id, "select_candidate", { candidateRank: candidate.rank })}
                                    >
                                      Use This
                                    </button>
                                  </div>
                                  <div className="candidate-text">{candidate.text}</div>
                                  {candidate.score?.reasons?.length > 0 && (
                                    <div className="candidate-meta">{candidate.score.reasons.join(" · ")}</div>
                                  )}
                                </div>
                              ))}
                          </div>
                        )}

                        <div className="draft-actions">
                          {editingId === selectedDraft.id ? (
                            <>
                              <button
                                className="btn approve sm"
                                disabled={draftAction === selectedDraft.id || editText.length > 280}
                                onClick={() => draftAct(selectedDraft.id, "edit", { editedText: editText })}
                              >
                                Save
                              </button>
                              <button className="btn sm" onClick={() => setEditingId(null)}>
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                className="btn approve sm"
                                disabled={!!draftAction}
                                onClick={() => draftAct(selectedDraft.id, "approve")}
                              >
                                {draftAction === selectedDraft.id ? "..." : "Approve + Post"}
                              </button>
                              <button
                                className="btn sm"
                                onClick={() => {
                                  setEditingId(selectedDraft.id)
                                  setEditText(selectedDraft.text)
                                }}
                              >
                                Edit
                              </button>
                              <button
                                className="btn reject sm"
                                disabled={!!draftAction}
                                onClick={() => draftAct(selectedDraft.id, "reject")}
                              >
                                Reject
                              </button>
                              {selectedDraft.auto_approve_at ? (
                                <button
                                  className="btn sm"
                                  disabled={!!draftAction}
                                  onClick={() => draftAct(selectedDraft.id, "cancel_auto_approve")}
                                >
                                  Cancel {countdownText(selectedDraft.auto_approve_at)}
                                </button>
                              ) : selectedDraft.approval_policy?.can_auto_approve === false ? (
                                <button className="btn sm" disabled>
                                  Review Only
                                </button>
                              ) : (
                                <button
                                  className="btn sm"
                                  disabled={!!draftAction}
                                  onClick={() => draftAct(selectedDraft.id, "auto_approve", {
                                    delayMinutes: selectedDraft.approval_policy?.recommended_delay_minutes,
                                  })}
                                >
                                  Auto {delayLabel(selectedDraft.approval_policy?.recommended_delay_minutes || 30)}
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
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
                <div className="stat">{hot10.date || "—"}</div>
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

            {/* Run Center */}
            <div className="card full" style={{ marginBottom: 16 }}>
              <h2>Run Center</h2>
              {latestBotRun ? (
                <>
                  <div className="run-summary">
                    <div className="run-stat">
                      <div className="run-stat-label">Latest Mode</div>
                      <div className="run-stat-value">{latestBotRun.mode}</div>
                    </div>
                    <div className="run-stat">
                      <div className="run-stat-label">Started</div>
                      <div className="run-stat-value">{timeAgo(latestBotRun.started_at)}</div>
                    </div>
                    <div className="run-stat">
                      <div className="run-stat-label">Sources</div>
                      <div className="run-stat-value">{latestBotRun.source_count || latestSourceRuns.length}</div>
                    </div>
                    <div className="run-stat">
                      <div className="run-stat-label">Drafts Created</div>
                      <div className="run-stat-value">{latestBotRun.drafted_count || 0}</div>
                    </div>
                  </div>

                  <div className="source-run-list">
                    {latestSourceRuns.map((source) => (
                      <div className="source-run" key={`${latestBotRun.id}-${source.source}`}>
                        <div className="source-run-head">
                          <span className="source-run-name">{source.source}</span>
                          <RunStatus status={source.status} />
                        </div>
                        <div className="source-run-meta">
                          <span>Observed: {source.observed ?? 0}</span>
                          <span>Promoted: {source.promoted ?? 0}</span>
                          <span>Drafted: {source.drafted ?? 0}</span>
                          <span>Duration: {formatDuration(source.duration_ms)}</span>
                        </div>
                        {source.note && <div className="source-run-note">{source.note}</div>}
                        {source.error && <div className="source-run-error">{source.error}</div>}
                      </div>
                    ))}
                  </div>
                  {failedSourceRuns.length > 0 && (
                    <div className="compose-status" style={{ marginTop: 12 }}>
                      {failedSourceRuns.length} source{failedSourceRuns.length === 1 ? "" : "s"} failed in the latest run.
                    </div>
                  )}
                </>
              ) : (
                <div className="empty">no bot run telemetry yet</div>
              )}
            </div>

            {/* Runs */}
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
