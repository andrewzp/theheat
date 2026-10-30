// Browser-safe quote/fact validation. No checks, review or source fetching.
export const MAX_ITEMS = 32, MAX_FACTS = 64, MAX_LIST = 64, MAX_BYTES = 16384, MAX_RECORD_FIELDS = 16
// A scalar fact is referenced whole; a list-valued fact only by one exact element.
// An element is a scalar or one flat record of scalars (e.g. one ranked Hot10 row);
// an empty list is retained but offers nothing to reference.
const POINTER = /^\/current_facts\/(0|[1-9][0-9]?)(?:\/value\/(0|[1-9][0-9]?))?$/
export const exact = (value, keys) => value && Object.getPrototypeOf(value) === Object.prototype
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
export const dense = (value, max) => Array.isArray(value) && value.length <= max
  && Object.keys(value).length === value.length && Array.from({ length: value.length }, (_, i) => Object.hasOwn(value, i)).every(Boolean)
export const validString = (value, limit) => typeof value === "string" && !!value.trim() && [...value].length <= limit
  && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value) && !/[\uD800-\uDFFF]/u.test(value)
const kindAliases = Object.freeze({ all_time_high: "open_meteo_archive_high", all_time_low: "open_meteo_archive_low",
  record: "calendar_record", record_low: "calendar_record_low" })
// Paired with operator_claim_kind_matches: directional saved legacy labels,
// exactly as documented in two_bot_dispatch; no family matching or coercion.
export function operatorClaimKindMatches(draftType, bundleKind) {
  return validString(draftType, 80) && validString(bundleKind, 80)
    && (draftType === bundleKind || (Object.hasOwn(kindAliases, draftType) && kindAliases[draftType] === bundleKind))
}
const scalar = value => value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) || validString(value, 2048)
const FIELD = /^[a-z][a-z0-9_]{0,63}$/
// Paired with _record: one flat row of named scalars, never nested.
export const isRecord = value => !!value && Object.getPrototypeOf(value) === Object.prototype
  && Object.keys(value).length >= 1 && Object.keys(value).length <= MAX_RECORD_FIELDS
  && Object.entries(value).every(([key, field]) => FIELD.test(key) && scalar(field))
const validFactValue = value => scalar(value) || (dense(value, MAX_LIST) && value.every(item => scalar(item) || isRecord(item)))
const validFact = row => row && Object.getPrototypeOf(row) === Object.prototype
  && validString(row.label, 160) && Object.hasOwn(row, "value") && validFactValue(row.value)
  && (row.unit == null || row.unit === "" || validString(row.unit, 80))
