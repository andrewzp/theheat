import { isDeepStrictEqual } from "node:util"
import { validGistTemperatureMedia } from "./gist-temperature-media.js"

// A storage boundary, not a source validator. Never repair or rehash evidence.
const MAX_BYTES = 8 * 1024 * 1024
const MAX_NODES = 1000000
const MAX_DEPTH = 64
const own = (value, key) => Object.hasOwn(value, key)
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value)
const fail = (code = "state_evidence_preservation") => {
  const message = code === "state_evidence_limit"
    ? "Saved state exceeds the supported editing size or depth"
    : "Saved state cannot be changed without losing retained evidence"
  throw Object.assign(new Error(message), { status: 409, code })
}

export function parseGistDocument(raw) {
  if (typeof raw !== "string") fail()
  if (Buffer.byteLength(raw, "utf8") > MAX_BYTES) fail("state_evidence_limit")
  let position = 0, count = 0
  const whitespace = () => { while (/[\x20\t\r\n]/.test(raw[position] || "x")) position++ }
  function stringToken() {
    const start = position++
    while (position < raw.length) {
      const character = raw[position++]
      if (character === "\\") position++
      else if (character === '"') {
        try { return JSON.parse(raw.slice(start, position)) } catch { fail() }
      }
    }
    fail()
  }
  function parse(depth) {
    if (++count > MAX_NODES || depth > MAX_DEPTH) fail("state_evidence_limit")
    whitespace()
    const start = position
    let value, children
    if (raw[position] === '"') value = stringToken()
    else if (raw[position] === "{" || raw[position] === "[") {
      const array = raw[position++] === "["
      const end = array ? "]" : "}"
      value = array ? [] : {}
      children = array ? [] : new Map()
      whitespace()
      if (raw[position] !== end) {
        while (true) {
          whitespace()
          let key
          if (!array) {
            if (raw[position] !== '"') fail()
            key = stringToken()
            if (children.has(key)) fail()
            whitespace()
            if (raw[position++] !== ":") fail()
          }
          const child = parse(depth + 1)
          if (array) { value.push(child.value); children.push(child) }
          else {
            children.set(key, child)
            // JSON's __proto__ is data, never a prototype assignment.
            Object.defineProperty(value, key, { value: child.value, enumerable: true, writable: true, configurable: true })
          }
          whitespace()
          if (raw[position] !== ",") break
          position++
        }
      }
      if (raw[position++] !== end) fail()
    } else {
      const token = /^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(raw.slice(position))?.[0]
      if (!token) fail()
      position += token.length
      value = JSON.parse(token)
      if (typeof value === "number" && (!Number.isFinite(value)
        || (Number.isInteger(value) && !Number.isSafeInteger(value)))) fail()
    }
    const descendants = children instanceof Map ? [...children.values()] : children || []
    const nodes = 1 + descendants.reduce((total, child) => total + child.nodes, 0)
    const height = descendants.reduce((maximum, child) => Math.max(maximum, child.height + 1), 0)
    return { value, children, raw: raw.slice(start, position), nodes, height }
  }
  const root = parse(0)
  whitespace()
  if (position !== raw.length || !object(root.value)) fail()
  return root
}

function field(node, key) { return node?.children instanceof Map ? node.children.get(key) : undefined }
function draftNodes(document) {
  const node = field(document, "drafts")
  if (!node) return new Map()
  if (!Array.isArray(node.children)) fail()
  const result = new Map()
  for (const draft of node.children) {
    const id = draft.value?.id
    if (typeof id !== "string" || !id || result.has(id)) fail()
    result.set(id, draft)
  }
  return result
}

// Ignore only decision/check fields that invalidateText intentionally removes.
function protectedEvidence(draft) {
  const result = {}
  for (const key of ["event_id", "type", "tweet_date", "hot10_rows", "media_attachment"]) {
    if (own(draft, key)) result[key] = draft[key]
  }
  if (own(draft, "review_context")) {
    const context = draft.review_context
    if (!object(context)) result.review_context = context
    else {
      result.review_context = Object.fromEntries(Object.entries(context).filter(([key]) => key !== "two_bot"))
      if (object(context.two_bot) && own(context.two_bot, "bundle")) result.review_context.two_bot = { bundle: context.two_bot.bundle }
      else if (own(context, "two_bot") && !object(context.two_bot)) result.review_context.two_bot = context.two_bot
    }
  }
  return result
}

function containsSource(draft) {
  return ["review_context", "hot10_rows", "media_attachment"].some(key => own(draft, key))
}

function knownMediaTransition(before, after) {
  if (isDeepStrictEqual(before.media_attachment, after.media_attachment)) return false
  if (own(after, "media_attachment") && !validGistTemperatureMedia(after)) return false
  if (!Number.isSafeInteger(before.content_revision ?? 0) || after.content_revision !== (before.content_revision ?? 0) + 1
      || !Number.isSafeInteger(before.decision_revision ?? 0) || after.decision_revision !== (before.decision_revision ?? 0) + 1
      || after.status !== "pending" || after.text !== before.text) return false
  for (const key of ["approval_binding", "review_binding", "media_review_binding", "approved_at", "auto_approve_at",
    "auto_approve_requested_at", "publish_requested_at", "publish_intent_id", "autoship_on_critic_pass"])
    if (own(after, key)) return false
  const history = after.revision_history, oldHistory = before.revision_history ?? []
  if (!Array.isArray(history) || !Array.isArray(oldHistory)
      || !oldHistory.every(row => history.some(current => isDeepStrictEqual(row, current)))) return false
  if (!history.some(row => row.text === before.text && row.content_revision === (before.content_revision ?? 0)
      && isDeepStrictEqual(row.review_context, before.review_context)
      && isDeepStrictEqual(row.media_attachment, before.media_attachment))) return false
  const left = protectedEvidence(before), right = protectedEvidence(after)
  delete left.media_attachment; delete right.media_attachment
  return isDeepStrictEqual(left, right)
}

