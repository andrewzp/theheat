// Browser-only presentation contract. Source qualification stays in Python.
import { EDITORIAL_POLICY_MANIFEST } from "./editorial-policy-manifest.js"
const SHA = /^[a-f0-9]{64}$/
const isSHA = value => typeof value === "string" && SHA.test(value)
const LIMIT = 1024 * 1024
const encoder = new TextEncoder()
const canonical = value => JSON.stringify(value, function (_key, item) {
  return item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item
})
const digestBytes = async bytes => Array.from(new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", bytes)))
  .map(byte => byte.toString(16).padStart(2, "0")).join("")
const digest = value => digestBytes(encoder.encode(value))

// Match editorial/revisions.py's typed fingerprint for this fixed ASCII-keyed
// renderer binding. This does not compute or qualify scientific source evidence.
function bindingPayload(value) {
  if (typeof value === "string") return ["string", value]
  if (typeof value === "number" && Number.isSafeInteger(value)) {
    const bytes = new Uint8Array(8)
    new DataView(bytes.buffer).setFloat64(0, value === 0 ? 0 : value, false)
    return ["number", Array.from(bytes).map(byte => byte.toString(16).padStart(2, "0")).join("")]
  }
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value).sort()
    if (keys.some(key => !/^[a-z_][a-z0-9_]*$/.test(key))) throw new Error("invalid binding")
    return ["object", keys.map(key => [key, bindingPayload(value[key])])]
  }
  throw new Error("invalid binding")
}

export function graphicRequest(draft, manifest) {
  const revision = draft?.revision_identity
  if (!draft || !["pending", "approved"].includes(draft.status) || draft.publish_blocked
      || draft.review_status === "conflict" || draft.revision_conflicts?.length || !revision
      || typeof draft.id !== "string" || !draft.id || draft.id.length > 200
      || !Number.isSafeInteger(revision.content_revision) || revision.content_revision < 0
      || !Number.isSafeInteger(revision.decision_revision) || revision.decision_revision < 0
      || revision.decision_revision >= Number.MAX_SAFE_INTEGER
      || !isSHA(revision.text_sha256) || !isSHA(revision.evidence_sha256)) return null
  return { draft_id: draft.id, expected_revision: {
    content_revision: revision.content_revision, text_sha256: revision.text_sha256,
    evidence_sha256: revision.evidence_sha256, decision_revision: revision.decision_revision,
  }, expected_policy_source_sha256: manifest.identity.policy_source_sha256,
  expected_preview_runtime_sha256: manifest.runtime_sha256 }
}

export function temperaturePNGRequest(draft, manifest) {
  const request = graphicRequest(draft, manifest)
  return request ? { ...request, format: "png" } : null
}

// Any reviewed Gist post-image family requests the PNG recipe; Python selects
// and qualifies the family from the retained source, never from this request.
export function mediaPNGRequest(draft, manifest, retainedInputSha256 = null) {
  const request = graphicRequest(draft, manifest)
  if (!request || (retainedInputSha256 !== null && !isSHA(retainedInputSha256))) return null
  return { ...request, format: "png", ...(retainedInputSha256 ? { retained_input_sha256: retainedInputSha256 } : {}) }
}

// Store-backed families need one explicitly selected retained input (exact SHA256).
const CYCLONE_SIGNALS = ["cyclone_rapid_intensification", "cyclone_tier_crossing", "cyclone_landfall",
  "cyclone_land_threat", "cyclone_basin_record"]
export function storeFamilyFor(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle, raw = bundle?.raw_signal_dump
  if (!bundle || !raw || typeof raw !== "object") return null
  if (bundle.signal_kind === "regional_sst_anomaly") return "crw"
  if (bundle.signal_kind === "severe_weather" && Object.hasOwn(raw, "source_evidence")) return "radar"
  if (CYCLONE_SIGNALS.includes(bundle.signal_kind) && raw.source === "nhc") return "cone"
  return null
}

export const graphicRequestKey = request => request ? canonical(request) : "unavailable"

// Products with a reviewed preview template. Suomi NPP, HMS and any mix stay held.
const FIRE_PREVIEW_PRODUCTS = { MODIS_NRT: "modis", VIIRS_NOAA20_NRT: "viirs", VIIRS_NOAA21_NRT: "viirs" }

