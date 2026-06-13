"use client"

export function RunStatus({ conclusion, status }) {
  if (status === "in_progress") return <span className="badge running">RUNNING</span>
  if (conclusion === "success") return <span className="badge success">OK</span>
  if (conclusion === "failure") return <span className="badge failure">FAIL</span>
  return <span className="badge neutral">{conclusion || status}</span>
}

export function SourceStatusBadge({ status }) {
  const map = {
    success: ["success", "OK"],
    failed: ["failure", "FAIL"],
    skipped: ["running", "SKIPPED"],
    partial_failure: ["running", "PARTIAL"],
  }
  const [cls, label] = map[status] || ["neutral", (status || "—").toUpperCase()]
  return <span className={`badge ${cls}`}>{label}</span>
}
