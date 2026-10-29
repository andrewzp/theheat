// Closed dispatch paired with src/media/gist_media.py and gist_hazard_media.py;
// never a plugin registry. The deployed temperature kind delegates unchanged. A
// kind joins only with its complete preview, joint-review, approval and sender
// path; any other attachment, including an experimental or PG one, stays refused
// (removal remains available). Source qualification and rendering stay in Python:
// this module checks structure, the retained-source binding and code pins only.
import { createHash } from "node:crypto"
import manifest from "./graphic-runtime-manifest.json" with { type: "json" }
import { draftIdentity, fingerprint } from "./draft-revisions.js"
import { prepareGistTemperatureMedia, validGistTemperatureMedia } from "./gist-temperature-media.js"

// Literals, not imports: an import cycle with draft-revisions.js must never
// evaluate another module's binding while this module initializes.
const TEMPERATURE = "gist_temperature_comparator_v1"
const PM25 = "gist_pm25_forecast_v1"
const MODIS = "gist_modis_locator_v1"
const VIIRS = "gist_viirs_locator_v1"
const FONT = "src/media/fonts/DejaVuSansMono.ttf"
// Schema 2: canonical, host-independent PNG bytes (src/media/canonical_png.py).
const CODEC_FILE = "src/media/canonical_png.py", PNG_CODEC = "canonical-png-fixed-huffman-1"
const FAMILIES = Object.freeze({
  [PM25]: Object.freeze({ template: "pm25_forecast_day", templateVersion: "p31-pm25-forecast-1",
    adapterVersion: "p31-cams-pm25-1", derivation: "pm25_delivery_v1", signalKind: "air_quality_hazard",
    products: ["open-meteo-cams-air-quality-auto"],
    files: ["src/media/gist_media.py", "src/media/gist_hazard_media.py", CODEC_FILE, FONT, "src/media/evidence_graphic.py",
      "src/media/temperature_graphic_adapter.py", "src/media/air_quality_graphic_adapter.py",
      "src/data/air_quality_contract.py", "src/data/air_quality_evidence.py"],
    source: ["bundle_sha256", "evidence_sha256", "source_product", "window_sha256", "selected_record_sha256",
      "valid_date", "timezone", "valid_start", "valid_end", "requested_at", "retrieved_at"] }),
  [MODIS]: Object.freeze({ template: "modis_thermal_detection_map", templateVersion: "p31-modis-locator-2-social",
    adapterVersion: "p31-firms-modis-map-2", derivation: "modis_delivery_v1", signalKind: "fire", products: ["MODIS_NRT"],
    files: ["src/media/gist_media.py", "src/media/gist_hazard_media.py", CODEC_FILE, FONT, "src/media/evidence_graphic.py",
      "src/media/temperature_graphic_adapter.py", "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
      "src/data/fire_source_contract.py", "src/data/fire_evidence.py", "src/media/maps/ne_110m_land_v4_1_0.json",
      "src/media/maps/manifest.json"],
    source: ["bundle_sha256", "evidence_sha256", "source_product", "receipt_sha256", "acquired_at"] }),
  [VIIRS]: Object.freeze({ template: "viirs_thermal_detection_map", templateVersion: "p31-viirs-locator-1",
    adapterVersion: "p31-firms-viirs-map-1", derivation: "viirs_delivery_v1", signalKind: "fire",
    products: ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"],
    files: ["src/media/gist_media.py", "src/media/gist_hazard_media.py", CODEC_FILE, FONT, "src/media/evidence_graphic.py",
      "src/media/temperature_graphic_adapter.py", "src/media/fire_graphic_adapter.py", "src/media/fire_map_graphic_adapter.py",
      "src/media/viirs_map_graphic_adapter.py", "src/data/fire_source_contract.py", "src/data/fire_evidence.py",
      "src/media/maps/ne_110m_land_v4_1_0.json", "src/media/maps/manifest.json"],
    source: ["bundle_sha256", "evidence_sha256", "source_product", "receipt_sha256", "acquired_at"] }),
})
// Bundle signals the hazard families own; any other signal keeps the temperature path.
const SIGNALS = ["air_quality_hazard", "fire"]
// Store-backed kinds (src/media/gist_crw_media.py, gist_published_media.py): Gist keeps
// only the exact SHA256 of a retained CRW source packet or published asset manifest.
const CRW = "gist_crw_anomaly_v1", RADAR = "gist_published_radar_v1", CHART = "gist_published_chart_v1"
const CRW_FAMILY = Object.freeze({ template: "crw_sampled_cells", templateVersion: "p31-crw-gist-cells-1",
  adapterVersions: ["p31-crw-erddap-1", "p31-crw-erddap-2"], derivation: "crw_delivery_v1", version: "gist-crw-png-1",
  files: ["src/media/gist_media.py", "src/media/gist_crw_media.py", "src/media/gist_hazard_media.py", CODEC_FILE,
    "src/media/gist_assets.py", FONT, "src/media/crw_graphic_adapter.py", "src/data/crw_contract.py",
    "src/data/ocean_sst_anomaly.py", "src/two_bot/intern/marine.py", "src/media/temperature_graphic_adapter.py"],
  source: ["bundle_sha256", "evidence_sha256", "packet_artifact_sha256", "packet_sha256", "region_slug",
    "product_date", "valid_cells", "total_cells"] })
