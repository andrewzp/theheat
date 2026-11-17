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

// Canonical AWC retains two structured observations. Flatten this one known
// shape for reading; do not broaden the generic scalar-fact contract or grant
// qualification, a model check, a review or posting authority.
function displayFacts(bundle) {
  const facts = bundle.current_facts
  if (bundle.signal_kind !== "observed_metar_contrast") return facts
  const schema = "awc-observed-airport-pair-v1", raw = bundle.raw_signal_dump
  const evidence = raw?.evidence, points = evidence?.points
  const labels = ["observed_airports", "sample_clock_utc", "sample_date_utc", "public_source_url", "claim_scope"]
  if (!dense(facts, 5) || facts.length !== 5 || !facts.every(row => object(row) && labels.includes(row.label))
      || new Set(facts.map(row => row.label)).size !== 5 || raw?.report_schema !== schema || evidence?.schema !== schema
      || !dense(points, 2) || points.length !== 2) return null
  const observed = facts.find(row => row.label === "observed_airports")
  if (!dense(observed.value, 2) || observed.value.length !== 2 || (observed.unit != null && observed.unit !== "")) return null
  const fields = ["station_id", "airport", "country_code", "country", "latitude", "longitude", "temperature_c",
    "valid_time", "metar_type", "maintenance", "raw_report_sha256"]
  const stamp = value => text(value, 32) && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?Z$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value.slice(0, 10)
  const point = value => object(value) && Object.keys(value).length === fields.length
    && fields.every(key => Object.hasOwn(value, key)) && typeof value.station_id === "string" && /^[A-Z][A-Z0-9]{3}$/.test(value.station_id)
    && text(value.airport, 200) && [...value.airport].length <= 100 && /\b(?:Arpt|Airport)\b/.test(value.airport)
    && text(value.country, 160) && typeof value.country_code === "string" && /^[A-Z]{2}$/.test(value.country_code)
    && ["latitude", "longitude", "temperature_c"].every(key => typeof value[key] === "number" && Number.isFinite(value[key]))
    && stamp(value.valid_time) && value.valid_time.endsWith(":00Z")
    && ["METAR", "SPECI"].includes(value.metar_type) && value.maintenance === false
    && typeof value.raw_report_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.raw_report_sha256)
  if (!points.every(point) || !observed.value.every(point)
      || !points.every((p, i) => fields.every(key => p[key] === observed.value[i][key]))
      || points[0].station_id === points[1].station_id || points[0].country_code === points[1].country_code
      || points[0].valid_time !== points[1].valid_time || bundle.when !== points[0].valid_time
      || !stamp(evidence.retrieved_at)) return null
  const byLabel = new Map(facts.map(row => [row.label, row]))
  const observedAt = new Date(bundle.when), months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  if (byLabel.get("sample_clock_utc").value !== bundle.when.slice(11, 16) + " UTC"
      || byLabel.get("sample_date_utc").value !== `${observedAt.getUTCDate()} ${months[observedAt.getUTCMonth()]}`
      || byLabel.get("public_source_url").value !== evidence.source_url) return null
  const expanded = points.flatMap((p, i) => {
    const prefix = `Airport ${"AB"[i]}`
    return [
      { label: prefix, value: `${p.airport} (${p.station_id}), ${p.country} (${p.country_code})` },
      { label: `${prefix} air temperature`, value: p.temperature_c, unit: "°C" },
      { label: `${prefix} observed at (UTC)`, value: p.valid_time },
      { label: `${prefix} latitude / longitude`, value: `${p.latitude}, ${p.longitude}` },
      { label: `${prefix} report type`, value: p.metar_type },
    ]
  })
  return [...expanded, ...facts.filter(row => row !== observed), { label: "Source capture (UTC)", value: evidence.retrieved_at }]
}

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
    const facts = displayFacts(bundle)
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
