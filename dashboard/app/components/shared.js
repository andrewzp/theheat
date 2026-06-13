"use client"

export function formatUtcStamp(dateStr) {
  if (!dateStr) return ""
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return ""
  const hh = String(d.getUTCHours()).padStart(2, "0")
  const mm = String(d.getUTCMinutes()).padStart(2, "0")
  return `${hh}:${mm} UTC`
}

export function draftOutcomeLabel(draft) {
  if (draft?.status === "posted") return "posted"
  if (draft?.status === "approved") return "approved"
  if (draft?.status === "rejected") return "rejected"
  if (draft?.auto_approve_at) return "auto-queued"
  return draft?.status || "pending"
}

export function draftOutcomeTone(draft) {
  if (draft?.status === "posted") return "success"
  if (draft?.status === "approved") return "running"
  if (draft?.status === "rejected") return "failure"
  return "neutral"
}

export function clipText(text, max = 96) {
  if (!text || text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

export function countdownText(dateStr) {
  if (!dateStr) return ""
  const diff = new Date(dateStr).getTime() - Date.now()
  if (diff <= 0) return "due now"
  const mins = Math.ceil(diff / 60000)
  if (mins < 60) return `auto in ${mins}m`
  const hrs = Math.floor(mins / 60)
  const rem = mins % 60
  return `auto in ${hrs}h ${rem}m`
}

export function delayLabel(minutes) {
  if (!minutes) return "manual"
  if (minutes < 60) return `${minutes}m`
  const hrs = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem ? `${hrs}h ${rem}m` : `${hrs}h`
}

export function policySummary(draft) {
  const policy = draft?.approval_policy
  if (!policy) return "policy pending"
  if (policy.mode === "manual_only") return "review only"
  if (draft?.auto_approve_at) return countdownText(draft.auto_approve_at)
  if (policy.recommended_delay_minutes) return `auto ${delayLabel(policy.recommended_delay_minutes)}`
  return "manual review"
}

export function findDraftRun(draft, botRuns) {
  const runId = draft?.review_context?.run_id
  if (!runId) return null
  return (botRuns || []).find((run) => run.id === runId) || null
}

export function findDraftSourceRun(draft, botRuns) {
  const run = findDraftRun(draft, botRuns)
  if (!run) return null
  const sourceKey = draft?.review_context?.source_key
  if (!sourceKey) return null
  return (run.sources || []).find((s) => s.source === sourceKey) || null
}

export function ScoreMeter({ label, value, inverse = false }) {
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