const PUBLISHED_FILES = ["src/media/gist_media.py", "src/media/gist_published_media.py", CODEC_FILE,
  "src/media/gist_assets.py", "src/media/published_radar.py"]
const PRODUCTS = Object.freeze({
  nws_local_standard_radar_v1: Object.freeze({ kind: RADAR, derivation: "ktlx_radar_delivery_v1",
    attestations: ["named_point_context_matches", "raster_labels_match", "unaltered_product_reuse_conditions_met"],
    source: ["bundle_sha256", "source_feature_sha256", "point_sha256", "frame_minute_utc", "valid_end", "useful_until"] }),
  nhc_track_cone_v1: Object.freeze({ kind: CHART, derivation: "nhc_cone_delivery_v1",
    attestations: ["chart_labels_match", "storm_and_advisory_match", "unaltered_product_reuse_conditions_met"],
    source: ["bundle_sha256", "storm_id", "advisory_number", "issued_utc", "useful_until"] }),
})
const CYCLONE_SIGNALS = ["cyclone_rapid_intensification", "cyclone_tier_crossing", "cyclone_landfall",
  "cyclone_land_threat", "cyclone_basin_record"]
export const GIST_STORE_KINDS = Object.freeze([CRW, RADAR, CHART])
export const GIST_MEDIA_KINDS = Object.freeze([TEMPERATURE, ...Object.keys(FAMILIES), ...GIST_STORE_KINDS])
export const GIST_HAZARD_KINDS = Object.freeze(Object.keys(FAMILIES))
export const MAX_DELIVERY = 1000
const MAX_DESCRIPTOR_BYTES = 16384, MAX_PNG_BYTES = 750000, MAX_FULL_BYTES = 100000
const SHA = /^[a-f0-9]{64}$/
const isSHA = value => typeof value === "string" && SHA.test(value)
const plain = value => value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype
const exact = (value, keys) => plain(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
const digest = value => createHash("sha256").update(value).digest("hex")
const refusal = (message, code = "graphic_recheck_required") => Object.assign(new Error(message), { status: 409, code })

export function gistMediaKind(value) {
  const kind = plain(value) ? value.kind : null
  return typeof kind === "string" && GIST_MEDIA_KINDS.includes(kind) ? kind : null
}

export const gistHazardClaims = bundle => plain(bundle) && SIGNALS.includes(bundle.signal_kind)

// The single family a retained bundle can request; only its own signal and retained
// primary product decide. A MODIS receipt is never reinterpreted as VIIRS.
export function gistHazardFamilyFor(bundle) {
  if (!gistHazardClaims(bundle)) return null
  const product = bundle.signal_kind === "fire" ? bundle.raw_signal_dump?.acquisition_provenance?.source_product : null
  return Object.keys(FAMILIES).find(kind => bundle.signal_kind === FAMILIES[kind].signalKind
    && (bundle.signal_kind !== "fire" || FAMILIES[kind].products.includes(product))) ?? null
}

function receipts(bundle) {
  const related = bundle.related_signals === undefined ? [] : bundle.related_signals
  return [bundle.raw_signal_dump.acquisition_provenance, ...related.map(row => row.acquisition_evidence)]
}

function wellFormed(text) {
  return typeof text === "string" && Buffer.from(text, "utf8").toString("utf8") === text
}

function sourceFields(kind, bundle) {
  const raw = bundle.raw_signal_dump
  if (kind === PM25) {
    const window = raw.forecast_window
    return { bundle_sha256: fingerprint(bundle), source_product: window.source_product, window_sha256: fingerprint(window),
      selected_record_sha256: window.selected_record_sha256, valid_date: window.date,
      ...Object.fromEntries(["timezone", "valid_start", "valid_end", "requested_at", "retrieved_at"].map(key => [key, window[key]])) }
  }
  if (FAMILIES[kind]?.signalKind === "fire") {
    const rows = receipts(bundle)
    return { bundle_sha256: fingerprint(bundle), source_product: rows[0].source_product,
      receipt_sha256: rows.map(row => fingerprint(row)), acquired_at: rows[0].acquired_at }
  }
  throw new Error("unsupported attachment")
}

function validHazardMedia(draft, value) {
  const family = FAMILIES[value.kind], bundle = draft?.review_context?.two_bot?.bundle
  const keys = ["schema_version", "kind", "template", "template_version", "adapter_version", "synthetic", "source", "renderer", "image", "description"]
  if (!exact(value, keys) || value.schema_version !== 2 || value.template !== family.template
      || value.template_version !== family.templateVersion || value.adapter_version !== family.adapterVersion
      || value.synthetic !== false || Buffer.byteLength(JSON.stringify(value), "utf8") > MAX_DESCRIPTOR_BYTES) return false
  if (Array.isArray(draft.hot10_rows) && draft.hot10_rows.length) return false
  if (!plain(bundle) || bundle.signal_kind !== family.signalKind) return false
  const source = value.source
  const fire = family.signalKind === "fire", list = source?.receipt_sha256
  if (!exact(source, family.source) || !Object.keys(source).every(k => k === "receipt_sha256" || typeof source[k] === "string")
      || !Object.keys(source).filter(k => k.endsWith("_sha256") && k !== "receipt_sha256").every(k => isSHA(source[k]))
      || fire !== Object.hasOwn(source, "receipt_sha256")
      || (fire && (!Array.isArray(list) || list.length < 1 || list.length > 4 || !list.every(isSHA)))
      || !family.products.includes(source.source_product)) return false
  const expected = sourceFields(value.kind, bundle)
  if (Object.keys(expected).some(key => JSON.stringify(expected[key]) !== JSON.stringify(source[key]))) return false
  const r = value.renderer, files = manifest.identity.files
  if (!exact(r, ["version", "files", "pillow", "freetype", "png_codec", "layout", "width", "height"])
      || r.version !== "gist-hazard-png-2" || r.pillow !== "12.2.0" || r.layout !== "basic" || r.png_codec !== PNG_CODEC
      || r.width !== 1200 || r.height !== 1500
      || !(typeof r.freetype === "string" && r.freetype.length > 0 && r.freetype.length <= 64)
      || !exact(r.files, family.files) || !family.files.every(path => isSHA(files[path]) && r.files[path] === files[path])) return false
  const image = value.image
  if (!exact(image, ["mime_type", "png_sha256", "byte_count", "width", "height", "mode"]) || image.mime_type !== "image/png"
      || !isSHA(image.png_sha256) || !Number.isSafeInteger(image.byte_count) || image.byte_count <= 0
      || image.byte_count > MAX_PNG_BYTES || image.width !== 1200 || image.height !== 1500 || image.mode !== "RGB") return false
  const d = value.description, text = d?.delivery_text
  return exact(d, ["derivation", "delivery_text", "delivery_sha256", "delivery_scalars", "delivery_bytes", "full_sha256", "full_bytes"])
    && d.derivation === family.derivation && wellFormed(text) && text.length > 0
    && [...text].length <= MAX_DELIVERY && Buffer.byteLength(text, "utf8") <= MAX_DELIVERY
    && d.delivery_scalars === [...text].length && d.delivery_bytes === Buffer.byteLength(text, "utf8")
    && d.delivery_sha256 === digest(text) && isSHA(d.full_sha256)
    && Number.isSafeInteger(d.full_bytes) && d.full_bytes > 0 && d.full_bytes <= MAX_FULL_BYTES
}

const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/
const isUTC = value => typeof value === "string" && UTC.test(value) && micros(value) !== null

function validDescription(d, derivation) {
  const text = d?.delivery_text
  return exact(d, ["derivation", "delivery_text", "delivery_sha256", "delivery_scalars", "delivery_bytes", "full_sha256", "full_bytes"])
    && d.derivation === derivation && wellFormed(text) && text.length > 0
    && [...text].length <= MAX_DELIVERY && Buffer.byteLength(text, "utf8") <= MAX_DELIVERY
    && d.delivery_scalars === [...text].length && d.delivery_bytes === Buffer.byteLength(text, "utf8")
    && d.delivery_sha256 === digest(text) && isSHA(d.full_sha256)
    && Number.isSafeInteger(d.full_bytes) && d.full_bytes > 0 && d.full_bytes <= MAX_FULL_BYTES
}

const pinned = (value, paths) => exact(value, paths) && paths.every(path => isSHA(manifest.identity.files[path]) && value[path] === manifest.identity.files[path])

function validCrwMedia(draft, value) {
  const f = CRW_FAMILY, bundle = draft?.review_context?.two_bot?.bundle, raw = bundle?.raw_signal_dump
  const keys = ["schema_version", "kind", "template", "template_version", "adapter_version", "synthetic", "source", "renderer", "image", "description"]
  if (!exact(value, keys) || value.schema_version !== 1 || value.template !== f.template || value.template_version !== f.templateVersion
      || !f.adapterVersions.includes(value.adapter_version) || value.synthetic !== false
      || Buffer.byteLength(JSON.stringify(value), "utf8") > MAX_DESCRIPTOR_BYTES) return false
  if ((Array.isArray(draft.hot10_rows) && draft.hot10_rows.length) || !plain(bundle) || bundle.signal_kind !== "regional_sst_anomaly") return false
  const s = value.source
  if (!exact(s, f.source) || !["bundle_sha256", "evidence_sha256", "packet_artifact_sha256", "packet_sha256"].every(k => isSHA(s[k]))
      || !Number.isSafeInteger(s.valid_cells) || !Number.isSafeInteger(s.total_cells) || s.valid_cells < 10
      || s.valid_cells > s.total_cells || s.total_cells > 20000 || s.bundle_sha256 !== fingerprint(bundle)
      || s.region_slug !== raw?.region_slug || s.product_date !== raw?.date) return false
  const r = value.renderer
  if (!exact(r, ["version", "files", "pillow", "freetype", "png_codec", "layout", "width", "height"]) || r.version !== f.version
      || r.pillow !== "12.2.0" || r.png_codec !== PNG_CODEC || r.layout !== "basic" || r.width !== 1200 || r.height !== 1500
      || !(typeof r.freetype === "string" && r.freetype.length > 0 && r.freetype.length <= 64) || !pinned(r.files, f.files)) return false
  const image = value.image
  return exact(image, ["mime_type", "png_sha256", "byte_count", "width", "height", "mode"]) && image.mime_type === "image/png"
    && isSHA(image.png_sha256) && Number.isSafeInteger(image.byte_count) && image.byte_count > 0 && image.byte_count <= MAX_PNG_BYTES
    && image.width === 1200 && image.height === 1500 && image.mode === "RGB" && validDescription(value.description, f.derivation)
}

function publishedProductFor(bundle) {
  const raw = bundle?.raw_signal_dump
  if (!plain(bundle) || !plain(raw)) return null
  if (bundle.signal_kind === "severe_weather" && Object.hasOwn(raw, "source_evidence")) return "nws_local_standard_radar_v1"
  if (CYCLONE_SIGNALS.includes(bundle.signal_kind) && raw.source === "nhc") return "nhc_track_cone_v1"
  return null
}

function validPublishedMedia(draft, value) {
  const bundle = draft?.review_context?.two_bot?.bundle, raw = bundle?.raw_signal_dump
  const keys = ["schema_version", "kind", "product", "synthetic", "asset", "source", "converter", "attestations", "description"]
  const product = PRODUCTS[value?.product]
  if (!exact(value, keys) || value.schema_version !== 1 || !product || product.kind !== value.kind || value.synthetic !== false
      || Buffer.byteLength(JSON.stringify(value), "utf8") > MAX_DESCRIPTOR_BYTES) return false
  if ((Array.isArray(draft.hot10_rows) && draft.hot10_rows.length) || publishedProductFor(bundle) !== value.product) return false
  const a = value.asset
  if (!exact(a, ["manifest_sha256", "original_sha256", "original_bytes", "original_mime", "derivative_sha256", "derivative_bytes", "width", "height"])
      || ![a.manifest_sha256, a.original_sha256, a.derivative_sha256].every(isSHA)
      || ![a.original_bytes, a.derivative_bytes, a.width, a.height].every(Number.isSafeInteger)
      || a.original_bytes <= 0 || a.original_bytes > 2 * 1024 * 1024 || a.derivative_bytes <= 0 || a.derivative_bytes > 8 * 1024 * 1024
      || !["image/gif", "image/png"].includes(a.original_mime) || a.width < 1 || a.width > 2400 || a.height < 1 || a.height > 2400) return false
  const s = value.source
  if (!exact(s, product.source) || s.bundle_sha256 !== fingerprint(bundle) || !isUTC(s.useful_until)) return false
  if (value.product === "nws_local_standard_radar_v1") {
    if (s.source_feature_sha256 !== raw?.source_evidence?.feature_sha256 || !isSHA(s.point_sha256)
        || !isUTC(s.frame_minute_utc) || !isUTC(s.valid_end)) return false
  } else if (s.storm_id !== raw?.storm_id || s.advisory_number !== String(raw?.advisory_number) || !isUTC(s.issued_utc)) return false
  const c = value.converter
  if (!exact(c, ["version", "method", "png_codec", "pillow", "files"]) || c.version !== "gist-published-png-1"
      || c.method !== "decode_rgba_canonical_png_v1" || c.png_codec !== PNG_CODEC || c.pillow !== "12.2.0"
      || !pinned(c.files, PUBLISHED_FILES)) return false
  return exact(value.attestations, ["version", "required"]) && value.attestations.version === 1
    && JSON.stringify(value.attestations.required) === JSON.stringify(product.attestations)
    && validDescription(value.description, product.derivation)
}

export function validGistMedia(draft, value = draft?.media_attachment) {
  const kind = gistMediaKind(value)
  if (kind === TEMPERATURE) return validGistTemperatureMedia(draft, value)
  if (!kind) return false
  try {
    if (kind === CRW) return validCrwMedia(draft, value)
    if (kind === RADAR || kind === CHART) return validPublishedMedia(draft, value)
    return validHazardMedia(draft, value)
  } catch { return false }
}

// Exact names a joint review must confirm (published originals only).
export function requiredAttestations(value) {
  return (value?.kind === RADAR || value?.kind === CHART) && PRODUCTS[value.product]?.kind === value.kind
    ? [...PRODUCTS[value.product].attestations] : []
}

export function gistNeedsRetainedInput(bundle) {
  return (plain(bundle) && bundle.signal_kind === "regional_sst_anomaly") || publishedProductFor(bundle) !== null
}

// Microseconds since the epoch for the exact UTC spelling the source contract accepts.
function micros(value) {
  const match = typeof value === "string"
    && /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value)
  if (!match) return null
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6]))
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 19) !== value.slice(0, 19)) return null
  return ms * 1000 + Number((match[7] || "").padEnd(6, "0"))
}

