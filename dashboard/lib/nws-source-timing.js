import { nwsWarningForDisplay } from "./nws-warning-evidence.js"

const WINDOW_MS = 6 * 60 * 60 * 1000
const needsSource = message => ({ status: "needs_source", blocked: true, message })

// Strict civil-date validation avoids Date.parse silently normalizing bad dates.
// Floor deadlines and ceil starts when source precision exceeds milliseconds:
// this preflight may hold up to 1ms early; it must never extend a source window.
function instant(value) {
  const parts = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/)
  if (!parts) throw new Error("Invalid aware timestamp")
  const [year, month, day, hour, minute, second] = parts.slice(1, 7).map(Number)
  if (year < 1 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) throw new Error("Invalid date")
  const civil = new Date(0)
  civil.setUTCFullYear(year, month - 1, day)
  civil.setUTCHours(hour, minute, second, 0)
  if (civil.getUTCFullYear() !== year || civil.getUTCMonth() !== month - 1 || civil.getUTCDate() !== day) throw new Error("Invalid civil date")
  const zone = parts[8]
  let offset = 0
  if (zone !== "Z") {
    const hours = Number(zone.slice(1, 3)), minutes = Number(zone.slice(4, 6))
    if (hours > 23 || minutes > 59) throw new Error("Invalid offset")
    offset = (hours * 60 + minutes) * (zone[0] === "-" ? -1 : 1)
  }
  const fraction = (parts[7] || "").padEnd(6, "0")
  const floor = civil.getTime() - offset * 60000 + Number(fraction.slice(0, 3))
  return { floor, ceil: floor + (Number(fraction.slice(3)) > 0 ? 1 : 0) }
}

export function nwsSourceTiming(draft, now = Date.now()) {
  const bundle = draft?.review_context?.two_bot?.bundle
  const raw = bundle?.raw_signal_dump, saved = raw?.source_evidence
  const nwsId = value => typeof value === "string" && value.startsWith("nws_")
  const isNws = draft?.type === "severe_weather" || nwsId(draft?.event_id) || nwsId(bundle?.event_id)
    || bundle?.signal_kind === "severe_weather" || saved?.source_url === "https://api.weather.gov/alerts/active"
  if (!isNws) return { status: "not_applicable", blocked: false }
  const display = nwsWarningForDisplay(draft)
  if (display.status !== "present") return needsSource("Source update needed: the saved NWS warning is missing or unreadable. Review and approval are held.")
  try {
    if (!Number.isSafeInteger(now)) throw new Error("Invalid clock")
    const props = saved.feature.properties
    const sent = instant(props.sent), effective = instant(props.effective), captured = instant(saved.captured_at)
    const expires = instant(props.expires)
    const end = props.ends == null || props.ends === "" ? expires.floor : Math.min(expires.floor, instant(props.ends).floor)
    const onset = props.onset == null || props.onset === "" ? effective.ceil : instant(props.onset).ceil
    if (sent.ceil > end || Math.max(effective.ceil, onset) >= end) throw new Error("Invalid interval")
    const cutoff = Math.min(end, sent.floor + WINDOW_MS, captured.floor + WINDOW_MS)
    if (now < Math.max(sent.ceil, effective.ceil, captured.ceil)) {
      return { ...needsSource("Source update needed: saved NWS source times are in the future. Review and approval are held."), cutoff: new Date(cutoff).toISOString() }
    }
    if (now >= cutoff) {
      return { ...needsSource("Source update needed: this saved NWS warning is expired or outside its six-hour review window. Review and approval are held."), cutoff: new Date(cutoff).toISOString() }
    }
    // This is only a timestamp preflight. Full source qualification and live
    // currentness remain the sender's responsibility, before paid safety/send.
    return { status: "saved_window", blocked: false, cutoff: new Date(cutoff).toISOString() }
  } catch {
    return needsSource("Source update needed: saved NWS timestamps are invalid or inconsistent. Review and approval are held.")
  }
}
