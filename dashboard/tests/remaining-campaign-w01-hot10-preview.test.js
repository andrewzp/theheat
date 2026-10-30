/** W01 Hot10 browser presentation: the real Python preview response for invented
 * qualified bulletins (standard and long-name / both-sign / two-local-day), rendered
 * through the actual GraphicPreview components. No network: Python runs with sockets
 * trapped. Markup checks are not a browser layout proof (see the owned UI journey).
 */
import assert from "node:assert/strict"
import test from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure, GraphicState, MediaControls, graphicState } from "../app/components/GraphicPreview.js"
import { hot10PreviewSourceStatus, mediaPNGRequest, validateGraphicResponse } from "../lib/graphic-preview.js"
import { pythonJSON } from "./helpers/gist-hazard-harness.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }

const trap = "import json,sys,socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external connection trapped'))\n"
const code = trap + `
from freezegun import freeze_time
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial.revisions import decision_revision, draft_identity
from tests.gist_hazard_helpers import CLOCKS, HOT10_MIXED, HOT10_MIXED_CAPTURE, HOT10_MIXED_CLOCK, hot10_bundle, saved_state
value=json.load(sys.stdin)
mixed=value['variant']=='mixed'
state=saved_state('hot10', bundle=hot10_bundle(HOT10_MIXED, now=HOT10_MIXED_CAPTURE, sampled=640) if mixed else None)
clock=HOT10_MIXED_CLOCK if mixed else CLOCKS['hot10'][0]
draft=state['drafts'][0]
request={'draft_id':draft['id'],'expected_revision':{**draft_identity(draft),'decision_revision':decision_revision(draft)},
  'expected_policy_source_sha256':value['policy'],'expected_preview_runtime_sha256':value['runtime'],'format':'png'}
with freeze_time(clock):
    current=json.loads(build_preview(request,policy_sha=value['policy'],runtime_sha=value['runtime'],read_state=lambda:state,budget=Budget()))
draft['revision_identity']=request['expected_revision']
print(json.dumps(dict(draft=draft,request=request,current=current),ensure_ascii=False))
`
const fixtures = {}
const fixture = variant => structuredClone(fixtures[variant] ??= pythonJSON(code, { variant,
  policy: manifest.identity.policy_source_sha256, runtime: manifest.runtime_sha256 }))
const render = element => renderToStaticMarkup(element)
const text = html => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ")