// A display affordance only. Matching product labels never qualifies source
// receipts; the Python adapter for that one product checks every selected row.
export function firePreviewSourceStatus(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle
  const raw = bundle?.raw_signal_dump
  const primary = raw?.acquisition_provenance
  if (!raw || !primary || typeof raw.source_product !== "string"
      || typeof primary.source_product !== "string") return "missing"
  const product = primary.source_product
  if (bundle.signal_kind !== "fire" || !Object.hasOwn(FIRE_PREVIEW_PRODUCTS, product)
      || raw.source_product !== product) return "unsupported"
  const related = bundle.related_signals === undefined ? [] : bundle.related_signals
  if (!Array.isArray(related) || related.length > 3) return "unsupported"
  for (const signal of related) {
    if (!signal?.acquisition_evidence || typeof signal.acquisition_evidence.source_product !== "string") return "missing"
    if (signal.signal_kind !== "fire" || signal.acquisition_evidence.source_product !== product) return "unsupported"
  }
  return FIRE_PREVIEW_PRODUCTS[product]
}

const temperatureKinds = {
  all_time_high: "open_meteo_archive_high", all_time_low: "open_meteo_archive_low",
  monthly_high: "monthly_high", monthly_low: "monthly_low",
  record: "calendar_record", record_low: "calendar_record_low",
}

export function isTemperaturePreviewType(type) {
  return Object.hasOwn(temperatureKinds, type)
}

// Affordance only. The Python adapter independently qualifies every warrant.
export function temperaturePreviewSourceStatus(draft) {
  const bundle = draft?.review_context?.two_bot?.bundle
  const evidence = bundle?.raw_signal_dump?.evidence
  if (!bundle || !evidence) return "missing"
  return isTemperaturePreviewType(draft.type) && bundle.signal_kind === temperatureKinds[draft.type]
    && evidence.source_product === "noaa-ghcn-daily-v2" && evidence.evidence_type === "observed"
    ? "ghcn" : "unsupported"
}

const templates = {
  temperature_comparator: { version: "p31-preview-3-mobile", source: "NOAA GHCN-Daily · station observations",
    adapter: "src/media/temperature_graphic_adapter.py", context: "ghcn_station_day" },
  modis_thermal_detection_map: { version: "p31-modis-locator-2-social", source: "NASA FIRMS · MODIS",
    adapter: "src/media/fire_map_graphic_adapter.py", context: "modis_acquisition" },
  viirs_thermal_detection_map: { version: "p31-viirs-locator-1", source: "NASA FIRMS · VIIRS",
    adapter: "src/media/viirs_map_graphic_adapter.py", context: "viirs_acquisition" },
  pm25_forecast_day: { version: "p31-pm25-forecast-1", source: "CAMS via Open-Meteo",
    adapter: "src/media/air_quality_graphic_adapter.py", context: "pm25_forecast_day" },
  crw_sampled_cells: { version: "p31-crw-gist-cells-1", source: "NOAA Coral Reef Watch · daily 5 km SST anomaly v3.1",
    adapter: "src/media/crw_graphic_adapter.py", context: "crw_product_day" },
}
const exactKeys = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
function calendarDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
function utcTimestamp(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    && calendarDate(value.slice(0, 10)) && Number(value.slice(11, 13)) < 24
    && Number(value.slice(14, 16)) < 60 && Number(value.slice(17, 19)) < 60
}
// Presentation shapes only: source eligibility and timezone arithmetic stay in Python.
function sourceContext(value, template) {
  const context = value.source_context
  if (context?.kind !== template.context) return false
  if (template.context === "modis_acquisition" || template.context === "viirs_acquisition")
    return exactKeys(context, ["kind", "acquired_at"])
    && utcTimestamp(context.acquired_at) && context.acquired_at.slice(17, 19) === "00"
  if (template.context === "crw_product_day")
    return exactKeys(context, ["kind", "product_date", "retrieved_at", "valid_cells", "total_cells"])
      && calendarDate(context.product_date) && utcTimestamp(context.retrieved_at)
      && Number.isSafeInteger(context.valid_cells) && Number.isSafeInteger(context.total_cells)
      && context.valid_cells >= 10 && context.valid_cells <= context.total_cells && context.total_cells <= 20000
  if (template.context === "ghcn_station_day")
    return exactKeys(context, ["kind", "station_id", "valid_date", "retrieved_at", "reporting_interval_known", "timezone"])
      && typeof context.station_id === "string" && /^[A-Z0-9]{11}$/.test(context.station_id)
      && calendarDate(context.valid_date) && utcTimestamp(context.retrieved_at)
      && context.reporting_interval_known === false && context.timezone === null
  return exactKeys(context, ["kind", "valid_date", "timezone", "valid_start", "valid_end", "requested_at", "retrieved_at"])
    && calendarDate(context.valid_date) && typeof context.timezone === "string" && context.timezone.length <= 128
    && /^[A-Za-z][A-Za-z0-9_+-]*(?:\/[A-Za-z0-9_+-]+)*$/.test(context.timezone)
    && [context.valid_start, context.valid_end, context.requested_at, context.retrieved_at].every(utcTimestamp)
}

