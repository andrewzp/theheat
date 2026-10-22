import { sameMediaTarget, retainedMediaBlob } from "./editor-media.js"

const LIMIT = 8 * 1024 * 1024
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
const uuid = value => typeof value === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value)
const keys = (value, expected) => value && typeof value === "object" && !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...expected].sort().join(",")
const identity = value => keys(value, ["draft_id", "content_revision", "decision_revision", "text_sha256", "evidence_sha256"]) &&
  ["content_revision", "decision_revision"].every(k => Number.isSafeInteger(value[k]) && value[k] >= 0) &&
  sha(value.text_sha256) && sha(value.evidence_sha256)
function unavailable() { throw new Error("Earlier local delivery content is unavailable. The saved history remains unchanged.") }
async function digest(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("")
}
function utf8(value) {
  if (typeof value !== "string") unavailable()
  const bytes = new TextEncoder().encode(value)
  if (new TextDecoder("utf-8", { fatal:true }).decode(bytes) !== value) unavailable()
  return bytes
}

export function deliveryHistoryKey(draft) {
  if (!draft?.local_preview || typeof draft.operator_subject !== "string" || !draft.operator_subject) return null
  return JSON.stringify([draft.operator_subject, draft.operator_role, draft.id,
    ...["content_revision", "decision_revision", "text_sha256", "evidence_sha256"].map(k => draft.revision_identity?.[k])])
}

export async function validateDeliveryContent(value, draft, intent) {
  const projected=value?.schema_version === 2
  if (!keys(value, ["schema_version", "draft_id", "target", "scope", "publication_approved", "intent_id", "command_id",
    "approved_at", "approved_target", "text", "proposal_sha256", "packet_sha256", "preparation_packet_sha256", "synthetic", "media", "operator_subject", ...(projected?["platform_description"]:[])]) ||
    !deliveryHistoryKey(draft) || value.operator_subject !== draft.operator_subject || !sameMediaTarget(value, draft) ||
    !identity(value.target) || !identity(value.approved_target) || value.approved_target.draft_id !== draft.id ||
    ![1,2].includes(value.schema_version) || value.scope !== "local_http_fixture_v1" || value.intent_id !== intent || !uuid(intent) ||
    !uuid(value.command_id) || typeof value.approved_at !== "string" || !Number.isFinite(Date.parse(value.approved_at)) ||
    ![value.proposal_sha256, value.packet_sha256, value.preparation_packet_sha256].every(sha) || typeof value.synthetic !== "boolean") unavailable()
  const media = value.media
  if (!keys(media, ["mime_type", "png_sha256", "byte_count", "width", "height", "alt_text", "alt_text_sha256"]) ||
    media.mime_type !== "image/png" || !sha(media.png_sha256) || !sha(media.alt_text_sha256) ||
    !Number.isSafeInteger(media.byte_count) || media.byte_count < 33 || media.byte_count > LIMIT ||
    ![media.width, media.height].every(v => Number.isSafeInteger(v) && v > 0 && v <= 16384)) unavailable()
  const text = utf8(value.text), alt = utf8(media.alt_text)
  if (alt.length > 1_000_000 || await digest(text) !== value.approved_target.text_sha256 ||
      await digest(alt) !== media.alt_text_sha256) unavailable()
  if(projected){
    const description=value.platform_description
    if(!keys(description,["description_sha256","derivation","wire_text","wire_sha256","raw_alt_sha256","status"]) ||
      !sha(description.description_sha256) || !sha(description.wire_sha256) || description.raw_alt_sha256!==media.alt_text_sha256 ||
      description.derivation!=="modis_source_projection_v1" || description.status!=="reviewed_for_local_delivery") unavailable()
    const wire=utf8(description.wire_text)
    if(!wire.length || wire.length>1_000_000 || await digest(wire)!==description.wire_sha256) unavailable()
  }
  return value
}

async function detailBytes(response, signal) {
  if (!response.ok || !/^application\/json(?:;|$)/.test(response.headers.get("content-type") || "") || !response.body) unavailable()
  const declared = response.headers.get("content-length")
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > LIMIT)) unavailable()
  const reader = response.body.getReader(), chunks = []
  let size = 0
  try {
    while (true) {
      if (signal.aborted) unavailable()
      const { done, value } = await reader.read()
      if (signal.aborted) unavailable()
      if (done) break
      size += value.byteLength
      if (size > LIMIT) unavailable()
      chunks.push(value)
    }
    const bytes = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
    return bytes
  } finally { void reader.cancel().catch(() => {}) }
}

export async function loadDeliveryContent(draft, intent, signal) {
  if (!deliveryHistoryKey(draft) || !uuid(intent)) unavailable()
  const controller = new AbortController(), abort = () => controller.abort()
  signal.addEventListener("abort", abort, { once:true })
  if (signal.aborted) controller.abort()
  const timer = setTimeout(abort, 8000)
  try {
    const response = await fetch(`/api/editor-media?draftId=${encodeURIComponent(draft.id)}&deliveryIntent=${intent}`,
      { cache:"no-store", redirect:"error", signal:controller.signal })
    const bytes = await detailBytes(response, controller.signal)
    const detail = await validateDeliveryContent(JSON.parse(new TextDecoder("utf-8", { fatal:true }).decode(bytes)), draft, intent)
    if (controller.signal.aborted) unavailable()
    const blob = await retainedMediaBlob({ draft_id:draft.id, preparation:{ proposal_sha256:detail.proposal_sha256 } }, controller.signal)
    const png = new Uint8Array(await blob.arrayBuffer())
    const dimensions = new DataView(png.buffer, png.byteOffset, png.byteLength)
    if (png.length !== detail.media.byte_count || await digest(png) !== detail.media.png_sha256 ||
        dimensions.getUint32(16) !== detail.media.width || dimensions.getUint32(20) !== detail.media.height || controller.signal.aborted) unavailable()
    return { detail, blob }
  } catch { unavailable() }
  finally { controller.abort(); clearTimeout(timer); signal.removeEventListener("abort", abort) }
}
