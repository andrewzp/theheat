import test from "node:test"
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { readFileSync, writeFileSync } from "node:fs"
import { spawnSync } from "node:child_process"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { DeliveryContentCard, DeliveryHistory } from "../app/components/DeliveryHistory.js"
import { deliveryHistoryKey, loadDeliveryContent, validateDeliveryContent } from "../lib/delivery-history.js"
import { GET } from "../app/api/editor-media/route.js"
import { localCommandRequest } from "../lib/draft-command-client.js"

const sha = bytes => createHash("sha256").update(bytes).digest("hex")
const intent = "11111111-2222-4333-8444-555555555555", command = "66666666-2222-4333-8444-555555555555"
const png = new Uint8Array(40); png.set([137,80,78,71,13,10,26,10])
new DataView(png.buffer).setUint32(16, 1200); new DataView(png.buffer).setUint32(20, 900)
function fixture(alt = "Full earlier description.\n") {
  const text = "The exact earlier approved sentence."
  const approved = { draft_id:"invented", content_revision:1, decision_revision:4, text_sha256:sha(text), evidence_sha256:"a".repeat(64) }
  const target = { ...approved, content_revision:2, decision_revision:5, text_sha256:sha("Edited sentence.") }
  const { draft_id, ...revision_identity } = target
  return { draft:{ id:draft_id, local_preview:true, operator_subject:"invented-viewer", operator_role:"viewer", revision_identity },
    detail:{ schema_version:1, draft_id, target, scope:"local_http_fixture_v1", publication_approved:false,
      intent_id:intent, command_id:command, approved_at:"2026-10-15T00:00:00Z", approved_target:approved, text,
      proposal_sha256:"b".repeat(64), packet_sha256:"c".repeat(64), preparation_packet_sha256:"d".repeat(64), synthetic:true,
      media:{ mime_type:"image/png", png_sha256:sha(png), byte_count:png.length, width:1200, height:900,
        alt_text:alt, alt_text_sha256:sha(alt) }, operator_subject:"invented-viewer" } }
}

test("history validates closed actor/full-target/intent identities and full raw alt", async () => {
  const { draft, detail } = fixture()
  assert.equal(await validateDeliveryContent(detail, draft, intent), detail)
  for (const change of [v => { v.operator_subject="other" }, v => { v.target.decision_revision++ },
    v => { v.target.extra=1 }, v => { v.intent_id=command }, v => { v.text+="changed" },
    v => { v.media.alt_text=v.media.alt_text.trim() }, v => { v.media.extra="private" },
    v => { v.publication_approved=true }, v => { v.extra="secret" }]) {
    const changed = structuredClone(detail); change(changed)
    await assert.rejects(validateDeliveryContent(changed, draft, intent), /unavailable/)
  }
  for (const key of ["operator_subject", "operator_role", "id"])
    assert.notEqual(deliveryHistoryKey({ ...draft, [key]:"other" }), deliveryHistoryKey(draft))
  for (const key of Object.keys(draft.revision_identity))
    assert.notEqual(deliveryHistoryKey({ ...draft, revision_identity:{ ...draft.revision_identity, [key]:"other" } }), deliveryHistoryKey(draft))
  assert.equal(deliveryHistoryKey({ ...draft, operator_subject:null }), null)
})

test("history retains maximal escaped and multibyte descriptions without trimming", async () => {
  const saved = globalThis.fetch
  try {
    for (const alt of ["\u0000".repeat(999_999)+"\n", "🌎".repeat(249_999)+"abc\n"]) {
      const { draft, detail } = fixture(alt)
      assert.equal(Buffer.byteLength(alt), 1_000_000)
      assert.ok(Buffer.byteLength(JSON.stringify(detail)) < 8*1024*1024)
      globalThis.fetch = async url => url.includes("deliveryIntent") ? Response.json(detail) : new Response(png, { headers:{ "Content-Type":"image/png" } })
      assert.equal((await loadDeliveryContent(draft, intent, new AbortController().signal)).detail.media.alt_text, alt)
    }
  } finally { globalThis.fetch=saved }
  const { draft, detail } = fixture("x".repeat(1_000_001))
  await assert.rejects(validateDeliveryContent(detail, draft, intent), /unavailable/)
})