const descriptorKeys = ["schema_version", "kind", "bundle_sha256", "source_revision_sha256",
  "baseline_revision_sha256", "station_id", "valid_date", "renderer", "png_sha256", "alt_text", "alt_sha256"]
const pngResponseKeys = ["schema_version", "draft_id", "revision_identity", "policy_source_sha256", "preview_runtime_sha256",
  "publication_approved", "attachment", "width", "height", "title", "alt_text", "scope", "source", "source_context",
  "png_base64", "png_sha256", "media_descriptor", "media_descriptor_sha256"]

function base64Bytes(base64, maxBytes) {
  if (typeof base64 !== "string" || base64.length === 0 || base64.length > Math.ceil(maxBytes / 3) * 4
      || base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64)) throw new Error("invalid bytes")
  const decoded = atob(base64)
  if (btoa(decoded) !== base64) throw new Error("invalid bytes")
  return Uint8Array.from(decoded, char => char.charCodeAt(0))
}

// Native posts are 1200x1500 within 750,000 bytes; a published derivative keeps its own product size.
function pngBytes(base64, width = 1200, height = 1500, maxBytes = 750_000) {
  const bytes = base64Bytes(base64, maxBytes)
  if (bytes.length < 33 || bytes.length > maxBytes
      || [137, 80, 78, 71, 13, 10, 26, 10].some((byte, index) => bytes[index] !== byte)
      || new DataView(bytes.buffer).getUint32(8) !== 13
      || String.fromCharCode(...bytes.slice(12, 16)) !== "IHDR"
      || new DataView(bytes.buffer).getUint32(16) !== width
      || new DataView(bytes.buffer).getUint32(20) !== height) throw new Error("invalid PNG")
  return bytes
}

// Schema-2 recipes: canonical host-independent PNG bytes (src/media/canonical_png.py).
const PNG_CODEC = "canonical-png-fixed-huffman-1"
// Store-backed modules are not in the native runtime; the policy manifest pins their exact source.
const pin = (files, path) => files?.[path] ?? EDITORIAL_POLICY_MANIFEST.files[path]
// Browser presentation guard paired with src/media/gist_hazard_media.py. Python
// qualifies sources and renders; the dashboard route rechecks before any write.
const HAZARD_FILES = ["src/media/gist_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py", "src/media/fonts/DejaVuSansMono.ttf",
  "src/media/evidence_graphic.py", "src/media/temperature_graphic_adapter.py"]
const HAZARD_MEDIA = {
  gist_pm25_forecast_v1: { template: "pm25_forecast_day", templateVersion: "p31-pm25-forecast-1",
    adapterVersion: "p31-cams-pm25-1", derivation: "pm25_delivery_v1",
    files: [...HAZARD_FILES, "src/media/air_quality_graphic_adapter.py", "src/data/air_quality_contract.py", "src/data/air_quality_evidence.py"] },
  gist_modis_locator_v1: { template: "modis_thermal_detection_map", templateVersion: "p31-modis-locator-2-social",
    adapterVersion: "p31-firms-modis-map-2", derivation: "modis_delivery_v1",
    files: [...HAZARD_FILES, "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
      "src/data/fire_source_contract.py", "src/data/fire_evidence.py", "src/media/maps/ne_110m_land_v4_1_0.json", "src/media/maps/manifest.json"] },
  gist_viirs_locator_v1: { template: "viirs_thermal_detection_map", templateVersion: "p31-viirs-locator-1",
    adapterVersion: "p31-firms-viirs-map-1", derivation: "viirs_delivery_v1",
    files: [...HAZARD_FILES, "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
      "src/media/viirs_map_graphic_adapter.py", "src/data/fire_source_contract.py", "src/data/fire_evidence.py",
      "src/media/maps/ne_110m_land_v4_1_0.json", "src/media/maps/manifest.json"] },
}
// CRW is a native sampled-cell chart (schema 4) rebuilt from a retained source packet.
HAZARD_MEDIA.gist_crw_anomaly_v1 = { template: "crw_sampled_cells", templateVersion: "p31-crw-gist-cells-1",
  adapterVersions: ["p31-crw-erddap-1", "p31-crw-erddap-2"], derivation: "crw_delivery_v1", rendererVersion: "gist-crw-png-1",
  files: ["src/media/gist_media.py", "src/media/gist_crw_media.py", "src/media/gist_hazard_media.py", "src/media/canonical_png.py",
    "src/media/gist_assets.py", "src/media/fonts/DejaVuSansMono.ttf", "src/media/crw_graphic_adapter.py", "src/data/crw_contract.py",
    "src/data/ocean_sst_anomaly.py", "src/two_bot/intern/marine.py", "src/media/temperature_graphic_adapter.py"] }
