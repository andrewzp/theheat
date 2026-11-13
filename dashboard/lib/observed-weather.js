// Editorial scope only: a missing hold never grants source quality or approval.
// Kept in parity with src/editorial/observed_scope.py by cross-language fixtures.
const KINDS = new Set(["hot10", "air_quality_hazard", "dust_event", "severe_weather",
  "official_warning", "nhc_advisory", "cyclone_land_threat", "wet_bulb_extreme", "extreme_wave"])
const PRODUCTS = new Set(["openmeteo-best-match-forecast-daily-v1", "open-meteo-cams-air-quality-auto",
  "Open-Meteo multi-model forecast precipitation", "openmeteo-marine-forecast"])
const TYPES = new Set(["forecast", "model_forecast"])
const object = value => value && typeof value === "object" && !Array.isArray(value)
const forecast = value => object(value) && (TYPES.has(value.evidence_type) || PRODUCTS.has(value.source_product))
const primary = value => {
  if (!object(value)) return false
  if (KINDS.has(value.signal_kind || value.type)) return true
  const raw = object(value.raw_signal_dump) ? value.raw_signal_dump : {}
  if (raw.source_leg === "open_meteo_flood" || (
    (value.signal_kind || value.type) === "precipitation_extreme" && raw.source_leg === "open_meteo")) return true
  if ([raw, raw.evidence, raw.forecast_window, raw.source_evidence, raw.rainfall_window, value.air_quality_evidence].some(forecast)) return true
  if (Array.isArray(value.current_facts) && value.current_facts.some(row => object(row) && (
    row.label === "evidence_type" && TYPES.has(row.value)
    || row.label === "source_product" && PRODUCTS.has(row.value)))) return true
  const metric = value.headline_metric
  return object(metric) && (metric.is_forecast === true || metric.label === "modeled_discharge_m3s"
    || typeof metric.label === "string" && metric.label.startsWith("forecast_"))
}

export function observedWeatherHold(value, observedOnly) {
  if (observedOnly !== true) return null
  if (primary(value)) return "editorial_forecast_excluded"
  const retained = value?.review_context?.two_bot?.bundle
  if (object(retained) && primary(retained)) return "editorial_forecast_excluded"
  const story = object(retained) ? retained : value
  return Array.isArray(story?.related_signals) && story.related_signals.some(primary)
    ? "editorial_forecast_excluded" : null
}

export const OBSERVED_WEATHER_MESSAGE = "TheHeat reports observed events and factual context; forecast stories are outside the current editorial scope."