// Paired with gist_hazard_media.currentness: explicit image-path recency for manual
// approval and sending, not a provider-certified expiry. Null when current.
export function gistMediaCurrentness(draft, nowMs = Date.now()) {
  const kind = gistMediaKind(draft?.media_attachment)
  if (!kind || kind === TEMPERATURE) return null
  const now = nowMs * 1000, bundle = draft.review_context?.two_bot?.bundle
  if (kind === CRW) {
    // Paired with crw_contract.fresh_day: product day 0-5 UTC days old.
    const day = bundle?.raw_signal_dump?.date
    if (typeof day !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(day) || micros(`${day}T00:00:00Z`) === null)
      return { code: "media_source_unqualified", message: "The retained CRW product day is not qualified" }
    const age = Math.floor(nowMs / 86400000) - Math.floor(Date.parse(`${day}T00:00:00Z`) / 86400000)
    if (age < 0) return { code: "media_source_future", message: "The CRW product day is in the future" }
    if (age > 5) return { code: "media_source_stale", message: "The CRW product day is older than the 0-5 day source window" }
    return null
  }
  if (kind === RADAR || kind === CHART) {
    // Paired with gist_published_media.currentness: radar 15 minutes, cone 6 hours (editorial ceilings).
    const s = draft.media_attachment.source
    const start = micros(kind === RADAR ? s?.frame_minute_utc : s?.issued_utc), until = micros(s?.useful_until)
    if (start === null || until === null) return { code: "media_source_unqualified", message: "The retained published time is not qualified" }
    if (now < start) return { code: "media_source_future", message: "The published image time is in the future" }
    if (now >= until) return { code: "media_published_stale", message: `The published image is past its editorial ceiling (${kind === RADAR ? "15 minutes for radar" : "6 hours for the forecast cone"})` }
    return null
  }
  if (kind === PM25) {
    const window = bundle?.raw_signal_dump?.forecast_window
    const [requested, retrieved, start, end] = ["requested_at", "retrieved_at", "valid_start", "valid_end"].map(key => micros(window?.[key]))
    if ([requested, retrieved, start, end].includes(null)) return { code: "media_source_unqualified", message: "The retained forecast window is not qualified" }
    if (!(requested <= retrieved) || retrieved > now) return { code: "media_source_future", message: "The forecast retrieval time is in the future or inconsistent" }
    if (now < start) return { code: "media_forecast_not_started", message: "The forecast day has not started" }
    if (now >= end) return { code: "media_forecast_ended", message: "The forecast day has ended" }
    if (now - requested > 24 * 3600 * 1000000) return { code: "media_forecast_request_old", message: "The forecast was requested more than 24 hours ago" }
    return null
  }
  if (FAMILIES[kind]?.signalKind === "fire") {
    // Paired with fire_source_contract.freshness: the existing 0-2 UTC source-day rule.
    let rows
    try { rows = receipts(bundle).map(row => row?.acquired_at) } catch { rows = null }
    if (!rows || rows.some(value => typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$/.test(value) || micros(value) === null))
      return { code: "media_source_unqualified", message: "A retained detection receipt is not qualified" }
    const minute = Math.floor(nowMs / 60000) * 60000, today = Math.floor(nowMs / 86400000)
    const results = rows.map(value => {
      const stamp = micros(value) / 1000
      if (stamp > minute) return "future"
      const days = today - Math.floor(stamp / 86400000)
      return days >= 0 && days <= 2 ? "fresh" : "stale"
    })
    if (results.includes("future")) return { code: "media_detection_future", message: "A detection's reported minute is in the future" }
    if (results.some(result => result !== "fresh")) return { code: "media_detection_stale", message: "A detection is older than the 0-2 UTC source-day window" }
    return null
  }
  return { code: "media_unsupported", message: "Unsupported attachment" }
}

