// Browser-safe quote/fact validation. No checks, review or source fetching.
export const MAX_ITEMS = 32, MAX_FACTS = 64, MAX_BYTES = 16384
export const exact = (value, keys) => value && Object.getPrototypeOf(value) === Object.prototype
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
export const dense = (value, max) => Array.isArray(value) && value.length <= max
  && Object.keys(value).length === value.length && Array.from({ length: value.length }, (_, i) => Object.hasOwn(value, i)).every(Boolean)
export const validString = (value, limit) => typeof value === "string" && !!value.trim() && [...value].length <= limit
  && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value) && !/[\uD800-\uDFFF]/u.test(value)
export function retainedClaimFacts(bundle) {
  const facts = bundle?.current_facts
  const scalar = value => value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) || validString(value, 2048)
  if (!dense(facts, MAX_FACTS) || !facts.every(row => row && Object.getPrototypeOf(row) === Object.prototype
    && validString(row.label, 160) && Object.hasOwn(row, "value") && scalar(row.value)
    && (row.unit == null || row.unit === "" || validString(row.unit, 80))))
    throw new Error("Saved source facts are unavailable; refresh before linking a quote")
  return facts
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
      if (!exact(source, ["pointer"]) || typeof source.pointer !== "string" || !/^\/current_facts\/(?:0|[1-9][0-9]?)$/.test(source.pointer))
        throw new Error("Select a saved source fact from this draft")
      if (Number(source.pointer.split("/").at(-1)) >= facts.length || pointers.has(source.pointer)) throw new Error("A selected source fact is missing or repeated")
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
    retainedClaimFacts(bundle)
    const items = view.items.map(item => {
      if (!exact(item, ["claim", "sources"]) || !dense(item.sources, MAX_FACTS)) throw new Error("Unavailable references")
      return { claim: item.claim, sources: item.sources.map(source => {
        if (!exact(source, ["pointer", "fact"]) || !exact(source.fact, ["label", "value", "unit"])) throw new Error("Unavailable fact")
        const index = Number(source.pointer?.split("/").at(-1)), current = bundle.current_facts[index]
        if (!current || source.fact.label !== current.label || source.fact.value !== current.value || source.fact.unit !== (current.unit ?? null)) throw new Error("Source changed")
        return { pointer: source.pointer }
      }) }
    })
    validateReferenceItems(draft.text, bundle, items)
    const string = (value, max) => validString(value, max) ? value : null
    return { status: "saved", items: structuredClone(view.items), where: string(view.where, 512), when: string(view.when, 128), source_type: string(view.source_type, 80) }
  } catch { return unavailable }
}
