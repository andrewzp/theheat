"use client"
// Read-only continuity view of one draft after import, restore or supersession.
// Renders a projectRecoveredRecord() value in the editor and Published views; a
// current record renders nothing. It never offers a control of its own.
import React from "react"
const h = React.createElement
const ORIGIN = { imported: "Imported history (read-only)", restored: "Restored history (read-only)",
  superseded: "Superseded revision (read-only)" }
export const recoveryLabel = record => ORIGIN[record?.provenance?.kind] || null
const HOLD = {
  imported_record_read_only: "Imported records are history only; act on a current draft.",
  restored_record_read_only: "Restored records are history only; act on a current draft.",
  imported_review_not_current: "An imported review is not a current review. Review again here.",
  superseded_by_newer_revision: "A newer revision replaced this one.",
  delivered_content_retained: "Delivered posts cannot be cancelled.",
  already_delivered: "Already delivered; never sent again.",
  delivered_original_preserved: "The delivered text is preserved exactly.",
  unknown_delivery_never_retried: "Outcome unknown: never retried without a receipt.",
  intent_cancelled: "This publication intent was cancelled; its evidence is kept.",
  review_required: "Review this exact text against its source first.",
  recovery_projection_unavailable: "This record's history could not be read; it stays read-only.",
}
export default function RecoveredRecord({ record }) {
  if (!record || !ORIGIN[record.provenance?.kind]) return null
  return h("section", { className: "recovered-record", "data-surface": record.surface, "aria-label": "Record history" },
    h("p", null, h("strong", null, ORIGIN[record.provenance.kind] || record.provenance.kind),
      record.provenance.import_id ? ` · ${record.provenance.import_id}` : null),
    record.delivered ? h("blockquote", { "data-tweet": record.delivered.tweet_id }, record.delivered.text) : null,
    h("ol", null, record.history.map((item, index) => h("li", { key: index }, item.kind === "revision"
      ? `Revision ${item.index + 1}` : `${item.kind === "attempt" ? "Attempt" : "Conflicting attempt"}: ${item.entry?.phase ?? (item.entry?.tweet_id ? "confirmed" : "legacy")}`))),
    record.holds.length ? h("ul", { className: "recovered-record-holds" }, record.holds.map(hold =>
      h("li", { key: `${hold.action}:${hold.code}` }, HOLD[hold.code] || hold.code))) : null)
}