// Published originals (schema 5): Python reverifies every retained byte; this guards presentation.
const PUBLISHED_FILES = ["src/media/gist_media.py", "src/media/gist_published_media.py", "src/media/canonical_png.py",
  "src/media/gist_assets.py", "src/media/published_radar.py"]
const PUBLISHED = {
  nws_local_standard_radar_v1: { kind: "gist_published_radar_v1", derivation: "ktlx_radar_delivery_v1",
    attestations: ["named_point_context_matches", "raster_labels_match", "unaltered_product_reuse_conditions_met"] },
  nhc_track_cone_v1: { kind: "gist_published_chart_v1", derivation: "nhc_cone_delivery_v1",
    attestations: ["chart_labels_match", "storm_and_advisory_match", "unaltered_product_reuse_conditions_met"] },
}
export const GIST_HAZARD_MEDIA_KINDS = Object.freeze(Object.keys(HAZARD_MEDIA))
export const GIST_POST_IMAGE_KINDS = Object.freeze(["gist_temperature_comparator_v1", ...GIST_HAZARD_MEDIA_KINDS,
  "gist_published_radar_v1", "gist_published_chart_v1"])
// Closed operator outcomes paired with src/dashboard_preview/errors.py MEDIA_HOLDS.
export const MEDIA_HOLD_MESSAGES = Object.freeze({
  media_store_unavailable: "No media store is configured here for published or retained-source images; native charts are unaffected.",
  media_retained_input_required: "Select the retained source packet or published asset for this image.",
  media_source_packet_missing: "The retained CRW source packet is not in the media store. Retain it locally first; nothing is fetched.",
  media_original_missing: "The published original is not in the media store. Retain it again; nothing is fetched.",
  media_asset_missing: "A retained asset is missing from the media store.",
  media_asset_changed: "Retained bytes no longer match their identity. Retain the asset again.",
  media_asset_invalid: "The retained asset is unsupported or incomplete: rights, labels, times or format are missing or changed.",
  media_context_mismatch: "The retained image is not for this draft's source (storm, advisory, warning, place or time).",
  media_source_unqualified: "The saved source cannot support this image.",
  media_source_future: "The retained source time is in the future.",
  media_unsupported: "This source has no reviewed image product.",
  media_renderer_changed: "The image profile changed; preview and review again.",
  media_preview_too_large: "This image is too large to preview and send here.",
  media_description_too_long: "The required image description does not fit the 1000-character limit; the text draft is unchanged.",
})
export const MAX_DELIVERY_DESCRIPTION = 1000

// Full port of editorial/revisions.py fingerprint (typed canonical JSON).
function typed(value) {
  if (value === null) return ["null"]
  if (typeof value === "boolean") return ["boolean", value]
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("invalid number")
    const bytes = new Uint8Array(8)
    new DataView(bytes.buffer).setFloat64(0, value === 0 ? 0 : value, false)
    return ["number", Array.from(bytes).map(byte => byte.toString(16).padStart(2, "0")).join("")]
  }
  if (typeof value === "string") {
    if (!value.isWellFormed()) throw new Error("invalid Unicode")
    return ["string", value]
  }
  if (Array.isArray(value)) return ["array", value.map(typed)]
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value).sort((a, b) => {
      const x = encoder.encode(a), y = encoder.encode(b)
      for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i]
      return x.length - y.length
    })
    return ["object", keys.map(key => [typed(key)[1], typed(value[key])])]
  }
  throw new Error("invalid JSON data")
}
export const typedFingerprint = value => digest(JSON.stringify(typed(value)))

const hazardKeys = ["schema_version", "draft_id", "revision_identity", "policy_source_sha256", "preview_runtime_sha256",
  "media_kind", "media_descriptor", "media_descriptor_sha256", "png_base64", "png_sha256", "title", "delivery_text",
  "expanded_description", "scope", "source", "source_context", "posting_window", "width", "height", "publication_approved", "attachment"]

function postingWindow(value) {
  return exactKeys(value, ["status", "code", "reason", "checked_at"]) && utcTimestamp(value.checked_at)
    && (value.status === "current" ? value.code === null && value.reason === null
      : value.status === "unavailable" && typeof value.code === "string" && /^media_[a-z_]{1,60}$/.test(value.code)
        && typeof value.reason === "string" && value.reason.length > 0 && value.reason.length <= 200)
}