function previewOrigin(request) {
  // Same confinement as the deployed temperature recheck in gist-temperature-media.js.
  const input = new URL(request.url), rawHost = (request.headers.get("host") || "").toLowerCase()
  if (process.env.VERCEL === "1") {
    const host = (process.env.VERCEL_URL || "").toLowerCase()
    const production = (process.env.VERCEL_PROJECT_PRODUCTION_URL || "").toLowerCase()
    const allowed = [host, production].filter(value => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app$/.test(value))
    if (input.protocol !== "https:" || !allowed.includes(input.hostname) || rawHost !== input.host)
      throw refusal("Open the protected dashboard to attach this graphic")
    return input.origin
  }
  const destination = new URL(`http://${rawHost}`)
  if (input.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(input.hostname)
      || !["127.0.0.1", "localhost"].includes(destination.hostname)
      || destination.host !== rawHost || destination.port !== input.port)
    throw refusal("Graphic preview origin is unavailable")
  return destination.origin
}

const hazardResponseKeys = ["schema_version", "draft_id", "revision_identity", "policy_source_sha256", "preview_runtime_sha256",
  "media_kind", "media_descriptor", "media_descriptor_sha256", "png_base64", "png_sha256", "title", "delivery_text",
  "expanded_description", "scope", "source", "source_context", "posting_window", "width", "height", "publication_approved", "attachment"]

