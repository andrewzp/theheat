import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { credentialReminders, CREDENTIAL_RENEWAL, CRED_WARN_DAYS } from "../lib/credential-status.js"
import { CredentialReminderBanner } from "../app/components/CredentialReminderBanner.js"

const NOW = Date.parse("2026-12-15T12:00:00Z")
const DAY = 86400000
const expiry = (offsetDays) => ({ EARTHDATA_TOKEN: { label: "NASA Earthdata",
  expires_at: new Date(NOW + offsetDays * DAY + 3600000).toISOString().replace(".000Z", "Z"), source: "jwt" } })
const render = (credentialExpiry) => renderToStaticMarkup(React.createElement(CredentialReminderBanner, { credentialExpiry, nowMs: NOW }))

test("reminders start 14 days before expiry and escalate at 3 days and after expiry", () => {
  assert.deepEqual(credentialReminders(expiry(CRED_WARN_DAYS + 1), NOW), [])
  assert.equal(credentialReminders(expiry(CRED_WARN_DAYS), NOW)[0].urgency, "soon")
  assert.equal(credentialReminders(expiry(3), NOW)[0].urgency, "critical")
  assert.equal(credentialReminders(expiry(0), NOW)[0].urgency, "critical")
  assert.equal(credentialReminders(expiry(-1), NOW)[0].urgency, "expired")
  assert.deepEqual(credentialReminders({ EARTHDATA_TOKEN: { label: "NASA Earthdata", expires_at: "not-a-date" } }, NOW), [])
  assert.deepEqual(credentialReminders({}, NOW), [])
})

test("the banner gives the renewal page and exact command but never a token", () => {
  assert.equal(render(expiry(30)), "")
  const soon = render(expiry(9))
  assert.match(soon, /role="status"/)
  assert.match(soon, /NASA Earthdata token expires in 9 days \(2026-12-24\)/)
  assert.match(soon, /href="https:\/\/urs\.earthdata\.nasa\.gov\/"/)
  assert.match(soon, /gh secret set EARTHDATA_TOKEN --repo andrewzp\/theheat/)
  assert.match(soon, /next run records the new expiry date/)
  const expired = render(expiry(-69))
  assert.match(expired, /role="alert"/)
  assert.match(expired, /token expired 69 days ago/)
  assert.match(expired, /GPM satellite rainfall stops while it is expired/)
  assert.doesNotMatch(expired, /eyJ/)
})

test("a tracked credential without renewal steps still gets a generic reminder", () => {
  const markup = render({ OTHER_TOKEN: { label: "Other service", expires_at: new Date(NOW + 2 * DAY).toISOString() } })
  assert.match(markup, /Other service token expires in 2 days/)
  assert.match(markup, /Renew OTHER_TOKEN with its provider/)
  assert.ok(CREDENTIAL_RENEWAL.EARTHDATA_TOKEN.lifetimeDays === 60)
})
