// Browser-safe retained NHC advisory inspection. This does not authenticate the
// source, establish that the advisory is still current, run checks or grant posting
// approval. NHC public advisories state no expiry: the upstream expiry stays
// unknown and is never shown as a time; the operator freshness deadline is ours.
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const exact = (value, keys) => object(value) && Object.keys(value).sort().join("|") === [...keys].sort().join("|")
const ORIGIN = "https://www.nhc.noaa.gov"
export const NHC_INDEX_URL = `${ORIGIN}/CurrentStorms.json`
export const NHC_UPSTREAM_EXPIRY_STATUS = "not_supplied_by_source"
export const NHC_OPERATOR_RULE = "Operator recheck deadline, at most 60 minutes after capture; not an NHC expiry."
const MINUTE = 60 * 1000, MAX_ISSUE_AGE = 6 * 60 * MINUTE
const recordKeys = ["schema", "assertion_kind", "nomination", "source", "index_row", "bulletin_utf8", "bulletin_sha256", "product", "times", "hazard", "place", "context"]
const nominationKeys = ["storm_id", "bin", "advisory", "hazard", "place", "country", "freshness_minutes"]
const timeKeys = ["issued_at", "captured_at", "upstream_expiry", "upstream_expiry_status", "operator_recheck_deadline", "operator_recheck_rule"]
const HAZARDS = ["RAINFALL", "WIND", "STORM SURGE", "SURF", "TORNADOES"]
function instant(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value)) throw new Error("time")
  const ms = Date.parse(value)
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 19) !== value.slice(0, 19)) throw new Error("time")
  return ms
}
function anchored(bulletin, value, keys) {
  if (!exact(value, keys) || !Number.isSafeInteger(value.start) || !Number.isSafeInteger(value.end)
      || value.start < 0 || value.start >= value.end || value.end > bulletin.length) throw new Error("anchor")
  return bulletin.slice(value.start, value.end)
}
const word = name => new RegExp(`(?<![A-Za-z0-9_])${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_])`, "gi")

export function nhcAdvisoryForDisplay(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle, raw = bundle?.raw_signal_dump
  const advisory = draft?.type === "nhc_advisory" || (typeof draft?.event_id === "string" && draft.event_id.startsWith("nhc_advisory:"))
    || bundle?.signal_kind === "nhc_advisory"
  if (!advisory) return { status: "unsupported" }
  try {
    const record = raw?.nhc_advisory
    if (draft.type !== "nhc_advisory" || bundle?.signal_kind !== "nhc_advisory" || draft.event_id !== bundle.event_id
        || raw.source_name !== "NHC" || !exact(record, recordKeys) || record.schema !== "theheat.nhc-advisory/v1"
        || record.assertion_kind !== "attributed_forecast_not_observation") throw new Error("identity")
    const n = record.nomination, bulletin = record.bulletin_utf8
    if (!exact(n, nominationKeys) || !/^(AL|EP)(0[1-9]|[1-4][0-9])20[2-9][0-9]$/.test(n.storm_id) || !/^(AT|EP)[1-5]$/.test(n.bin)
        || !/^[1-9][0-9]{0,2}[A-Z]?$/.test(n.advisory) || !HAZARDS.includes(n.hazard) || typeof n.place !== "string"
        || n.place.length < 2 || n.place.length > 120 || !/^[A-Z]{2}$/.test(n.country)
        || !Number.isSafeInteger(n.freshness_minutes) || n.freshness_minutes < 1 || n.freshness_minutes > 60) throw new Error("nomination")
    const advisoryUrl = `${ORIGIN}/text/MIATCP${n.bin}.shtml`
    if (raw.source_url !== advisoryUrl || record.source?.advisory_url !== advisoryUrl || record.source?.index_url !== NHC_INDEX_URL) throw new Error("url")
    if (typeof bulletin !== "string" || !bulletin || bulletin.length > 16384 || /[^\r\n\x20-\x7e]/.test(bulletin)
        || !/^[a-f0-9]{64}$/.test(record.bulletin_sha256)) throw new Error("bulletin")
    const t = record.times
    if (!exact(t, timeKeys) || t.upstream_expiry !== null || t.upstream_expiry_status !== NHC_UPSTREAM_EXPIRY_STATUS
        || t.operator_recheck_rule !== NHC_OPERATOR_RULE) throw new Error("times")
    const issued = instant(t.issued_at), captured = instant(t.captured_at), deadline = instant(t.operator_recheck_deadline)
    if (issued > captured || deadline !== captured + n.freshness_minutes * MINUTE) throw new Error("times")
    const statement = anchored(bulletin, record.hazard, ["key", "start", "end", "text"])
    if (record.hazard.key !== n.hazard || record.hazard.text !== statement || !statement.startsWith(`${n.hazard}:`)) throw new Error("hazard")
    if (anchored(bulletin, record.place, ["name", "start", "end"]) !== n.place || record.place.name !== n.place
        || record.place.start < record.hazard.start || record.place.end > record.hazard.end || bundle.where !== n.place) throw new Error("place")
    if (!Array.isArray(record.context) || record.context.length > 8
        || record.context.some(row => anchored(bulletin, row, ["start", "end", "text"]) !== row.text)) throw new Error("context")
    const p = record.product
    if (!object(p) || p.atcf_id !== n.storm_id || typeof p.storm_kind !== "string" || typeof p.storm_name !== "string"
        || typeof p.advisory !== "string") throw new Error("product")
    return { status: "present", issuer: "National Hurricane Center (NHC)", storm: `${p.storm_kind} ${p.storm_name}`,
      advisory: p.advisory, hazard: n.hazard, statement, place: n.place, context: record.context.map(row => row.text),
      bulletinText: bulletin, sourceUrl: advisoryUrl, issued, captured, deadline, times: t, record }
  } catch { return { status: "unreadable" } }
}

