import assert from "node:assert/strict"
import test from "node:test"
import { createHash } from "node:crypto"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { GraphicPreview, GraphicPreviewFigure } from "../app/components/GraphicPreview.js"
import { fingerprint } from "../lib/draft-revisions.js"
import manifest from "../lib/graphic-runtime-manifest.json" with { type: "json" }
import { graphicRequest, isTemperaturePreviewType, temperaturePreviewSourceStatus,
  validateGraphicResponse } from "../lib/graphic-preview.js"

const kinds = { all_time_high:"open_meteo_archive_high", all_time_low:"open_meteo_archive_low",
  monthly_high:"monthly_high", monthly_low:"monthly_low", record:"calendar_record", record_low:"calendar_record_low" }
// Display shapes only; actual source qualification and cross-language rendering
// use the engineered source archives in test_dashboard_temperature_preview.py.
const draft = (type="all_time_high") => ({ id:"invented-station", type, status:"pending",
  revision_identity:{content_revision:0,decision_revision:0,text_sha256:"a".repeat(64),evidence_sha256:"b".repeat(64)},
  review_context:{two_bot:{bundle:{signal_kind:kinds[type],raw_signal_dump:{evidence:{
    source_product:"noaa-ghcn-daily-v2",evidence_type:"observed"}}}}} })
const render = (value,props={}) => renderToStaticMarkup(React.createElement(GraphicPreview,{draft:value,...props}))
const sha = value => createHash("sha256").update(value).digest("hex")

function response() {
  const req=graphicRequest(draft(),manifest), files=manifest.identity.files
  const binding={template:"temperature_comparator",template_version:"p31-preview-3-mobile",
    source_evidence_sha256:"c".repeat(64),renderer:{library:"ReportLab",version:"4.4.9",format:"svg",schema_version:1,
      width:1200,height:1500,implementation_sha256:files["src/media/evidence_graphic_render.py"],
      contract_sha256:files["src/media/evidence_graphic.py"],adapter_sha256:files["src/media/temperature_graphic_adapter.py"],
      font_sha256:files["src/media/fonts/DejaVuSansMono.ttf"]}}
  const svg='<svg xmlns="http://www.w3.org/2000/svg"><title>Invented station comparison</title></svg>'
  return {schema_version:2,draft_id:req.draft_id,revision_identity:req.expected_revision,
    policy_source_sha256:req.expected_policy_source_sha256,preview_runtime_sha256:req.expected_preview_runtime_sha256,
    publication_approved:false,attachment:false,width:1200,height:1500,
    source:"NOAA GHCN-Daily · station observations",source_context:{kind:"ghcn_station_day",station_id:"USC99000001",
      valid_date:"2026-09-08",retrieved_at:"2026-09-09T12:00:00Z",reporting_interval_known:false,timezone:null},
    title:"Invented comparison",scope:"Station samples only",alt_text:"Complete invented station comparison description.",
    binding,cache_key:fingerprint(binding),svg_utf8:svg,svg_sha256:sha(svg)}
}

test("six station comparison types offer an explicit preview with no initial image", () => {
  for(const type of Object.keys(kinds)) {
    assert.equal(isTemperaturePreviewType(type),true)
    assert.equal(temperaturePreviewSourceStatus(draft(type)),"ghcn")
    const html=render(draft(type))
    assert.match(html,/saved observed station reading/)
    assert.match(html,/No new source fetch or AI generation/)
    assert.match(html,/Preview only; not attached or approved/)
    assert.match(html,/Preview graphic/)
    assert.doesNotMatch(html,/<img|certified record/)
    assert.doesNotMatch(render(draft(type),{editing:true}),/<button|<img/)
    assert.doesNotMatch(render(draft(type),{updating:true}),/<button|<img/)
  }
  for(const type of [null,undefined,"constructor","__proto__","rainfall","absolute_extreme"])
    assert.equal(isTemperaturePreviewType(type),false)
})

test("missing, mismatched, forecast and other archive evidence does not offer a station preview", () => {
  for(const change of [d=>{delete d.review_context},d=>{delete d.review_context.two_bot.bundle.raw_signal_dump.evidence},
    d=>{d.review_context.two_bot.bundle.signal_kind="monthly_low"},
    d=>{d.review_context.two_bot.bundle.raw_signal_dump.evidence.source_product="open-meteo"},
    d=>{d.review_context.two_bot.bundle.raw_signal_dump.evidence.evidence_type="forecast"}]) {
    const d=draft(); change(d)
    assert.notEqual(temperaturePreviewSourceStatus(d),"ghcn")
    assert.match(render(d),/No comparison preview is available/)
    assert.doesNotMatch(render(d),/<button|<img/)
  }
})

test("station context keeps the observed source date separate from retrieval UTC", async () => {
  const value=response(), req=graphicRequest(draft(),manifest)
  assert.deepEqual(await validateGraphicResponse(value,req,manifest),value)
  const html=renderToStaticMarkup(React.createElement(GraphicPreviewFigure,{value,url:"blob:invented"}))
  assert.match(html,/Station USC99000001 · 2026-09-08 source-calendar date · observed/)
  assert.match(html,/reporting interval and timezone unknown/)
  assert.match(html,/Archive retrieved 2026-09-09T12:00:00Z/)
  assert.match(html,/not a certified record/)
  assert.match(html,/Read the full graphic description/)
  assert.doesNotMatch(html,/2026-09-08 00:00|model forecast/)
  for(const mutation of [v=>{v.source_context.kind="pm25_forecast_day"},v=>{v.source_context.station_id="London"},
    v=>{v.source_context.valid_date="2026-02-30"},v=>{v.source_context.retrieved_at="2026-09-09"},
    v=>{v.source_context.reporting_interval_known=true},v=>{v.source_context.timezone="UTC"},
    v=>{v.source_context.valid_start="2026-09-08T00:00:00Z"},v=>{delete v.source_context.timezone},
    v=>{v.source="NOAA certified record"},v=>{v.binding.renderer.adapter_sha256="e".repeat(64)},
    v=>{v.binding.template="temperature_trajectory"},v=>{v.publication_approved=true},v=>{v.attachment=true}]) {
    const bad=structuredClone(value); mutation(bad)
    await assert.rejects(validateGraphicResponse(bad,req,manifest),/invalid preview/)
  }
})
