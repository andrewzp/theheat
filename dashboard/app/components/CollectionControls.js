"use client"
import { createElement as h, useEffect, useState } from "react"
import { collectionAvailability, COLLECTION_STATUS_MAX_AGE_MS } from "../../lib/collection-control.js"

export default function CollectionControls({ observation, triggering, result, onTrigger }) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!observation) return
    const remaining = observation.observedAt + COLLECTION_STATUS_MAX_AGE_MS - Date.now()
    if (remaining <= 0) return
    const timer = setTimeout(() => tick(value => value + 1), remaining + 1)
    return () => clearTimeout(timer)
  }, [observation])
  const availability = collectionAvailability(observation)
  return h("section", { className: "card full", style: { marginBottom: 16 }, "aria-label": "Generate drafts" },
    h("h2", null, "Generate Drafts"),
    h("p", { id: "collection-availability", className: "runtime-note", role: "status" }, availability.message),
    h("div", { className: "trigger-bar", "aria-describedby": "collection-availability" },
      [["both", "Run Both"], ["alerts", "Alerts Only"], ["leaderboard", "Leaderboard Only"]].map(([mode, label]) =>
        h("button", { key: mode, type: "button", className: mode === "both" ? "btn primary" : "btn",
          disabled: Boolean(triggering) || !availability.allowed, onClick: () => onTrigger(mode) }, triggering === mode ? "…" : label)),
      result ? h("span", { className: "trigger-result", role: "status" }, result) : null))
}
