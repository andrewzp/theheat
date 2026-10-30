"use client"
import { createElement as h, useCallback, useEffect, useState } from "react"

const words = value => String(value || "unknown").replaceAll("_", " ")
const stageLabels = { source_input_retained: "Source evidence retained", scientific_evidence_qualified: "Scientific qualification",
  physical_episode_detected: "Physical episode", story_prepared: "Story prepared", report_review_opened: "Evidence review opened",
  generation_accepted: "Draft generation accepted", candidate_retained: "Candidate retained", checks_completed: "Checks completed",
  draft_saved: "Draft saved", publication_confirmed: "Publication confirmed" }
const stateLabels = { recorded: "Recorded", held: "Evidence needed", not_observed_in_retained_scope: "Not in retained trace",
  unavailable: "Unavailable", not_applicable: "Not applicable", unsupported: "Not yet supported" }

const bindingLabels = { current: "Current evidence binding", superseded: "Superseded — historical evidence only", unresolved: "Evidence binding unresolved" }

export function coverageCommand(view, now = new Date()) {
  return { command_id: crypto.randomUUID(), action: "evaluate_reference_coverage", targets: [],
    requested_at: now.toISOString(), expires_at: new Date(now.getTime() + 3600000).toISOString(),
    payload: Object.fromEntries(["set_id", "expected_set_sha256", "expected_state_version", "expected_policy_sha256"].map(key => [key, view[key]])) }
}

const matchLabels = { matched: "Matched production records", ambiguous: "More than one production event matches — not counted as found or missed",
  near_match: "No match; the closest records differ as shown", unobserved: "No production record observed for this reference", unmatched: "No match" }
const checkWords = { alias: "event identity", hazard: "hazard type", place: "place", window: "time window" }

// W15.2: why a reference did or did not match, from the exact rows that decided it.
export function MatchEvidence({ match }) {
  const rows = [...(match.matched || []), ...(match.near || [])]
  return h("details", null, h("summary", null, matchLabels[match.status] || words(match.status)),
    h("p", { className: "runtime-note" }, `Rule: ${match.rule}.`),
    h("ul", null, ...rows.map(row => h("li", { key: `${row.kind}-${row.id}`, style: { overflowWrap: "anywhere" } },
      `${words(row.kind)} ${row.id}${row.event_id ? ` (${row.event_id})` : ""}: `,
      Object.entries(row.evidence).map(([key, value]) => `${checkWords[key] || key} ${value === true ? "agrees" : value === false ? "differs" : "unknown"}`).join(", "),
      row.difference ? ` — ${words(row.difference)}` : ""))),
    match.source_failures?.length ? h("p", { className: "runtime-note" }, `Source runs that failed in the window: ${match.source_failures.join(", ")}.`) : null)
}

export function CoverageAssessment({ assessment, onOpenReport }) {
  if (!assessment) return h("p", null, "No saved assessment is available. The reference evidence still needs review.")
  return h("div", null,
    h("p", { className: "runtime-note" }, `Retained trace cutoff: ${assessment.cutoff}. Assessment completed: ${assessment.evaluated_at}.`),
    h("p", null, "These are report-review and retained-workflow records. They do not measure global event recall."),
    ...(assessment.units || []).map(unit => h("article", { key: unit.unit_id, style: { marginTop: 16 } },
      h("h3", null, unit.source_label),
      h("p", null, `Reference review: ${words(unit.reference_state)}.`),
      h("p", null, `Evidence still needed: ${(unit.holds || []).map(words).join("; ") || "Reference qualification"}.`),
      unit.match_evidence && h(MatchEvidence, { match: unit.match_evidence }),
      ...(unit.report_refs || []).map(report => h("button", { key: report.lineage_id, type: "button", className: "btn",
        style: { minHeight: 44 }, disabled: !onOpenReport, onClick: () => onOpenReport?.(report.lineage_id) }, "Open evidence")),
      h("details", null, h("summary", null, "Retained workflow evidence"),
        h("dl", null, ...(unit.stages || []).flatMap(cell => [
          h("dt", { key: `${cell.stage}-label` }, stageLabels[cell.stage] || words(cell.stage)),
          h("dd", { key: cell.stage }, `${stateLabels[cell.state] || "Unknown"}${cell.execution_class === "archival_replay" ? " · archival replay" : ""}${cell.execution_class === "invented_fixture" ? " · invented fixture" : ""}`,
            h("span", { className: "runtime-note", style: { display: "block" } }, bindingLabels[cell.current_binding] || bindingLabels.unresolved),
            cell.reason_codes?.length ? ` — ${cell.reason_codes.map(words).join("; ")}` : "") ]))))),
    h("p", { className: "runtime-note" }, "Source availability is shown separately in Source Health. Regional memberships may overlap; they are not an additive event count."))
}

