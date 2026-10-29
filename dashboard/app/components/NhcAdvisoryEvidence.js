import React from "react"
import { nhcAdvisoryForDisplay, nhcAdvisoryTiming } from "../../lib/nhc-advisory-evidence.js"
const h = React.createElement
const field = (label, value) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))

export function NhcAdvisoryEvidence({ draft, now = Date.now() }) {
  const source = nhcAdvisoryForDisplay(draft)
  if (source.status === "unsupported") return null
  const timing = nhcAdvisoryTiming(draft, now)
  return h("section", { className: "forecast-evidence", "aria-label": "Saved NHC public advisory" },
    h("h3", null, "NHC public advisory saved with this draft"),
    timing.blocked && h("p", { role: "status", className: "draft-feedback error" }, timing.message),
    source.status === "present" && h(React.Fragment, null,
      h("p", null, "This is an attributed NHC forecast, not a report that the forecast conditions occurred."),
      h("dl", { className: "forecast-fields" }, field("Issuing authority", source.issuer),
        field("Storm / advisory", `${source.storm} / Advisory ${source.advisory}`), field("Hazard", source.hazard),
        field("Place", source.place), field("Issued (UTC)", source.times.issued_at), field("Saved (UTC)", source.times.captured_at),
        field("Upstream expiry", "Not stated by NHC (unknown)"),
        field("Operator freshness deadline (UTC)", `${source.times.operator_recheck_deadline} (our recheck limit, not an NHC expiry)`)),
      h("p", { className: "nws-warning-text" }, source.statement),
      source.context.length > 0 && h("p", null, `NHC outlook context: ${source.context.join(" ")}`),
      h("details", { className: "forecast-details" }, h("summary", null, "Read the saved original bulletin"),
        h("pre", { className: "nhc-bulletin-text" }, source.bulletinText),
        h("a", { href: source.sourceUrl, target: "_blank", rel: "noreferrer noopener" }, "Open the NHC advisory (opens in a new tab)")),
      h("p", null, "This saved advisory may have changed. Displaying it, or a reviewed label, does not authenticate the source or approve the draft. Posting needs a fresh source check.")))
}
