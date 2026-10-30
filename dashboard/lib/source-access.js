// Owner-access health for the credentialed GPM/Earthdata lane (mirror of
// src/data/source_access.py gpm_access_health). Retained state only: the
// credential's expiry date (never a value), the age of the newest data date the
// primary GPM path retained (the model witness never refreshes it), a bounded
// refusal backoff for the same credential, and the owner-access hold. Nothing
// here fetches; an empty or witness-served feed is not current GPM coverage.
import { sourceIncidents } from "./source-incidents.js"

export const ACCESS_SCHEMA = "theheat.source-access/v1"
export const REFUSAL_BACKOFF_HOURS = [6, 24, 72]
const GPM = "gpm_imerg"
const CURRENT_DATA_DAYS = 2
const DAY_MS = 86400000

function parse(value) {
  if (typeof value !== "string" || !value) return null
  const at = new Date(value)
  return Number.isNaN(at.getTime()) ? null : at
}

function iso(at) {
  return at.toISOString().replace(/\.\d{3}Z$/, "Z")
}

function utcDay(at) {
  return Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate())
}

function rowsNewestFirst(runHistory, source) {
  const rows = []
  for (const run of Array.isArray(runHistory) ? runHistory : []) {
    if (!run || typeof run !== "object") continue
    for (const entry of Array.isArray(run.sources) ? run.sources : []) {
      if (entry && typeof entry === "object" && entry.source === source) rows.push([String(run.started_at ?? ""), entry])
    }
  }
  return rows.sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0))
}

function accessRecord(entry) {
  const access = entry?.details?.earthdata_access
  return access && typeof access === "object" && access.schema === ACCESS_SCHEMA ? access : null
}

export function refusalBackoff(runHistory, { credentialExpiresAt, now }) {
  let refusals = 0
  let latest = null
  for (const [, entry] of rowsNewestFirst(runHistory, GPM)) {
    if (entry?.details?.incident?.product_state === "primary_qualified") break
    const access = accessRecord(entry)
    if (!access || !access.refused) continue
    if ((access.credential_expires_at ?? null) !== (credentialExpiresAt ?? null)) break
    refusals += 1
    if (latest === null) latest = parse(access.refused_at)
  }
  if (!refusals || latest === null) return null
  const hours = REFUSAL_BACKOFF_HOURS[Math.min(refusals, REFUSAL_BACKOFF_HOURS.length) - 1]
  const after = new Date(latest.getTime() + hours * 3600000)
  if (now >= after) return null
  return { refused_at: iso(latest), consecutive_refusals: refusals, next_attempt_after: iso(after),
    credential_expires_at: credentialExpiresAt ?? null, requests_sent: 0 }
}

export function gpmLastGood(state, { now }) {
  let newest = null
  let cities = 0
  const recent = state?.precip_recent_by_city
  for (const rows of recent && typeof recent === "object" ? Object.values(recent) : []) {
    for (const row of Array.isArray(rows) ? rows : []) {
      const text = row?.date
      if (typeof text !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(text)) continue
      if (newest === null || text > newest) newest = text
    }
    cities += 1
  }
  if (newest === null) return { data_date: null, age_days: null, basis: "no_retained_primary_gpm_data", cities: 0 }
  const age = Math.floor((utcDay(now) - Date.parse(`${newest}T00:00:00Z`)) / DAY_MS)
  return { data_date: newest, age_days: age, basis: "precip_recent_by_city (primary GPM only)", cities }
}

function earthdataHold(runHistory) {
  const rows = sourceIncidents(runHistory, GPM).filter(row => String(row.product_id ?? "").startsWith("gpm_imerg.")
    && (row.role === "primary" || row.role === "alternate_route"))
  const access = rows.filter(row => row.state === "access_hold")
  if (!access.length) return null
  const latestRefusal = access.map(row => String(row.last_failure ?? "")).sort().at(-1)
  if (rows.some(row => (row.state === "recovered" || row.state === "qualified") && String(row.last_at ?? "") > latestRefusal)) return null
  return { stage: String(access.at(-1).last_outcome) }
}

export function gpmAccessHealth(state, { asOf = new Date().toISOString() } = {}) {
  const now = new Date(asOf)
  const row = state?.credential_expiry?.EARTHDATA_TOKEN
  const expires = parse(row?.expires_at)
  const expired = Boolean(expires && expires <= now)
  const credential = { tracked: expires !== null, expires_at: expires ? iso(expires) : null, expired,
    days_since_expiry: expired ? Math.floor((now - expires) / DAY_MS) : null }
  const lastGood = gpmLastGood(state, { now })
  const runHistory = state?.run_history
  const newest = rowsNewestFirst(runHistory, GPM)[0]
  const latestAccess = newest ? accessRecord(newest[1]) : null
  const latestRun = (Array.isArray(runHistory) ? runHistory : []).filter(run => parse(run?.started_at))
    .sort((a, b) => parse(b.started_at) - parse(a.started_at))[0]
  const inventory = latestRun?.runtime_inventory
  const captured = parse(inventory?.captured_at), started = parse(latestRun?.started_at)
  const reported = inventory?.flags?.earthdata_refusal_backoff_enabled
  const enabled = typeof reported === "boolean" && inventory?.schema_version === 1
    && captured && started && started <= captured && captured <= now && now - captured <= 6 * 3600000 ? reported : null
  const backoff = enabled === true ? refusalBackoff(runHistory, { credentialExpiresAt: credential.expires_at, now }) : null
  const hold = earthdataHold(runHistory)
  let stage
  if (expired) stage = "access_expired"
  else if (backoff) stage = "refused_backoff"
  else if (hold) stage = hold.stage === "access_backoff" && enabled !== true ? "access_refused" : hold.stage
  else if (lastGood.age_days !== null && lastGood.age_days <= CURRENT_DATA_DAYS) stage = "current"
  else stage = "no_current_data"
  const age = lastGood.age_days
  const lastText = age !== null
    ? `Last good GPM data ${lastGood.data_date} (${age} day${age !== 1 ? "s" : ""} old).`
    : "No good GPM data is retained."
  const lead = {
    access_expired: `Earthdata access expired ${credential.expires_at ? credential.expires_at.slice(0, 10) : ""}; owner renewal required. No request is sent until then. `,
    refused_backoff: `Earthdata refused this credential; the same credential is retried only after ${backoff ? backoff.next_attempt_after : ""} unless renewed. `,
    access_refused: "Earthdata refused access; retry suppression is disabled or unverified. Owner action is needed. ",
    current: "",
    no_current_data: "No qualified GPM run is retained for the current window. ",
  }[stage] ?? `Earthdata owner-access hold (${stage}); a renewed credential is tried at the next scheduled run. `
  return { schema: ACCESS_SCHEMA, source: GPM, as_of: iso(now), stage, credential, last_good: lastGood, backoff, backoff_enabled: enabled,
    latest_access_record: latestAccess, hold_stage: hold ? hold.stage : null,
    public_text: (lead + lastText).trim(), empty_feed_is_not_coverage: true }
}
