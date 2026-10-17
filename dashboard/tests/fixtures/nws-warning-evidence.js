// Invented data only; no network, publication or real weather assertion.
export function nwsDraft() {
  const id = "urn:oid:2.49.0.1.840.0.abcdef1234567890.001.1"
  const eventId = "nws_" + id
  return {
    id: "invented-warning", type: "severe_weather", event_id: eventId, text: "Invented pending copy.",
    status: "pending", content_revision: 2,
    review_context: { two_bot: { signal_kind: "severe_weather", bundle: {
      signal_kind: "severe_weather", event_id: eventId,
      raw_signal_dump: { event_id: eventId, source_evidence: {
        schema_version: 1, source_url: "https://api.weather.gov/alerts/active", source_alert_id: id,
        captured_at: "2026-01-01T00:10:00Z",
        feature: { type: "Feature", id: "https://api.weather.gov/alerts/" + id, properties: {
          id, event: "Typhoon Warning", areaDesc: "Invented Pelican Island", senderName: "NWS Test Office",
          messageType: "Alert", sent: "2026-01-01T10:00:00+10:00", effective: "2026-01-01T10:00:00+10:00",
          expires: "2026-01-01T16:00:00+10:00", ends: null,
          description: "INVENTED TEST WARNING\n\n" + "Earlier background information. ".repeat(40)
            + "\n\nTAIL: Dangerous winds are possible tonight; this is a forecast, not an observation.",
          instruction: "Invented advice: finish preparations before the forecast wind onset.",
        } },
      } },
    } } },
  }
}
