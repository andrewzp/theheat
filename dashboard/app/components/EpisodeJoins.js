"use client"

import React, { useEffect, useState } from "react"

const h = React.createElement
const human = value => String(value ?? "").replaceAll("_", " ")

// Exact request body for one episode correction; expectedRevision is the draft revision on screen.
export function episodeRequest(draft, action, payload = {}) {
  return { action, draftId: draft.id, expectedRevision: draft.revision_identity, ...payload }
}

async function send(fetchImpl, body) {
  const response = await fetchImpl("/api/episodes", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) })
  const value = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(value.error || "The correction was not saved.")
  return value
}

// Mount with key=draft id + revision identity so a saved change reloads the view.
export function EpisodeJoins({ draft, initialView = null, onChanged = null, fetchImpl = globalThis.fetch }) {
  const [view, setView] = useState(initialView)
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [splitId, setSplitId] = useState("")
  const [target, setTarget] = useState("")
  useEffect(() => {
    if (initialView || !draft?.id) return
    let live = true
    fetchImpl(`/api/episodes?draftId=${encodeURIComponent(draft.id)}`, { cache: "no-store" })
      .then(response => response.json().then(value => ({ ok: response.ok, value })))
      .then(({ ok, value }) => { if (live) ok ? setView(value) : setMessage(value.error || "Episode details are unavailable.") })
      .catch(() => { if (live) setMessage("Episode details are unavailable.") })
    return () => { live = false }
  }, [draft?.id, initialView, fetchImpl])
  if (!view) return message ? h("p", { className: "text-muted" }, message) : null
  const run = async (action, payload, confirmText) => {
    if (confirmText && typeof window !== "undefined" && !window.confirm(confirmText)) return
    setBusy(true); setMessage("")
    try {
      const result = await send(fetchImpl, episodeRequest(draft, action, payload))
      setView(result.view)
      setMessage("Saved. Review and approval were cleared; review this draft again.")
      onChanged?.(result)
    } catch (error) { setMessage(error.message) } finally { setBusy(false) }
  }
  if (!view.bound) {
    return h("section", { className: "forecast-evidence", "aria-label": "Physical episode" },
      h("h3", null, "Physical episode"), h("p", { className: "text-muted" }, view.message),
      view.hold ? h("p", null, `Identity gap: ${human(view.hold)}.`) : null)
  }
  const disabled = busy || !view.editable
  return h("section", { className: "forecast-evidence", "aria-label": "Physical episode", style: { overflowWrap: "anywhere", minWidth: 0 } },
    h("h3", null, "Physical episode"),
    h("dl", null,
      h("dt", null, "Episode"), h("dd", null, h("code", null, view.identity.episode_id),
        view.status !== "active" ? ` (${human(view.status)}${view.superseded_by ? ` by ${view.superseded_by}` : ""})` : ""),
      h("dt", null, "Source revision"), h("dd", null, h("code", null, String(view.identity.source_revision ?? "").slice(0, 12))),
      h("dt", null, "Candidate"), h("dd", null, h("code", null, view.identity.candidate_id)),
      h("dt", null, "Publication"), h("dd", null, view.identity.publication.tweet_id ? `posted (${view.identity.publication.tweet_id})` : `draft ${view.identity.publication.draft_id}`),
      h("dt", null, "Why this is a writer opportunity"), h("dd", null, view.admission.eligibility.map(human).join(", ") || "not recorded",
        view.admission.update_of ? `; updates revision ${String(view.admission.update_of).slice(0, 12)}` : "")),
    view.same_episode.length > 0 && h("div", null, h("h4", null, "Joined in this episode"),
      h("ul", null, view.same_episode.map(row => h("li", { key: row.draft_id }, h("strong", null, row.draft_id), ` (${row.status}): ${row.why}`)))),
    view.separate.length > 0 && h("div", null, h("h4", null, "Kept separate"),
      h("ul", null, view.separate.map(row => h("li", { key: row.draft_id }, h("strong", null, row.draft_id), ` (${row.status}): ${row.why}`)))),
    view.report_joins.length > 0 && h("div", null, h("h4", null, "Report joins"),
      h("p", { className: "text-muted" }, "Only matched statements reach the writer, each with its own attribution and time. The original report stays in the private archive; removing a join keeps it there."),
      h("ul", null, view.report_joins.map(row => h("li", { key: row.join_id, "data-join-status": row.removed ? "removed" : row.status },
        h("strong", null, row.removed ? "Removed" : row.status === "matched" ? "Matched" : "Report claim only"),
        row.statement ? ` — “${row.statement}”${row.attribution ? ` (${row.attribution})` : ""}` : "",
        ` — ${human(row.reason)}; report ${String(row.report_sha256 ?? "").slice(0, 12)}`,
        !row.removed && h("button", { type: "button", className: "btn btn-ghost", disabled, style: { minHeight: 44, marginLeft: 8 },
          onClick: () => run("remove_join", { joinId: row.join_id }, "Remove this join? Review and approval of this draft will be cleared.") },
        "Remove join"))))),
    view.editable && h("div", null, h("h4", null, "Correct this episode"),
      h("label", null, "Split into a new episode ID ",
        h("input", { value: splitId, onChange: event => setSplitId(event.target.value), disabled, "aria-label": "New episode source ID" })),
      h("button", { type: "button", className: "btn btn-ghost", disabled: disabled || !splitId, style: { minHeight: 44 },
        onClick: () => run("split", { newSourceId: splitId }, "Split this draft into a new episode? Its joins stay in history and review is cleared.") }, "Split"),
      view.supersede_targets.length > 0 && h("label", null, " Superseded by ",
        h("select", { value: target, onChange: event => setTarget(event.target.value), disabled, "aria-label": "Superseding episode" },
          h("option", { value: "" }, "Choose an episode"), view.supersede_targets.map(id => h("option", { key: id, value: id }, id)))),
      view.supersede_targets.length > 0 && h("button", { type: "button", className: "btn btn-ghost", disabled: disabled || !target, style: { minHeight: 44 },
        onClick: () => run("supersede", { supersededBy: target }, "Mark this episode superseded? Review is cleared.") }, "Supersede")),
    !view.editable && h("p", { className: "text-muted" }, "Delivered or unreconciled drafts keep their snapshot; corrections apply only to pending drafts."),
    message && h("p", { role: "status" }, message))
}
