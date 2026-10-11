// Presentation only. These checks neither qualify source evidence nor clear review.
const PRODUCT = "open-meteo-cams-air-quality-auto"
const SOURCE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
const METHOD = "Mean or maximum of 24 instantaneous hourly forecast samples on a local calendar day"
const VARIABLES = [
  ["pm2_5", "PM2.5", "μg/m³"], ["pm10", "PM10", "μg/m³"],
  ["dust", "Dust", "μg/m³"], ["aerosol_optical_depth", "Aerosol optical depth", "dimensionless"],
  ["us_aqi", "US AQI", "US AQI"],
]
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const number = value => typeof value === "number" && Number.isFinite(value)
const label = (value, max) => typeof value === "string" && value.trim().length > 0 && value.length <= max
const coordinates = (lat, lon) => number(lat) && number(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180

function boundedJson(value) {
  let nodes = 0
  function visit(item, depth) {
    if (++nodes > 4096 || depth > 10) return false
    if (item === null || typeof item === "boolean") return true
    if (typeof item === "number") return number(item)
    if (typeof item === "string") return item.length <= 32768
    if (Array.isArray(item)) {
      if (item.length > 4096 || Object.keys(item).length !== item.length) return false
      for (let i = 0; i < item.length; i++) if (!Object.hasOwn(item, i) || !visit(item[i], depth + 1)) return false
      return true
    }
    if (!object(item) || ![Object.prototype, null].includes(Object.getPrototypeOf(item))) return false
    return Object.entries(item).every(([key, entry]) => key.length <= 32768 && visit(entry, depth + 1))
  }
  return visit(value, 0) && new TextEncoder().encode(JSON.stringify(value)).length <= 32768
}

function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function utc(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
      || !validDate(value.slice(0, 10)) || Number(value.slice(11, 13)) > 23
      || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return null
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : null
}

function knownTimezone(value) {
  if (!label(value, 128) || !/^[A-Za-z][A-Za-z0-9_+-]*(?:\/[A-Za-z0-9_+-]+)*$/.test(value)) return false
  try { new Intl.DateTimeFormat("en", { timeZone: value }); return true } catch { return false }
}

export function forecastEvidenceForDisplay(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle
  if (!["air_quality_hazard", "dust_event"].includes(bundle?.signal_kind)) return { status: "unsupported" }
  const raw = bundle.raw_signal_dump
  const window = raw?.forecast_window
  if (window == null) return { status: "missing" }
  const unreadable = { status: "unreadable" }
  try {
    if (!object(window) || !boundedJson(window) || !label(draft.event_id, 512)
        || draft.event_id !== bundle.event_id || draft.event_id !== raw.event_id
        || window.schema_version !== 1 || window.source_product !== PRODUCT || window.source_url !== SOURCE_URL
        || window.evidence_type !== "model_forecast" || window.domain_selection !== "auto" || window.method !== METHOD
        || !validDate(window.date) || !knownTimezone(window.timezone)
        || !Number.isInteger(window.utc_offset_seconds) || Math.abs(window.utc_offset_seconds) > 86400) return unreadable
    const times = [window.valid_start, window.valid_end, window.requested_at, window.retrieved_at].map(utc)
    if (times.includes(null) || times[0] >= times[1] || times[2] > times[3]) return unreadable
    const place = window.requested_location, grid = window.grid_location
    if (!object(place) || !label(place.city, 160) || !label(place.country, 160) || !coordinates(place.lat, place.lon)
        || !Array.isArray(grid) || grid.length !== 2 || !coordinates(...grid)) return unreadable
    if (!Array.isArray(window.hours) || window.hours.length !== 24
        || window.hours.some((hour, i) => hour !== `${window.date}T${String(i).padStart(2, "0")}:00`)) return unreadable
    if (!object(window.series) || Object.keys(window.series).length !== VARIABLES.length) return unreadable
    const series = []
    for (const [key, name, unit] of VARIABLES) {
      const entry = window.series[key]
      if (!object(entry) || Object.keys(entry).length !== 3 || entry.unit !== unit) return unreadable
      const { status, values } = entry
      if (["missing", "invalid"].includes(status)) {
        if (values !== null) return unreadable
        series.push({ key, label: name, unit, status, count: 0, rows: null })
      } else {
        if (!["complete", "incomplete"].includes(status) || !Array.isArray(values) || values.length !== 24
            || values.some(value => value !== null && (!number(value) || value < 0))) return unreadable
        const count = values.filter(value => value !== null).length
        if ((status === "complete") !== (count === 24)) return unreadable
        series.push({ key, label: name, unit, status, count,
          rows: window.hours.map((hour, i) => ({ hour: hour.slice(11), value: values[i] })) })
      }
    }
    return {
      status: "present", date: window.date, timezone: window.timezone,
      location: { city: place.city, country: place.country, lat: place.lat, lon: place.lon },
      grid: [...grid], validStart: window.valid_start, validEnd: window.valid_end,
      requestedAt: window.requested_at, retrievedAt: window.retrieved_at, method: window.method, series,
    }
  } catch {
    return unreadable
  }
}
