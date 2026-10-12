// Only bounded references survive reload. Text and authority stay on the server.
export function recoveryKey(origin, subject) {
  return typeof subject === "string" && subject.length > 0 && subject.length <= 200
    ? `theheat-local-command-v1:${origin}:${encodeURIComponent(subject)}` : null
}
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value)
function canonical(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value)
  if (typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value)
  if (typeof value === "string") {
    if (new TextDecoder().decode(new TextEncoder().encode(value)) !== value) throw new Error("Invalid request Unicode")
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    const utf8 = key => new TextEncoder().encode(key)
    const compare = (a,b) => { const x=utf8(a),y=utf8(b); for(let i=0;i<Math.min(x.length,y.length);i++) if(x[i]!==y[i]) return x[i]-y[i]; return x.length-y.length }
    return `{${Object.keys(value).sort(compare).map(key=>`${canonical(key)}:${canonical(value[key])}`).join(",")}}`
  }
  throw new Error("Unsupported request identity")
}
export async function commandRequestSHA(command) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(command)))
  return Array.from(new Uint8Array(bytes), value=>value.toString(16).padStart(2,"0")).join("")
}
export async function withCommandReference(saved) {
  const request_sha256 = await commandRequestSHA(saved.command)
  if (saved.request_sha256 && saved.request_sha256 !== request_sha256) throw new Error("Recovered request fingerprint differs")
  return { ...saved, original_action:saved.command.action, request_sha256 }
}
export function saveCommandReference(storage, key, saved) {
  if (!key || !sha(saved.request_sha256) || saved.original_action === "abandon_submission") return false
  try {
    storage.setItem(key, JSON.stringify({ command_id:saved.command.command_id, draftId:saved.draftId, action:saved.action,
      original_action:saved.original_action, request_sha256:saved.request_sha256 }))
    return true
  } catch { return false }
}
export function readCommandReference(storage, key) {
  if (!key) return null
  try {
    const raw = storage.getItem(key)
    if (!raw || raw.length > 2048) return null
    const value = JSON.parse(raw), keys=Object.keys(value).sort().join(",")
    const modern=keys === "action,command_id,draftId,original_action,request_sha256"
    if ((!modern && keys !== "action,command_id,draftId") ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.command_id) ||
        typeof value.draftId !== "string" || value.draftId.length > 200 ||
        typeof value.action !== "string" || value.action.length > 64 ||
        (modern && (!sha(value.request_sha256) || typeof value.original_action !== "string" ||
          value.original_action.length > 64 || value.original_action === "abandon_submission"))) return null
    return { command:{ command_id:value.command_id }, draftId:value.draftId, action:value.action,
      ...(modern ? { original_action:value.original_action, request_sha256:value.request_sha256 } : {}) }
  } catch { return null }
}
export function abandonmentBody(saved) {
  if (!sha(saved?.request_sha256) || !saved.original_action || saved.original_action === "abandon_submission") return null
  return { action:"abandon_submission", original_action:saved.original_action, request_sha256:saved.request_sha256 }
}
export function clearCommandReference(storage, key) {
  try { if (key) storage.removeItem(key) } catch { /* No authority is created. */ }
}