async function validateHazardPNGResponse(value, request, manifest) {
  const descriptor = value?.media_descriptor, family = HAZARD_MEDIA[value?.media_kind]
  const template = family ? templates[family.template] : null
  const r = descriptor?.renderer, d = descriptor?.description, image = descriptor?.image, files = manifest?.identity?.files
  if (!family || !exactKeys(value, hazardKeys) || value.schema_version !== 4 || value.draft_id !== request.draft_id
      || canonical(value.revision_identity) !== canonical(request.expected_revision)
      || value.policy_source_sha256 !== request.expected_policy_source_sha256
      || value.preview_runtime_sha256 !== request.expected_preview_runtime_sha256
      || value.publication_approved !== false || value.attachment !== false
      || value.width !== 1200 || value.height !== 1500 || value.source !== template.source
      || !sourceContext(value, template) || !postingWindow(value.posting_window)
      || ![value.title, value.scope].every(text => typeof text === "string" && text.length > 0 && text.length <= 1000)
      || typeof value.delivery_text !== "string" || !value.delivery_text.isWellFormed()
      || [...value.delivery_text].length > MAX_DELIVERY_DESCRIPTION || encoder.encode(value.delivery_text).length > MAX_DELIVERY_DESCRIPTION
      || typeof value.expanded_description !== "string" || !value.expanded_description.isWellFormed()
      || !exactKeys(descriptor, ["schema_version", "kind", "template", "template_version", "adapter_version", "synthetic", "source", "renderer", "image", "description"])
      || descriptor.schema_version !== (family.rendererVersion ? 1 : 2) || descriptor.kind !== value.media_kind || descriptor.template !== family.template
      || descriptor.template_version !== family.templateVersion
      || !(family.adapterVersions ?? [family.adapterVersion]).includes(descriptor.adapter_version)
      // A CRW chart is bound to the exact retained packet the request named; native recipes name none.
      || (family.rendererVersion ? descriptor.source?.packet_artifact_sha256 !== request.retained_input_sha256
        || !isSHA(request.retained_input_sha256) : Object.hasOwn(request, "retained_input_sha256"))
      || descriptor.synthetic !== false || encoder.encode(JSON.stringify(descriptor)).length > 16384
      || !exactKeys(r, ["version", "files", "pillow", "freetype", "png_codec", "layout", "width", "height"])
      || r.version !== (family.rendererVersion ?? "gist-hazard-png-2") || r.pillow !== "12.2.0" || r.layout !== "basic" || r.width !== 1200 || r.height !== 1500
      || r.png_codec !== PNG_CODEC
      // Native families pin only the sealed runtime; the store-backed CRW family may use the policy manifest.
      || !exactKeys(r.files, family.files) || !family.files.every(path => {
        const expected = family.rendererVersion ? pin(files, path) : files?.[path]
        return isSHA(expected) && r.files[path] === expected
      })
      || !exactKeys(image, ["mime_type", "png_sha256", "byte_count", "width", "height", "mode"])
      || image.png_sha256 !== value.png_sha256 || !isSHA(value.png_sha256)
      || !exactKeys(d, ["derivation", "delivery_text", "delivery_sha256", "delivery_scalars", "delivery_bytes", "full_sha256", "full_bytes"])
      || d.derivation !== family.derivation || d.delivery_text !== value.delivery_text
      || d.delivery_scalars !== [...value.delivery_text].length || d.delivery_bytes !== encoder.encode(value.delivery_text).length
      || d.full_bytes !== encoder.encode(value.expanded_description).length) throw new Error("invalid preview")
  const bytes = pngBytes(value.png_base64)
  if (bytes.length !== image.byte_count || await digestBytes(bytes) !== value.png_sha256
      || await digest(value.delivery_text) !== d.delivery_sha256 || await digest(value.expanded_description) !== d.full_sha256
      || await typedFingerprint(descriptor) !== value.media_descriptor_sha256) throw new Error("invalid preview")
  return value
}

const publishedKeys = ["schema_version", "draft_id", "revision_identity", "policy_source_sha256", "preview_runtime_sha256",
  "media_kind", "media_descriptor", "media_descriptor_sha256", "png_base64", "png_sha256", "title", "delivery_text",
  "expanded_description", "scope", "posting_window", "publication_approved", "attachment", "original_base64",
  "original_sha256", "original_mime", "inspection", "width", "height"]
