"use client"
import { createElement as h, useCallback, useEffect, useState } from "react"

export function generationCommand(brief, now = new Date()) {
  const keys = ["brief_id", "brief_sha256", "expected_state_version", "expected_policy_sha256"]
  return { command_id: crypto.randomUUID(), action: "request_sourced_generation", targets: [],
    requested_at: now.toISOString(), expires_at: new Date(now.getTime() + 3600000).toISOString(),
    payload: Object.fromEntries(keys.map((key) => [key, brief[key]])) }
}

export function WriterUsage({ usage }) {
  if (!usage) return null
  const counts = usage.counts || {}
  const label = value => value == null ? "unknown" : String(value)
  return h("details", null,
    h("summary", null, "Writer usage · final charge unknown"),
    h("p", null, `Input: ${label(counts.input_tokens)} tokens; output: ${label(counts.output_tokens)}; cache read: ${label(counts.cache_read_input_tokens)}.`),
    h("p", { className: "runtime-note" }, "Reported tokens are not a final bill. The request’s budget remains tracked separately."))
}

export default function SourcedGeneration({ onRefresh, readOnly = false }) {
  const [briefs, setBriefs] = useState([])
  const [selected, setSelected] = useState("")
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("Loading retained source briefs…")
  const load = useCallback(async () => {
    const res = await fetch("/api/generate", { cache: "no-store" })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || "Source briefs are unavailable.")
    setBriefs(data.briefs || [])
    setMessage(data.enabled ? (data.briefs?.length ? "Select retained evidence to request one draft." : "No retained source briefs are available.") : "Sourced generation is unavailable.")
  }, [])
  useEffect(() => { load().catch((error) => setMessage(error.message)) }, [load])
  const brief = briefs.find((item) => item.brief_id === selected)

  async function start() {
    if (busy || readOnly || !brief && !pending) return
    const body = pending || generationCommand(brief)
    setPending(body)
    setBusy(true)
    try {
      const res = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      const result = await res.json()
      if (!res.ok) {
        // Explicit refusal is final; an unavailable/lost acknowledgment keeps
        // the same identity so a retry cannot buy another request.
        if ([400, 401, 403, 409, 413, 415, 422].includes(res.status)) setPending(null)
        throw new Error(result.error || "Request unavailable; retry the same request.")
      }
      setMessage("Request accepted. Check progress shortly.")
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
        if (!res.ok) throw new Error(result.error || "Progress unavailable; retain this request.")
        if (result.status === "completed") {
          outcome = result.result.status === "rejected" ? result.result.message : "Generation is queued. The workbench will show the candidate when its result is retained."
          setPending(null)
        } else outcome = "Accepted; waiting for generation to start."
      }
      await load()
      if (outcome) setMessage(outcome)
      if (onRefresh) await onRefresh()
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }

  return h("section", { className: "card full", style: { marginBottom: 16 }, "aria-labelledby": "sourced-generation-title" },
    h("h2", { id: "sourced-generation-title" }, "Write from retained evidence"),
    h("p", { className: "runtime-note" }, "One draft per source brief. Required checks run before it enters the workbench. Publishing remains off; retained usage is not a final bill."),
    h("label", { htmlFor: "generation-brief" }, "Source brief"),
    h("select", { id: "generation-brief", value: selected, onChange: e => setSelected(e.target.value), disabled: busy || !!pending,
      style: { minHeight: 44, maxWidth: "100%", width: "100%" } },
      h("option", { value: "" }, "Choose retained evidence"),
      ...briefs.map(item => h("option", { key: item.brief_id, value: item.brief_id }, `${item.where} · ${item.signal_kind} · ${item.status}`))),
    brief && h("p", null, `${brief.source_key} · ${brief.when} · ${brief.status.replaceAll("_", " ")}`),
    brief && h(WriterUsage, { usage: brief.writer_usage }),
    h("div", { className: "preview-actions" },
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, disabled: busy || readOnly || !pending && (!brief || brief.status !== "ready"), onClick: start }, pending ? "Retry same request" : "Request draft"),
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, disabled: busy, onClick: refresh }, "Check progress")),
    h("p", { role: "status", "aria-live": "polite" }, message))
}
