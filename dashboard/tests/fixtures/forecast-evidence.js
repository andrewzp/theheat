// Invented saved-input fixture. Not a provider response or scientific approval.
export function forecastDraft(kind = "air_quality_hazard") {
  const eventId = `${kind}_invented_harbour_2026-01-15`
  const series = Object.fromEntries([
    ["pm2_5", "μg/m³"], ["pm10", "μg/m³"], ["dust", "μg/m³"],
    ["aerosol_optical_depth", "dimensionless"], ["us_aqi", "US AQI"],
  ].map(([key, unit], index) => [key, {
    status: "complete", unit, values: Array.from({ length: 24 }, (_, hour) => index * 10 + hour / 10),
  }]))
  return {
    id: "invented-forecast-draft", event_id: eventId, type: kind,
    text: "An invented forecast for local interface testing.", status: "pending", review_status: "required",
    revision_identity: { content_revision: 1, text_sha256: "text-a", evidence_sha256: "evidence-a", decision_revision: 0 },
    editorial_policy: { policy_sha256: "policy-a" }, automatic_publication: { enabled: false },
    review_context: { facts: [{ label: "City", value: "Invented Harbour" }], two_bot: { bundle: {
      signal_kind: kind, event_id: eventId, raw_signal_dump: { event_id: eventId, forecast_window: {
        schema_version: 1, source_product: "open-meteo-cams-air-quality-auto",
        source_url: "https://air-quality-api.open-meteo.com/v1/air-quality",
        evidence_type: "model_forecast", domain_selection: "auto",
        date: "2026-01-15", timezone: "Asia/Kolkata", utc_offset_seconds: 19800,
        requested_at: "2026-01-15T00:01:00Z", retrieved_at: "2026-01-15T00:01:02Z",
        valid_start: "2026-01-14T18:30:00Z", valid_end: "2026-01-15T18:30:00Z",
        requested_location: { city: "Invented Harbour", country: "Example Country", lat: 10.12, lon: 75.24 },
        grid_location: [10, 75.5], hours: Array.from({ length: 24 }, (_, i) => `2026-01-15T${String(i).padStart(2, "0")}:00`),
        series, method: "Mean or maximum of 24 instantaneous hourly forecast samples on a local calendar day",
        selected_record_sha256: "invented-placeholder-not-authentication",
      } },
    } } },
  }
}
export const savedWindow = draft => draft.review_context.two_bot.bundle.raw_signal_dump.forecast_window
