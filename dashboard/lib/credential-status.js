// Pure, JSX-free credential-expiry helpers (mirrors automation-status.js).
//
// Drives the dashboard CREDENTIALS card so a token's expiry is visible BEFORE it
// silently breaks a source. On 2026-06-23 the 60-day NASA Earthdata token aged
// out and 401'd every GPM path; nobody saw it coming. These counters give ~2
// weeks of warning instead. The bot writes only the derived expiry date to
// state (src/credentials.py) — the token itself never reaches the dashboard.

export const CRED_WARN_DAYS = 14 // amber at or under 14 days left
export const CRED_CRIT_DAYS = 3 // red at or under 3 days left (or already expired)

const DAY_MS = 24 * 60 * 60 * 1000

// Whole days until expiry (negative once expired), or null if the date is unparseable.
export function daysUntil(expiresAt, now = Date.now()) {
  const exp = Date.parse(expiresAt)
  if (Number.isNaN(exp)) return null
  return Math.floor((exp - now) / DAY_MS)
}

// Map days-left onto the dashboard's existing badge palette (Badge.js):
// success = green, running = amber/warn, failure = red, neutral = unknown.
export function badgeClassForDays(days) {
  if (days === null) return "neutral"
  if (days <= CRED_CRIT_DAYS) return "failure"
  if (days <= CRED_WARN_DAYS) return "running"
  return "success"
}

// Project state.credential_expiry into sorted display rows, soonest-to-expire
// first, each carrying its color so the most urgent credential is always on top.
export function credentialRows(credentialExpiry = {}, now = Date.now()) {
  return Object.entries(credentialExpiry || {})
    .map(([name, info]) => {
      const days = daysUntil(info?.expires_at, now)
      return {
        name,
        label: info?.label || name,
        expiresAt: info?.expires_at || null,
        daysLeft: days,
        badgeClass: badgeClassForDays(days),
      }
    })
    .sort((a, b) => (a.daysLeft ?? Infinity) - (b.daysLeft ?? Infinity))
}

// How to renew each tracked credential. The banner never shows a token: only its
// expiry date (written by the bot) and where to renew it. Add one entry per new
// tracked credential alongside src/credentials.py TRACKED_CREDENTIALS.
export const CREDENTIAL_RENEWAL = {
  EARTHDATA_TOKEN: {
    lifetimeDays: 60,
    renewUrl: "https://urs.earthdata.nasa.gov/",
    renewLabel: "Open Earthdata",
    steps: "Sign in at Earthdata, open Generate Token, click the Generate Token button, then Show Token and copy it.",
    command: "gh secret set EARTHDATA_TOKEN --repo andrewzp/theheat",
    impact: "GPM satellite rainfall stops while it is expired.",
  },
}

// Credentials that need renewing now: within the warning window or already
// expired, soonest first. Unparseable dates stay on the card as unknown and are
// not turned into a reminder.
export function credentialReminders(credentialExpiry = {}, now = Date.now()) {
  return credentialRows(credentialExpiry, now)
    .filter((row) => row.daysLeft !== null && row.daysLeft <= CRED_WARN_DAYS)
    .map((row) => ({
      ...row,
      urgency: row.daysLeft < 0 ? "expired" : row.daysLeft <= CRED_CRIT_DAYS ? "critical" : "soon",
      renewal: CREDENTIAL_RENEWAL[row.name] ?? null,
    }))
}
