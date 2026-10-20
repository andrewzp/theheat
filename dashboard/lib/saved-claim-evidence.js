// Bounded display projection only. Model extraction is not a source warrant.
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
const text = (value, limit) => typeof value === "string" && value.trim().length > 0
  && value.length <= limit && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value)
const bounded = value => new TextEncoder().encode(JSON.stringify(value)).length <= 16384
const dense = (value, limit) => Array.isArray(value) && value.length <= limit
  && Object.keys(value).length === value.length && Array.from({ length: value.length }, (_, i) => Object.hasOwn(value, i)).every(Boolean)
const scalar = value => value === null || typeof value === "boolean"
  || (typeof value === "number" && Number.isFinite(value)) || text(value, 2048)
const validFacts = facts => dense(facts, 64) && facts.every(row => object(row)
  && text(row.label, 160) && scalar(row.value) && (row.unit == null || row.unit === "" || text(row.unit, 80)))
const validClaims = claims => dense(claims, 32) && claims.every(row => object(row)
  && Object.keys(row).length === 2 && Object.hasOwn(row, "text") && Object.hasOwn(row, "kind")
  && text(row.text, 2048) && text(row.kind, 80)) && bounded(claims)

function sourceForDisplay(source) {
  if (source?.status !== "saved") return { status: source?.status === "unreadable" ? "unreadable" : "missing", facts: [] }
  if (!text(source.where, 512) || !text(source.when, 128) || !validFacts(source.facts)) return { status: "unreadable", facts: [] }
  const facts = source.facts.map(row => ({ label: row.label, value: row.value, unit: row.unit ?? null }))
  return bounded(facts) ? { status: "saved", where: source.where, when: source.when, facts }
    : { status: "unreadable", facts: [] }
}

export function projectSavedClaimEvidence(draft, { identity, analysisMatches }) {
  const two = draft.review_context?.two_bot
  const bundle = two?.bundle
  let source = { status: "missing", facts: [] }
  if (bundle != null) {
    const facts = bundle.current_facts
    const valid = object(bundle) && text(draft.event_id, 512) && draft.event_id === bundle.event_id
      && text(draft.type, 80) && draft.type === bundle.signal_kind
      && text(bundle.where, 512) && text(bundle.when, 128)
      && validFacts(facts)
    if (valid) {
      const rows = facts.map(row => ({ label: row.label, value: row.value, unit: row.unit ?? null }))
      source = bounded(rows) ? { status: "saved", where: bundle.where, when: bundle.when, facts: rows }
        : { status: "unreadable", facts: [] }
    } else source = { status: "unreadable", facts: [] }
  }
  const raw = two?.fact_check?.extracted_claims
  let claims = { status: "missing", items: [] }
  if (raw != null) {
    if (!validClaims(raw)) {
      claims = { status: "unreadable", items: [] }
    } else if (!analysisMatches) claims = { status: "unbound", items: [] }
    else claims = { status: "bound", items: raw.map(({ text, kind }) => ({ text, kind })) }
  }
  return { schema_version: 1, identity: { ...identity }, claims, source }
}

export function claimEvidenceForDisplay(draft, { editing = false } = {}) {
  const saved = draft?.claim_evidence, identity = draft?.revision_identity
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
  const same = object(saved?.identity) && Number.isSafeInteger(identity?.content_revision)
    && identity.content_revision >= 0 && ["text_sha256", "evidence_sha256"].every(key => sha(identity[key]))
    && ["content_revision", "text_sha256", "evidence_sha256"].every(key => saved.identity[key] === identity[key])
  if (!same || saved.schema_version !== 1) return { claims: { status: editing ? "editing" : "unavailable", items: [] }, source: { status: "missing", facts: [] } }
  // Revalidate the display subset at the client boundary without granting any
  // authority to caller-supplied status strings or performing scientific checks.
  const claims = saved.claims
  return {
    claims: editing ? { status: "editing", items: [] }
      : claims?.status === "bound" ? validClaims(claims.items)
        ? { status: "bound", items: claims.items.map(({ text, kind }) => ({ text, kind })) }
        : { status: "unreadable", items: [] }
        : { status: ["missing", "unbound", "unreadable"].includes(claims?.status) ? claims.status : "unavailable", items: [] },
    source: sourceForDisplay(saved.source),
  }
}
