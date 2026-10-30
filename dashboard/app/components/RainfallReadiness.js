"use client"

import React from "react"

const h = React.createElement

// Regional rainfall scan and named packet holds for one source (W06.6). Display only.
export function RainfallReadiness({ source, readiness }) {
  if (!readiness) return null
  const { scan, regions, packet_holds: packets } = readiness
  return h("div", { className: "source-incidents rainfall-readiness", "aria-label": `${source} rainfall readiness` },
    scan && h("p", null,
      h("strong", null, "Regional rainfall scan"),
      ` examined ${scan.examined ?? "unknown"} of ${scan.selected ?? "unknown"} selected regions (${scan.universe ?? "unknown"} in the set)`,
      scan.not_attempted.length ? `; not attempted within the call/deadline limit: ${scan.not_attempted.join(", ")}` : "",
      `. ${scan.scope}`),
    regions.length > 0 && h("ul", { "aria-label": `${source} rainfall regions` },
      regions.map(row => h("li", { key: row.region, "data-rainfall-outcome": row.outcome },
        h("strong", null, row.region), `: ${row.outcome === "qualified" ? "Qualified" : row.outcome.replaceAll("_", " ")}`,
        row.hold ? ` — hold: ${row.hold}` : "", row.failure_class ? ` (${row.failure_class})` : "",
        row.revisit_age_days == null ? "; never examined in retained runs" : `; last examined ${row.revisit_age_days} day(s) ago`))),
    packets && packets.rows.length > 0 && h("ul", { "aria-label": `${source} rainfall packets stopped before generation` },
      packets.rows.map(row => h("li", { key: row.event_id ?? row.location, "data-rainfall-outcome": "packet_held" },
        h("strong", null, row.location ?? row.event_id ?? "Unnamed packet"),
        `: stopped before paid generation — ${row.holds.map(hold => hold.text).join("; ")}`))))
}
