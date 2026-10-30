import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

// Paths are relative to the dashboard directory (this file's ../..), not the process cwd,
// so `node --test dashboard/tests/...` from the repository root resolves the same modules.
const DASHBOARD = fileURLToPath(new URL("../..", import.meta.url))

export async function importFresh(relativePath) {
  const absPath = path.resolve(DASHBOARD, relativePath)
  const url = pathToFileURL(absPath)
  url.searchParams.set("t", `${Date.now()}-${Math.random()}`)
  return import(url.href)
}