const text = (value, max) => typeof value === "string" && value.length > 0 && value.length <= max && value.isWellFormed()

function inspection(value, product) {
  return exactKeys(value, ["product", "label", "source_url", "retrieved_at", "attribution", "reuse_url",
    "product_reference_url", "time_literal", "quantity", "context", "legend", "required_attestations"])
    && value.product === product && ["label", "attribution", "time_literal", "quantity", "context"].every(key => text(value[key], 2048))
    && ["source_url", "reuse_url", "product_reference_url"].every(key => text(value[key], 2048) && value[key].startsWith("https://"))
    && utcTimestamp(value.retrieved_at) && Array.isArray(value.legend) && value.legend.length > 0 && value.legend.length <= 32
    && value.legend.every(label => text(label, 2048)) && Array.isArray(value.required_attestations)
    && JSON.stringify(value.required_attestations.map(row => row?.name)) === JSON.stringify(PUBLISHED[product].attestations)
    && value.required_attestations.every(row => exactKeys(row, ["name", "text"]) && text(row.text, 300))
}

async function validatePublishedResponse(value, request, manifest) {
  const descriptor = value?.media_descriptor, product = PUBLISHED[descriptor?.product]
  const a = descriptor?.asset, c = descriptor?.converter, d = descriptor?.description, files = manifest?.identity?.files
  if (!product || !exactKeys(value, publishedKeys) || value.schema_version !== 5 || value.draft_id !== request.draft_id
      || canonical(value.revision_identity) !== canonical(request.expected_revision)
      || value.policy_source_sha256 !== request.expected_policy_source_sha256
      || value.preview_runtime_sha256 !== request.expected_preview_runtime_sha256
      || value.publication_approved !== false || value.attachment !== false || value.media_kind !== product.kind
      || descriptor.kind !== product.kind || descriptor.schema_version !== 1 || descriptor.synthetic !== false
      || !exactKeys(descriptor, ["schema_version", "kind", "product", "synthetic", "asset", "source", "converter", "attestations", "description"])
      || encoder.encode(JSON.stringify(descriptor)).length > 16384 || !postingWindow(value.posting_window)
      || !text(value.title, 1000) || !text(value.scope, 1000) || !inspection(value.inspection, descriptor.product)
      || !exactKeys(a, ["manifest_sha256", "original_sha256", "original_bytes", "original_mime", "derivative_sha256", "derivative_bytes", "width", "height"])
      || a.manifest_sha256 !== request.retained_input_sha256 || value.width !== a.width || value.height !== a.height
      || value.png_sha256 !== a.derivative_sha256 || value.original_sha256 !== a.original_sha256 || value.original_mime !== a.original_mime
      || !["image/gif", "image/png"].includes(a.original_mime) || !Number.isSafeInteger(a.width) || !Number.isSafeInteger(a.height)
      || a.width < 1 || a.width > 2400 || a.height < 1 || a.height > 2400
      || !exactKeys(c, ["version", "method", "png_codec", "pillow", "files"]) || c.version !== "gist-published-png-1"
      || c.method !== "decode_rgba_canonical_png_v1" || c.png_codec !== PNG_CODEC || c.pillow !== "12.2.0"
      || !exactKeys(c.files, PUBLISHED_FILES) || !PUBLISHED_FILES.every(path => isSHA(pin(files, path)) && c.files[path] === pin(files, path))
      || canonical(descriptor.attestations) !== canonical({ version: 1, required: product.attestations })
      || !exactKeys(d, ["derivation", "delivery_text", "delivery_sha256", "delivery_scalars", "delivery_bytes", "full_sha256", "full_bytes"])
      || d.derivation !== product.derivation || d.delivery_text !== value.delivery_text || !text(value.delivery_text, 1000)
      || [...value.delivery_text].length > MAX_DELIVERY_DESCRIPTION || encoder.encode(value.delivery_text).length > MAX_DELIVERY_DESCRIPTION
      || d.delivery_scalars !== [...value.delivery_text].length || d.delivery_bytes !== encoder.encode(value.delivery_text).length
      || typeof value.expanded_description !== "string" || !value.expanded_description.isWellFormed()
      || d.full_bytes !== encoder.encode(value.expanded_description).length) throw new Error("invalid preview")
  const derivative = pngBytes(value.png_base64, a.width, a.height, 8 * 1024 * 1024)
  const original = base64Bytes(value.original_base64, 2 * 1024 * 1024)
  if (derivative.length !== a.derivative_bytes || await digestBytes(derivative) !== a.derivative_sha256
      || original.length !== a.original_bytes || await digestBytes(original) !== a.original_sha256
      || await digest(value.delivery_text) !== d.delivery_sha256 || await digest(value.expanded_description) !== d.full_sha256
      || await typedFingerprint(descriptor) !== value.media_descriptor_sha256) throw new Error("invalid preview")
  return value
}

