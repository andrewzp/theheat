// OFFLINE FIXTURE CLIENT (P00c proofs): one independently started dashboard process that
// calls the REAL Next route handler once, against the file-backed fixture Gist preloaded by
// route-fixture-fetch.mjs. Usage: node --import ./tests/helpers/route-fixture-fetch.mjs
//   tests/helpers/route-client.mjs <app/api/.../route.js> <json body>
import path from "node:path"
import { pathToFileURL, fileURLToPath } from "node:url"

const DASHBOARD = fileURLToPath(new URL("../..", import.meta.url))
const [routePath, body] = process.argv.slice(2)
const route = await import(pathToFileURL(path.resolve(DASHBOARD, routePath)).href)
const headers = { "Content-Type": "application/json", origin: "http://localhost", "sec-fetch-site": "same-origin",
  authorization: `Basic ${Buffer.from(`${process.env.DASHBOARD_USERNAME}:${process.env.DASHBOARD_PASSWORD}`).toString("base64")}` }
const response = await route.POST(new Request("http://localhost/api/client", { method: "POST", headers, body }))
process.stdout.write(JSON.stringify({ status: response.status, body: await response.json() }) + "\n")
