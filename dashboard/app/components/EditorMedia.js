"use client"

import React, { useEffect, useState } from "react"
import { confirmationsFor, mediaCommand, mediaStatus, sameMediaTarget, retainedMediaBlob } from "../../lib/editor-media.js"

const h = React.createElement

export function EditorMediaPanel({ view, role, busy, imageUrl, imageError, confirmations, setConfirmations, reason, setReason, submit, refresh }) {
  const packet = view.packet, media = packet?.media
  const checks = confirmationsFor(packet)
  const accepted = !!imageUrl && Object.keys(checks).every(k => confirmations[k] === true) && !!reason.trim()
  const button = (label, action, disabled = false) => h("button", { type: "button", className: "btn sm",
    disabled: busy || role === "viewer" || disabled, style: { minHeight:44 }, onClick: () => submit(action) }, label)
  return h(React.Fragment, null,
    h("p", { role:"status", "aria-live":"polite" }, mediaStatus(view)),
    view.source_label && h("p", null, view.source_label),
    packet && h("figure", { className:"graphic-preview-figure" },
      imageUrl ? h("img", { src:imageUrl, alt:media.alt_text, width:media.width, height:media.height })
        : h("p", {role:"status"}, imageError || "Loading the retained graphic…"),
      h("figcaption", null, h("strong", null, packet.schema_version === 2 ? (packet.synthetic ? "Invented radar test image" : "Published NWS radar · human label review required") : "Invented local graphic"), h("p", null, view.text),
        packet.schema_version === 2 && h(React.Fragment, null,
          h("p", null, `KTLX · ${packet.published.frame_minute_utc} · dBZ · NATIONAL WEATHER SERVICE`),
          h("p", null, packet.published.context),
          h("p", null, `Eligible only before ${packet.published.useful_until}; status must be rechecked before any action.`),
          h("a", { href:`/api/editor-media?draftId=${encodeURIComponent(view.draft_id)}&proposal=${view.preparation.proposal_sha256}&original=1`, target:"_blank", rel:"noopener noreferrer" }, "Inspect the unchanged original at full size")) ,
        h("details", null, h("summary", null, "Read the full image description"), h("p", null, media.alt_text)))),
    packet && !view.review_current && h("fieldset", { disabled:busy || role === "viewer" || !imageUrl },
      h("legend", null, "Review text and graphic together"),
      Object.entries(checks).map(([key,label]) => h("label", { key, style:{ display:"flex", gap:10, alignItems:"flex-start", padding:"8px 0" } },
        h("input", { type:"checkbox", checked:confirmations[key] === true,
          onChange:event => setConfirmations({ ...confirmations, [key]:event.target.checked }) }), label)),
      h("label", null, "Review note", h("textarea", { value:reason, maxLength:2000, rows:3, style:{ width:"100%" },
        onChange:event => setReason(event.target.value) })),
      button(view.status === "prepared" ? "Attach reviewed graphic" : "Record new joint review",
        view.status === "prepared" ? "attach_media_revision" : "review_media_revision", !accepted)),
    h("div", { className:"draft-actions" },
      view.status === "ready" && button("Prepare graphic", "prepare_media_revision"),
      view.review_current && !view.parked && view.checks_status !== "passed" && view.checks_status !== "pending" &&
        button("Run fresh checks", "request_revision_checks"),
      view.checks_status === "passed" && !view.parked && button("Park approval locally", "approve_media_revision", role !== "publisher" || !imageUrl),
      view.parked && button("Cancel parked approval", "cancel_approval"),
      view.removal && button("Remove graphic", "remove_media_revision"),
      h("button", { type:"button", className:"btn sm", disabled:busy, style:{ minHeight:44 }, onClick:refresh }, "Refresh graphic status")),
    view.checks && h("ul", null, Object.entries(view.checks).map(([stage,status]) => h("li", { key:stage }, `${stage.replaceAll("_", " ")}: ${status}`))),
    view.checks_status && !["not_requested", "pending", "passed"].includes(view.checks_status) && h("p", { role:"status" }, view.checks_status.replaceAll("_", " ")),
    view.delivery?.scope === "local_http_fixture_v1" && view.delivery.publication_approved === false && view.delivery.intents.length > 0 &&
      h("section", { "aria-label":"Local delivery test results" }, h("h4", null, "Local delivery test"),
        h("p", null, "These receipts describe the invented local test only. They do not authorize publishing."),
        view.delivery.intents.map((intent, index) => h("div", { key:intent.intent_id },
          h("p", null, `Review ${index + 1}: ${intent.current ? "current" : "no longer current; no new delivery steps"}.`),
          h("ul", null, Object.entries(intent.stages).flatMap(([platform, stages]) => Object.entries(stages).map(([stage, receipt]) =>
            h("li", { key:`${platform}-${stage}` }, `${platform === "x" ? "X" : "Bluesky"} ${stage === "alt" ? "image description" : stage === "upload" ? "image upload" : "post creation"}: ${
              ({ pending:"waiting", confirmed:"confirmed by the local test", not_sent:"not sent", unknown:"outcome unknown; automatic retry blocked" })[receipt.status] || "unavailable"}`))))))),
    h("p", { className:"graphic-preview-note" }, "Human review and model checks are separate. Model cost remains unknown until reconciled. Publishing stays unavailable."))
}