async function validatePNGResponse(value, request, manifest) {
  const descriptor = value?.media_descriptor, renderer = descriptor?.renderer, files = manifest?.identity?.files
  const template = templates.temperature_comparator
  if (!exactKeys(value, pngResponseKeys) || value.schema_version !== 3 || value.draft_id !== request.draft_id
      || canonical(value.revision_identity) !== canonical(request.expected_revision)
      || value.policy_source_sha256 !== request.expected_policy_source_sha256
      || value.preview_runtime_sha256 !== request.expected_preview_runtime_sha256
      || value.publication_approved !== false || value.attachment !== false
      || value.width !== 1200 || value.height !== 1500 || value.source !== template.source
      || !sourceContext(value, template)
      || ![value.title, value.alt_text, value.scope].every(text => typeof text === "string" && text.length > 0 && text.length <= 10000)
      || !isSHA(value.png_sha256) || !isSHA(value.media_descriptor_sha256)
      || !exactKeys(descriptor, descriptorKeys) || descriptor.schema_version !== 2
      || descriptor.kind !== "gist_temperature_comparator_v1" || encoder.encode(JSON.stringify(descriptor)).length > 16384
      || ![descriptor.bundle_sha256, descriptor.source_revision_sha256, descriptor.baseline_revision_sha256,
        descriptor.png_sha256, descriptor.alt_sha256].every(isSHA)
      || descriptor.station_id !== value.source_context.station_id || descriptor.valid_date !== value.source_context.valid_date
      || descriptor.png_sha256 !== value.png_sha256 || descriptor.alt_text !== value.alt_text
      || !exactKeys(renderer, ["implementation_sha256", "font_sha256", "codec_sha256", "png_codec", "pillow", "freetype", "width", "height"])
      || renderer.png_codec !== PNG_CODEC || !isSHA(files?.["src/media/canonical_png.py"])
      || renderer.codec_sha256 !== files["src/media/canonical_png.py"]
      || renderer.width !== 1200 || renderer.height !== 1500
      || !isSHA(files?.["src/media/gist_temperature_media.py"])
      || !isSHA(files?.["src/media/fonts/DejaVuSansMono.ttf"])
      || renderer.implementation_sha256 !== files["src/media/gist_temperature_media.py"]
      || renderer.font_sha256 !== files["src/media/fonts/DejaVuSansMono.ttf"]
      || ![renderer.pillow, renderer.freetype].every(value => typeof value === "string" && value.length > 0 && value.length <= 64)
      || await digestBytes(pngBytes(value.png_base64)) !== value.png_sha256
      || await digest(value.alt_text) !== descriptor.alt_sha256
      || await digest(JSON.stringify(bindingPayload(descriptor))) !== value.media_descriptor_sha256) throw new Error("invalid preview")
  return value
}

export async function validateGraphicResponse(value, request, manifest) {
  if (request?.format === "png" && value?.schema_version === 5) return validatePublishedResponse(value, request, manifest)
  if (request?.format === "png" && value?.schema_version === 4) return validateHazardPNGResponse(value, request, manifest)
  if (request?.format === "png") return validatePNGResponse(value, request, manifest)
  const r = value?.binding?.renderer, files = manifest.identity.files
  const template = Object.hasOwn(templates, value?.binding?.template) ? templates[value.binding.template] : null
  if (!value || value.schema_version !== 2 || value.draft_id !== request.draft_id
      || canonical(value.revision_identity) !== canonical(request.expected_revision)
      || value.policy_source_sha256 !== request.expected_policy_source_sha256
      || value.preview_runtime_sha256 !== request.expected_preview_runtime_sha256
      || value.publication_approved !== false || value.attachment !== false
      || value.width !== 1200 || value.height !== 1500
      || !template || value.source !== template.source || !sourceContext(value, template)
      || Object.hasOwn(value, "source_time")
      || ![value.title, value.alt_text, value.scope].every(text => typeof text === "string" && text.length > 0 && text.length <= 20000)
      || typeof value.svg_utf8 !== "string" || encoder.encode(value.svg_utf8).length > 1_000_000
      || !value.svg_utf8.includes("<svg") || /<!DOCTYPE|<script|<foreignObject|\son[a-z]+\s*=/i.test(value.svg_utf8)
      || !isSHA(value.svg_sha256) || !isSHA(value.cache_key)
      || value.binding?.template_version !== template.version
      || !isSHA(value.binding?.source_evidence_sha256)
      || r?.library !== "ReportLab" || r?.version !== "4.4.9" || r?.format !== "svg" || r?.schema_version !== 1
      || r?.width !== value.width || r?.height !== value.height
      || r?.implementation_sha256 !== files["src/media/evidence_graphic_render.py"]
      || r?.contract_sha256 !== files["src/media/evidence_graphic.py"]
      || r?.adapter_sha256 !== files[template.adapter]
      || r?.font_sha256 !== files["src/media/fonts/DejaVuSansMono.ttf"]
      || await digest(value.svg_utf8) !== value.svg_sha256
      || await digest(JSON.stringify(bindingPayload(value.binding))) !== value.cache_key) throw new Error("invalid preview")
  return value
}

