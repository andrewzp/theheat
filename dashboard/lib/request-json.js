export async function readJsonObject(request) {
  let body
  try {
    body = await request.json()
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