const ATTRIBUTION = /(?<![A-Za-z0-9_])(?:NHC|National Hurricane Center)(?![A-Za-z0-9_])/gi
const MODALITY = /\b(?:forecasts?|forecast to|expected|could|may|might|possible|possibly|likely|risk|warns?|advisory)\b/i
const OBSERVED = /\b(?:flooded|(?:has|have|had) (?:caused )?flood(?:ed|ing)|flooding (?:has|have))\b/i

// Mirrors the Python necessary-binding check; entailment remains the required checks' job.
export function nhcAdvisoryCopyProblem(text, value) {
  if (typeof text !== "string" || !text.trim()) return "The text is empty."
  if (!new RegExp(ATTRIBUTION.source, "i").test(text)) return "The text must attribute the forecast to NHC or the National Hurricane Center."
  if (!word(value.place).test(text)) return "The text must name the supported place."
  const rest = text.replace(ATTRIBUTION, "").replace(word(value.place), "")
  if (!MODALITY.test(rest)) return "The text must describe an attributed forecast, not observed conditions."
  const source = [value.statement, ...value.context].join(" ")
  for (const claim of ["landfall", "record", "population"]) {
    const expression = new RegExp(`\\b${claim}\\b`, "i")
    if (expression.test(text) && !expression.test(source)) return "The text makes a claim the saved advisory does not support."
  }
  if (OBSERVED.test(text)) return "The text makes a claim the saved advisory does not support."
  return null
}

export function nhcAdvisoryTiming(draft, now = Date.now()) {
  const value = nhcAdvisoryForDisplay(draft)
  if (value.status === "unsupported") return { blocked: false }
  if (value.status !== "present") return { blocked: true, message: "The saved NHC advisory is missing or inconsistent; fresh source review is required." }
  if (draft.review_context?.nhc_advisory_source_hold) return { blocked: true, message: "The NHC advisory changed; fresh source review is required." }
  if (!Number.isFinite(now) || value.captured > now || value.issued > now) {
    return { blocked: true, message: "The saved NHC advisory has inconsistent times. A fresh source check is required." }
  }
  if (value.deadline <= now) {
    return { blocked: true, message: "The operator freshness deadline passed (this is not an NHC expiry). A fresh source check is required." }
  }
  if (now - value.issued > MAX_ISSUE_AGE) return { blocked: true, message: "The saved NHC advisory is more than six hours old. A fresh source check is required." }
  const problem = nhcAdvisoryCopyProblem(String(draft.text || ""), value)
  return problem ? { blocked: true, message: problem } : { blocked: false }
}