async function readBounded(response) {
  if (Number(response.headers.get("Content-Length")) > LIMIT
      || !response.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) throw new Error("invalid response")
  const reader = response.body.getReader(), chunks = []
  let length = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (length > LIMIT) throw new Error("large response")
      chunks.push(value)
    }
  } finally { await reader.cancel() }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes))
}

const errors = {
  401: "Sign in to preview this draft.",
  403: "Open the protected dashboard address to preview this draft.",
  404: "This saved draft is no longer available. Refresh the queue.",
  409: "This draft changed or has conflicting versions. Refresh it before previewing.",
  422: "The saved source or display limits cannot support this graphic. No substitute was used.",
  429: "Another preview is being built. Try again in a moment.",
}
const unavailable = "The preview is unavailable. Your draft has not changed; try again later."

// Own every in-flight request and Blob. A disposed/replaced request can never
// install an image, even when its fetch/validation completes after cancellation.
async function holdMessage(response) {
  // A store-backed lane names its closed outcome; the text comes from this client's table only.
  try {
    if (response.status !== 422) return null
    const body = await readBounded(response)
    return body?.code === "media_hold" && Object.hasOwn(MEDIA_HOLD_MESSAGES, body.hold) ? { hold: body.hold, message: MEDIA_HOLD_MESSAGES[body.hold] } : null
  } catch { return null }
}

export function createGraphicPreviewController({ manifest, onChange, fetcher = globalThis.fetch,
  createURL = blob => URL.createObjectURL(blob), revokeURL = url => URL.revokeObjectURL(url), timeoutMs = 35000 }) {
  let generation = 0, active = null, url = null, originalURL = null, disposed = false
  function clear() {
    generation++
    active?.abort(); active = null
    if (url) revokeURL(url)
    if (originalURL) revokeURL(originalURL)
    url = null; originalURL = null
  }
  return {
    dispose() { disposed = true; clear() },
    // Discard any in-flight or shown preview (e.g. a different retained input was chosen).
    cancel() { if (disposed) return; clear(); onChange({ status: "idle" }) },
    async start(request) {
      if (disposed || active || !request) return
      clear()
      const current = generation, controller = new AbortController()
      active = controller
      const valid = () => !disposed && current === generation
      const timeout = setTimeout(() => {
        controller.abort()
        if (valid()) { generation++; active = null; onChange({ status: "error", message: unavailable }) }
      }, timeoutMs)
      onChange({ status: "loading" })
      try {
        const response = await fetcher("/api/graphic_preview", { method: "POST", credentials: "same-origin",
          cache: "no-store", redirect: "error", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request), signal: controller.signal })
        if (!valid()) return
        if (!response.ok) {
          const held = await holdMessage(response)
          if (valid()) onChange(held ? { status: "error", message: held.message, hold: held.hold }
            : { status: "error", message: errors[response.status] || unavailable })
          return
        }
        const value = await validateGraphicResponse(await readBounded(response), request, manifest)
        if (!valid() || controller.signal.aborted) return
        const png = [3, 4, 5].includes(value.schema_version)
        const image = value.schema_version === 5 ? pngBytes(value.png_base64, value.width, value.height, 8 * 1024 * 1024)
          : png ? pngBytes(value.png_base64) : value.svg_utf8
        url = createURL(new Blob([image], { type: png ? "image/png" : "image/svg+xml" }))
        if (value.schema_version === 5)
          originalURL = createURL(new Blob([base64Bytes(value.original_base64, 2 * 1024 * 1024)], { type: value.original_mime }))
        onChange({ status: "ready", value, url, originalURL })
      } catch {
        if (valid()) onChange({ status: "error", message: unavailable })
      } finally {
        clearTimeout(timeout)
        if (valid()) active = null
      }
    },
  }
}
