/** W10.3/10.4/10.6 store-backed image closure through the actual routes and components.
 * Invented Gist, invented local SQLite media stores and the real Python preview handler
 * (sockets trapped). Nothing is fetched, uploaded or published.
 */
import assert from "node:assert/strict"
import test from "node:test"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicRequirement, RETAINED_INPUT_REFUSAL_CODE, RETAINED_INPUT_REFUSALS } from "../app/components/GraphicPreview.js"
import { DeliveredFigure } from "../app/components/DeliveredGraphics.js"
import { GraphicFamilies } from "../app/components/ProductHealthPanel.js"
import { GRAPHIC_FAMILIES, graphicAvailabilityPayload, mediaStoreSetting } from "../lib/graphic-availability.js"
import { deliveredPNGRequest, validateGraphicResponse } from "../lib/graphic-preview.js"
import { importFresh } from "./helpers/import-fresh.js"
import { body, pythonJSON, withGist } from "./helpers/gist-hazard-harness.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const visible = html => html.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ")
const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const deliveredCode = trap + `
from copy import deepcopy
from pathlib import Path
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial import revisions
from src.media import gist_assets
from tests.gist_store_helpers import CLOCKS, retain, saved_state
value=json.load(sys.stdin); family=value['family']
store=gist_assets.SQLiteMediaStore(Path(value['store']))
retained=retain(family,store)
state=saved_state(family); draft=state['drafts'][0]
def request(d, **extra):
    return {'draft_id':d['id'],'format':'png','expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],
            'expected_revision':{**revisions.draft_identity(d),'decision_revision':revisions.decision_revision(d)},**extra}
def build(req, at):
    with freeze_time(at):
        return json.loads(build_preview(req,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget(),store=store))
first=build(request(draft,retained_input_sha256=retained),CLOCKS[family][0])
revisions.invalidate_media_attachment(draft,first['media_descriptor'],at=CLOCKS[family][0])
state['publish_ledger']={draft['event_id']:{**revisions.draft_identity(draft),'text':draft['text'],'intent_id':'invented-intent',
  'tweet_id':'invented-x-'+family,'phase':'confirmed','at':CLOCKS[family][0],'confirmed_at':CLOCKS[family][0]}}
revisions.invalidate_text(draft,draft['text']+' Later correction.',at=CLOCKS[family][1])
revisions.invalidate_media_attachment(draft,None,at=CLOCKS[family][1])
draft['status']='posted'; draft['tweet_id']='invented-x-'+family
req=request(draft,delivered=True); req.pop('retained_input_sha256',None)
print(json.dumps(dict(first=first,delivered=build(req,'2027-01-01T00:00:00Z'),request=req,raw_state=json.dumps(state,ensure_ascii=False)),ensure_ascii=False))
`

test("10.3: a pasted URL, path or name is refused by the actual route before any preview or write", async () => {
  await withGist("cone", async t => {
    const before = t.raw()
    for (const typed of ["https://www.nhc.noaa.gov/storm_graphics/AT05/AL052026_5day_cone_with_line_and_wind.png", "/private/invented/cone.png", "AL052026"]) {
      const result = await t.post(body(t.get(), "attach_graphic", { expectedMediaSha256: "0".repeat(64), retainedInputSha256: typed }))
      assert.equal(result.status, 409); assert.equal(result.body.code, "media_retained_input_required")
    }
    assert.equal(t.previews.length, 0); assert.equal(t.patches.length, 0); assert.equal(t.raw(), before)
  })
  assert.equal(RETAINED_INPUT_REFUSAL_CODE("https://example.invalid/cone.png"), "url")
  assert.equal(RETAINED_INPUT_REFUSAL_CODE("/private/invented/cone.png"), "path")
  assert.equal(RETAINED_INPUT_REFUSAL_CODE("AL052026 advisory 12"), "identity")
  assert.match(RETAINED_INPUT_REFUSALS.url, /never fetched/)
})

