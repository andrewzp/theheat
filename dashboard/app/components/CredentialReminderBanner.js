"use client"

import React, { useState } from "react"
import { credentialReminders } from "../../lib/credential-status.js"

const h = React.createElement
const day = (iso) => {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? "an unknown date" : parsed.toISOString().slice(0, 10)
}

function headline(row) {
  if (row.urgency === "expired") return `${row.label} token expired ${-row.daysLeft} day${row.daysLeft === -1 ? "" : "s"} ago (${day(row.expiresAt)}).`
  if (row.daysLeft === 0) return `${row.label} token expires today (${day(row.expiresAt)}).`
  return `${row.label} token expires in ${row.daysLeft} day${row.daysLeft === 1 ? "" : "s"} (${day(row.expiresAt)}).`
}

function CopyCommand({ command }) {
  const [copied, setCopied] = useState(false)
  return h("span", { className: "credential-banner-command" },
    h("code", null, command),
    h("button", { type: "button", className: "refresh-btn", onClick: () => {
      try {
        navigator.clipboard.writeText(command).then(() => setCopied(true), () => setCopied(false))
      } catch { setCopied(false) }
    } }, copied ? "copied" : "copy"))
}

// Shown on every tab, 14 days before a tracked token expires and until the bot
// reports a renewed date. The bot writes only the expiry date, never the token.
export function CredentialReminderBanner({ credentialExpiry, nowMs }) {
  const reminders = credentialReminders(credentialExpiry, nowMs)
  if (!reminders.length) return null
  const urgent = reminders.some((row) => row.urgency !== "soon")
  return h("section", { className: `credential-banner ${urgent ? "urgent" : "soon"}`, role: urgent ? "alert" : "status",
    "aria-label": "Credentials to renew" },
    ...reminders.map((row) => h("div", { key: row.name, className: "credential-banner-row" },
      h("p", null, h("strong", null, headline(row)), row.renewal?.impact ? ` ${row.renewal.impact}` : ""),
      row.renewal
        ? h("ol", null,
          h("li", null, h("a", { href: row.renewal.renewUrl, target: "_blank", rel: "noreferrer" }, row.renewal.renewLabel), ". ", row.renewal.steps),
          h("li", null, "In a terminal, run this and paste the new token when asked (it stays hidden): ", h(CopyCommand, { command: row.renewal.command })))
        : h("p", null, `Renew ${row.name} with its provider, then update the matching GitHub Actions secret.`))),
    h("p", { className: "credential-banner-note" },
      "This clears after the bot's next run records the new expiry date. Tokens are never shown here."))
}
