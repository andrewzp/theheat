import React from "react"
import PostOutcomeHistory from "./PostOutcomeHistory.js"
import RecoveredRecord from "./RecoveredRecord.js"
import { LANE_TEXT } from "../../lib/graphic-availability.js"

const h = React.createElement
function label(value) { return value ? String(value).replaceAll("_", " ") : "unknown" }
function age(hours) {
  if (typeof hours !== "number" || !Number.isFinite(hours) || hours < 0) return "Unknown"
  if (hours < 1) return "Within the last hour"
  if (hours < 24) return `${Math.floor(hours)}h ago`
  return `${Math.floor(hours / 24)}d ago`
}
function setting(value) { return value === true ? "On" : value === false ? "Off" : value ?? "Unknown" }

function PostingCadence({ value }) {
  if (!value) return null
  function amount(window) {
    if (!Number.isSafeInteger(window?.minimum_count) || window.minimum_count < 0 || !["recorded", "partial"].includes(window.status)) return "Unknown"
    if (window.status === "partial") return window.minimum_count ? `At least ${window.minimum_count}` : "Unknown (0 dated receipts)"
    return String(window.minimum_count)
  }
  return h("div", { className: "runtime-note", "aria-label": "Recorded X posting cadence" },
    h("p", null, "X posts · Goal: 4 per day"),
    h("p", null, `Today (UTC): ${amount(value.today)} · Last 24 hours: ${amount(value.last_24h)}`),
    h("p", null, "Saved X receipts only. Drafts and send attempts are not posts."),
    value.inventory_known === false ? h("p", null, "Retained publication data is incomplete.") : null,
    Number.isSafeInteger(value.uncertain_time_receipts) && value.uncertain_time_receipts > 0
      ? h("p", null, `${value.uncertain_time_receipts} post IDs have missing or conflicting times.`) : null)
}

function PublicationEvidenceNotice({ health, enabled }) {
  if (enabled !== true) return null
  const receipt = health.milestones?.post_confirmed
  const dated = receipt?.status === "recorded" && typeof receipt.at === "string"
    && Number.isFinite(Date.parse(receipt.at)) && Number.isFinite(receipt.age_hours) && receipt.age_hours >= 0
  // Attention threshold only: never a publication gate, quota or platform probe.
  if (dated && receipt.age_hours < 24) return null
  return h("p", { className: "runtime-note runtime-publication-notice", role: "status",
    "data-publication-evidence": dated ? "old_receipt" : "undated_receipt" },
  dated ? `No recent dated X receipt in saved data. The latest dated receipt is ${age(receipt.age_hours)}.`
    : "No dated X receipt is available in saved data. Publication is unverified.",
  " Enabled settings and successful jobs do not verify a newer post. Check writing and delivery results.")
}

function Milestone({ title, value }) {
  return h("div", { className: "runtime-milestone" },
    h("dt", null, title),
    h("dd", null, value?.at
      ? h("time", { dateTime: value.at, title: value.at }, age(value.age_hours))
      : "Unknown"))
}

function LatestSavedDraft({ value }) {
  if (!value) return null
  const labels = { rejected: "rejected", pending: "pending", approved: "approval recorded; sending unverified",
    receipt_recorded: "receipt recorded", posted_without_receipt: "marked posted without a receipt",
    delivery_unresolved: "delivery unresolved", unknown: "outcome unknown" }
  const textHolds = { automatic_text_over_200_scalars: "over the 200 characters allowed for automatic text",
    automatic_text_malformed_unicode: "malformed Unicode", automatic_text_implies_media: "copy refers to media that automatic text does not send",
    unclassified: "reason unavailable", unknown: "text unavailable" }
  const sendHolds = { approval_unverified: "review or revision approval was not current", policy_changed: "editorial policy changed",
    critic_not_passed: "a critic pass was missing", event_already_posted: "the event already had a recorded post",
    stale_framing: "the source or draft was stale", delivery_unresolved: "an earlier delivery was unresolved",
    autoship_disabled: "automatic sending was disabled", policy_blocked: "the approval policy blocked automatic sending",
    awc_source_changed: "the airport source changed at recheck", awc_observation_expired: "the airport observations expired",
    awc_source_insufficient_window: "too little airport source time remained", awc_source_disabled: "the airport source route was disabled",
    awc_observed_mode_required: "observed-only source settings were required", awc_current_source_unexpected: "the airport recheck was unavailable",
    awc_draft_invalid: "the airport draft could not be validated", awc_draft_identity_changed: "the airport draft identity changed",
    airport_source_recheck: "the airport source needed review", ...textHolds }
  const disposition = value.status === "recorded" && Object.hasOwn(labels, value.disposition) ? value.disposition : "unknown"
  return h("div", { className: "runtime-note", "data-latest-draft-disposition": disposition },
    h("p", null, value.status === "ambiguous" ? "Latest saved draft cannot be uniquely identified in retained records."
      : value.status !== "recorded" ? "Latest saved draft outcome is unavailable."
        : `Latest saved draft: ${labels[disposition]}.`),
    value.status === "recorded" ? h(React.Fragment, null,
      value.rejection === "awc_source_window_elapsed" ? h("p", null, "This draft was rejected after its airport observations expired.") : null,
      value.send_hold && Object.hasOwn(sendHolds, value.send_hold) ? h("p", null, `Last recorded send hold: ${sendHolds[value.send_hold]}.`) : null,
      value.recorded_text_hold && Object.hasOwn(textHolds, value.recorded_text_hold)
        ? h("p", null, `Saved automatic text hold: ${textHolds[value.recorded_text_hold]}.`)
        : value.text_hold && Object.hasOwn(textHolds, value.text_hold)
          ? h("p", null, `Current automatic text hold: ${textHolds[value.text_hold]}.`) : null,
      value.recorded_text_hold && value.recorded_text_hold !== "unclassified" && value.text_hold === null
        ? h("p", null, "Current text no longer has that automatic text hold.") : null,
      value.source_hold_recorded === true ? h("p", null, "A source hold is recorded; its reason is unavailable here.") : null,
      value.undated_rows > 0 ? h("p", null, "Other retained drafts have unavailable creation times; this is the latest dated record.") : null,
    ) : null)
}

