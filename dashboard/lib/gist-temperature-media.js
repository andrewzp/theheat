import { createHash } from "node:crypto"
import manifest from "./graphic-runtime-manifest.json" with { type: "json" }
import { draftIdentity, fingerprint } from "./draft-revisions.js"

export const GIST_TEMPERATURE_KIND = "gist_temperature_comparator_v1"
const SHA = /^[a-f0-9]{64}$/
const keys = ["schema_version", "kind", "bundle_sha256", "source_revision_sha256", "baseline_revision_sha256", "station_id", "valid_date", "renderer", "png_sha256", "alt_text", "alt_sha256"]
// Schema 2: canonical host-independent PNG bytes; the codec source replaces the zlib version.
const rendererKeys = ["implementation_sha256", "font_sha256", "codec_sha256", "png_codec", "pillow", "freetype", "width", "height"]
const exact = (x, names) => x && Object.getPrototypeOf(x) === Object.prototype && Object.keys(x).length === names.length && names.every(k => Object.hasOwn(x, k))
const refusal = message => Object.assign(new Error(message), { status: 409, code: "graphic_recheck_required" })
const digest = value => createHash("sha256").update(value).digest("hex")

export function validGistTemperatureMedia(draft, value = draft?.media_attachment) {
  try {
    if (!exact(value, keys) || value.schema_version !== 2 || value.kind !== GIST_TEMPERATURE_KIND
        || Buffer.byteLength(JSON.stringify(value), "utf8") > 16384) return false
    if (!["bundle_sha256", "source_revision_sha256", "baseline_revision_sha256", "png_sha256", "alt_sha256"].every(k => typeof value[k] === "string" && SHA.test(value[k]))) return false
    const bundle = draft.review_context?.two_bot?.bundle, source = bundle?.raw_signal_dump?.evidence
    if (!source || value.bundle_sha256 !== fingerprint(bundle) || value.source_revision_sha256 !== source.revision_id
        || value.baseline_revision_sha256 !== source.baseline?.revision_id || value.station_id !== source.station_id
        || value.valid_date !== source.valid_date || !/^[A-Z0-9]{11}$/.test(value.station_id)
        || !/^\d{4}-\d{2}-\d{2}$/.test(value.valid_date)) return false
    const r = value.renderer, files = manifest.identity.files
    return exact(r, rendererKeys) && r.width === 1200 && r.height === 1500 && r.pillow === "12.2.0"
      && r.implementation_sha256 === files["src/media/gist_temperature_media.py"] && SHA.test(r.implementation_sha256)
      && r.font_sha256 === files["src/media/fonts/DejaVuSansMono.ttf"] && SHA.test(r.font_sha256)
      && r.codec_sha256 === files["src/media/canonical_png.py"] && SHA.test(r.codec_sha256)
      && r.png_codec === "canonical-png-fixed-huffman-1"
      && typeof r.freetype === "string" && r.freetype.length > 0 && r.freetype.length <= 64
      && typeof value.alt_text === "string" && value.alt_text.length > 0 && [...value.alt_text].length <= 1000
      && Buffer.byteLength(value.alt_text, "utf8") <= 1000
      && Buffer.from(value.alt_text).toString("utf8") === value.alt_text && digest(value.alt_text) === value.alt_sha256
  } catch { return false }
}

function previewOrigin(request) {
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
  // Next may normalize its internal URL to localhost while retaining a numeric
  // loopback Host. Both hosts must remain loopback and their ports must match.
  if (input.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(input.hostname)
      || !["127.0.0.1", "localhost"].includes(destination.hostname)
      || destination.host !== rawHost || destination.port !== input.port)
    throw refusal("Graphic preview origin is unavailable")
  return destination.origin
}

export async function prepareGistTemperatureMedia(request, draft, expectedMediaSha256, fetcher = globalThis.fetch) {
  if (typeof expectedMediaSha256 !== "string" || !SHA.test(expectedMediaSha256)) throw refusal("Preview this exact graphic first")
  const origin = previewOrigin(request), headers = { "Content-Type": "application/json", Origin: origin }
  // Existing request credentials remain on the exact authenticated deployment.
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
  const descriptor = result.media_descriptor
  if (result.schema_version !== 3 || result.draft_id !== draft.id || fingerprint(result.revision_identity) !== fingerprint(revision)
      || result.policy_source_sha256 !== manifest.identity.policy_source_sha256 || result.preview_runtime_sha256 !== manifest.runtime_sha256
      || result.publication_approved !== false || result.attachment !== false || !validGistTemperatureMedia(draft, descriptor)
      || result.media_descriptor_sha256 !== fingerprint(descriptor) || result.media_descriptor_sha256 !== expectedMediaSha256)
    throw refusal("The graphic changed; preview and review it again")
  if (result.png_sha256 !== descriptor.png_sha256 || result.alt_text !== descriptor.alt_text
      || typeof result.png_base64 !== "string" || !/^[A-Za-z0-9+/]+={0,2}$/.test(result.png_base64))
    throw refusal("The graphic bytes or description changed")
  const png = Buffer.from(result.png_base64, "base64")
  if (png.length > 750000 || png.length < 24 || png.toString("base64") !== result.png_base64
      || !png.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))
      || png.readUInt32BE(16) !== 1200 || png.readUInt32BE(20) !== 1500 || digest(png) !== descriptor.png_sha256)
    throw refusal("The graphic bytes changed; preview again")
  return descriptor
}
