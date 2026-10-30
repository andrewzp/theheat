"use client"

import React, { useEffect, useRef, useState } from "react"
import manifest from "../../lib/graphic-runtime-manifest.json" with { type: "json" }
import { createGraphicPreviewController, deliveredPNGRequest } from "../../lib/graphic-preview.js"
import { FullSizeImage, Hot10Rows } from "./GraphicPreview.js"

const h = React.createElement
const utc = value => typeof value === "string" ? value.slice(0, 16).replace("T", " ") + " UTC" : "time unknown"

async function defaultLoad() {
  const response = await fetch("/api/drafts?delivered=1", { cache: "no-store", credentials: "same-origin" })
  if (!response.ok) throw new Error("Delivered graphics are unavailable")
  const value = await response.json()
  return Array.isArray(value.delivered) ? value.delivered : []
}

// What was actually delivered: the receipt-named snapshot, rebuilt and checked byte-for-byte.
export function DeliveredFigure({ value, url }) {
  const receipt = value.delivered, context = value.source_context
  return h("figure", { className: "graphic-preview-figure" },
    h("img", { src: url, alt: value.delivery_text, width: value.width, height: value.height }),
    h(FullSizeImage, { url, alt: value.delivery_text, title: value.title }),
    h("figcaption", null,
      h("strong", null, value.title),
      h("p", { className: "graphic-kind" }, `Delivered X post ${receipt.tweet_id} · ${utc(receipt.confirmed_at)} · revision ${receipt.content_revision}`),
      h("div", { className: "graphic-full-description" }, h("strong", null, "Posted text"), h("p", null, receipt.text)),
      h("div", { className: "graphic-full-description" }, h("strong", null, "Image description sent to X"), h("p", null, value.delivery_text)),
      h("p", null, `Rebuilt from the delivered recipe; PNG SHA256 ${value.png_sha256} matches what was sent. Later edits to the current draft do not change this snapshot.`),
      // Published originals (radar/cone) carry their attribution instead of a native source line.
      h("p", null, `${value.source ?? value.inspection?.attribution ?? "Retained published image"} · ${value.scope}`),
      value.original_sha256 && h("p", null, `Original as retained: SHA256 ${value.original_sha256} (${value.original_mime}); X received the pixel-equivalent PNG above.`),
      context?.kind === "hot10_bulletin" && h(Hot10Rows, { context }),
      h("details", null, h("summary", null, "Expanded source details (not sent)"), h("p", { style: { whiteSpace: "pre-wrap" } }, value.expanded_description))))
}

export function DeliveredGraphics({ load = defaultLoad, refreshKey = null }) {
  const [items, setItems] = useState(null)
  const [selected, setSelected] = useState(null)
  const [preview, setPreview] = useState({ status: "idle" })
  const controller = useRef(null)
  useEffect(() => {
    const instance = createGraphicPreviewController({ manifest, onChange: setPreview })
    controller.current = instance
    return () => { instance.dispose(); controller.current = null }
  }, [])
  useEffect(() => {
    let live = true
    load().then(value => { if (live) setItems(value) }).catch(() => { if (live) setItems([]) })
    return () => { live = false }
  }, [load, refreshKey])
  const inspect = item => {
    const request = deliveredPNGRequest(item, manifest)
    if (!request) return
    setSelected(item.id)
    controller.current?.start(request)
  }
  return h("section", { className: "graphic-preview delivered-graphics", "aria-label": "Delivered graphics" },
    h("h3", null, "Delivered posts with graphics"),
    h("p", { className: "graphic-preview-note" }, "Exactly what was sent, rebuilt from its retained recipe. Inspection only: nothing is fetched, approved or sent from here."),
    items === null ? h("p", { role: "status" }, "Loading delivered posts…")
      : items.length === 0 ? h("p", null, "No delivered post with a graphic is retained.")
      : h("ul", { className: "delivered-graphics-list" }, items.map(item => h("li", { key: item.id },
        h("p", null, h("strong", null, `${item.type} · X post ${item.delivered.tweet_id}`), ` · ${utc(item.delivered.confirmed_at)}`),
        item.delivered.text && h("p", { className: "draft-text" }, item.delivered.text),
        item.status !== "posted" && h("p", { className: "runtime-note" }, "The current draft changed after this delivery; the snapshot below is the delivered revision."),
        h("button", { type: "button", className: "btn sm", disabled: preview.status === "loading" || !deliveredPNGRequest(item, manifest),
          "aria-expanded": selected === item.id && preview.status === "ready", onClick: () => inspect(item) },
          selected === item.id && preview.status === "ready" ? "Rebuild delivered graphic" : "Inspect delivered graphic")))),
    h("div", { role: "status", "aria-live": "polite" },
      preview.status === "loading" ? "Rebuilding the delivered graphic…" : preview.status !== "error" ? ""
        : preview.hold === "media_renderer_changed"
          ? "The renderer changed since this delivery, so its exact bytes cannot be rebuilt here. The posted text and receipt above are unchanged."
          : preview.message),
    preview.status === "ready" && preview.value.draft_id === selected && h(DeliveredFigure, { value: preview.value, url: preview.url }))
}