async function prepareHazardMedia(request, draft, kind, expectedMediaSha256, fetcher) {
  const origin = previewOrigin(request), headers = { "Content-Type": "application/json", Origin: origin }
  for (const name of ["authorization", "cookie", "x-vercel-protection-bypass"]) {
    const value = request.headers.get(name)
    if (value) headers[name] = value
  }
  const revision = { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 }
  const response = await fetcher(`${origin}/api/graphic_preview`, { method: "POST", headers,
    body: JSON.stringify({ draft_id: draft.id, expected_revision: revision, format: "png",
      expected_policy_source_sha256: manifest.identity.policy_source_sha256,
      expected_preview_runtime_sha256: manifest.runtime_sha256 }), cache: "no-store", redirect: "error",
    signal: AbortSignal.timeout(30000) })
  if (!response.ok || !response.headers.get("Content-Type")?.startsWith("application/json")) throw refusal("The saved graphic could not be rechecked")
  const reader = response.body.getReader(), chunks = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > 1024 * 1024) throw refusal("Graphic response exceeds its limit")
      chunks.push(Buffer.from(value))
    }
  } finally { await reader.cancel() }
  const result = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)))
  const descriptor = result?.media_descriptor
  if (!exact(result, hazardResponseKeys) || result.schema_version !== 4 || result.draft_id !== draft.id
      || fingerprint(result.revision_identity) !== fingerprint(revision)
      || result.policy_source_sha256 !== manifest.identity.policy_source_sha256 || result.preview_runtime_sha256 !== manifest.runtime_sha256
      || result.publication_approved !== false || result.attachment !== false || result.media_kind !== kind
      || gistMediaKind(descriptor) !== kind || !validGistMedia(draft, descriptor)
      || result.media_descriptor_sha256 !== fingerprint(descriptor) || result.media_descriptor_sha256 !== expectedMediaSha256)
    throw refusal("The graphic changed; preview and review it again")
  const { image, description } = descriptor
  if (result.png_sha256 !== image.png_sha256 || result.delivery_text !== description.delivery_text
      || !wellFormed(result.expanded_description) || Buffer.byteLength(result.expanded_description, "utf8") !== description.full_bytes
      || digest(result.expanded_description) !== description.full_sha256
      || typeof result.png_base64 !== "string" || !/^[A-Za-z0-9+/]+={0,2}$/.test(result.png_base64))
    throw refusal("The graphic bytes or description changed")
  const png = Buffer.from(result.png_base64, "base64")
  if (png.length > MAX_PNG_BYTES || png.length < 24 || png.length !== image.byte_count || png.toString("base64") !== result.png_base64
      || !png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      || png.readUInt32BE(16) !== 1200 || png.readUInt32BE(20) !== 1500 || digest(png) !== image.png_sha256)
    throw refusal("The graphic bytes changed; preview again")
  return descriptor
}

