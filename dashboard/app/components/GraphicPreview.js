"use client"

import React, { useEffect, useRef, useState } from "react"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, firePreviewSourceStatus, graphicRequest, graphicRequestKey,
  isTemperaturePreviewType, temperaturePNGRequest, temperaturePreviewSourceStatus } from "../../lib/graphic-preview.js"

const h = React.createElement

export function GraphicPreviewFigure({ value, url }) {
  const context = value.source_context
  const timing = context.kind === "pm25_forecast_day"
    ? `${context.valid_date} · ${context.timezone} · model forecast`
    : context.kind === "ghcn_station_day"
      ? `Station ${context.station_id} · ${context.valid_date} source-calendar date · observed; reporting interval and timezone unknown`
    : `${context.acquired_at.slice(0, 16).replace("T", " ")} UTC (minute precision)`
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.alt_text, width: value.width, height: value.height }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", null, `${value.source} · ${timing}`),
      context.kind === "ghcn_station_day" && h("p", null, `Archive retrieved ${context.retrieved_at}; comparison uses accepted source samples, not a certified record.`),
      h("p", null, value.scope),
      value.schema_version === 3
        ? h("div", { className: "graphic-full-description" }, h("strong", null, "Full graphic description"), h("p", null, value.alt_text))
        : h("details", null, h("summary", null, "Read the full graphic description"), h("p", null, value.alt_text))))
}

const FIRE_LABELS = { modis: "MODIS", viirs: "NOAA-20/NOAA-21 VIIRS" }

export function TemperatureMediaControls({ draft, preview, reviewConfirmed, onConfirm, onAction }) {
  const attached = draft.media_attachment_sha256
  const present = Object.hasOwn(draft, "media_attachment") || typeof attached === "string"
  const ready = preview.status === "ready" && preview.value?.schema_version === 3
  const mediaSha = ready ? preview.value.media_descriptor_sha256 : null
  const matching = ready && typeof attached === "string" && /^[a-f0-9]{64}$/.test(attached) && attached === mediaSha
  const mutable = ["pending", "approved"].includes(draft.status) && !draft.publish_blocked
    && draft.review_status !== "conflict" && !draft.revision_conflicts?.length
  const canReview = matching && mutable && draft.status === "pending"
    && /^[a-f0-9]{64}$/.test(draft.editorial_policy?.policy_sha256 ?? "")
  const expectedRevision = draft.revision_identity
  return h("div", { className: "temperature-media-controls" },
    present ? h(React.Fragment, null,
      h("p", null, matching ? "This image and description are attached to the saved draft."
        : "Build the current preview to inspect the attached image and description."),
      h("button", { type: "button", className: "btn sm", disabled: !mutable || !onAction,
        onClick: () => onAction?.("remove_graphic", { expectedRevision }) }, "Remove graphic"))
      : ready && h("button", { type: "button", className: "btn sm", disabled: !mutable || !onAction,
        onClick: () => onAction?.("attach_graphic", { expectedRevision, expectedMediaSha256: mediaSha }) }, "Attach graphic"),
    canReview && h("div", { className: "workbench-panel", "aria-label": "Review text and attached graphic" },
      h("h3", null, "Review this text and graphic"),
      h("p", { className: "draft-text" }, draft.text),
      h("p", null, "Check this exact text, the image above and its full description against the saved source evidence."),
      h("label", null, h("input", { type: "checkbox", checked: reviewConfirmed, disabled: !onAction,
        onChange: event => onConfirm(event.target.checked) }), " I checked the exact text, image and full graphic description."),
      h("button", { type: "button", className: "btn sm", disabled: !reviewConfirmed || !onAction,
        onClick: () => reviewConfirmed && onAction?.("review", { reviewConfirmed: true, mediaReviewConfirmed: true,
          expectedMediaSha256: mediaSha, expectedPolicySha256: draft.editorial_policy.policy_sha256,
          expectedRevision }) }, "Record joint review")))
}

