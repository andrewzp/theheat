"use client"

import React from "react"
import { readableGHCNWarrantForDisplay } from "../../lib/ghcn-readable-warrant.js"

const h = React.createElement

export function GhcnReadableWarrant({ draft }) {
  const view = readableGHCNWarrantForDisplay(draft)
  if (view.status === "absent") return null
  if (view.status !== "saved") return h("section", { className: "forecast-evidence ghcn-warrant", "aria-label": "Saved station archive" },
    h("h3", null, "Saved station archive"), h("p", { role: "status" }, "This saved archive table is unavailable or uses an unsupported format."))
  return h("details", { className: "forecast-evidence ghcn-warrant" },
    h("summary", null, `Saved GHCN archive · ${view.rows.length} calendar days`),
    h("p", null, `Station ${view.station} · source-calendar day ${view.validDate}`),
    h("p", { className: "text-muted" }, "Retained input, not a live source check. The historical comparison references this same complete baseline."),
    h("dl", { className: "claim-facts" },
      h("div", null, h("dt", null, "Archive cutoff"), h("dd", null, view.cutoff || "Not supplied")),
      h("div", null, h("dt", null, "Retrieved"), h("dd", null, view.retrievedAt || "Not supplied"))),
    h("p", null, "Max/min columns describe accepted daily temperatures in °C. A dash group means no retained calendar entry, never zero. The UTC reporting interval is unknown."),
    h("div", { className: "ghcn-warrant-table", role: "region", "aria-label": "Complete retained GHCN calendar table", tabIndex: 0 },
      h("table", null,
        h("caption", null, "Saved accepted-year/sample counts and previous source dates/values. Scroll to see all columns and days."),
        h("thead", null, h("tr", null, view.columns.map(column => h("th", { key: column, scope: "col" }, column)))),
        h("tbody", null, view.rows.map(row => h("tr", { key: row[0] }, row.map((value, index) => index === 0
          ? h("th", { key: index, scope: "row" }, value)
          : h("td", { key: index }, value === null ? "—" : String(value)))))))),
    h("p", { className: "text-muted ghcn-warrant-digest" }, `Saved full-baseline identity: ${view.baselineSHA256}`))
}
