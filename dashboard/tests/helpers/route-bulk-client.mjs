// OFFLINE FIXTURE CLIENT (P00c v2 proofs): one dashboard process that calls the REAL Next route
// handler once per body, sequentially, against the file-backed fixture Gist preloaded by
// route-fixture-fetch.mjs. Usage: node --import ./tests/helpers/route-fixture-fetch.mjs
//   tests/helpers/route-bulk-client.mjs <app/api/.../route.js> <json array of bodies>
import path from "node:path"
import { pathToFileURL, fileURLToPath } from "node:url"

const DASHBOARD = fileURLToPath(new URL("../..", import.meta.url))
const [routePath, bodies] = process.argv.slice(2)
const route = await import(pathToFileURL(path.resolve(DASHBOARD, routePath)).href)
const headers = { "Content-Type": "application/json", origin: "http://localhost", "sec-fetch-site": "same-origin",
  authorization: `Basic ${Buffer.from(`${process.env.DASHBOARD_USERNAME}:${process.env.DASHBOARD_PASSWORD}`).toString("base64")}` }
const out = []
for (const body of JSON.parse(bodies)) {
  const response = await route.POST(new Request("http://localhost/api/client", { method: "POST", headers, body: JSON.stringify(body) }))
  out.push({ status: response.status, body: await response.json() })
}
process.stdout.write(JSON.stringify(out) + "\n")