function SavedPreview({ request, forecast, fireSource, temperature, draft, onAction }) {
  const [preview, setPreview] = useState({ status: "idle" })
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const controller = useRef(null)
  useEffect(() => {
    const instance = createGraphicPreviewController({ manifest, onChange: state => {
      setReviewConfirmed(false)
      setPreview(state)
    } })
    controller.current = instance
    return () => { instance.dispose(); controller.current = null }
  }, [])
  return h(React.Fragment, null,
    h("p", null, forecast ? "Build a chart from the saved PM2.5 model forecast. No new source fetch or AI generation."
      : temperature ? "Compare the saved observed station reading with its qualified archive samples. No new source fetch or AI generation."
      : `Preview the saved ${FIRE_LABELS[fireSource]} detections. Source and display checks can still withhold the graphic. No new source fetch or AI generation.`),
    h("button", { type: "button", className: "btn sm", disabled: preview.status === "loading",
      onClick: () => controller.current?.start(request) }, preview.status === "ready" ? "Rebuild preview" : "Preview graphic"),
    h("div", { role: "status", "aria-live": "polite" },
      preview.status === "loading" ? "Building the saved-source preview…" : preview.status === "error" ? preview.message : ""),
    preview.status === "ready" && h(GraphicPreviewFigure, { value: preview.value, url: preview.url }),
    temperature && h(TemperatureMediaControls, { draft, preview, reviewConfirmed, onConfirm: setReviewConfirmed, onAction }))
}

export function GraphicPreview({ draft, editing = false, updating = false, onAction }) {
  const temperature = isTemperaturePreviewType(draft?.type)
  if (!["fire", "air_quality_hazard"].includes(draft?.type) && !temperature) return null
  const forecast = draft.type === "air_quality_hazard"
  const missingWindow = forecast && !draft.review_context?.two_bot?.bundle?.raw_signal_dump?.forecast_window
  const fireSource = draft.type === "fire" ? firePreviewSourceStatus(draft) : null
  const temperatureSource = temperature ? temperaturePreviewSourceStatus(draft) : null
  const request = temperature ? temperaturePNGRequest(draft, manifest) : graphicRequest(draft, manifest)
  return h("section", { className: "graphic-preview", "aria-label": "Saved-source graphic preview" },
    h("h3", null, "Saved-source preview"),
    h("p", { className: "graphic-preview-note" }, temperature
      ? `${Object.hasOwn(draft, "media_attachment") || draft.media_attachment_sha256 ? "A graphic is attached; review its current preview below." : "Preview only; not attached or approved."} Build the saved-source image, attach it, then review the text and graphic together.`
      : "Preview only; not attached or approved."),
    updating ? h("p", null, "Updating this draft. Build a new preview after it finishes.")
      : editing ? h("p", null, "Save or cancel your text edit before building a preview.")
      : !request ? h("p", null, "Refresh the saved draft and resolve any conflicting versions before previewing.")
        : missingWindow ? h("p", null, "The hourly forecast was not saved with this draft. A graphic is unavailable.")
          : temperature && temperatureSource !== "ghcn" ? h("p", null, "Qualified observed GHCN station evidence was not retained with this draft. No comparison preview is available.")
          : fireSource === "missing" ? h("p", null, "Saved fire source receipts are missing or incomplete. No graphic preview is available for this draft.")
          : fireSource === "unsupported" ? h("p", null, "This fire preview supports MODIS or NOAA-20/NOAA-21 VIIRS receipts from one product only. The saved source set is unsupported; no preview is available.")
          : h(SavedPreview, { key: `${draft.type}:${draft.status}:${graphicRequestKey(request)}`, request, forecast, fireSource, temperature, draft, onAction }),
    temperature && Object.hasOwn(draft, "media_attachment") && !editing && !updating
      && (!request || temperatureSource !== "ghcn")
      && h(TemperatureMediaControls, { draft, preview: { status: "idle" }, reviewConfirmed: false, onConfirm() {}, onAction }))
}
