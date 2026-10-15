"use client"

import React, { useEffect, useRef, useState } from "react"
import { deliveryHistoryKey, loadDeliveryContent } from "../../lib/delivery-history.js"

const h = React.createElement

export function DeliveryContentCard({ detail, imageUrl }) {
  return h("article", { id:`delivery-history-${detail.intent_id}`, style:{ maxWidth:"100%", overflowWrap:"anywhere" } },
    h("h5", null, "Earlier local delivery content"),
    h("p", null, "Historical content — does not approve this draft."),
    h("p", null, detail.synthetic ? "Invented local test content" : "Retained local content; no production publication authorization"),
    h("p", { style:{ whiteSpace:"pre-wrap" } }, detail.text),
    h("figure", { style:{ margin:0 } }, h("img", { src:imageUrl, alt:detail.media.alt_text,
      width:detail.media.width, height:detail.media.height, style:{ maxWidth:"100%", height:"auto" } }),
      h("figcaption", null, `Earlier local approval recorded ${detail.approved_at}.`)),
    h("details", null, h("summary", { style:{ minHeight:44 } }, "Read the full earlier image description"),
      h("p", { style:{ whiteSpace:"pre-wrap" } }, detail.media.alt_text)))
}

export function DeliveryHistory({ view, draft, busy }) {
  const [selected, setSelected] = useState(null), [serial, setSerial] = useState(0), [result, setResult] = useState(null)
  const key = deliveryHistoryKey(draft), requestKey = JSON.stringify([key, selected, serial, !!busy])
  const latest = useRef(requestKey)
  latest.current = requestKey
  useEffect(() => {
    const control = new AbortController()
    let url
    setResult(null)
    if (key && selected && !busy) {
      loadDeliveryContent(draft, selected, control.signal).then(({ detail, blob }) => {
        if (control.signal.aborted || latest.current !== requestKey) return
        url = URL.createObjectURL(blob)
        setResult({ key:requestKey, detail, url })
      }).catch(() => {
        if (!control.signal.aborted && latest.current === requestKey)
          setResult({ key:requestKey, error:"Earlier local delivery content is unavailable. The saved stage history remains visible." })
      })
    }
    return () => { control.abort(); if (url) URL.revokeObjectURL(url) }
  }, [requestKey])
  const current = result?.key === requestKey ? result : null
  return h("section", { "aria-label":"Local delivery test results" }, h("h4", null, "Local delivery test"),
    h("p", null, "These receipts describe the invented local test only. They do not authorize publishing."),
    view.delivery.intents.map((intent, index) => h("div", { key:intent.intent_id },
      h("p", null, `Review ${index + 1}: ${intent.current ? "current" : "no longer current; no new delivery steps"}.`),
      h("ul", null, Object.entries(intent.stages).flatMap(([platform, stages]) => Object.entries(stages).map(([stage, receipt]) =>
        h("li", { key:`${platform}-${stage}` }, `${platform === "x" ? "X" : "Bluesky"} ${stage === "alt" ? "image description" : stage === "upload" ? "image upload" : "post creation"}: ${
          ({ pending:"waiting", confirmed:"confirmed by the local test", not_sent:"not sent", unknown:"outcome unknown; automatic retry blocked" })[receipt.status] || "unavailable"}`)))),
      key && h("button", { type:"button", className:"btn sm", disabled:busy, style:{ minHeight:44 },
        "aria-expanded":selected === intent.intent_id, "aria-controls":`delivery-history-${intent.intent_id}`,
        onClick:() => setSelected(previous => previous === intent.intent_id ? null : intent.intent_id) },
      selected === intent.intent_id ? "Hide earlier content" : `View earlier content for review ${index + 1}`))),
    selected && key && !busy && (current?.detail ? h(DeliveryContentCard, { detail:current.detail, imageUrl:current.url })
      : current?.error ? h("div", { role:"alert", id:`delivery-history-${selected}` }, h("p", null, current.error),
        h("button", { type:"button", className:"btn sm", style:{ minHeight:44 }, onClick:() => setSerial(n => n + 1) }, "Retry earlier content"))
        : h("p", { role:"status", id:`delivery-history-${selected}` }, "Loading earlier local delivery content…")))
}
