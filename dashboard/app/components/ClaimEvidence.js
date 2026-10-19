"use client"

import React, { useRef } from "react"
import { claimEvidenceForDisplay } from "../../lib/saved-claim-evidence.js"

const h = React.createElement
const messages = {
  bound: "These are claims the model extracted from this saved version. They are not individual source citations or independent verification.",
  missing: "No model claim list was saved for this version. Review the source evidence directly.",
  unbound: "Saved model analysis could not be tied to this text and source snapshot. Its claims are hidden.",
  unreadable: "The saved claim list is incomplete or too large to display. No claims were substituted.",
  unavailable: "The saved claim analysis is unavailable for this version. Refresh before reviewing.",
  editing: "Editing in progress. Saved model claims are hidden; they have not checked your changes.",
}

export function ClaimEvidence({ draft, editing = false, sourceHold = null }) {
  const { claims, source } = claimEvidenceForDisplay(draft, { editing })
  const sourceDetails = useRef(null), sourceSummary = useRef(null)
  const openSource = () => {
    if (sourceDetails.current) sourceDetails.current.open = true
    sourceSummary.current?.focus()
  }
  return h("section", { className: "forecast-evidence claim-evidence", "aria-label": "Claims and saved source evidence" },
    h("h3", null, "Claims and evidence"),
    h("p", { role: "status" }, messages[claims.status]),
    sourceHold && h("p", { className: "draft-feedback error" }, sourceHold),
    claims.status === "bound" && h(React.Fragment, null,
      h("p", null, "Individual source links were not retained. Compare each claim with the shared saved input; matching a number does not establish support."),
      h("details", null,
        h("summary", null, `Saved model claims · ${claims.items.length}`),
        claims.items.length ? h("ol", { className: "claim-list" }, claims.items.map((claim, index) => h("li", { key: index },
          h("span", { className: "text-muted" }, claim.kind.replaceAll("_", " ")), h("p", null, claim.text))))
          : h("p", null, "The model retained an empty claim list. This does not establish that the text contains no factual claims.")),
      source.status === "saved" && h("button", { type: "button", className: "btn sm btn-ghost", onClick: openSource }, "Compare with shared source facts")),
    source.status === "saved" ? h("details", { ref: sourceDetails, className: "claim-source" },
      h("summary", { ref: sourceSummary }, `Saved source facts · ${source.facts.length}`),
      h("p", null, `Saved place: ${source.where}`), h("p", null, `Saved source time: ${source.when}`),
      h("p", null, "Retained input for this draft, not per-claim citations or a new source check. Check the source type, time window and scope before review."),
      source.facts.length ? h("dl", { className: "claim-facts" }, source.facts.map((fact, index) => h("div", { key: index },
        h("dt", null, fact.label.replaceAll("_", " ")), h("dd", null,
          fact.value === null ? "Not supplied" : `${String(fact.value)}${fact.unit ? ` ${fact.unit}` : ""}`))))
        : h("p", null, "No structured facts were retained in this source packet."))
      : h("p", null, source.status === "unreadable"
        ? "The saved source facts are incomplete, inconsistent or too large to display. Inspect the original source before review."
        : "No structured source packet is available here. The other saved source panels may contain more detail."),
    h("p", { className: "text-muted" }, "This panel does not run checks, record a review or authorize publication."))
}
