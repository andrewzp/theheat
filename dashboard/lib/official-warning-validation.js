// Server-only exact retained-byte validation; a source hash is not authentication.
import { createHash } from "node:crypto"
import { parseGistDocument } from "./lossless-gist.js"
import { officialWarningForDisplay, officialWarningTiming } from "./official-warning-evidence.js"
const digest = value => createHash("sha256").update(value, "utf8").digest("hex")

export function officialWarningValidation(draft, now = Date.now()) {
  const value = officialWarningForDisplay(draft)
  if (value.status === "unsupported") return { blocked: false }
  const invalid = { blocked: true, message: "The exact retained warning changed or is unreadable. Fresh source review is required." }
  if (value.status !== "present") return invalid
  try {
    const { metadata, saved } = value
    // Reuse the strict duplicate-key, depth and number boundary. JSON.parse by
    // itself is used only by the read-only view, never this mutation preflight.
    parseGistDocument(saved.metadata_utf8)
    if (digest(saved.metadata_utf8) !== saved.metadata_sha256 || digest(saved.source_utf8) !== metadata.content_sha256) return invalid
    const url = new URL(metadata.source_url)
    const identity = { schema: "theheat.warning-evidence/v1", metadata_sha256: saved.metadata_sha256,
      content_sha256: metadata.content_sha256, issuer_id: metadata.issuer_id, issuer_name: value.issuer,
      origin: ["https", url.hostname, Number(url.port || 443)], report_id: metadata.report_id,
      revision: metadata.revision, original_language: metadata.original_language }
    const canonical = JSON.stringify(Object.fromEntries(Object.keys(identity).sort().map(key => [key, identity[key]])))
    if (digest(canonical) !== saved.evidence_sha256) return invalid
    return officialWarningTiming(draft, now)
  } catch { return invalid }
}