const storeResponseKeys = {
  4: hazardResponseKeys,
  5: ["schema_version", "draft_id", "revision_identity", "policy_source_sha256", "preview_runtime_sha256", "media_kind",
    "media_descriptor", "media_descriptor_sha256", "png_base64", "png_sha256", "title", "delivery_text", "expanded_description",
    "scope", "posting_window", "publication_approved", "attachment", "original_base64", "original_sha256", "original_mime",
    "inspection", "width", "height"],
}

async function previewJSON(request, draft, extra, fetcher) {
  const origin = previewOrigin(request), headers = { "Content-Type": "application/json", Origin: origin }
  for (const name of ["authorization", "cookie", "x-vercel-protection-bypass"]) {
    const value = request.headers.get(name)
    if (value) headers[name] = value
  }
  const revision = { ...draftIdentity(draft), decision_revision: draft.decision_revision ?? 0 }
  const response = await fetcher(`${origin}/api/graphic_preview`, { method: "POST", headers,
    body: JSON.stringify({ draft_id: draft.id, expected_revision: revision, format: "png", ...extra,
      expected_policy_source_sha256: manifest.identity.policy_source_sha256,
      expected_preview_runtime_sha256: manifest.runtime_sha256 }), cache: "no-store", redirect: "error",
    signal: AbortSignal.timeout(30000) })
  if (!response.ok || !response.headers.get("Content-Type")?.startsWith("application/json")) throw refusal("The saved graphic could not be rechecked")
  const reader = response.body.getReader(), chunks = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > 1024 * 1024) throw refusal("Graphic response exceeds its limit")
      chunks.push(Buffer.from(value))
    }
  } finally { await reader.cancel() }
  return { result: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks))), revision }
}