test("history GET loader verifies selected PNG hash/size/dimensions and rejects cancelled late responses", async () => {
  const saved = globalThis.fetch, { draft, detail } = fixture(), calls=[]
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options })
      return url.includes("deliveryIntent") ? Response.json(detail) : new Response(png, { headers:{ "Content-Type":"image/png" } })
    }
    const value = await loadDeliveryContent(draft, intent, new AbortController().signal)
    assert.deepEqual(value.detail, detail); assert.equal(value.blob.size, png.length)
    assert.equal(calls.length, 2); assert.ok(calls.every(c => c.options.method === undefined && c.options.redirect === "error"))
    const changed = png.slice(); changed[39]=1
    globalThis.fetch = async url => url.includes("deliveryIntent") ? Response.json(detail) : new Response(changed, { headers:{ "Content-Type":"image/png" } })
    await assert.rejects(loadDeliveryContent(draft, intent, new AbortController().signal), /unavailable/)
    let release
    globalThis.fetch = () => new Promise(resolve => { release=resolve })
    const control = new AbortController(), waiting = loadDeliveryContent(draft, intent, control.signal)
    control.abort(); release(Response.json(detail))
    await assert.rejects(waiting, /unavailable/)
  } finally { globalThis.fetch=saved }
})

test("history metadata refuses declared and streamed oversize or invalid UTF-8 before a PNG GET", async () => {
  const saved=globalThis.fetch, {draft}=fixture()
  try {
    for (const response of [new Response("{}", {headers:{"Content-Type":"application/json","Content-Length":String(8*1024*1024+1)}}),
      new Response(new Uint8Array(8*1024*1024+1), {headers:{"Content-Type":"application/json"}}),
      new Response(Uint8Array.of(255), {headers:{"Content-Type":"application/json"}})]) {
      let calls=0, signal
      globalThis.fetch=async(_url,options)=>{ calls++; signal=options.signal; return response }
      await assert.rejects(loadDeliveryContent(draft,intent,new AbortController().signal), /unavailable/)
      assert.equal(calls,1)
      assert.equal(signal.aborted,true,"Early size/encoding refusal closes the original transport")
    }
  } finally { globalThis.fetch=saved }
})

test("history card is explicitly historical and preserves whitespace without mutation controls", () => {
  const {draft,detail}=fixture("line one\nline two\n")
  const html=renderToStaticMarkup(React.createElement(DeliveryContentCard,{detail,imageUrl:"blob:invented"}))
  assert.match(html,/Earlier local delivery content/); assert.match(html,/Historical content — does not approve this draft/)
  assert.match(html,/line one\nline two\n/); assert.match(html,/white-space:pre-wrap/)
  assert.doesNotMatch(html,/<button|<input|<textarea|>Restore|>Approve|>Send/)
  const summary=renderToStaticMarkup(React.createElement(DeliveryHistory,{draft,view:{delivery:{intents:[{intent_id:intent,current:false,
    stages:{x:{create:{status:"unknown"}}}}]}}}))
  assert.match(summary,/aria-expanded="false"/); assert.match(summary,/View earlier content for review 1/)
  assert.match(summary,/outcome unknown; automatic retry blocked/); assert.doesNotMatch(summary,/<img/)
})

test("history proxy refuses mixed/duplicate/body references and keeps the existing bounded GET transport", async () => {
  const saved={...process.env}, fetch=globalThis.fetch, calls=[]
  process.env.NODE_ENV="test";process.env.DASHBOARD_AUTH_DISABLED="1";process.env.THEHEAT_LOCAL_COMMAND_URL="http://127.0.0.1:3999"
  for(const key of Object.keys(process.env))if(/(?:TOKEN|SECRET|PASSWORD|API_KEY)$/.test(key))delete process.env[key]
  const request=(query,extra={})=>new Request(`http://127.0.0.1:3133/api/editor-media?${query}`,{headers:{Host:"127.0.0.1:3133",Origin:"http://127.0.0.1:3133",Authorization:"Basic "+Buffer.from("viewer:invented").toString("base64"),...extra}})
  const query=`draftId=invented&deliveryIntent=${intent}`
  try {
    globalThis.fetch=async(url,options)=>{calls.push([url,options]);return Response.json(fixture().detail)}
    assert.equal((await GET(request(query))).status,200)
    assert.equal(calls[0][0],`http://127.0.0.1:3999/drafts/invented/media/delivery/${intent}`)
    for(const invalid of [query+`&deliveryIntent=${intent}`,query+"&draftId=other",query+"&original=1",query+"&proposal="+"a".repeat(64),query+"&extra=1","draftId=invented&deliveryIntent=bad"])
      assert.equal((await GET(request(invalid))).status,400)
    for(const headers of [{"Content-Length":"1"},{Range:"bytes=0-20"},{"Transfer-Encoding":"chunked"}])
      assert.equal((await GET(request(query,headers))).status,400)
    assert.equal(calls.length,1)
    await assert.rejects(localCommandRequest(request(query),`/drafts/invented/media/delivery/${intent}`,{method:"POST",raw:"{}"}),/invalid_command_route/)
    const maximumAlt="\u0000".repeat(999_999)+"\n"
    globalThis.fetch=async()=>Response.json(fixture(maximumAlt).detail)
    const largeResponse=await GET(request(query))
    assert.equal(largeResponse.status,200)
    assert.equal((await largeResponse.json()).media.alt_text,maximumAlt)
    globalThis.fetch=async()=>new Response("{}",{headers:{"Content-Type":"application/json","Content-Length":String(8*1024*1024+1)}})
    assert.equal((await GET(request(query))).status,503)
    globalThis.fetch=async()=>new Response(new Uint8Array(8*1024*1024+1),{headers:{"Content-Type":"application/json"}})
    assert.equal((await GET(request(query))).status,413)
  } finally {
    globalThis.fetch=fetch
    for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key]
    Object.assign(process.env,saved)
  }
})

