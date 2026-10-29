// Server codec paired with src/editorial/operator_claim_references.py.
import { draftIdentity, fingerprint, textHash } from "./draft-revisions.js"
import { dense, exact, MAX_BYTES, MAX_ITEMS, retainedClaimFacts, validString, validateReferenceItems } from "./operator-claim-reference-input.js"

export function buildOperatorClaimReferences(text, bundle, items) {
  const checked = validateReferenceItems(text, bundle, items)
  if (!checked.length) return null
  const facts = retainedClaimFacts(bundle)
  const result = { schema_version: 1, origin: "operator_supplied", text_sha256: textHash(text), bundle_sha256: fingerprint(bundle),
    items: checked.map(({ claim, sources }) => ({ claim, sources: sources.map(({ pointer }) => ({ pointer,
      value_sha256: fingerprint(facts[Number(pointer.split("/").at(-1))]) })) })) }
  if (Buffer.byteLength(JSON.stringify(result), "utf8") > MAX_BYTES) throw new Error("Selected references exceed the 16 KiB limit; remove some references")
  return result
}

export function readOperatorClaimReferences(text, bundle, value) {
  if (!exact(value, ["schema_version", "origin", "text_sha256", "bundle_sha256", "items"])
    || value.schema_version !== 1 || value.origin !== "operator_supplied" || !dense(value.items, MAX_ITEMS) || !value.items.length) return null
  try {
    const items = value.items.map(item => {
      if (!exact(item, ["claim", "sources"]) || !dense(item.sources, 64) || !item.sources.every(row => exact(row, ["pointer", "value_sha256"]))) throw new Error("Malformed saved references")
      return { claim: item.claim, sources: item.sources.map(({ pointer }) => ({ pointer })) }
    })
    const expected = buildOperatorClaimReferences(text, bundle, items)
    return fingerprint(expected) === fingerprint(value) ? expected : null
  } catch { return null }
}

export function projectOperatorClaimReferences(draft, identity = draftIdentity(draft)) {
  const review = draft.review_context, bundle = review?.two_bot?.bundle
  if (!review || !Object.hasOwn(review, "operator_claim_references")) return { status: "missing", identity: { ...identity }, items: [] }
  const value = readOperatorClaimReferences(draft.text, bundle, review.operator_claim_references)
  if (!value || draft.revision_conflicts?.length || bundle.event_id !== draft.event_id || bundle.signal_kind !== draft.type)
    return { status: "unavailable", identity: { ...identity }, items: [] }
  const string = (v, max) => validString(v, max) ? v : null
  return { status: "saved", identity: { ...identity }, items: value.items.map(item => ({ claim: item.claim, sources: item.sources.map(({ pointer }) => {
    const row = bundle.current_facts[Number(pointer.split("/").at(-1))]
    return { pointer, fact: { label: row.label, value: row.value, unit: row.unit ?? null } }
  }) })), where: string(bundle.where, 512), when: string(bundle.when, 128), source_type: string(review.source, 80) }
}