async function prepareStoreMedia(request, draft, kind, expectedMediaSha256, retainedInputSha256, fetcher) {
  if (!isSHA(retainedInputSha256)) throw refusal("Select the retained source packet or published asset for this image", "media_retained_input_required")
  const { result, revision } = await previewJSON(request, draft, { retained_input_sha256: retainedInputSha256 }, fetcher)
  const descriptor = result?.media_descriptor, schema = kind === CRW ? 4 : 5
  if (!exact(result, storeResponseKeys[schema]) || result.schema_version !== schema || result.draft_id !== draft.id
      || fingerprint(result.revision_identity) !== fingerprint(revision)
      || result.policy_source_sha256 !== manifest.identity.policy_source_sha256 || result.preview_runtime_sha256 !== manifest.runtime_sha256
      || result.publication_approved !== false || result.attachment !== false || result.media_kind !== kind
      || gistMediaKind(descriptor) !== kind || !validGistMedia(draft, descriptor)
      || result.media_descriptor_sha256 !== fingerprint(descriptor) || result.media_descriptor_sha256 !== expectedMediaSha256)
    throw refusal("The graphic changed; preview and review it again")
  const reference = kind === CRW ? descriptor.source.packet_artifact_sha256 : descriptor.asset.manifest_sha256
  if (reference !== retainedInputSha256) throw refusal("The selected retained input changed; preview it again")
  const description = descriptor.description
  if (result.delivery_text !== description.delivery_text || !wellFormed(result.expanded_description)
      || Buffer.byteLength(result.expanded_description, "utf8") !== description.full_bytes
      || digest(result.expanded_description) !== description.full_sha256
      || typeof result.png_base64 !== "string" || !/^[A-Za-z0-9+/]+={0,2}$/.test(result.png_base64))
    throw refusal("The graphic bytes or description changed")
  const png = Buffer.from(result.png_base64, "base64")
  const [size, sha, width, height] = kind === CRW
    ? [descriptor.image.byte_count, descriptor.image.png_sha256, 1200, 1500]
    : [descriptor.asset.derivative_bytes, descriptor.asset.derivative_sha256, descriptor.asset.width, descriptor.asset.height]
  if (png.length !== size || png.length < 24 || png.toString("base64") !== result.png_base64
      || !png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      || png.readUInt32BE(16) !== width || png.readUInt32BE(20) !== height || digest(png) !== sha || result.png_sha256 !== sha)
    throw refusal("The graphic bytes changed; preview again")
  if (kind !== CRW) {
    const original = Buffer.from(String(result.original_base64), "base64")
    if (original.length !== descriptor.asset.original_bytes || digest(original) !== descriptor.asset.original_sha256
        || result.original_sha256 !== descriptor.asset.original_sha256 || result.original_mime !== descriptor.asset.original_mime)
      throw refusal("The published original changed; retain and preview it again")
  }
  return descriptor
}

export async function prepareGistMedia(request, draft, expectedMediaSha256, fetcher = globalThis.fetch, retainedInputSha256 = null) {
  const bundle = draft?.review_context?.two_bot?.bundle
  if (gistNeedsRetainedInput(bundle)) {
    if (typeof expectedMediaSha256 !== "string" || !SHA.test(expectedMediaSha256)) throw refusal("Preview this exact graphic first")
    const kind = bundle.signal_kind === "regional_sst_anomaly" ? CRW : PRODUCTS[publishedProductFor(bundle)].kind
    return prepareStoreMedia(request, draft, kind, expectedMediaSha256, retainedInputSha256, fetcher)
  }
  const kind = gistHazardFamilyFor(bundle)
  if (!kind && gistHazardClaims(bundle)) throw refusal("This saved source has no reviewed post-image family")
  if (!kind) return prepareGistTemperatureMedia(request, draft, expectedMediaSha256, fetcher)
  if (typeof expectedMediaSha256 !== "string" || !SHA.test(expectedMediaSha256)) throw refusal("Preview this exact graphic first")
  return prepareHazardMedia(request, draft, kind, expectedMediaSha256, fetcher)
}