test("historical proxy native stream cleanup preserves primary errors without detached rejection", () => {
  const moduleURL=new URL("../app/api/editor-media/route.js",import.meta.url).href
  const result=spawnSync(process.execPath,["--unhandled-rejections=strict","--input-type=module","--eval",`
    import assert from "node:assert/strict";
    import { GET } from ${JSON.stringify(moduleURL)};
    const request=()=>new Request("http://127.0.0.1:3133/api/editor-media?draftId=invented&deliveryIntent=11111111-2222-4333-8444-555555555555",{
      headers:{Host:"127.0.0.1:3133",Origin:"http://127.0.0.1:3133",Authorization:"Basic "+Buffer.from("viewer:invented").toString("base64")}});
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    let calls=0;
    const check=async(status,code)=>{
      const before=calls,response=await GET(request());
      assert.equal(response.status,status);
      assert.equal((await response.json()).code,code);
      assert.equal(calls,before+1,"No transport retry");
      await tick();
    };
    for(const primary of [new Error("Invented body failure"),new DOMException("Invented canceled body","AbortError")]) {
      globalThis.fetch=async()=>{calls++;return new Response(new ReadableStream({start(controller){controller.error(primary)}}),
        {headers:{"content-type":"application/json"}})};
      await check(503,"local_authority_unavailable_retry_same_command");
    }
    let canceled=0;
    globalThis.fetch=async()=>{calls++;return new Response(new ReadableStream({
      start(controller){controller.enqueue(new Uint8Array(8*1024*1024+1))},
      cancel(){canceled++;throw new Error("Invented oversize cleanup failure")}
    }),{headers:{"content-type":"application/json"}})};
    await check(413,"command_too_large");assert.equal(canceled,1);
    let deadlineCanceled=0,signal;
    globalThis.fetch=async(_url,options)=>{calls++;signal=options.signal;return new Response(new ReadableStream({
      cancel(){deadlineCanceled++;throw new Error("Invented timeout cleanup failure")}
    }),{headers:{"content-type":"application/json"}})};
    const started=Date.now();
    await check(503,"local_authority_timeout");
    assert.ok(Date.now()-started>=7900,"Original real eight-second timer was not shortened");
    assert.equal(signal.aborted,true);assert.equal(deadlineCanceled,1);assert.equal(calls,4);
  `],{encoding:"utf8",timeout:15000,env:{PATH:process.env.PATH,NODE_ENV:"test",DASHBOARD_AUTH_DISABLED:"1",THEHEAT_LOCAL_COMMAND_URL:"http://127.0.0.1:3999"}})
  assert.ifError(result.error)
  assert.equal(result.status,0,result.stderr||result.stdout)
})

