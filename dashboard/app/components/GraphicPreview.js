"use client"

import React, { useEffect, useRef, useState } from "react"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, graphicRequest, graphicRequestKey } from "../../lib/graphic-preview.js"

const h = React.createElement

export function GraphicPreviewFigure({ value, url }) {
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.alt_text, width: value.width, height: value.height }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", null, `${value.source} · ${value.source_time.slice(0, 16).replace("T", " ")} UTC (minute precision)`),
      h("p", null, value.scope),
      h("details", null, h("summary", null, "Read the full graphic description"), h("p", null, value.alt_text))))
}

function SavedPreview({ request }) {
  const [preview, setPreview] = useState({ status: "idle" })
  const controller = useRef(null)
  useEffect(() => {
    const instance = createGraphicPreviewController({ manifest, onChange: setPreview })
    controller.current = instance
    return () => { instance.dispose(); controller.current = null }
  }, [])
  return h(React.Fragment, null,
    h("p", null, "Build a chart from the saved MODIS detections. No new source fetch or AI generation."),
    h("button", { type: "button", className: "btn sm", disabled: preview.status === "loading",
      onClick: () => controller.current?.start(request) }, preview.status === "ready" ? "Rebuild preview" : "Preview graphic"),
    h("div", { role: "status", "aria-live": "polite" },
      preview.status === "loading" ? "Building the saved-source preview…" : preview.status === "error" ? preview.message : ""),
    preview.status === "ready" && h(GraphicPreviewFigure, { value: preview.value, url: preview.url }))
}

export function GraphicPreview({ draft, editing = false, updating = false }) {
  if (draft?.type !== "fire") return null
  const request = graphicRequest(draft, manifest)
  return h("section", { className: "graphic-preview", "aria-label": "Saved-source graphic preview" },
    h("h3", null, "Saved-source preview"),
    h("p", { className: "graphic-preview-note" }, "Preview only; not attached or approved."),
    updating ? h("p", null, "Updating this draft. Build a new preview after it finishes.")
      : editing ? h("p", null, "Save or cancel your text edit before building a preview.")
      : !request ? h("p", null, "Refresh the saved draft and resolve any conflicting versions before previewing.")
        : h(SavedPreview, { key: `${draft.status}:${graphicRequestKey(request)}`, request }))
}
