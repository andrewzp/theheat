import React from "react"
import { officialWarningForDisplay, officialWarningTiming } from "../../lib/official-warning-evidence.js"
const h = React.createElement
const field = (label, value) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))

export function OfficialWarningEvidence({ draft, now = Date.now() }) {
  const source = officialWarningForDisplay(draft)
  if (source.status === "unsupported") return null
  const timing = officialWarningTiming(draft, now)
  return h("section", { className: "forecast-evidence", "aria-label": "Saved official warning" },
    h("h3", null, "Official warning saved with this draft"),
    timing.blocked && h("p", { role: "status", className: "draft-feedback error" }, timing.message),
    source.status === "present" && h(React.Fragment, null,
      h("p", null, "This is an attributed warning, not a report that the forecast conditions occurred."),
      h("dl", { className: "forecast-fields" }, field("Issuing authority", source.issuer), field("Place", source.place),
        field("Issued (UTC)", source.metadata.issued_at), field("Message expires (UTC)", source.metadata.valid_until),
        field("Saved (UTC)", source.metadata.captured_at), field("Report / revision", `${source.metadata.report_id} / ${source.metadata.revision}`)),
      h("p", { className: "nws-warning-text" }, source.statement),
      h("details", { className: "forecast-details" }, h("summary", null, "Read the saved original"),
        h("p", { className: "nws-warning-text" }, source.sourceText),
        h("a", { href: source.sourceUrl, target: "_blank", rel: "noreferrer noopener" }, "Open source (opens in a new tab)")),
      h("p", null, "This saved warning may have changed. Displaying it does not authenticate the source or approve the draft. Posting needs a fresh source check.")))
}
