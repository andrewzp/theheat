// Browser-safe retained-input inspection. This does not authenticate the source,
// establish its current upstream revision, run checks or grant posting approval.
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const exact = (value, keys) => object(value) && Object.keys(value).sort().join("|") === [...keys].sort().join("|")
const utf8 = new TextEncoder()
const bounded = (value, max) => typeof value === "string" && value.length > 0 && value.length <= max
  && utf8.encode(value).length <= max && new TextDecoder("utf-8", { fatal: true }).decode(utf8.encode(value)) === value
const identifier = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value)
const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const keys = ["schema", "issuer_id", "report_id", "revision", "source_url", "content_sha256", "issued_at", "captured_at", "valid_until", "original_language", "translation", "warning", "place"]
function instant(value) {
  if (typeof value !== "string" || value.startsWith("0000") || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(value)) throw new Error("time")
  const ms = Date.parse(value)
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 19) !== value.slice(0, 19)) throw new Error("time")
  return ms
}
function anchored(value, bytes) {
  if (!exact(value, ["start", "end", "text"]) || !Number.isSafeInteger(value.start) || !Number.isSafeInteger(value.end)
      || value.start < 0 || value.start >= value.end || value.end > bytes.length || value.end - value.start > 16384
      || !bounded(value.text, 16384) || !value.text.trim()
      || new TextDecoder("utf-8", { fatal: true }).decode(bytes.slice(value.start, value.end)) !== value.text) throw new Error("anchor")
}

export function officialWarningForDisplay(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle, raw = bundle?.raw_signal_dump
  const warning = draft?.type === "official_warning" || (typeof draft?.event_id === "string" && draft.event_id.startsWith("official_warning:"))
    || bundle?.signal_kind === "official_warning"
  if (!warning) return { status: "unsupported" }
  try {
    const saved = raw?.official_warning
    if (draft.type !== "official_warning" || bundle?.signal_kind !== "official_warning" || draft.event_id !== bundle.event_id
        || !bounded(raw.source_name, 300) || !object(saved) || saved.assertion_kind !== "attributed_warning_not_observation"
        || !bounded(saved.metadata_utf8, 131072) || !bounded(saved.source_utf8, 32768)
        || saved.source_utf8.includes("\x00") || !hash(saved.metadata_sha256) || !hash(saved.evidence_sha256)) throw new Error("identity")
    const metadata = JSON.parse(saved.metadata_utf8)
    if (!exact(metadata, keys) || metadata.schema !== "theheat.official-warning/v1"
        || ![metadata.issuer_id, metadata.report_id, metadata.revision].every(identifier)
        || metadata.original_language !== "en" || metadata.translation !== null || !hash(metadata.content_sha256)) throw new Error("metadata")
    if (!bounded(metadata.source_url, 2048) || /[^\x21-\x7e]/.test(metadata.source_url)) throw new Error("url")
    const url = new URL(metadata.source_url)
    if (url.protocol !== "https:" || url.username || url.password || url.hash || url.port === "0") throw new Error("url")
    const issued = instant(metadata.issued_at), captured = instant(metadata.captured_at), until = instant(metadata.valid_until)
    if (issued > captured || issued >= until) throw new Error("time")
    const bytes = utf8.encode(saved.source_utf8)
    anchored(metadata.warning, bytes)
    if (!exact(metadata.place, ["name", "country", "anchor"]) || !bounded(metadata.place.name, 300)
        || typeof metadata.place.country !== "string" || !/^[A-Z]{2}$/.test(metadata.place.country)
        || bundle.where !== metadata.place.name) throw new Error("place")
    anchored(metadata.place.anchor, bytes)
    if (metadata.place.anchor.text !== metadata.place.name || metadata.place.anchor.start < metadata.warning.start
        || metadata.place.anchor.end > metadata.warning.end) throw new Error("place")
    return { status: "present", issuer: raw.source_name, metadata, sourceText: saved.source_utf8,
      statement: metadata.warning.text, place: metadata.place.name, sourceUrl: metadata.source_url,
      issued, captured, until, saved }
  } catch { return { status: "unreadable" } }
}

export function officialWarningTiming(draft, now = Date.now()) {
  const value = officialWarningForDisplay(draft)
  if (value.status === "unsupported") return { blocked: false }
  if (value.status !== "present") return { blocked: true, message: "The saved official warning is missing or inconsistent; fresh source review is required." }
  if (draft.review_context?.official_warning_source_hold) return { blocked: true, message: "The supplied warning changed. Review a fresh source revision." }
  if (!Number.isFinite(now) || value.captured > now || value.issued > now || value.until <= now) {
    return { blocked: true, message: "The saved warning is expired or has inconsistent times. A fresh source is required." }
  }
  let modality = String(draft.text || "").toLowerCase()
  for (const name of [value.issuer, value.place]) {
    const escaped = name.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const expression = new RegExp(`(?<![\\p{L}\\p{N}_])${escaped}(?![\\p{L}\\p{N}_])`, "gu")
    if (!expression.test(modality)) return { blocked: true, message: "The text must retain the issuing authority and supported place." }
    modality = modality.replace(expression, "")
  }
  if (!/\b(?:warns?|warning|watch|advisory|forecasts?)\b/i.test(modality)) {
    return { blocked: true, message: "The text must describe an attributed warning, not observed conditions." }
  }
  return { blocked: false }
}