for (const variant of ["standard", "mixed"]) {
  test(`${variant}: the real Hot10 response satisfies the browser contract and lists all ten rows legibly`, async () => {
    const { draft, request, current } = fixture(variant)
    assert.equal(hot10PreviewSourceStatus(draft), "bulletin")
    assert.deepEqual(mediaPNGRequest(draft, manifest), request)
    assert.equal(await validateGraphicResponse(current, request, manifest), current)
    assert.equal(current.media_kind, "gist_hot10_bulletin_v1"); assert.equal(current.posting_window.status, "current")
    const html = render(React.createElement(GraphicPreviewFigure, { value: current, url: "blob:invented" }))
    const visible = text(html)
    assert.match(html, /<ol aria-label="Hot 10 ranked rows">/)
    assert.equal(html.match(/<li value="\d+">/g).length, 10)
    const bundle = draft.review_context.two_bot.bundle.raw_signal_dump
    for (const [index, row] of bundle.cities.entries()) {
      const sign = row.anomaly_c > 0 ? "+" : row.anomaly_c < 0 ? "−" : "+"
      assert.ok(html.includes(`<li value="${index + 1}">`))
      assert.ok(visible.includes(`${row.city}, ${row.country} ${sign}${Math.abs(row.anomaly_c).toFixed(1)} °C vs normal`), row.city)
      assert.ok(visible.includes(`forecast ${row.temp_high_c.toFixed(1)} °C, normal ${row.normal_high_c.toFixed(1)} °C · ${row.valid_date} (${row.timezone})`))
    }
    assert.match(visible, /Forecast departure table \(sampled cities\)/)
    assert.match(visible, /Forecasts, not observations, records or the world's hottest places/)
    if (variant === "mixed") {
      assert.match(visible, /Local days 2026-10-29, 2026-10-30; each row shows its own local day/)
      assert.ok(html.includes('class="hot10-cool"') && html.includes('class="hot10-warm"'))
      assert.match(visible, /Santiago de los Caballeros, Dominican Republic/); assert.match(visible, /Ra’s Bayrūt, Lebanon/)
    } else assert.match(visible, /12 of 14 sampled catalogue cities qualified\. Local day 2026-10-29\./)
  })
}

test("hot10: tampered presentation rows are refused before any image is shown", async () => {
  const { request, current } = fixture("standard")
  const changes = [
    v => { v.source_context.rows.pop() }, v => { v.source_context.rows[1].rank = 3 },
    v => { v.source_context.rows[0].valid_date = "2026-11-02" }, v => { v.source_context.rows[2].departure_c = "9.9" },
    v => { v.source_context.rows[4].city = "" }, v => { v.source_context.qualified_cities = 9 },
    v => { v.source_context.extra = true }, v => { v.source = "Open-Meteo" }, v => { v.media_descriptor.template = "pm25_forecast_day" },
  ]
  for (const change of changes) {
    const bad = structuredClone(current); change(bad)
    await assert.rejects(validateGraphicResponse(bad, request, manifest), undefined, change.toString())
  }
})

test("hot10: the saved-source panel offers the bulletin family; a legacy Hot10 shape gets no preview", () => {
  const { draft } = fixture("standard")
  const html = render(React.createElement(GraphicPreview, { draft }))
  assert.match(html, /Build the ten-row table from the saved qualified Hot 10 bulletin/)
  assert.match(html, /Preview graphic/)
  const legacy = structuredClone(draft)
  legacy.review_context.two_bot.bundle.raw_signal_dump = { cities: legacy.hot10_rows, changes: [], event_id: legacy.event_id }
  assert.equal(hot10PreviewSourceStatus(legacy), "unsupported")
  assert.equal(render(React.createElement(GraphicPreview, { draft: legacy })), "")
})

test("hot10: preview, attached, needs re-review and unavailable are distinct visible states", () => {
  const { draft, current } = fixture("standard")
  const ready = { status: "ready", value: current, url: "blob:invented" }
  const base = { ...draft, editorial_policy: { policy_sha256: "a".repeat(64) } }
  const attached = { ...base, media_attachment: current.media_descriptor, media_attachment_sha256: current.media_descriptor_sha256 }
  const state = (value, preview) => {
    const html = render(React.createElement(React.Fragment, null,
      MediaControls({ draft: value, preview, reviewConfirmed: false, onConfirm() {}, onAction() {} }),
      React.createElement(GraphicState, { draft: value, preview })))
    return [html.match(/data-graphic-state="([a-z_]+)"/)[1], text(html)]
  }
  assert.deepEqual(state(base, { status: "idle" })[0], "none")
  const [previewKey, previewText] = state(base, ready)
  assert.equal(previewKey, "preview"); assert.match(previewText, /Preview only: not attached; the text can still be reviewed and posted without it/)
  const [unavailableKey, unavailableText] = state(base, { status: "error", message: "invented refusal" })
  assert.equal(unavailableKey, "unavailable"); assert.match(unavailableText, /Graphic unavailable: the text draft is unchanged/)
  const [needsKey, needsText] = state({ ...attached, review_status: "media_review_required" }, ready)
  assert.equal(needsKey, "needs_review"); assert.match(needsText, /Needs joint review: the text, image or source changed/)
  assert.match(needsText, /Record joint review/)
  const [doneKey, doneText] = state({ ...attached, review_status: "passed", review_kind: "human_media" }, ready)
  assert.equal(doneKey, "attached"); assert.match(doneText, /Attached: reviewed together with this exact text/)
  assert.equal(graphicState({ draft: { ...attached, review_status: "passed", review_kind: "delegated_media" }, preview: ready,
    present: true, matching: true }).detail, "reviewed together with this exact text (delegated, one manual post).")
  assert.equal(graphicState({ draft: attached, preview: ready, present: true, matching: false, held: true }).key, "held")
})
