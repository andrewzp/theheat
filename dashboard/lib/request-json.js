import { parseGistDocument } from "./lossless-gist.js"

// Same bound as the serialized command path (src/commands/schema.MAX_COMMAND_BYTES).
export const MAX_JSON_BODY_BYTES = 128 * 1024
const TOO_LARGE = Symbol("request_body_too_large")

async function boundedText(request, limit) {
  const declared = request.headers.get("content-length")
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > limit)) throw TOO_LARGE
  if (!request.body) return ""
  const reader = request.body.getReader()
  const chunks = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > limit) throw TOO_LARGE
      chunks.push(value)
    }
  } finally { void reader.cancel().catch(() => {}) }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return new TextDecoder().decode(bytes)
}

export async function readJsonObject(request, { strict = false, maxBytes = MAX_JSON_BODY_BYTES } = {}) {
  let body
  try {
    // The draft edit boundary must refuse duplicate keys and unsafe JSON
    // numbers before selecting quotes/pointers or evaluating a revision.
    const text = await boundedText(request, maxBytes)
    body = strict ? parseGistDocument(text).value : JSON.parse(text)
  } catch (error) {
    if (error === TOO_LARGE) {
      return { error: Response.json({ error: "JSON body too large", code: "request_body_too_large" }, { status: 413 }) }
    }
    return {
      error: Response.json({ error: "Invalid JSON body" }, { status: 400 }),
    }
  }

  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return {
      error: Response.json({ error: "JSON body must be an object" }, { status: 400 }),
    }
  }

  return { body }
}