test("10.6: the picker names each family's lane and the missing input; nothing claims hosted proof", () => {
  const cone = { type: "cyclone_land_threat", review_context: { two_bot: { bundle: { signal_kind: "cyclone_land_threat", raw_signal_dump: { source: "nhc" } } } } }
  const missingStore = visible(renderToStaticMarkup(React.createElement(GraphicRequirement, { family: "cone", draft: cone, mediaStore: mediaStoreSetting({}) })))
  assert.match(missingStore, /Published NHC forecast cone: an unaltered published image retained in the media store · missing: a read-only media store \(THEHEAT_MEDIA_STORE\)/)
  assert.match(missingStore, /three human attestations at joint review/)
  const configured = visible(renderToStaticMarkup(React.createElement(GraphicRequirement, { family: "cone", draft: { ...cone, media_attachment: {} },
    mediaStore: mediaStoreSetting({ THEHEAT_MEDIA_STORE: "postgres", THEHEAT_MEDIA_STORE_DSN: "host=invented password=invented-secret" }) })))
  assert.match(configured, /access is checked only when you preview\. This is not hosted or native rendering proof/)
  assert.doesNotMatch(configured, /invented-secret|host=/)
  const crw = visible(renderToStaticMarkup(React.createElement(GraphicRequirement, { family: "crw",
    draft: { review_context: { two_bot: { bundle: { signal_kind: "regional_sst_anomaly", raw_signal_dump: {} } } } }, mediaStore: mediaStoreSetting({ THEHEAT_MEDIA_STORE: "sqlite:/invented/media.sqlite3" }) })))
  assert.match(crw, /missing: this draft's retained CRW packet identity/)
  const native = visible(renderToStaticMarkup(React.createElement(GraphicRequirement, { family: "pm25", draft: {}, mediaStore: null })))
  assert.match(native, /rebuilt from the saved source; no store needed/); assert.doesNotMatch(native, /missing:/)
  // The real picker carries the requirement for a store-backed draft without blocking the text story.
  const picker = visible(renderToStaticMarkup(React.createElement(GraphicPreview, { draft: { id: "invented-cone", ...cone, text: "Invented.", status: "pending" }, mediaStore: mediaStoreSetting({}) })))
  assert.match(picker, /missing: a read-only media store/)
})

test("10.6: Operations lists every family with its requirement and missing input; the API never returns store values", async () => {
  assert.deepEqual(mediaStoreSetting({ THEHEAT_MEDIA_STORE: "postgres" }), { configured: false, backend: "postgres", reader_credential: "missing" })
  assert.deepEqual(mediaStoreSetting({ THEHEAT_MEDIA_STORE: "https://invented.example/store" }), { configured: false, backend: "unsupported", reader_credential: "not_required" })
  const payload = graphicAvailabilityPayload({})
  assert.deepEqual(payload.families.map(row => [row.family, row.status]), GRAPHIC_FAMILIES.map(row =>
    [row.family, row.lane === "native" ? "from_saved_source" : "missing_input"]))
  const html = visible(renderToStaticMarkup(React.createElement(GraphicFamilies, { graphics: payload })))
  assert.match(html, /Post-image families · 3 need an input here/)
  assert.match(html, /Published NWS KTLX radar frame — an unaltered published image retained in the media store\. Missing here: a read-only media store \(THEHEAT_MEDIA_STORE\)\./)
  assert.match(html, /revokes the joint review and any approval/)
  const keys = ["NODE_ENV", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD", "THEHEAT_STATE_BACKEND", "THEHEAT_DB_PATH", "GIST_ID", "GITHUB_TOKEN", "THEHEAT_MEDIA_STORE", "THEHEAT_MEDIA_STORE_DSN"]
  const previous = Object.fromEntries(keys.map(key => [key, process.env[key]])), originalFetch = globalThis.fetch
  Object.assign(process.env, { NODE_ENV: "production", DASHBOARD_USERNAME: "invented", DASHBOARD_PASSWORD: "invented-pass", THEHEAT_STATE_BACKEND: "gist",
    THEHEAT_DB_PATH: "", GIST_ID: "invented-gist", GITHUB_TOKEN: "invented-token", THEHEAT_MEDIA_STORE: "postgres",
    THEHEAT_MEDIA_STORE_DSN: "host=invented.example dbname=invented user=invented password=invented-dsn-secret sslmode=verify-full sslrootcert=system" })
  globalThis.fetch = async url => {
    const href = String(url)
    if (href.includes("/actions/runs")) return new Response(JSON.stringify({ workflow_runs: [] }))
    if (href === "https://api.github.com/gists/invented-gist") return new Response(JSON.stringify({ files: { "state.json": { content: JSON.stringify({ drafts: [], run_history: [] }) } } }))
    throw new Error(`Unexpected request ${href}`)
  }
  try {
    const { GET } = await importFresh("app/api/dashboard/route.js")
    const response = await GET(new Request("http://localhost:3000/api/dashboard", { headers: { Authorization: `Basic ${Buffer.from("invented:invented-pass").toString("base64")}` } }))
    const text = await response.text(), value = JSON.parse(text)
    assert.equal(response.status, 200)
    assert.deepEqual(value.graphicAvailability.store, { configured: true, backend: "postgres", reader_credential: "present" })
    assert.equal(value.graphicAvailability.families.find(row => row.family === "cone").status, "store_configured_unverified")
    assert.doesNotMatch(text, /invented-dsn-secret|invented\.example|sslrootcert/)
  } finally {
    globalThis.fetch = originalFetch
    for (const key of keys) { if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key] }
  }
})

for (const family of ["crw", "radar", "cone"]) {
  test(`10.4 ${family}: the delivered-history reader rebuilds the preview's exact bytes and the route lists it`, async () => {
    const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "theheat-w10-delivered-")))
    const value = pythonJSON(deliveredCode, { family, store: path.join(folder, "media.sqlite3"),
      policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 })
    assert.equal(value.delivered.png_base64, value.first.png_base64)
    assert.deepEqual(value.delivered.media_descriptor, value.first.media_descriptor)
    assert.deepEqual(await validateGraphicResponse(structuredClone(value.delivered), value.request, manifest), value.delivered)
    const tampered = structuredClone(value.delivered); tampered.delivered.tweet_id = "invented x/other"
    await assert.rejects(validateGraphicResponse(tampered, value.request, manifest))
    const html = visible(renderToStaticMarkup(React.createElement(DeliveredFigure, { value: value.delivered, url: "blob:invented" })))
    assert.match(html, new RegExp(`Delivered X post invented-x-${family}`))
    assert.doesNotMatch(html, /undefined/)
    await withGist(family, async t => {
      t.replaceState(value.raw_state)
      const listed = await t.delivered()
      assert.equal(listed.length, 1); assert.equal(listed[0].delivered.tweet_id, `invented-x-${family}`)
      assert.deepEqual(deliveredPNGRequest(listed[0], manifest).expected_revision, value.request.expected_revision)
    })
  })
}
