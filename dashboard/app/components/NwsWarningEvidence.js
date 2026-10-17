import React from "react"
import { nwsWarningForDisplay } from "../../lib/nws-warning-evidence.js"

const h = React.createElement
const field = (label, value) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))

export function NwsWarningEvidence({ draft }) {
  const source = nwsWarningForDisplay(draft)
  if (source.status === "unsupported") return null
  const title = h("h3", null, "Warning saved with this draft")
  if (source.status !== "present") return h("section", { className: "forecast-evidence nws-warning-evidence", "aria-label": "Saved NWS warning" },
    title, h("p", null, source.status === "missing" ? "The complete NWS warning was not saved with this draft."
      : "The saved NWS warning cannot be displayed because its fields are missing, inconsistent or too large."),
    h("p", null, "Check the original warning before recording a human review. Missing evidence is not a passing check."))
  return h("section", { className: "forecast-evidence nws-warning-evidence", "aria-label": "Saved NWS warning" },
    title,
    h("p", null, "Read the full warning and preparation advice below before reviewing the text. A warning designation does not establish observed harm."),
    h("dl", { className: "forecast-fields" },
      field("Product", source.event), field("Area", source.area), field("Issuing office", source.office),
      field("Message type", source.messageType), field("Issued (source time)", source.sent),
      field("Saved at", source.capturedAt)),
    h("details", { className: "forecast-details" },
      h("summary", null, "Read full warning and instructions"),
      h("h4", null, "Warning statement"),
      h("p", { className: "nws-warning-text" }, source.description),
      h("h4", null, "Instructions"),
      h("p", { className: "nws-warning-text" }, source.instruction || "No separate instructions were supplied."),
      h("dl", { className: "forecast-fields" },
        field("Effective (source time)", source.effective), field("Expires (source time)", source.expires),
        field("Ends (source time)", source.ends || "Not supplied")),
      h("a", { href: source.sourceUrl, target: "_blank", rel: "noreferrer noopener" }, "Open NWS source (opens in a new tab)")),
    h("p", null, "These are the saved source values and time offsets. The warning may have changed since capture. Displaying it does not authenticate the source or approve this draft; current source checks still run before posting."))
}
