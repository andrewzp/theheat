import { parseGistDocument } from "./lossless-gist.js"

export async function readJsonObject(request, { strict = false } = {}) {
  let body
  try {
    // The draft edit boundary must refuse duplicate keys and unsafe JSON
    // numbers before selecting quotes/pointers or evaluating a revision.
    body = strict ? parseGistDocument(await request.text()).value : await request.json()
  } catch {
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
