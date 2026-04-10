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

function toneForStatus(status, conclusion) {
  if (status === "success" || conclusion === "success") return "good"
  if (status === "in_progress") return "warn"
  if (status === "partial_failure" || status === "skipped") return "warn"
  if (status === "failed" || conclusion === "failure") return "bad"
  return "neutral"
}

function labelForStatus(status, conclusion) {
  if (status === "in_progress") return "running"
  if (status === "partial_failure") return "partial"
  if (status === "skipped") return "skipped"
  if (status === "success" || conclusion === "success") return "healthy"
  if (status === "failed" || conclusion === "failure") return "failed"
  return conclusion || status || "unknown"
}

function formatUtcStamp(dateStr) {
  if (!dateStr) return "—"
  const date = new Date(dateStr)
  return `${date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  })} UTC`
}

function draftOutcomeTone(draft) {
  if (draft?.status === "posted") return "good"
  if (draft?.status === "rejected") return "bad"
  if (draft?.auto_approve_at) return "warn"
  return "neutral"
}

function draftOutcomeLabel(draft) {
  if (draft?.status === "posted") return "posted"
  if (draft?.status === "approved") return "approved"
  if (draft?.status === "rejected") return "rejected"
  if (draft?.auto_approve_at) return countdownText(draft.auto_approve_at)
  return draft?.status || "pending"
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
    setDraftFeedback(null)
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, draftId, ...payload }),
      })
      const result = await res.json()
      if (!res.ok || result.ok === false) {
        setDraftFeedback({
          type: "error",
          text: result.error || "Draft action failed",
        })
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
  const healthySourceRuns = latestSourceRuns.filter((source) => source.status === "success")
  const totalObserved = latestSourceRuns.reduce((sum, source) => sum + (source.observed || 0), 0)
  const totalPromoted = latestSourceRuns.reduce((sum, source) => sum + (source.promoted || 0), 0)
  const totalDrafted = latestSourceRuns.reduce((sum, source) => sum + (source.drafted || 0), 0)
  const runHealth = latestSourceRuns.length
    ? Math.round((healthySourceRuns.length / latestSourceRuns.length) * 100)
    : 0
  const autoQueuedDrafts = drafts.filter((draft) => !!draft.auto_approve_at).length
  const manualOnlyDrafts = drafts.filter((draft) => draft.approval_policy?.can_auto_approve === false).length
  const recentDraftOutcomes = [...(state?.drafts || [])]
    .sort((a, b) => new Date(b.updated_at || b.posted_at || b.created_at || 0) - new Date(a.updated_at || a.posted_at || a.created_at || 0))
    .slice(0, 3)
  const timelineRows = latestBotRun
    ? [
        {
          key: `${latestBotRun.id}-start`,
          time: latestBotRun.started_at,
          tone: latestBotRun.failure_count ? "warn" : "good",
          label: "run started",
          text: `${latestBotRun.mode} created ${latestBotRun.id} and opened ${latestSourceRuns.length || latestBotRun.source_count || 0} source slots.`,
        },
        ...latestSourceRuns
          .filter((source) => source.observed || source.promoted || source.drafted || source.note || source.error)
          .slice(0, 3)
          .map((source) => ({
            key: `${latestBotRun.id}-${source.source}`,
            time: latestBotRun.ended_at || latestBotRun.started_at,
            tone: toneForStatus(source.status),
            label: source.source,
            text: source.error
              ? `${source.source} failed after ${formatDuration(source.duration_ms)}. ${source.error}`
              : `${source.observed || 0} observations, ${source.promoted || 0} promoted, ${source.drafted || 0} drafts in ${formatDuration(source.duration_ms)}.`,
          })),
        {
          key: `${latestBotRun.id}-queue`,
          time: latestBotRun.ended_at || latestBotRun.started_at,
          tone: autoQueuedDrafts ? "warn" : "good",
          label: "queue updated",
          text: `${drafts.length} drafts are waiting. ${autoQueuedDrafts} timed auto-approvals and ${manualOnlyDrafts} manual-only reviews remain in the queue.`,
        },
      ]
    : []

  return (
    <>
      <style jsx global>{`
        :root {
          --bg: #0c0f14;
          --bg-soft: #111722;
          --panel: rgba(19, 24, 32, 0.9);
          --panel-alt: rgba(16, 21, 29, 0.86);
          --line: rgba(103, 148, 255, 0.14);
          --line-strong: rgba(143, 176, 255, 0.3);
          --text: #eef4ff;
          --muted: #9aa8bf;
          --soft: #6f7d93;
          --accent: #8fb0ff;
          --accent-2: #d5e1ff;
          --good: #86d796;
          --warn: #ffd266;
          --bad: #ff8f8f;
        }

        * { box-sizing: border-box; }
        html, body { margin: 0; min-height: 100%; }
        body {
          min-height: 100vh;
          color: var(--text);
          background:
            radial-gradient(circle at top right, rgba(143, 176, 255, 0.18), transparent 24%),
            linear-gradient(180deg, #0a0d12 0%, #0d1117 100%);
          font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
        }
        button, input, textarea { font: inherit; }
        a { color: inherit; }

        .shell {
          width: min(1440px, calc(100% - 32px));
          margin: 24px auto 40px;
          display: grid;
          gap: 18px;
        }
        .panel {
          border-radius: 24px;
          border: 1px solid var(--line);
          background: var(--panel);
          padding: 24px;
          box-shadow: 0 24px 90px rgba(0, 0, 0, 0.3);
          backdrop-filter: blur(16px);
        }
        .topbar {
          display: flex;
          justify-content: space-between;
          gap: 20px;
          align-items: flex-start;
        }
        .eyebrow {
          color: var(--accent);
          text-transform: uppercase;
          letter-spacing: 0.16em;
          font-size: 11px;
          margin-bottom: 10px;
        }
        .brand-row {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          align-items: baseline;
          margin-bottom: 12px;
        }
        h1, h2, h3, p { margin: 0; }
        h1 {
          font-size: clamp(34px, 5vw, 58px);
          line-height: 0.98;
          font-family: "Iowan Old Style", "Book Antiqua", serif;
          letter-spacing: -0.03em;
        }
        .subhead {
          color: var(--soft);
          text-transform: uppercase;
          letter-spacing: 0.18em;
          font-size: 11px;
        }
        .lede {
          color: var(--muted);
          font-size: 15px;
          line-height: 1.6;
          max-width: 62ch;
        }
        .top-actions {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
          justify-content: flex-end;
          align-items: center;
        }
        .backend-pill, .signal-badge, .workbench-pill, .badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          border-radius: 999px;
          border: 1px solid var(--line);
          font-size: 11px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--accent-2);
          background: rgba(255, 255, 255, 0.025);
        }
        .backend-pill { color: var(--accent); }
        .signal-badge.good, .badge.success { color: var(--good); }
        .signal-badge.warn, .badge.running { color: var(--warn); }
        .signal-badge.bad, .badge.failure { color: var(--bad); }
        .signal-badge.neutral { color: var(--soft); }
        .badge.neutral { color: var(--soft); }
        .refresh-btn, .btn {
          appearance: none;
          border: 1px solid var(--line-strong);
          background: rgba(255, 255, 255, 0.04);
          color: var(--text);
          cursor: pointer;
          transition: 120ms ease;
        }
        .refresh-btn {
          padding: 10px 14px;
          border-radius: 999px;
          font-size: 12px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }
        .refresh-btn:hover, .btn:hover {
          border-color: rgba(143, 176, 255, 0.5);
          background: rgba(143, 176, 255, 0.08);
        }
        .hero {
          display: grid;
          grid-template-columns: 1.18fr 0.82fr;
          gap: 18px;
          align-items: stretch;
        }
        .hero h2 {
          font-size: clamp(32px, 4.6vw, 54px);
          line-height: 0.98;
          font-family: "Iowan Old Style", "Book Antiqua", serif;
          letter-spacing: -0.03em;
          margin-bottom: 14px;
        }
        .hero-copy {
          color: var(--muted);
          font-size: 15px;
          line-height: 1.6;
          max-width: 60ch;
        }
        .hero-metrics {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
        }
        .metric {
          padding: 18px;
          border-radius: 20px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.03);
        }
        .metric span {
          display: block;
          color: var(--soft);
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 10px;
          margin-bottom: 10px;
        }
        .metric strong {
          display: block;
          font-size: clamp(28px, 4vw, 36px);
          margin-bottom: 8px;
        }
        .metric p {
          color: var(--muted);
          font-size: 13px;
          line-height: 1.45;
        }
        .two-up {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 18px;
        }
        .section-title {
          font-size: 13px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--accent-2);
          margin-bottom: 18px;
        }
        .section-head {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: flex-start;
          margin-bottom: 18px;
        }
        .section-kicker {
          color: var(--soft);
          font-size: 13px;
          line-height: 1.5;
          max-width: 56ch;
        }
        .source-row, .timeline-row, .table-row {
          display: grid;
          gap: 10px;
          padding: 14px 0;
          border-top: 1px solid var(--line);
        }
        .source-row:first-of-type,
        .timeline-row:first-of-type,
        .table-row:first-of-type {
          border-top: none;
          padding-top: 0;
        }
        .source-head, .table-head {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
        }
        .source-head strong, .table-head strong {
          font-size: 15px;
        }
        .meta {
          display: flex;
          flex-wrap: wrap;
          gap: 8px 18px;
          color: var(--muted);
          font-size: 13px;
        }
        .timeline-panel p,
        .table-panel p {
          color: var(--muted);
          font-size: 14px;
          line-height: 1.55;
        }
        .source-run-error, .error-source { color: var(--bad); }
        .source-run-note { color: var(--soft); }
        .desk-panel { padding: 26px; }
        .draft-desk {
          display: grid;
          grid-template-columns: 320px minmax(0, 1fr);
          gap: 18px;
          align-items: start;
        }
        .draft-queue {
          display: grid;
          gap: 10px;
          align-content: start;
          max-height: 920px;
          overflow: auto;
          padding-right: 4px;
        }
        .queue-item {
          width: 100%;
          text-align: left;
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.03);
          padding: 14px;
          color: inherit;
          cursor: pointer;
          transition: 140ms ease;
        }
        .queue-item:hover,
        .queue-item.selected {
          border-color: rgba(143, 176, 255, 0.5);
          background: rgba(143, 176, 255, 0.08);
          transform: translateY(-1px);
        }
        .queue-item-head {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          align-items: center;
          margin-bottom: 8px;
        }
        .queue-score {
          color: var(--soft);
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }
        .draft-type {
          display: inline-flex;
          align-items: center;
          border-radius: 999px;
          border: 1px solid var(--line);
          padding: 5px 10px;
          color: var(--accent-2);
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          background: rgba(255, 255, 255, 0.03);
        }
        .queue-text {
          color: var(--text);
          font-size: 14px;
          line-height: 1.5;
          margin-bottom: 10px;
        }
        .queue-meta {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          color: var(--soft);
          font-size: 11px;
        }
        .draft-workbench {
          border-radius: 22px;
          border: 1px solid var(--line);
          background: linear-gradient(180deg, rgba(16, 21, 29, 0.94), rgba(12, 17, 24, 0.9));
          padding: 20px;
        }
        .draft-meta {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
          font-size: 12px;
        }
        .draft-time { color: var(--soft); }
        .draft-status-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 14px;
        }
        .workbench-pill { color: var(--muted); }
        .draft-text {
          font-size: 22px;
          line-height: 1.45;
          color: var(--text);
          margin-bottom: 10px;
          font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
        }
        .draft-chars {
          font-size: 11px;
          color: var(--soft);
          margin-bottom: 12px;
          text-transform: uppercase;
          letter-spacing: 0.12em;
        }
        .draft-chars.over { color: var(--bad); }
        .draft-reason-block { display: grid; gap: 4px; margin-bottom: 12px; }
        .draft-reason-line { font-size: 12px; color: var(--muted); }
        .draft-reason-line strong { color: var(--accent-2); font-weight: 600; }
        .draft-edit-area,
        .compose-input,
        .preview-tweet {
          width: 100%;
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.03);
          color: var(--text);
          padding: 14px 16px;
          font-size: 14px;
          line-height: 1.6;
          resize: vertical;
        }
        .draft-edit-area:focus,
        .compose-input:focus,
        .preview-tweet:focus {
          outline: none;
          border-color: rgba(143, 176, 255, 0.5);
        }
        .workbench-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
          margin: 18px 0;
        }
        .workbench-panel {
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.02);
          padding: 14px;
        }
        .workbench-panel h3 {
          font-size: 10px;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          color: var(--accent-2);
          margin-bottom: 10px;
        }
        .workbench-headline {
          color: var(--text);
          font-size: 15px;
          line-height: 1.45;
          margin-bottom: 10px;
        }
        .fact-list { display: grid; gap: 8px; }
        .fact-row {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--line);
        }
        .fact-row:last-child { border-bottom: none; padding-bottom: 0; }
        .fact-label { color: var(--soft); font-size: 12px; }
        .fact-value { color: var(--text); font-size: 12px; text-align: right; }
        .run-trace { display: grid; gap: 8px; }
        .trace-line {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          color: var(--muted);
          font-size: 12px;
        }
        .trace-line strong { color: var(--text); font-weight: 600; }
        .score-meter { margin-bottom: 12px; }
        .score-meter:last-child { margin-bottom: 0; }
        .score-meter-head {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          color: var(--soft);
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          margin-bottom: 6px;
        }
        .score-meter-track {
          height: 8px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.05);
          overflow: hidden;
        }
        .score-meter-fill {
          height: 100%;
          border-radius: 999px;
          background: linear-gradient(90deg, #8fb0ff, #d5e1ff);
        }
        .score-meter-fill.inverse {
          background: linear-gradient(90deg, #86d796, #ffd266);
        }
        .candidate-list {
          display: grid;
          gap: 10px;
          padding-top: 16px;
          border-top: 1px solid var(--line);
        }
        .candidate-item {
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.03);
          padding: 12px;
        }
        .candidate-head {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          align-items: center;
          margin-bottom: 8px;
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: var(--soft);
        }
        .candidate-text { color: var(--text); font-size: 14px; line-height: 1.55; margin-bottom: 8px; }
        .candidate-meta { color: var(--muted); font-size: 11px; }
        .draft-actions, .trigger-bar, .preview-actions {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
          align-items: center;
        }
        .btn {
          border-radius: 999px;
          padding: 10px 15px;
          font-size: 12px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .btn:disabled { opacity: 0.45; cursor: not-allowed; }
        .btn.primary {
          background: rgba(143, 176, 255, 0.16);
          color: var(--accent-2);
        }
        .btn.approve {
          background: rgba(134, 215, 150, 0.1);
          color: var(--good);
          border-color: rgba(134, 215, 150, 0.3);
        }
        .btn.reject {
          background: rgba(255, 143, 143, 0.08);
          color: var(--bad);
          border-color: rgba(255, 143, 143, 0.2);
        }
        .btn.sm {
          padding: 8px 12px;
          font-size: 11px;
        }
        .draft-feedback, .status-banner {
          margin-top: 12px;
          padding: 12px 14px;
          border-radius: 16px;
          border: 1px solid var(--line);
          font-size: 13px;
        }
        .draft-feedback.success, .status-banner.success {
          color: var(--good);
          background: rgba(134, 215, 150, 0.08);
        }
        .draft-feedback.error, .status-banner.error {
          color: var(--bad);
          background: rgba(255, 143, 143, 0.08);
        }
        .compose {
          display: grid;
          gap: 12px;
        }
        .preview-box {
          border-radius: 20px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.025);
          padding: 16px;
        }
        .preview-label {
          display: flex;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 10px;
          color: var(--accent);
          text-transform: uppercase;
          letter-spacing: 0.14em;
          font-size: 11px;
        }
        .char-count { color: var(--good); }
        .char-count.over { color: var(--bad); }
        .card-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 18px;
        }
        .stat-block {
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255, 255, 255, 0.025);
          padding: 16px;
          margin-bottom: 12px;
        }
        .stat-block:last-child { margin-bottom: 0; }
        .stat-label {
          color: var(--soft);
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 10px;
          margin-bottom: 8px;
        }
        .stat {
          font-size: 26px;
          margin-bottom: 8px;
          font-family: "Iowan Old Style", "Book Antiqua", serif;
        }
        .stat-copy {
          color: var(--muted);
          font-size: 13px;
          line-height: 1.5;
        }
        .hot10-list, .error-list {
          list-style: none;
          padding: 0;
          margin: 0;
        }
        .hot10-list li, .error-list li {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 12px 0;
          border-top: 1px solid var(--line);
          font-size: 13px;
        }
        .hot10-list li:first-child, .error-list li:first-child { border-top: none; padding-top: 0; }
        .rank { color: var(--soft); width: 28px; }
        .city { flex: 1; }
        .streak-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .streak-chip {
          border-radius: 999px;
          border: 1px solid var(--line);
          padding: 8px 12px;
          font-size: 12px;
          color: var(--muted);
          background: rgba(255, 255, 255, 0.03);
        }
        .streak-chip .days { color: var(--accent-2); font-weight: 600; }
        .runs-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .runs-table th {
          text-align: left;
          color: var(--soft);
          font-weight: 500;
          padding: 0 0 12px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          font-size: 10px;
        }
        .runs-table td {
          padding: 12px 10px 12px 0;
          border-top: 1px solid var(--line);
          color: var(--muted);
        }
        .runs-table a {
          color: var(--accent);
          text-decoration: none;
        }
        .runs-table a:hover { color: var(--accent-2); }
        .error-source { font-weight: 600; }
        .error-msg {
          color: var(--muted);
          display: block;
          margin-top: 4px;
          line-height: 1.5;
        }
        .error-ts { color: var(--soft); }
        .empty {
          color: var(--soft);
          font-size: 13px;
          font-style: italic;
        }
        .draft-empty {
          color: var(--soft);
          font-size: 14px;
          font-style: italic;
          padding: 16px 0;
        }
        .loading {
          padding: 120px 0;
          text-align: center;
          color: var(--soft);
          font-size: 14px;
        }

        @media (max-width: 1120px) {
          .hero, .two-up, .card-grid, .draft-desk, .workbench-grid {
            grid-template-columns: 1fr;
          }
          .hero-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 720px) {
          .shell {
            width: min(100% - 16px, 100%);
            margin: 12px auto 28px;
          }
          .panel { padding: 18px; border-radius: 20px; }
          .topbar, .section-head, .draft-meta, .source-head, .table-head {
            flex-direction: column;
            align-items: flex-start;
          }
          .hero-metrics { grid-template-columns: 1fr; }
        }
      `}</style>

      <div className="shell">
        <header className="topbar">
          <div>
            <div className="eyebrow">Run Center</div>
            <div className="brand-row">
              <h1>@theheat</h1>
              <span className="subhead">editorial desk</span>
            </div>
            <p className="lede">
              Operational truth, not workflow vibes. The dashboard now treats source health, funnel quality,
              queue state, and publishing outcomes as the product instead of hiding everything behind a green
              GitHub Actions check.
            </p>
          </div>
          <div className="top-actions">
            <span className="backend-pill">{(data?.stateBackend || "gist").toUpperCase()} backend</span>
            <button className="refresh-btn" onClick={fetchData}>Refresh</button>
          </div>
        </header>

        {loading ? (
          <div className="loading">loading...</div>
        ) : (
          <>
            <section className="hero panel">
              <div>
                <div className="eyebrow">Live Ops</div>
                <h2>Operational truth, not workflow vibes.</h2>
                <p className="hero-copy">
                  The current run view tells you what each source returned, what got filtered out, what cleared
                  editorial scoring, what made it into the queue, and what failed. Success is measured in signal
                  quality and publishing safety, not just cron completion.
                </p>
              </div>
              <div className="hero-metrics">
                <div className="metric">
                  <span>Current run</span>
                  <strong>{latestBotRun ? `${runHealth}%` : "—"}</strong>
                  <p>
                    {latestBotRun
                      ? `${healthySourceRuns.length} of ${latestSourceRuns.length || latestBotRun.source_count || 0} sources finished healthy.`
                      : "No run telemetry yet."}
                  </p>
                </div>
                <div className="metric">
                  <span>Signals</span>
                  <strong>{latestBotRun ? totalObserved : drafts.length}</strong>
                  <p>
                    {latestBotRun
                      ? `${totalPromoted} promoted events, ${totalDrafted} queue-ready drafts.`
                      : `${drafts.length} drafts waiting for review.`}
                  </p>
                </div>
                <div className="metric">
                  <span>Failures</span>
                  <strong>{failedSourceRuns.length}</strong>
                  <p>
                    {failedSourceRuns.length
                      ? `${failedSourceRuns.length} source slots need attention.`
                      : "No source failures in the latest run."}
                  </p>
                </div>
                <div className="metric">
                  <span>Queue</span>
                  <strong>{drafts.length}</strong>
                  <p>{autoQueuedDrafts} auto-timed drafts. {manualOnlyDrafts} review-only items.</p>
                </div>
              </div>
            </section>

            <section className="two-up">
              <article className="panel">
                <h2 className="section-title">Source Health</h2>
                {latestSourceRuns.length > 0 ? (
                  latestSourceRuns.map((source) => (
                    <div className="source-row" key={`${latestBotRun.id}-${source.source}`}>
                      <div className="source-head">
                        <strong>{source.source}</strong>
                        <span className={`signal-badge ${toneForStatus(source.status)}`}>
                          {labelForStatus(source.status)}
                        </span>
                      </div>
                      <div className="meta">
                        <span>{source.observed || 0} observed</span>
                        <span>{source.promoted || 0} promoted</span>
                        <span>{source.drafted || 0} drafted</span>
                        <span>{formatDuration(source.duration_ms)} latency</span>
                      </div>
                      {source.note && <div className="source-run-note">{source.note}</div>}
                      {source.error && <div className="source-run-error">{source.error}</div>}
                    </div>
                  ))
                ) : (
                  <div className="empty">No source telemetry yet.</div>
                )}
              </article>

              <article className="panel">
                <h2 className="section-title">Funnel</h2>
                <div className="source-row">
                  <div className="source-head">
                    <strong>Observations ingested</strong>
                    <span className="signal-badge good">{totalObserved}</span>
                  </div>
                  <div className="meta">
                    <span>raw payloads normalized into canonical facts</span>
                  </div>
                </div>
                <div className="source-row">
                  <div className="source-head">
                    <strong>Events created</strong>
                    <span className="signal-badge good">{totalPromoted}</span>
                  </div>
                  <div className="meta">
                    <span>duplicates clustered and low-confidence items suppressed</span>
                  </div>
                </div>
                <div className="source-row">
                  <div className="source-head">
                    <strong>Draft candidates generated</strong>
                    <span className="signal-badge good">
                      {drafts.reduce((sum, draft) => sum + (draft.candidates?.length || 1), 0)}
                    </span>
                  </div>
                  <div className="meta">
                    <span>3-5 variants per high-scoring event when available</span>
                  </div>
                </div>
                <div className="source-row">
                  <div className="source-head">
                    <strong>Queue-ready drafts</strong>
                    <span className={`signal-badge ${drafts.length ? "warn" : "neutral"}`}>{drafts.length}</span>
                  </div>
                  <div className="meta">
                    <span>best candidates that survived quality gates and policy rules</span>
                  </div>
                </div>
              </article>
            </section>

            <section className="panel timeline-panel">
              <h2 className="section-title">Run Timeline</h2>
              {timelineRows.length > 0 ? (
                timelineRows.map((entry) => (
                  <div className="timeline-row" key={entry.key}>
                    <div className="table-head">
                      <strong>{formatUtcStamp(entry.time)}</strong>
                      <span className={`signal-badge ${entry.tone}`}>{entry.label}</span>
                    </div>
                    <p>{entry.text}</p>
                  </div>
                ))
              ) : (
                <div className="empty">No run timeline yet.</div>
              )}
            </section>

            <section className="two-up">
              <article className="panel table-panel">
                <h2 className="section-title">Recent Publishing Outcomes</h2>
                {recentDraftOutcomes.length > 0 ? (
                  recentDraftOutcomes.map((draft) => (
                    <div className="table-row" key={`outcome-${draft.id}`}>
                      <div className="table-head">
                        <strong>{`${draft.type || "draft"} / ${draftOutcomeLabel(draft)}`}</strong>
                        <span className={`signal-badge ${draftOutcomeTone(draft)}`}>{draftOutcomeLabel(draft)}</span>
                      </div>
                      <div className="meta">
                        <span>{clipText(draft.text, 72)}</span>
                        <span>{timeAgo(draft.updated_at || draft.posted_at || draft.created_at)}</span>
                        {draft.post_error && <span>{draft.post_error}</span>}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="empty">No publishing outcomes yet.</div>
                )}
              </article>

              <article className="panel">
                <div className="section-head">
                  <div>
                    <h2 className="section-title">Command Deck</h2>
                    <p className="section-kicker">
                      Trigger the pipeline, watch the queue, and keep manual intervention close without leaving the run view.
                    </p>
                  </div>
                </div>
                <div className="trigger-bar">
                  <button
                    className="btn primary"
                    disabled={!!triggering}
                    onClick={() => trigger("both")}
                  >
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
                {data?.stateError && <div className="status-banner error">{data.stateError}</div>}
                {data?.runsError && <div className="status-banner error">{data.runsError}</div>}
              </article>
            </section>

            <section className="panel desk-panel">
              <div className="section-head">
                <div>
                  <h2 className="section-title">Draft Workbench</h2>
                  <p className="section-kicker">
                    Review the queue with source facts, score context, alternate copy, and approval policy all in one place.
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
                        {draftFeedback && (
                          <div className={`draft-feedback ${draftFeedback.type}`}>
                            {draftFeedback.text}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <div className="draft-empty">
                  No drafts waiting. Trigger a run below or compose one manually.
                </div>
              )}
            </section>

            <section className="two-up">
              <article className="panel">
                <div className="section-head">
                  <div>
                    <h2 className="section-title">Compose Tweet</h2>
                    <p className="section-kicker">
                      Manually write or generate a tweet, then send it through the same review and posting pathway.
                    </p>
                  </div>
                </div>
                <div className="compose">
                  <textarea
                    className="compose-input"
                    placeholder="Describe the data (e.g. Phoenix hit 122F today, old record 121F from 2024)..."
                    value={composePrompt}
                    onChange={(e) => setComposePrompt(e.target.value)}
                    rows={3}
                  />
                  <button className="btn" disabled={generating || !composePrompt.trim()} onClick={generateTweet}>
                    {generating ? "Generating..." : "Generate Preview"}
                  </button>
                  {composeTweet && (
                    <div className="preview-box">
                      <div className="preview-label">
                        <span>Preview</span>
                        <span className={`char-count ${composeTweet.length > 280 ? "over" : ""}`}>
                          {composeTweet.length}/280
                        </span>
                      </div>
                      <textarea
                        className="preview-tweet"
                        value={composeTweet}
                        onChange={(e) => setComposeTweet(e.target.value)}
                        rows={4}
                      />
                      <div className="preview-actions">
                        <button
                          className="btn approve"
                          disabled={posting || !composeTweet.trim() || composeTweet.length > 280}
                          onClick={postComposed}
                        >
                          {posting ? "Sending..." : "Approve + Post"}
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
                  {composeStatus && (
                    <div className={`status-banner ${composeStatus.startsWith("Error") ? "error" : "success"}`}>
                      {composeStatus}
                    </div>
                  )}
                </div>
              </article>

              <article className="panel">
                <h2 className="section-title">Desk Stats</h2>
                <div className="stat-block">
                  <div className="stat-label">Tweets today</div>
                  <div className="stat">{todayCount}</div>
                  <div className="stat-copy">of the 10-post daily cap</div>
                </div>
                <div className="stat-block">
                  <div className="stat-label">Last Hot 10</div>
                  <div className="stat">{hot10.date || "—"}</div>
                  <div className="stat-copy">
                    {hot10.date ? `${hot10.cities?.[0] || "Leader"} led ${timeAgo(`${hot10.date}T12:00:00Z`)}` : "No leaderboard yet."}
                  </div>
                </div>
                <div className="stat-block">
                  <div className="stat-label">Streak leader</div>
                  <div className="stat">{sortedStreaks[0]?.[0] || "—"}</div>
                  <div className="stat-copy">
                    {sortedStreaks[0] ? `${sortedStreaks[0][1].consecutive_days} consecutive days in the Hot 10.` : "No active streaks."}
                  </div>
                </div>
              </article>
            </section>

            <section className="two-up">
              <article className="panel">
                <h2 className="section-title">Hot 10 Leaderboard</h2>
                {hot10.cities?.length > 0 ? (
                  <ul className="hot10-list">
                    {hot10.cities.map((city, i) => (
                      <li key={city}>
                        <span className="rank">{i + 1}.</span>
                        <span className="city">{city}</span>
                        <span className="error-ts">{i === 0 ? "leader" : "tracking"}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="empty">No leaderboard data yet.</div>
                )}
              </article>

              <article className="panel">
                <h2 className="section-title">Streaks</h2>
                {sortedStreaks.length > 0 ? (
                  <div className="streak-list">
                    {sortedStreaks.map(([city, s]) => (
                      <span className="streak-chip" key={city}>
                        {city} <span className="days">{s.consecutive_days}d</span>
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="empty">No active streaks.</div>
                )}
              </article>
            </section>

            <section className="two-up">
              <article className="panel">
                <h2 className="section-title">Recent Workflow Runs</h2>
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
                  <div className="empty">No workflow runs yet.</div>
                )}
              </article>

              <article className="panel">
                <h2 className="section-title">Recent Errors</h2>
                {errors.length > 0 ? (
                  <ul className="error-list">
                    {errors.slice(-10).reverse().map((e, i) => (
                      <li key={`${e.source}-${e.ts}-${i}`}>
                        <span className="error-source">{e.source}</span>
                        <span className="error-ts">{timeAgo(e.ts)}</span>
                        <span className="error-msg">{e.msg}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="empty">No recent errors. Suspicious in a good way.</div>
                )}
              </article>
            </section>
          </>
        )}
      </div>
    </>
  )
}
