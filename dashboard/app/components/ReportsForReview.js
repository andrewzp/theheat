"use client"
import { createElement as h, useCallback, useEffect, useState } from "react"

export function reportCommand(report, now = new Date()) {
  return { command_id: crypto.randomUUID(), action: "open_report_evidence", targets: [],
    requested_at: now.toISOString(), expires_at: new Date(now.getTime() + 3600000).toISOString(),
    payload: Object.fromEntries(["lineage_id", "report_sha256", "expected_policy_sha256", "episode_reference"].map(key => [key, report[key]])) }
}

export function ReportDetail({ report }) {
  return h("div", null,
    h("p", null, "Reported claims — evidence review required. Opening a report does not request a draft."),
    report.related_story && h("p", null, "This report refers to a current story’s source identity. Its claims have not been added to the draft evidence."),
    ...(report.claims || []).map(claim => h("article", { key: claim.claim_id, style: { marginTop: 16 } },
      h("h3", null, claim.summary),
      h("p", { className: "runtime-note" }, `${claim.kind.replaceAll("_", " ")} · attributed to ${claim.attribution}`),
      h("details", null, h("summary", null, "Original source wording"),
        ...(claim.excerpts || []).map((entry, index) => h("blockquote", { key: index }, entry.text))),
      h("p", null, `Original language: ${claim.original_language}.`),
      claim.translation?.text && h("p", null, `Translation (${claim.translation.status.replaceAll("_", " ")}): ${claim.translation.text}`),
      h("dl", null, ...["event_start", "event_end", "published_at", "as_of"].flatMap(key => [
        h("dt", { key: `${key}-label` }, key.replaceAll("_", " ")),
        h("dd", { key }, claim.times?.[key]?.original || "Unknown") ])),
      h("p", null, `Still needed: ${(claim.holds || []).map(value => value.replaceAll("_", " ")).join("; ") || "Claim qualification"}`))))
}

export default function ReportsForReview({ readOnly = false }) {
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState("")
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("Loading retained reports…")
  const load = useCallback(async () => {
    const res = await fetch("/api/reports", { cache: "no-store" })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || "Retained reports are unavailable.")
    setReports(data.reports || [])
    setMessage(data.reports?.length ? "Review a report’s evidence, even when there is no sensor alert." : "No retained reports are configured.")
  }, [])
  useEffect(() => { load().catch(error => setMessage(error.message)) }, [load])
  const report = reports.find(row => row.lineage_id === selected)
  async function open() {
    if (busy || readOnly || !pending && (!report || report.development_status === "unavailable")) return
    const body = pending || reportCommand(report)
    setPending(body)
    setBusy(true)
    try {
      const res = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      const result = await res.json()
      if (!res.ok) {
        if ([400, 401, 403, 409, 413, 415, 422].includes(res.status)) setPending(null)
        throw new Error(result.error || "Status is unknown. Retry the same request.")
      }
      setMessage("Request accepted. Refresh to see the evidence-review item.")
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  async function refresh() {
    if (busy) return
    setBusy(true)
    try {
      let outcome
      if (pending) {
        const res = await fetch(`/api/drafts?commandId=${pending.command_id}`, { cache: "no-store" })
        const result = await res.json()
        if (!res.ok) throw new Error(result.error || "Status is unavailable. Keep this request for retry.")
        if (result.status === "completed") {
          outcome = result.result.status === "rejected" ? result.result.message : "Evidence review is open. No draft or model request was created."
          setPending(null)
        } else outcome = "Accepted; waiting for evidence review to open."
      }
      await load()
      if (outcome) setMessage(outcome)
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  return h("section", { className: "card full", "aria-labelledby": "reports-review-title", style: { marginTop: 16 } },
    h("h2", { id: "reports-review-title" }, "Reports needing evidence"),
    h("p", { className: "runtime-note" }, "Original reports, forecasts and impact claims stay separate from measured observations. Publishing remains off."),
    h("label", { htmlFor: "report-choice" }, "Retained report"),
    h("select", { id: "report-choice", value: selected, onChange: e => setSelected(e.target.value), disabled: busy || !!pending,
      style: { width: "100%", maxWidth: "100%", minHeight: 44 } },
      h("option", { value: "" }, "Choose a report"), ...reports.map(row => h("option", { key: row.lineage_id, value: row.lineage_id }, `${row.source_label} · ${row.development_status.replaceAll("_", " ")}`))),
    report && h(ReportDetail, { report }),
    h("div", { className: "preview-actions" },
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, onClick: open,
        disabled: busy || readOnly || !pending && (!report || report.development_status === "unavailable") }, pending ? "Retry same request" : "Open evidence"),
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, onClick: refresh, disabled: busy }, "Refresh")),
    h("p", { role: "status", "aria-live": "polite" }, message))
}
