// Read-only presentation of retained input, never source qualification or approval.
const FEED = "https://api.weather.gov/alerts/active"
const ALERT = "https://api.weather.gov/alerts/"
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const text = (value, maximum) => typeof value === "string" && value.trim().length > 0 && value.length <= maximum
  && new TextDecoder().decode(new TextEncoder().encode(value)) === value
const optional = (value, maximum) => value == null || value === "" || text(value, maximum)

export function nwsWarningForDisplay(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle
  const raw = bundle?.raw_signal_dump
  const saved = raw?.source_evidence
  const isNws = draft?.type === "severe_weather" || (typeof draft?.event_id === "string" && draft.event_id.startsWith("nws_"))
    || bundle?.signal_kind === "severe_weather" || saved?.source_url === FEED
  if (!isNws) return { status: "unsupported" }
  if (saved == null) return { status: "missing" }
  const unreadable = { status: "unreadable" }
  try {
    if (!object(saved) || saved.schema_version !== 1 || saved.source_url !== FEED
        || !text(saved.source_alert_id, 512) || !/^urn:oid:[A-Za-z0-9.-]+$/.test(saved.source_alert_id)
        || !object(saved.feature) || saved.feature.type !== "Feature") return unreadable
    const id = saved.source_alert_id, props = saved.feature.properties
    if (!object(props) || props.id !== id || saved.feature.id !== ALERT + id
        || draft.event_id !== "nws_" + id || bundle?.event_id !== draft.event_id
        || raw.event_id !== draft.event_id || bundle.signal_kind !== "severe_weather") return unreadable
    if (![props.event, props.areaDesc, props.senderName, props.messageType].every(value => text(value, 4096))
        || !text(props.description, 65536) || !optional(props.instruction, 65536)
        || ![props.sent, props.effective, props.expires, saved.captured_at].every(value => text(value, 160))
        || !optional(props.ends, 160)) return unreadable
    // Keep original time strings/offsets and full source wording. This view does
    // not infer a current status, convert a forecast into an observation, or
    // silently truncate the part of a warning that contains its consequences.
    return {
      status: "present", event: props.event, area: props.areaDesc, office: props.senderName,
      messageType: props.messageType, sent: props.sent, effective: props.effective,
      expires: props.expires, ends: props.ends || null, capturedAt: saved.captured_at,
      description: props.description, instruction: props.instruction || null, sourceUrl: ALERT + id,
    }
  } catch { return unreadable }
}