// W10.6: each post-image family's requirement and the input missing on this deployment.
export function GraphicFamilies({ graphics }) {
  const families = Array.isArray(graphics?.families) ? graphics.families : []
  const store = graphics?.store
  return h("details", { className: "runtime-details", "aria-label": "Post-image families" },
    h("summary", { style: { minHeight: 44 } }, `Post-image families · ${families.filter(row => row.status === "missing_input").length} need an input here`),
    h("p", { className: "runtime-note" }, !store ? "The media store setting is not reported. Native charts do not need it."
      : store.configured ? `Media store setting present (${store.backend}). Access is checked only by a preview or the sender; this is not hosted, cross-host or native rendering proof.`
        : "No usable media store setting here. Native charts and text posts are unaffected; retained and published images stay held."),
    !families.length ? h("p", { className: "runtime-note" }, "Family requirements are unavailable.")
      : h("ul", { style: { overflowWrap: "anywhere", paddingLeft: 18 } }, families.map(row => h("li", { key: row.family, "data-graphic-family": row.family, "data-graphic-status": row.status },
        h("strong", null, row.label), ` — ${LANE_TEXT[row.lane] || row.lane}. `,
        row.missing ? `Missing here: ${row.missing}.` : row.status === "store_configured_unverified" ? "Store setting present; access unverified." : "Available from the saved source.",
        h("span", { className: "runtime-note", style: { display: "block" } }, `Needs: ${row.needs.join("; ")}.`)))),
    h("p", { className: "runtime-note" }, "Replacing or recovering an image is a new revision: it revokes the joint review and any approval."))
}

// W14.6: delivered records whose provenance is imported/restored/superseded (local preview only).
// Read-only history beside, never inside, the post outcome list; empty renders nothing.
export function RecoveredPublished({ records }) {
  const rows = Array.isArray(records) ? records.filter(Boolean) : []
  if (!rows.length) return null
  return h("section", { "aria-label": "Recovered published history" },
    h("h3", null, "Recovered published history"),
    rows.map(record => h(RecoveredRecord, { key: record.draft_id ?? record.event_id, record })))
}