export function assertGistEvidenceUnchanged(document, drafts) {
  const originals = draftNodes(document), seen = new Set()
  if (!Array.isArray(drafts)) fail()
  for (const draft of drafts) {
    if (!object(draft) || typeof draft.id !== "string" || !draft.id || seen.has(draft.id)) fail()
    seen.add(draft.id)
    const original = originals.get(draft.id)
    if (original) {
      if (!isDeepStrictEqual(protectedEvidence(draft), protectedEvidence(original.value))
          && !knownMediaTransition(original.value, draft)) fail()
    } else if (containsSource(draft)) fail()
  }
}

// Raw numeric identity is deliberately stricter than editorial fingerprints.
// It catches 500.0 -> 500 drift at the second read, without treating whitespace
// or object-key order as a changed decision.
function numericIdentity(node) {
  if (!node) return null
  if (typeof node.value === "number") return node.raw
  if (Array.isArray(node.children)) return node.children.map(numericIdentity)
  if (node.children instanceof Map) return [...node.children.keys()].sort().map(key => [key, numericIdentity(node.children.get(key))])
  return null
}

export function gistDraftNumericIdentity(document, draftId) {
  return JSON.stringify(numericIdentity(draftNodes(document).get(draftId)))
}

function historyKey(value) {
  if (!object(value) || typeof value.text !== "string") return null
  const revision = value.content_revision ?? 0
  if (!Number.isSafeInteger(revision) || revision < 0) fail()
  return JSON.stringify([revision, value.text])
}

function historySources(draft) {
  const result = new Map(), pending = [draft]
  while (pending.length) {
    const node = pending.pop(), key = historyKey(node.value)
    if (key !== null) result.set(key, [...(result.get(key) || []), node])
    for (const name of ["revision_history", "revision_conflicts"]) {
      const rows = field(node, name)
      if (Array.isArray(rows?.children)) pending.push(...rows.children)
    }
  }
  return result
}

function historySource(row, sources) {
  const candidates = sources.get(historyKey(row)) || []
  // An invalidation snapshot omits event/type/date/hot10 fields. Compare only
  // its supplied evidence fields with this draft's exact historical revision.
  const evidence = protectedEvidence(row)
  const matching = candidates.filter(node => Object.entries(evidence).every(([key, value]) =>
    own(protectedEvidence(node.value), key) && isDeepStrictEqual(value, protectedEvidence(node.value)[key])))
  if (!matching.length) { if (containsSource(row)) fail(); return undefined }
  const exact = matching.filter(node => isDeepStrictEqual(row, node.value))
  const selected = exact.length ? exact : matching
  function numericProjection(value, node) {
    if (typeof value === "number") return node?.raw ?? null
    if (Array.isArray(value)) return value.map((item, index) => numericProjection(item, node?.children?.[index]))
    if (object(value)) return Object.keys(value).sort().map(key => [key, numericProjection(value[key], field(node, key))])
    return null
  }
  const signatures = new Set(selected.map(node => JSON.stringify(exact.length
    ? numericIdentity(node) : numericProjection(evidence, node))))
  if (signatures.size !== 1) fail()
  return selected[0]
}

export function stringifyGistDocument(state, document) {
  const originals = draftNodes(document)
  assertGistEvidenceUnchanged(document, state.drafts || [])
  let count = 0
  function encode(value, node, depth, history = null, name = "") {
    if (++count > MAX_NODES || depth > MAX_DEPTH) fail("state_evidence_limit")
    if (node && isDeepStrictEqual(value, node.value)) {
      count += node.nodes - 1
      if (count > MAX_NODES || depth + node.height > MAX_DEPTH) fail("state_evidence_limit")
      return node.raw
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) fail()
      return Object.is(value, -0) ? "-0.0" : JSON.stringify(value)
    }
    if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value)
    if (Array.isArray(value)) {
      return "[" + value.map((item, index) => {
        if (depth === 1 && name === "drafts") {
          const source = originals.get(item.id)
          return encode(item, source, depth + 1, source ? historySources(source) : new Map())
        }
        const source = history && ["revision_history", "revision_conflicts"].includes(name)
          ? historySource(item, history) : node?.children?.[index]
        return encode(item, source, depth + 1, history)
      }).join(",") + "]"
    }
    if (!object(value) || Object.getPrototypeOf(value) !== Object.prototype) fail()
    return "{" + Object.entries(value).filter(([, item]) => item !== undefined).map(([key, item]) =>
      JSON.stringify(key) + ":" + encode(item, field(node, key), depth + 1, history, key)).join(",") + "}"
  }
  const raw = encode(state, document, 0)
  if (Buffer.byteLength(raw, "utf8") > MAX_BYTES) fail("state_evidence_limit")
  return raw
}