export default function CoverageEvidence({ readOnly = false, onOpenReport, initialView = null }) {
  const [view, setView] = useState(initialView)
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("Loading coverage evidence…")
  const load = useCallback(async () => {
    const response = await fetch("/api/coverage", { cache: "no-store" })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || "Coverage evidence is unavailable.")
    setView(result)
    if (result.pending_command) setPending(result.pending_command)
    setMessage(result.currentness === "refresh_required" ? "The evidence changed. The saved assessment is historical; refresh it when ready." : "Reference review is still needed before coverage can be measured.")
  }, [])
  useEffect(() => { load().catch(error => setMessage(error.message)) }, [load])
  async function requestAssessment() {
    if (busy || readOnly || !pending && !view?.ready) return
    const body = pending || coverageCommand(view)
    setPending(body)
    setBusy(true)
    try {
      const response = await fetch("/api/coverage", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      const result = await response.json()
      if (!response.ok) {
        if ([400, 401, 403, 409, 413, 415, 422].includes(response.status)) setPending(null)
        throw new Error(result.error || "Request status is unknown. Retry the same request.")
      }
      setMessage("Assessment requested. Check status to read the saved result.")
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  async function refresh() {
    if (busy) return
    setBusy(true)
    try {
      let message
      if (pending) {
        const response = await fetch(`/api/drafts?commandId=${pending.command_id}`, { cache: "no-store" })
        const result = await response.json()
        if (!response.ok) throw new Error(result.error || "Status is unavailable. Keep this request for retry.")
        if (result.status === "completed") {
          message = result.result.status === "rejected" ? result.result.message : "Assessment saved. No draft or model request was created."
          setPending(null)
        } else message = "Accepted; waiting for the saved assessment."
      }
      await load()
      if (message) setMessage(message)
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  const readiness = view?.assessment?.reference_readiness || view?.reference_readiness
  return h("section", { className: "card full", "aria-labelledby": "coverage-evidence-title", style: { marginTop: 16 } },
    h("h2", { id: "coverage-evidence-title" }, "Coverage evidence"),
    h("p", null, "Global event coverage is not yet measurable."),
    readiness && h("p", null, `${readiness.report_lineages ?? "Unknown"} retained report lineages. ${readiness.human_decisions_recorded ?? "Unknown"} recorded human decisions. A qualified event baseline and quiet-period evidence are still needed.`),
    view?.currentness === "refresh_required" && h("p", { role: "status" }, "Evidence changed — the saved assessment needs refreshing."),
    !view?.assessment && (view?.reports || []).map(report => h("p", { key: report.lineage_id },
      report.source_label, " — reference review pending. ", h("button", { type: "button", className: "btn", style: { minHeight: 44 },
        disabled: !onOpenReport, onClick: () => onOpenReport?.(report.lineage_id) }, "Open evidence"))),
    h(CoverageAssessment, { assessment: view?.assessment, onOpenReport }),
    h("div", { className: "preview-actions" },
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, disabled: busy || readOnly || !pending && !view?.ready,
        onClick: requestAssessment }, pending ? "Retry same assessment request" : "Refresh assessment"),
      h("button", { type: "button", className: "btn", style: { minHeight: 44 }, disabled: busy, onClick: refresh }, pending ? "Check status" : "View saved assessment")),
    h("p", { role: "status", "aria-live": "polite" }, message))
}
