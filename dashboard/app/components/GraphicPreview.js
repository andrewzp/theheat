"use client"

import React, { useEffect, useRef, useState } from "react"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, firePreviewSourceStatus, graphicRequest, graphicRequestKey } from "../../lib/graphic-preview.js"

const h = React.createElement

export function GraphicPreviewFigure({ value, url }) {
  const context = value.source_context
  const timing = context.kind === "pm25_forecast_day"
    ? `${context.valid_date} · ${context.timezone} · model forecast`
    : `${context.acquired_at.slice(0, 16).replace("T", " ")} UTC (minute precision)`
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.alt_text, width: value.width, height: value.height }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", null, `${value.source} · ${timing}`),
      h("p", null, value.scope),
      h("details", null, h("summary", null, "Read the full graphic description"), h("p", null, value.alt_text))))
}

function SavedPreview({ request, forecast }) {
  const [preview, setPreview] = useState({ status: "idle" })
  const controller = useRef(null)
  useEffect(() => {
    const instance = createGraphicPreviewController({ manifest, onChange: setPreview })
    controller.current = instance
    return () => { instance.dispose(); controller.current = null }
  }, [])
  return h(React.Fragment, null,
    h("p", null, forecast ? "Build a chart from the saved PM2.5 model forecast. No new source fetch or AI generation."
      : "Preview the saved MODIS detections. Source and display checks can still withhold the graphic. No new source fetch or AI generation."),
    h("button", { type: "button", className: "btn sm", disabled: preview.status === "loading",
      onClick: () => controller.current?.start(request) }, preview.status === "ready" ? "Rebuild preview" : "Preview graphic"),
    h("div", { role: "status", "aria-live": "polite" },
      preview.status === "loading" ? "Building the saved-source preview…" : preview.status === "error" ? preview.message : ""),
    preview.status === "ready" && h(GraphicPreviewFigure, { value: preview.value, url: preview.url }))
}

export function GraphicPreview({ draft, editing = false, updating = false }) {
  if (!["fire", "air_quality_hazard"].includes(draft?.type)) return null
  const forecast = draft.type === "air_quality_hazard"
  const missingWindow = forecast && !draft.review_context?.two_bot?.bundle?.raw_signal_dump?.forecast_window
  const fireSource = forecast ? null : firePreviewSourceStatus(draft)
  const request = graphicRequest(draft, manifest)
  return h("section", { className: "graphic-preview", "aria-label": "Saved-source graphic preview" },
    h("h3", null, "Saved-source preview"),
    h("p", { className: "graphic-preview-note" }, "Preview only; not attached or approved."),
    updating ? h("p", null, "Updating this draft. Build a new preview after it finishes.")
      : editing ? h("p", null, "Save or cancel your text edit before building a preview.")
      : !request ? h("p", null, "Refresh the saved draft and resolve any conflicting versions before previewing.")
        : missingWindow ? h("p", null, "The hourly forecast was not saved with this draft. A graphic is unavailable.")
          : fireSource === "missing" ? h("p", null, "Saved MODIS source receipts are missing or incomplete. No graphic preview is available for this draft.")
          : fireSource === "unsupported" ? h("p", null, "This fire preview supports MODIS source receipts only. The saved source set is unsupported; no preview is available.")
          : h(SavedPreview, { key: `${draft.type}:${draft.status}:${graphicRequestKey(request)}`, request, forecast }))
}