export function EditorMedia({ draft, editing, updating, submitCommand }) {
  const [view, setView] = useState(null), [error, setError] = useState(""), [serial, setSerial] = useState(0)
  const [confirmations, setConfirmations] = useState({}), [reason, setReason] = useState("")
  const [image, setImage] = useState(null), [imageError, setImageError] = useState("")
  const currentView = view && sameMediaTarget(view, draft) ? view : null
  useEffect(() => {
    const control = new AbortController()
    setView(null); setError(""); setConfirmations({}); setReason("")
    if (!editing && !updating) {
      fetch(`/api/editor-media?draftId=${encodeURIComponent(draft.id)}`, { cache:"no-store", signal:control.signal })
        .then(async response => {
          const value = await response.json()
          if (!response.ok || !sameMediaTarget(value, draft)) throw new Error("Refresh the draft before reviewing its graphic.")
          if (!control.signal.aborted) setView(value)
        }).catch(error => { if (!control.signal.aborted) setError(error.message) })
    }
    return () => control.abort()
  }, [draft.id, draft.revision_identity, draft.operator_role, editing, updating, serial])
  useEffect(() => {
    const control = new AbortController()
    let url
    setImage(null); setImageError("")
    if (currentView?.packet && !editing && !updating) {
      retainedMediaBlob(currentView, control.signal).then(blob => {
        if (control.signal.aborted) return
        url=URL.createObjectURL(blob)
        setImage({ view:currentView, url })
      }).catch(error => { if(!control.signal.aborted) setImageError(error.message) })
    }
    return () => { control.abort(); if(url) URL.revokeObjectURL(url) }
  }, [currentView, draft.operator_role, editing, updating])
  if (!draft.local_preview || !["fire", "air_quality_hazard", "severe_weather"].includes(draft.type)) return null
  return h("section", { className:"graphic-preview", "aria-label":"Local text and graphic review", style:{ overflowWrap:"anywhere" } },
    h("h3", null, "Text and graphic"),
    editing || updating ? h("p", { role:"status" }, editing ? "Save or cancel the text edit before reviewing a graphic." : "Waiting for the local action to finish. Previous review controls are paused.")
      : error ? h("div", { role:"alert" }, h("p", null, error), h("button", { type:"button", className:"btn sm", onClick:()=>setSerial(n=>n+1) }, "Retry status"))
      : !currentView ? h("p", { role:"status" }, "Loading current graphic status…")
      : h(EditorMediaPanel, { view:currentView, role:draft.operator_role, busy:updating, imageUrl:image?.view === currentView ? image.url : null, imageError, confirmations, setConfirmations, reason, setReason,
        refresh:()=>setSerial(n=>n+1), submit:action => submitCommand({ command:mediaCommand(view, action,
          { decision:"accept", confirmations, reason }), draftId:draft.id, action }) }))
}
