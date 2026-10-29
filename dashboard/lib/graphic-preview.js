// Browser-only presentation contract. Source qualification stays in Python.
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

function pngBytes(base64) {
  if (typeof base64 !== "string" || base64.length === 0 || base64.length > 1_000_000
      || base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64)) throw new Error("invalid PNG")
  const decoded = atob(base64)
  if (btoa(decoded) !== base64) throw new Error("invalid PNG")
  const bytes = Uint8Array.from(decoded, char => char.charCodeAt(0))
  if (bytes.length < 33 || bytes.length > 750_000
      || [137, 80, 78, 71, 13, 10, 26, 10].some((byte, index) => bytes[index] !== byte)
      || new DataView(bytes.buffer).getUint32(8) !== 13
      || String.fromCharCode(...bytes.slice(12, 16)) !== "IHDR"
      || new DataView(bytes.buffer).getUint32(16) !== 1200
      || new DataView(bytes.buffer).getUint32(20) !== 1500) throw new Error("invalid PNG")
  return bytes
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
      || !exactKeys(descriptor, descriptorKeys) || descriptor.schema_version !== 1
      || descriptor.kind !== "gist_temperature_comparator_v1" || encoder.encode(JSON.stringify(descriptor)).length > 16384
      || ![descriptor.bundle_sha256, descriptor.source_revision_sha256, descriptor.baseline_revision_sha256,
        descriptor.png_sha256, descriptor.alt_sha256].every(isSHA)
      || descriptor.station_id !== value.source_context.station_id || descriptor.valid_date !== value.source_context.valid_date
      || descriptor.png_sha256 !== value.png_sha256 || descriptor.alt_text !== value.alt_text
      || !exactKeys(renderer, ["implementation_sha256", "font_sha256", "pillow", "freetype", "zlib", "width", "height"])
      || renderer.width !== 1200 || renderer.height !== 1500
      || !isSHA(files?.["src/media/gist_temperature_media.py"])
      || !isSHA(files?.["src/media/fonts/DejaVuSansMono.ttf"])
      || renderer.implementation_sha256 !== files["src/media/gist_temperature_media.py"]
      || renderer.font_sha256 !== files["src/media/fonts/DejaVuSansMono.ttf"]
      || ![renderer.pillow, renderer.freetype, renderer.zlib].every(value => typeof value === "string" && value.length > 0 && value.length <= 64)
      || await digestBytes(pngBytes(value.png_base64)) !== value.png_sha256
      || await digest(value.alt_text) !== descriptor.alt_sha256
      || await digest(JSON.stringify(bindingPayload(descriptor))) !== value.media_descriptor_sha256) throw new Error("invalid preview")
  return value
}

export async function validateGraphicResponse(value, request, manifest) {
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
export function createGraphicPreviewController({ manifest, onChange, fetcher = globalThis.fetch,
  createURL = blob => URL.createObjectURL(blob), revokeURL = url => URL.revokeObjectURL(url), timeoutMs = 35000 }) {
  let generation = 0, active = null, url = null, disposed = false
  function clear() {
    generation++
    active?.abort(); active = null
    if (url) revokeURL(url)
    url = null
  }
  return {
    dispose() { disposed = true; clear() },
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
        if (!response.ok) { onChange({ status: "error", message: errors[response.status] || unavailable }); return }
        const value = await validateGraphicResponse(await readBounded(response), request, manifest)
        if (!valid() || controller.signal.aborted) return
        const image = value.schema_version === 3 ? pngBytes(value.png_base64) : value.svg_utf8
        url = createURL(new Blob([image], { type: value.schema_version === 3 ? "image/png" : "image/svg+xml" }))
        onChange({ status: "ready", value, url })
      } catch {
        if (valid()) onChange({ status: "error", message: unavailable })
      } finally {
        clearTimeout(timeout)
        if (valid()) active = null
      }
    },
  }
}