export function ProductHealthPanel({ health, config, deployment, codeRevision = null, stale = false, graphics = null, recovered = null }) {
  if (!health) return h("section", { className: "card full runtime-panel", "aria-label": "Operating status" },
    h("h2", null, "Operating status"),
    h("p", { className: "runtime-note" }, "Operating evidence is unavailable. Missing data does not mean the system is healthy."))
  const queue = health.queue || {}
  const writer = health.writer || {}
  const metrics = health.metrics || {}
  const flags = config?.flags || {}
  return h("section", { className: "card full runtime-panel", "aria-label": "Operating status" },
    h("div", { className: "runtime-heading" }, h("h2", null, "Operating status"),
      h("span", { className: "runtime-note" }, stale ? "Refresh failed · showing the last loaded evidence" : "From retained bot evidence")),
    h("p", { className: "runtime-note", role: "status" }, flags.automatic_publication_enabled === false
      ? "Automatic publication paused in the last bot report. Release requires fresh checks and new approval."
      : flags.automatic_publication_enabled === true ? "Automatic publication was enabled in the last bot report. Approvals must match its release epoch."
        : "Automatic publication state is unverified; scheduling is unavailable until the bot reports its release policy."),
    h(PublicationEvidenceNotice, { health, enabled: flags.automatic_publication_enabled }),
    h(PostingCadence, { value: health.publication_cadence }),
    config?.report_kind === "configuration_only" ? h("p", { className: "runtime-note" }, "Configuration refreshed only. This did not collect stories, write drafts or verify provider access.") : null,
    codeRevision ? h("p", { className: "runtime-note", "data-code-revision": codeRevision.status },
      `Code revision · ${label(codeRevision.status)}: ${codeRevision.reason}`,
      codeRevision.deployed_revision_pipeline_run?.at ? ` Last pipeline run on it: ${codeRevision.deployed_revision_pipeline_run.at}.` : "") : null,
    h("dl", { className: "runtime-milestones" },
      h(Milestone, { title: "Last nonempty source run", value: health.milestones?.source_observed }),
      h(Milestone, { title: "Last saved draft", value: health.milestones?.draft_created }),
      h(Milestone, { title: "Last current draft review", value: health.milestones?.draft_reviewed }),
      h(Milestone, { title: "Latest dated X receipt", value: health.milestones?.post_confirmed })),
    h(LatestSavedDraft, { value: health.latest_saved_draft }),
    h("div", { className: "runtime-summary" },
      h("div", null,
        h("h3", null, "Review queue"),
        h("p", null, `${queue.waiting_count ?? "Unknown"} waiting · ${queue.unresolved_publish_count ?? "Unknown"} unresolved deliveries`),
        h("p", { className: "runtime-note" }, queue.oldest_waiting_at
          ? `Oldest waiting draft: ${age(queue.oldest_waiting_age_hours)}. Age alone never authorizes posting.`
          : queue.waiting_count === 0 ? "No waiting drafts in retained state. An empty queue does not show that nothing worth covering happened worldwide." : "Waiting draft age is unknown."),
        queue.unknown_age_count > 0 ? h("p", { className: "runtime-note" }, `${queue.unknown_age_count} waiting drafts have unknown ages.`) : null),
      h("div", null,
        h("h3", null, `Writing pipeline · ${label(writer.status)}`),
        h("p", { className: "runtime-note" }, writer.status === "failed"
          ? `Retained ${label(writer.last_failure?.stage)} failure; recovery is unverified.`
          : writer.last_recorded_call_day ? `Last recorded responses: ${writer.last_recorded_call_day} UTC. Current access is unverified.`
            : "No retained writer responses establish current access."),
        writer.last_failure?.reasons?.[0] ? h("p", { className: "runtime-note" }, writer.last_failure.reasons[0].slice(0, 180)) : null),
      h("div", null,
        h("h3", null, `Engagement collection · ${metrics.collection_enabled === false ? "disabled" : label(metrics.status)}`),
        h("p", null, `${metrics.eligible_post_count ?? "Unknown"} eligible posts in the ${metrics.lookback_days || 30}-day window`),
        h("p", { className: "runtime-note" }, metrics.status === "inactive"
          ? "No eligible retained posts. Collection access remains unverified."
          : `Retained metrics: ${label(metrics.status)}. Missing samples are not zero engagement.`),
        metrics.collector_unseen_receipt_count > 0 ? h("p", { className: "runtime-note" }, `${metrics.collector_unseen_receipt_count} retained receipts are outside the collector's current selection path.`) : null)),
    h(PostOutcomeHistory, { outcomes: health.post_outcomes }),
    h(RecoveredPublished, { records: recovered }),
    h(GraphicFamilies, { graphics }),
    h("details", { className: "runtime-details" },
      h("summary", null, `Bot settings and evidence · ${label(config?.status)}`),
      h("p", { className: "runtime-note" }, config?.reason || "The bot has not recorded its runtime settings yet."),
      config?.captured_at ? h("p", { className: "runtime-note" }, `Bot report: ${config.captured_at} · ${config.mode || "unknown mode"}`) : null,
      h("dl", { className: "runtime-settings" },
        Object.entries({
          "Writer model": config?.writer_model, "Fact-check model": config?.fact_check_model,
          "Critic model": config?.critic_model, "Safety model": config?.safety_model,
          "Automatic scheduling after critic pass": setting(flags.autoship_on_critic_pass),
          "Critic enabled": setting(flags.critic_enabled),
          "Writer samples": flags.writer_samples, "Metrics collection enabled": setting(flags.metrics_enabled),
          "Bot version": config?.bot_version, "Bot code revision": config?.bot_git_sha,
          "Dashboard code revision": deployment?.git_sha, "Dashboard environment": deployment?.environment,
        }).map(([key, value]) => h("div", { key }, h("dt", null, key), h("dd", null, value ?? "Unknown")))),
      h("p", { className: "runtime-note" }, "Additional settings reported by this invocation:"),
      h("dl", { className: "runtime-settings" }, Object.entries(flags).filter(([key]) =>
        !["autoship_on_critic_pass", "critic_enabled", "writer_samples", "metrics_enabled"].includes(key)).map(([key, value]) =>
        h("div", { key }, h("dt", null, label(key)), h("dd", null, setting(value))))),
      h("p", { className: "runtime-note" }, "Credential presence indicates configuration only. It does not verify access, expiry or credits."),
      h("dl", { className: "runtime-settings" }, Object.entries(config?.credentials_present || {}).map(([key, value]) =>
        h("div", { key }, h("dt", null, label(key)), h("dd", null, value ? "Present · access unverified" : "Missing")))),
      h("dl", { className: "runtime-settings" }, Object.entries(config?.capabilities || {}).map(([key, value]) =>
        h("div", { key }, h("dt", null, label(key)), h("dd", null, label(value))))),
      [...(writer.notes || []), ...(metrics.notes || []), ...(queue.notes || []), ...(health.notes || [])]
        .map((note, i) => h("p", { className: "runtime-note", key: i }, note))))
}
