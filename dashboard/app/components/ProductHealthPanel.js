import React from "react"

const h = React.createElement
function label(value) { return value ? String(value).replaceAll("_", " ") : "unknown" }
function age(hours) {
  if (typeof hours !== "number" || !Number.isFinite(hours) || hours < 0) return "Unknown"
  if (hours < 1) return "Within the last hour"
  if (hours < 24) return `${Math.floor(hours)}h ago`
  return `${Math.floor(hours / 24)}d ago`
}
function setting(value) { return value === true ? "On" : value === false ? "Off" : value ?? "Unknown" }

function Milestone({ title, value }) {
  return h("div", { className: "runtime-milestone" },
    h("dt", null, title),
    h("dd", null, value?.at
      ? h("time", { dateTime: value.at, title: value.at }, age(value.age_hours))
      : "Unknown"))
}

export function ProductHealthPanel({ health, config, deployment, stale = false }) {
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
    h("dl", { className: "runtime-milestones" },
      h(Milestone, { title: "Last nonempty source run", value: health.milestones?.source_observed }),
      h(Milestone, { title: "Last saved draft", value: health.milestones?.draft_created }),
      h(Milestone, { title: "Last current draft review", value: health.milestones?.draft_reviewed }),
      h(Milestone, { title: "Last post with receipt", value: health.milestones?.post_confirmed })),
    h("div", { className: "runtime-summary" },
      h("div", null,
        h("h3", null, "Review queue"),
        h("p", null, `${queue.waiting_count ?? "Unknown"} waiting · ${queue.unresolved_publish_count ?? "Unknown"} unresolved deliveries`),
        h("p", { className: "runtime-note" }, queue.oldest_waiting_at
          ? `Oldest waiting draft: ${age(queue.oldest_waiting_age_hours)}. Age alone never authorizes posting.`
          : queue.waiting_count === 0 ? "No waiting drafts in retained state." : "Waiting draft age is unknown."),
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
