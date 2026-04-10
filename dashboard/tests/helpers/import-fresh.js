import path from "node:path"
import { pathToFileURL } from "node:url"

export async function importFresh(relativePath) {
  const absPath = path.resolve(process.cwd(), relativePath)
  const url = pathToFileURL(absPath)
  url.searchParams.set("t", `${Date.now()}-${Math.random()}`)
  return import(url.href)
}
