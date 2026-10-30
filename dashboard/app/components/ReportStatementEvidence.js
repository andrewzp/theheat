import React from "react"
import { reportStatementsForDisplay } from "../../lib/report-statement-evidence.js"
const h = React.createElement
const field = (label, value) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))
const short = value => `${value.slice(0, 12)}…`

export function ReportStatementEvidence({ draft }) {
  const source = reportStatementsForDisplay(draft)
  if (source.status === "unsupported") return null
  return h("section", { className: "forecast-evidence", "aria-label": "Attributed report statements" },
    h("h3", null, "Report statements in this draft's brief"),
    source.status === "unreadable"
      ? h("p", { role: "status", className: "draft-feedback error" },
        "The saved report statements are incomplete or differ from what the checks saw; do not rely on them. Re-run the source.")
      : h(React.Fragment, null,
        h("p", null, "Attributed statements from a retained report, not observations or adjudicated impacts. ",
          "A translation is never independent confirmation."),
        source.statements.map(row => h("div", { key: row.claim_id, className: "report-statement", "data-claim-id": row.claim_id },
          h("p", { className: "nws-warning-text" }, `“${row.quote}” — ${row.attribution}`),
          row.translated_text && h("p", null, `Reviewed translation: ${row.translated_text}`),
          h("dl", { className: "forecast-fields" },
            field("Source", row.source_name), field("Source date", row.source_date),
            field("Original language", row.language ?? "unknown"),
            field("Translation", row.translation_state === "source_language" ? "Not needed (source language)"
              : `Human-reviewed (${row.translation_identity})`),
            field("Retrieval", row.retrieval === "full_text_retained" ? "Full text retained; quote bound to it" : "Attested excerpt"),
            field("Source revision", `retained text ${short(row.retained_text_sha256)} · supplied report ref ${short(row.report_sha256)}`),
            row.episode && field("Physical episode join", `${row.episode.join_id} → ${row.episode.episode_id}`)),
          h("a", { href: row.url, target: "_blank", rel: "noreferrer noopener" }, "Open source (opens in a new tab)"))),
        h("p", null, source.cited === null ? "The writer did not report whether it cited a report statement."
          : source.cited ? "The writer reported citing a report statement." : "The writer reported not citing a report statement."),
        h("p", null, "Displaying these does not authenticate the publisher or approve the draft.")))
}
