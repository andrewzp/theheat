"use client"
// Operations: inspect publish attempts and confirm/cancel one with receipt evidence.
// Self-contained; mounts beside the existing Operations views (see LANE-COST.md).
import React, { useEffect, useState } from "react"
const h = React.createElement
const ENDPOINT = "/api/delivery-reconciliation"

const PHASE = {
  confirmed: "Delivered (receipt on record)", unknown: "Outcome unknown — needs a receipt",
  submitted: "Submitted — outcome unknown", not_sent: "Not sent (proven)", legacy_unknown: "Legacy attempt — outcome unknown",
  malformed: "Unreadable evidence (preserved)",
}
const HOLD = {
  receipt_required_unknown_stays_unknown: "Stays unknown until a matching receipt is supplied. Timing or silence is never proof.",
  attempt_conflicts_require_review: "Conflicting attempts are recorded; review them before any action.",
  draft_missing_or_ambiguous: "The draft for this attempt is missing or duplicated.",
  malformed_evidence_preserved: "This evidence cannot be read; it is kept unchanged.",
}
const REFUSAL = {
  receipt_text_mismatch: "That post's text is not the text this attempt sent.",
  receipt_bound_elsewhere: "That post ID already belongs to another attempt.",
  receipt_predates_attempt: "That post was created before this attempt.",
  receipt_media_mismatch: "That post's image description does not match this attempt.",
  stale_decision_revision: "The draft changed. Refresh before reconciling.",
  source_snapshot_changed: "The source evidence changed since this attempt.",
  delivered_content_retained: "Delivered posts cannot be cancelled.",
  delivery_reconciliation_disabled: "Reconciliation writes are turned off for this dashboard.",
  revision_conflict: "This attempt changed while you were working. Refresh.",
}
export const refusalMessage = code => REFUSAL[code] || "Reconciliation was refused. Nothing changed."

function Row({ row, onSubmit }) {
  const [tweetId, setTweetId] = useState("")
  const [createdAt, setCreatedAt] = useState("")
  const [text, setText] = useState("")
  const [altText, setAltText] = useState("")
  const base = { event_id: row.event_id, intent_id: row.intent_id, expected_decision_revision: row.decision_revision,
    expected_evidence_sha256: row.evidence_sha256, reason: "Operator reconciliation" }
  const id = action => `${action}:${row.event_id}:${row.intent_id}:${row.decision_revision}`
  return h("li", { className: "delivery-reconciliation-row", "data-event": row.event_id },
    h("strong", null, PHASE[row.phase] || row.phase),
    h("span", null, ` ${row.event_id}`), row.tweet_id ? h("span", null, ` · post ${row.tweet_id}`) : null,
    row.cancelled ? h("span", null, " · intent cancelled; evidence kept") : null,
    row.hold ? h("p", { className: "delivery-reconciliation-hold" }, HOLD[row.hold] || row.hold) : null,
    row.actions.includes("confirm") ? h("form", { onSubmit: event => { event.preventDefault()
      onSubmit({ ...base, reconciliation_id: id("confirm"), action: "confirm",
        receipt: { tweet_id: tweetId, text, created_at: createdAt, ...(row.delivery_identity?.alt_sha256 ? { alt_text: altText } : {}) } }) } },
      h("input", { "aria-label": "Post ID", value: tweetId, onChange: e => setTweetId(e.target.value) }),
      h("input", { "aria-label": "Post text exactly as published", value: text, onChange: e => setText(e.target.value) }),
      h("input", { "aria-label": "Post created at (UTC)", value: createdAt, onChange: e => setCreatedAt(e.target.value) }),
      row.delivery_identity?.alt_sha256 ? h("input", { "aria-label": "Image description as published", value: altText, onChange: e => setAltText(e.target.value) }) : null,
      h("button", { type: "submit" }, "Confirm with receipt")) : null,
    row.actions.includes("cancel") ? h("button", { type: "button", onClick: () => onSubmit({ ...base, reconciliation_id: id("cancel"), action: "cancel" }) },
      "Cancel this intent") : null)
}

export default function DeliveryReconciliation({ initial = null }) {
  const [view, setView] = useState(initial)
  const [notice, setNotice] = useState(null)
  const load = () => fetch(ENDPOINT, { cache: "no-store" }).then(r => r.json()).then(setView).catch(() => setNotice("Attempts are unavailable right now."))
  useEffect(() => { if (!initial) load() }, [])
  const submit = async body => {
    const response = await fetch(ENDPOINT, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
    const payload = await response.json().catch(() => ({}))
    setNotice(response.ok ? (payload.status === "unchanged" ? "Already recorded." : "Recorded.") : refusalMessage(payload.code))
    load()
  }
  const rows = (view?.rows || []).filter(row => row.phase !== "confirmed" || row.reconciliation)
  return h("section", { className: "delivery-reconciliation", "aria-label": "Publish attempt reconciliation" },
    h("h3", null, "Publish attempts"),
    notice ? h("p", { role: "status" }, notice) : null,
    rows.length ? h("ul", null, rows.map(row => h(Row, { key: row.event_id, row, onSubmit: submit })))
      : h("p", null, view ? "No attempt needs reconciliation." : "Loading attempts…"))
}
