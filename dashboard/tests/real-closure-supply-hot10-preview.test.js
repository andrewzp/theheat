/** Real closure, supply: a Hot10 bulletin ranked against the NOAA GHCN-Daily mean daily maximum
 * (noaa-ghcnd-monthly-mean-tmax-v1) through the real Python preview and the browser contract.
 * The source label must be that product's, its context must name the product and its wording,
 * and a label/product mismatch or a Meteostat label on it is refused. Invented values only; Python
 * runs with sockets trapped. (Depends on the regenerated graphic runtime manifest: in a lane branch
 * with packaged-source edits the descriptor's file pins are stale until the owner regenerates it.)
 */
import assert from "node:assert/strict"
import test from "node:test"
import { validateGraphicResponse } from "../lib/graphic-preview.js"
import { pythonJSON } from "./helpers/gist-hazard-harness.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const trap = "import json,sys,socket,tempfile\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const code = trap + `
from pathlib import Path
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.data import ghcnd_monthly_normals as gn
from src.editorial import hot10_contract as contract
from src.editorial.revisions import decision_revision, draft_identity
from src.two_bot.intern import build_hot10_bundle
from tests import live_content_harness as h
from tests.gist_hazard_helpers import CLOCKS, HOT10_CAPTURE, saved_state
from tests.real_closure import supply_ghcnd_fixture as gf
value=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
    path=gf.write_rows(Path(directory)/gn.INSTALLED_NAME, gf.installed_rows(HOT10_CAPTURE.month))
    normals=gn.load_normals(path)
result=contract.qualify(h.city_temps(HOT10_CAPTURE), normals, sampled=14, now=HOT10_CAPTURE, product=contract.GHCND_PRODUCT)
bundle=build_hot10_bundle(result['rows'], changes=[], event_id='hot10_2026-10-29', universe=result['universe']).to_dict()
state=saved_state('hot10', bundle=bundle)
draft=state['drafts'][0]
request={'draft_id':draft['id'],'expected_revision':{**draft_identity(draft),'decision_revision':decision_revision(draft)},
  'expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],'format':'png'}
with freeze_time(CLOCKS['hot10'][0]):
    current=json.loads(build_preview(request,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
print(json.dumps(dict(request=request,current=current),ensure_ascii=False))
`
let cached
const fixture = () => structuredClone(cached ??= pythonJSON(code, {
  policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 }))

test("GHCN-Daily Hot10: the real preview names its product, attribution and mean-daily-maximum wording", async () => {
  const { request, current } = fixture()
  assert.equal(current.source, "Open-Meteo forecast · NOAA GHCN-Daily mean daily maximum 1991-2020")
  assert.equal(current.source_context.baseline_product, "noaa-ghcnd-monthly-mean-tmax-v1")
  assert.equal(current.source_context.baseline_wording, "mean daily maximum, 1991-2020")
  assert.match(current.delivery_text, /mean daily maximum, 1991-2020/)
  assert.match(current.delivery_text, /13 qualified of 14 sampled cities/)
  assert.doesNotMatch(current.delivery_text + current.expanded_description, /Meteostat/)
  assert.equal(await validateGraphicResponse(current, request, manifest), current)
})

test("GHCN-Daily Hot10: a Meteostat label, an unknown product or altered wording is refused", async () => {
  const { request, current } = fixture()
  const changes = [
    v => { v.source = "Open-Meteo forecast · Meteostat point normals" },
    v => { v.source_context.baseline_product = "meteostat-normals-point-v1" },
    v => { v.source_context.baseline_product = "noaa-ghcnd-monthly-max-tmax-v1" },
    v => { v.source_context.baseline_wording = "monthly record maximum, 1991-2020" },
    v => { delete v.source_context.baseline_wording },
  ]
  for (const change of changes) {
    const bad = structuredClone(current); change(bad)
    await assert.rejects(validateGraphicResponse(bad, request, manifest), undefined, change.toString())
  }
})
