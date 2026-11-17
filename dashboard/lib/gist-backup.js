// Read-only descriptors for the application's configured Gists. No restore,
// source certification, cross-Gist transaction or publishing authority.
import { createHash } from "node:crypto"
import { getStateBackend } from "./state-store.js"
import { previewConfigured } from "./local-preview-boundary.js"

export const BACKUP_LIMITS = Object.freeze({ files: 32, fileBytes: 8 * 1024 * 1024,
  totalBytes: 64 * 1024 * 1024, metadataBytes: 16 * 1024 * 1024,
  metadataRequests: 4, metadataMilliseconds: 30_000, downloadSeconds: 180 })
const GIST = /^[a-f0-9]{5,40}$/
const REVISION = /^[a-f0-9]{40}$/
const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/
const object = value => value !== null && typeof value === "object" && !Array.isArray(value)
export class GistBackupError extends Error {
  constructor(code) { super(code); this.code = code }
}
const require = (value, code) => { if (!value) throw new GistBackupError(code) }

// Detect duplicate keys before JSON.parse can discard an inventory entry.
// Source file content is inert string data, never parsed or normalized here.
function metadataJson(text) {
  let at = 0, nodes = 0
  const white = () => { while (/[\x20\t\r\n]/.test(text[at] || "x")) at++ }
  function string(key = false) {
    const start = at++
    while (at < text.length) {
      const character = text[at++]
      if (character === "\\") at++
      else if (character === '"') return key ? JSON.parse(text.slice(start, at)) : null
    }
    throw new GistBackupError("backup_metadata_invalid")
  }
  function value(depth) {
    require(depth <= 64 && ++nodes <= 1_000_000, "backup_metadata_limit")
    white()
    if (text[at] === '"') { string(); return }
    if (text[at] === "{" || text[at] === "[") {
      const array = text[at++] === "[", end = array ? "]" : "}", keys = new Set()
      white()
      if (text[at] !== end) {
        while (true) {
          white()
          if (!array) {
            require(text[at] === '"', "backup_metadata_invalid")
            const key = string(true)
            require(!keys.has(key), "backup_metadata_duplicate_key"); keys.add(key)
            white(); require(text[at++] === ":", "backup_metadata_invalid")
          }
          value(depth + 1); white()
          if (text[at] !== ",") break
          at++
        }
      }
      require(text[at++] === end, "backup_metadata_invalid"); return
    }
    const literal = /(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/y
    literal.lastIndex = at
    require(literal.exec(text), "backup_metadata_invalid"); at = literal.lastIndex
  }
  value(0); white(); require(at === text.length, "backup_metadata_invalid")
  return JSON.parse(text)
}

export function validateBackupRawUrl(raw, { owner, id, filename }) {
  require(typeof raw === "string" && raw.length <= 8192 && !/[\x00-\x20\x7f]/.test(raw), "backup_raw_url_invalid")
  let url, decoded
  try { url = new URL(raw); decoded = decodeURIComponent(url.pathname.split("/").at(-1)) }
  catch { throw new GistBackupError("backup_raw_url_invalid") }
  const parts = url.pathname.split("/")
  require(url.protocol === "https:" && url.hostname === "gist.githubusercontent.com"
    && !url.username && !url.password && !url.port && !url.search && !url.hash
    && parts.length === 6 && parts[0] === "" && parts[1].toLowerCase() === owner.toLowerCase()
    && parts[2] === id && parts[3] === "raw" && REVISION.test(parts[4])
    && decoded === filename && !/[\\/]/.test(decoded), "backup_raw_url_invalid")
  // Raw file revision and enclosing Gist commit are separate provider identities.
  return { url: raw, raw_revision: parts[4] }
}

function configuredSources() {
  require(!previewConfigured(), "backup_preview_unavailable")
  let backend
  try { backend = getStateBackend() } catch { throw new GistBackupError("backup_configuration_refused") }
  const token = process.env.GITHUB_TOKEN || "", state = process.env.GIST_ID || ""
  const feedback = process.env.THEHEAT_FEEDBACK_GIST_ID || ""
  require(backend === "gist" && GIST.test(state) && (!feedback || GIST.test(feedback))
    && token.length > 0 && token.length <= 4096 && !/[^\x21-\x7e]/.test(token), "backup_configuration_refused")
  const sources = new Map([[state, ["state"]]])
  if (feedback) sources.set(feedback, [...(sources.get(feedback) || []), "feedback"])
  return { token, sources }
}

function inventory(metadata, id, revision) {
  require(object(metadata) && metadata.id === id && metadata.truncated === false
    && object(metadata.owner) && typeof metadata.owner.login === "string" && OWNER.test(metadata.owner.login)
    && Array.isArray(metadata.history) && metadata.history[0]?.version === revision
    && object(metadata.files), "backup_inventory_unverified")
  const entries = Object.entries(metadata.files)
  require(entries.length > 0 && entries.length <= BACKUP_LIMITS.files, "backup_inventory_limit")
  const files = entries.map(([name, file]) => {
    require(object(file) && file.filename === name && typeof name === "string"
      && name.length > 0 && Buffer.byteLength(name) <= 1024 && !/[\x00-\x1f\x7f\\/]/.test(name)
      && ![".", ".."].includes(name) && Number.isSafeInteger(file.size)
      && file.size >= 0 && file.size <= BACKUP_LIMITS.fileBytes, "backup_file_unverified")
    const raw = validateBackupRawUrl(file.raw_url, { owner: metadata.owner.login, id, filename: name })
    return { filename: name, source_bytes: file.size, ...raw }
  }).sort((a, b) => a.filename < b.filename ? -1 : a.filename > b.filename ? 1 : 0)
  return { owner: metadata.owner.login, files }
}

export async function collectGistBackupManifest({ fetchImpl = globalThis.fetch } = {}) {
  const { token, sources } = configuredSources()
  const started = new Date().toISOString(), controller = new AbortController()
  const readers = new Set()
  let requests = 0, timer
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort()
      reject(new GistBackupError("backup_metadata_deadline"))
    }, BACKUP_LIMITS.metadataMilliseconds)
  })
  const current = () => require(!controller.signal.aborted, "backup_metadata_deadline")
  async function metadata(path) {
    current(); require(++requests <= BACKUP_LIMITS.metadataRequests, "backup_metadata_limit")
    const response = await fetchImpl(`https://api.github.com/gists/${path}`, {
      method: "GET", redirect: "error", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28" },
    })
    current()
    require(response.status === 200 && !response.redirected && response.body, "backup_metadata_unavailable")
    const declared = response.headers.get("content-length")
    require(declared === null || /^\d+$/.test(declared) && Number(declared) <= BACKUP_LIMITS.metadataBytes,
      "backup_metadata_limit")
    const reader = response.body.getReader(), chunks = []
    readers.add(reader)
    let size = 0
    try {
      while (true) {
        const { done, value } = await reader.read(); current()
        if (done) break
        size += value.byteLength
        require(size <= BACKUP_LIMITS.metadataBytes, "backup_metadata_limit")
        chunks.push(value)
      }
    } finally { readers.delete(reader); void reader.cancel().catch(() => {}) }
    const bytes = Buffer.concat(chunks, size)
    return { value: metadataJson(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
      metadata_sha256: createHash("sha256").update(bytes).digest("hex") }
  }
  async function capture() {
    const records = []
    let fileCount = 0, byteCount = 0
    for (const [id, roles] of sources) {
      const first = await metadata(id), revision = first.value?.history?.[0]?.version
      require(typeof revision === "string" && REVISION.test(revision), "backup_revision_unverified")
      const before = inventory(first.value, id, revision)
      const pinned = await metadata(`${id}/${revision}`), saved = inventory(pinned.value, id, revision)
      require(JSON.stringify(before) === JSON.stringify(saved), "backup_revision_inventory_changed")
      fileCount += saved.files.length; byteCount += saved.files.reduce((n, row) => n + row.source_bytes, 0)
      require(fileCount <= BACKUP_LIMITS.files && byteCount <= BACKUP_LIMITS.totalBytes, "backup_inventory_limit")
      records.push({ id, roles, revision, owner: saved.owner,
        metadata_sha256: pinned.metadata_sha256, files: saved.files })
    }
    current()
    const finished = new Date().toISOString()
    require(finished >= started, "backup_capture_clock_changed")
    return { schema: "theheat-gist-backup-descriptors-v1", capture_started_at: started,
      capture_finished_at: finished, metadata_requests: requests, sources: records,
      limits: BACKUP_LIMITS, scope: "Configured Gist revisions only; no transaction, restore or approval authority." }
  }
  try { return await Promise.race([capture(), deadline]) }
  catch (error) {
    if (error instanceof GistBackupError) throw error
    throw new GistBackupError("backup_metadata_unavailable")
  } finally {
    clearTimeout(timer); controller.abort()
    for (const reader of readers) void reader.cancel().catch(() => {})
  }
}