test("actual authenticated history Next ingress PG detail and PNG stay read-only",{skip:!process.env.THEHEAT_DELIVERY_HISTORY_CONFIG},async()=>{
  const config=JSON.parse(readFileSync(process.env.THEHEAT_DELIVERY_HISTORY_CONFIG)),saved={...process.env},actualFetch=globalThis.fetch,calls=[]
  process.env.NODE_ENV="test";process.env.THEHEAT_LOCAL_COMMAND_URL=config.endpoint
  globalThis.fetch=(url,options)=>{assert.equal(new URL(url).origin,config.endpoint);assert.equal(options.method,"GET");calls.push(url);return actualFetch(url,options)}
  const request=(query=`draftId=${config.draft_id}&deliveryIntent=${config.intent_id}`,role="viewer",headers={})=>GET(new Request(`${config.origin}/api/editor-media?${query}`,{headers:{Origin:config.origin,Host:new URL(config.origin).host,Authorization:`Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`,...headers}}))
  try {
    for(const role of ["viewer","editor","publisher"]){
      const response=await request(undefined,role)
      assert.equal(response.status,200,await response.clone().text())
      assert.equal(response.headers.get("cache-control"),"private, no-store")
      assert.equal(response.headers.get("x-content-type-options"),"nosniff")
      assert.deepEqual(await response.json(),{...config.expected,operator_subject:`invented-${role}`})
    }
    const response=await request(`draftId=${config.draft_id}&proposal=${config.expected.proposal_sha256}`)
    assert.equal(response.status,200);assert.equal(sha(Buffer.from(await response.arrayBuffer())),config.expected.media.png_sha256)
    assert.equal((await request(undefined,"invalid")).status,401)
    assert.equal((await request(undefined,"viewer",{Authorization:""})).status,401)
    assert.equal((await request(undefined,"viewer",{Origin:"http://evil.invalid"})).status,403)
    assert.equal((await request(`draftId=${config.other_draft}&deliveryIntent=${config.intent_id}`)).status,409)
    assert.equal((await request(`draftId=${config.other_draft}&proposal=${config.expected.proposal_sha256}`)).status,409)
    assert.equal((await request(`draftId=absent&deliveryIntent=${config.intent_id}`)).status,409)
    assert.equal((await request(`draftId=${config.draft_id}&deliveryIntent=ffffffff-ffff-4fff-8fff-ffffffffffff`)).status,409)
    const operatorBytes=readFileSync(config.operators)
    try {
      const operators=JSON.parse(operatorBytes);operators.operators=operators.operators.filter(row=>row.role!=="viewer")
      writeFileSync(config.operators,JSON.stringify(operators))
      assert.equal((await request()).status,401)
    } finally {writeFileSync(config.operators,operatorBytes)}
    assert.ok(calls.length>8)
  } finally {
    globalThis.fetch=actualFetch
    for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key]
    Object.assign(process.env,saved)
  }
})

test("versioned MODIS history keeps exact reviewed wire distinct from unchanged raw detail", async () => {
  const {draft,detail}=fixture("Full retained historical description.\n")
  detail.schema_version=2
  detail.platform_description={description_sha256:"f".repeat(64),derivation:"modis_source_projection_v1",wire_text:"Exact earlier reviewed MODIS wire.",wire_sha256:sha("Exact earlier reviewed MODIS wire."),raw_alt_sha256:detail.media.alt_text_sha256,status:"reviewed_for_local_delivery"}
  assert.equal(await validateDeliveryContent(detail,draft,intent),detail)
  const html=renderToStaticMarkup(React.createElement(DeliveryContentCard,{detail,imageUrl:"blob:invented"}))
  assert.match(html,/Earlier reviewed platform description/)
  assert.match(html,/Exact earlier reviewed MODIS wire/)
  assert.match(html,/Full retained historical description/)
  assert.match(html,/stage results show whether delivery was attempted or confirmed/)
  assert.doesNotMatch(html,/was sent|was published|<button|<input|<textarea/)
  for(const change of [v=>{v.schema_version=3},v=>{delete v.platform_description},v=>{v.platform_description.extra=true},
    v=>{v.platform_description.wire_text+="changed"},v=>{v.platform_description.wire_text="\ud800"},v=>{v.platform_description.raw_alt_sha256="a".repeat(64)},
    v=>{v.platform_description.status="confirmed"},v=>{v.platform_description.derivation="operator_shortened"},v=>{v.platform_description.description_sha256="bad"}]){
    const copy=structuredClone(detail);change(copy)
    await assert.rejects(validateDeliveryContent(copy,draft,intent),/unavailable/)
  }
  const original=fixture()
  original.detail.platform_description=detail.platform_description
  await assert.rejects(validateDeliveryContent(original.detail,original.draft,intent),/unavailable/)
})