export function retainedClaimFacts(bundle) {
  const facts = bundle?.current_facts
  if (!dense(facts, MAX_FACTS) || !facts.every(validFact))
    throw new Error("Saved source facts are unavailable; refresh before linking a quote")
  return facts
}
// Why references are unavailable, in operator terms (display only; validation stays above).
export function unavailableFactReason(bundle) {
  const facts = bundle?.current_facts
  if (!Array.isArray(facts) || !facts.length) return "This draft saved no structured source facts."
  if (!dense(facts, MAX_FACTS)) return `This draft saved more than ${MAX_FACTS} source facts; references are limited to ${MAX_FACTS}.`
  const index = facts.findIndex(row => !validFact(row))
  if (index < 0) return null
  const row = facts[index], name = validString(row?.label, 160) ? row.label.replaceAll("_", " ") : `fact ${index + 1}`
  if (Array.isArray(row?.value) && row.value.length > MAX_LIST) return `Saved fact “${name}” has more than ${MAX_LIST} entries, so it cannot be referenced.`
  if (Array.isArray(row?.value)) return `Saved fact “${name}” has entries that are not plain values or flat rows, so it cannot be referenced.`
  return `Saved fact “${name}” is not a plain value, so it cannot be referenced.`
}
// Deep equality for a referenced value (scalar or flat record), in saved key order.
export function sameFactValue(a, b) {
  if (isRecord(a) || isRecord(b)) return isRecord(a) && isRecord(b) && Object.keys(a).length === Object.keys(b).length
    && Object.keys(a).every(key => Object.hasOwn(b, key) && a[key] === b[key])
  return a === b
}
// One plain-language line for a referenced value; a record lists every named field.
export function factValueText(value) {
  if (value === null) return "Not supplied"
  if (isRecord(value)) return Object.entries(value).map(([key, field]) => `${key.replaceAll("_", " ")} ${field === null ? "not supplied" : String(field)}`).join(" · ")
  return String(value)
}
// Paired with resolve_reference: the exact fact (or list element) and the value its digest binds.
export function resolveReference(facts, pointer, fingerprint = null) {
  const match = typeof pointer === "string" ? POINTER.exec(pointer) : null
  if (!match) throw new Error("Select a saved source fact from this draft")
  const index = Number(match[1])
  if (index >= facts.length) throw new Error("A selected source fact is missing or repeated")
  const fact = facts[index], listed = Array.isArray(fact.value)
  if (match[2] === undefined) {
    if (listed) throw new Error("Select one exact element of a list-valued source fact")
    return { view: { label: fact.label, value: fact.value, unit: fact.unit ?? null }, bound: fact }
  }
  const element = Number(match[2])
  if (!listed || element >= fact.value.length) throw new Error("A selected source fact is missing or repeated")
  return { view: { label: `${fact.label}[${element}]`, value: fact.value[element], unit: fact.unit ?? null },
    bound: fingerprint ? { fact_sha256: fingerprint(fact), element, value: fact.value[element] } : null }
}
// One choice per scalar fact and per element of a list-valued fact, in saved order.
export function referenceChoices(facts) {
  return facts.flatMap((fact, index) => Array.isArray(fact.value)
    ? fact.value.map((_, element) => ({ pointer: `/current_facts/${index}/value/${element}`, fact: resolveReference(facts, `/current_facts/${index}/value/${element}`).view }))
    : [{ pointer: `/current_facts/${index}`, fact: resolveReference(facts, `/current_facts/${index}`).view }])
}
export function validateReferenceItems(text, bundle, items) {
  if (!validString(text, 280)) throw new Error("The quote must belong to a valid current draft")
  if (!dense(items, MAX_ITEMS)) throw new Error("Use at most 32 operator-selected references")
  if (!items.length) return []
  const facts = retainedClaimFacts(bundle), spans = new Set()
  let selected = 0
  return items.map(item => {
    if (!exact(item, ["claim", "sources"])) throw new Error("Each reference needs an exact quote and selected source facts")
    const { claim, sources } = item, points = [...text]
    if (!exact(claim, ["start", "end", "text"]) || !Number.isSafeInteger(claim.start) || !Number.isSafeInteger(claim.end)
      || claim.start < 0 || claim.start >= claim.end || claim.end > points.length || !validString(claim.text, 280)
      || points.slice(claim.start, claim.end).join("") !== claim.text) throw new Error("The selected quote has changed; select it again")
    const span = `${claim.start}:${claim.end}`
    if (spans.has(span)) throw new Error("Combine the source facts for each selected quote")
    spans.add(span)
    if (!dense(sources, MAX_FACTS) || !sources.length) throw new Error("Select at least one saved source fact for each quote")
    selected += sources.length
    if (selected > MAX_FACTS) throw new Error("Use at most 64 selected source facts in total")
    const pointers = new Set()
    for (const source of sources) {
      if (!exact(source, ["pointer"]) || typeof source.pointer !== "string") throw new Error("Select a saved source fact from this draft")
      resolveReference(facts, source.pointer)
      if (pointers.has(source.pointer)) throw new Error("A selected source fact is missing or repeated")
      pointers.add(source.pointer)
    }
    return structuredClone(item)
  })
}
// DOM textarea offsets are UTF-16; metadata uses Unicode code points.
export function quoteFromSelection(text, start, end) {
  if (typeof text !== "string" || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > text.length)
    throw new Error("Select the quote in the draft text first")
  const prefix = text.slice(0, start), quote = text.slice(start, end), suffix = text.slice(end)
  if (!validString(quote, 280) || /[\uD800-\uDFFF]/u.test(prefix + "|" + quote + "|" + suffix)) throw new Error("Select the complete quote again")
  return { start: [...prefix].length, end: [...prefix].length + [...quote].length, text: quote }
}

export function operatorReferencesForDisplay(draft) {
  const view = draft?.operator_claim_reference_view, identity = draft?.revision_identity
  const unavailable = { status: "unavailable", items: [] }
  if (!Number.isSafeInteger(identity?.content_revision) || identity.content_revision < 0
    || !["text_sha256", "evidence_sha256"].every(key => typeof identity[key] === "string" && /^[a-f0-9]{64}$/.test(identity[key]))
    || !view?.identity || !["content_revision", "text_sha256", "evidence_sha256"].every(key => identity[key] === view.identity[key])) return unavailable
  if (view.status === "missing") return { status: "missing", items: [] }
  if (view.status !== "saved" || !dense(view.items, MAX_ITEMS) || !view.items.length) return unavailable
  try {
    const bundle = draft.review_context?.two_bot?.bundle
    if (bundle?.event_id !== draft.event_id || !operatorClaimKindMatches(draft.type, bundle?.signal_kind)) throw new Error("Source changed")
    retainedClaimFacts(bundle)
    const items = view.items.map(item => {
      if (!exact(item, ["claim", "sources"]) || !dense(item.sources, MAX_FACTS)) throw new Error("Unavailable references")
      return { claim: item.claim, sources: item.sources.map(source => {
        if (!exact(source, ["pointer", "fact"]) || !exact(source.fact, ["label", "value", "unit"])) throw new Error("Unavailable fact")
        const current = resolveReference(bundle.current_facts, source.pointer).view
        if (source.fact.label !== current.label || !sameFactValue(source.fact.value, current.value) || source.fact.unit !== current.unit) throw new Error("Source changed")
        return { pointer: source.pointer }
      }) }
    })
    validateReferenceItems(draft.text, bundle, items)
    const string = (value, max) => validString(value, max) ? value : null
    return { status: "saved", items: structuredClone(view.items), where: string(view.where, 512), when: string(view.when, 128), source_label: string(view.source_label, 80),
      source_type: string(view.source_type, 80), scope: string(view.scope, 160), issued_at: string(view.issued_at, 128),
      valid_start: string(view.valid_start, 128), valid_end: string(view.valid_end, 128) }
  } catch { return unavailable }
}
