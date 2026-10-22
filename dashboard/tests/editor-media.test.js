import test from "node:test"
import assert from "node:assert/strict"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { EditorMedia, EditorMediaPanel } from "../app/components/EditorMedia.js"
import { jointConfirmations, confirmationsFor, mediaCommand, sameMediaTarget, retainedMediaBlob } from "../lib/editor-media.js"
import { GET } from "../app/api/editor-media/route.js"
import { recoveryKey, saveCommandReference, readCommandReference, clearCommandReference, withCommandReference, commandRequestSHA, abandonmentBody } from "../lib/local-command-recovery.js"
import { createHash } from "node:crypto"
import { spawnSync } from "node:child_process"

test("reload retains only a command reference, scoped to origin and current operator", async () => {
  const rows = new Map(), storage = { getItem:k=>rows.get(k), setItem:(k,v)=>rows.set(k,v), removeItem:k=>rows.delete(k) }
  const key = recoveryKey("http://127.0.0.1:3143", "invented-editor")
  const saved = await withCommandReference({ command:mediaCommand(view(), "attach_media_revision", reviewed), action:"attach_media_revision", draftId:"invented-draft" })
  assert.equal(saveCommandReference(storage, key, saved), true)
  const raw = storage.getItem(key)
  assert.doesNotMatch(raw, /confirmations|policy_sha256|reason|payload|review/)
  assert.deepEqual(readCommandReference(storage,key), { command:{command_id:saved.command.command_id}, action:saved.action, draftId:saved.draftId, original_action:saved.original_action, request_sha256:saved.request_sha256 })
  assert.deepEqual(abandonmentBody(readCommandReference(storage,key)), {action:"abandon_submission",original_action:saved.original_action,request_sha256:saved.request_sha256})
  assert.equal(readCommandReference(storage,recoveryKey("http://127.0.0.1:3143","other-editor")),null)
  assert.equal(readCommandReference(storage,recoveryKey("http://127.0.0.1:3144","invented-editor")),null)
  clearCommandReference(storage,key)
  assert.equal(readCommandReference(storage,key),null)
})

test("request digest matches canonical UTF-8 JSON and legacy references do not gain authority", async () => {
  const value={z:"é 🌡",a:[true,null,{"😀":"one", "\ue000":"two", n:2}]}
  const expected='{"a":[true,null,{"n":2,"\ue000":"two","😀":"one"}],"z":"é 🌡"}'
  assert.equal(await commandRequestSHA(value),createHash("sha256").update(expected).digest("hex"))
  await assert.rejects(()=>commandRequestSHA({a:1.5}))
  await assert.rejects(()=>commandRequestSHA({a:"\ud800"}))
  const legacy={command_id:crypto.randomUUID(),action:"edit",draftId:"invented"}
  const reference=readCommandReference({getItem:()=>JSON.stringify(legacy)},"key")
  assert.equal(abandonmentBody(reference),null)
  const command={command_id:legacy.command_id,action:"edit_revision",payload:{text:"Private draft prose."}}
  const upgraded=await withCommandReference({...reference,command})
  assert.equal(abandonmentBody(upgraded).original_action,"edit_revision")
  await assert.rejects(()=>withCommandReference({...upgraded,command:{...command,payload:{text:"changed"}}}))
})

const sha = "a".repeat(64)
function view() {
  return { draft_id:"invented-draft", target:{ draft_id:"invented-draft", content_revision:2, decision_revision:3, text_sha256:sha, evidence_sha256:sha },
    publication_approved:false, status:"prepared", text:"An invented source claim.", expected_policy_sha256:sha,
    expected_renderer_profile_sha256:sha, expected_review_sha256:sha, expected_check_completion_sha256:sha,
    preparation:{ proposal_sha256:sha }, packet:{ packet_sha256:sha, media:{ alt_text:"Complete invented description, forecast qualifiers and date.", width:1200, height:1500 } },
    removal:{ expected_proposal_sha256:sha, requested_at:"2026-10-11T12:00:00Z", expires_at:"2026-10-11T12:05:00Z" } }
}
const reviewed = { decision:"accept", confirmations:Object.fromEntries(Object.keys(jointConfirmations).map(k=>[k,true])), reason:"Checked the invented source." }

test("new description review displays exact wire separately and requires its sixth confirmation", () => {
  const current=view()
  current.platform_description={ record:{description_sha256:"b".repeat(64)}, wire_text:current.packet.media.alt_text+"\n", status:"platform_api_unqualified", qualification:"unqualified" }
  const render=confirmations=>renderToStaticMarkup(React.createElement(EditorMediaPanel,{
    view:current,role:"editor",imageUrl:"blob:invented",confirmations,reason:"Checked exact bytes.",setConfirmations(){},setReason(){},submit(){},refresh(){},
  }))
  const html=render(reviewed.confirmations)
  assert.equal((html.match(/type="checkbox"/g)||[]).length,6)
  assert.match(html,/Exact platform description/)
  assert.match(html,/Read the full image description/)
  assert.match(html,/Live posting is not qualified for this platform setup/)
  assert.match(html,/disabled=""[^>]*>Attach reviewed graphic/)
  const confirmed={...reviewed.confirmations,platform_description_faithful:true}
  assert.doesNotMatch(render(confirmed),/disabled=""[^>]*>Attach reviewed graphic/)
  const request=mediaCommand(current,"attach_media_revision",{...reviewed,confirmations:confirmed})
  assert.equal(request.payload.review.expected_platform_description_sha256,"b".repeat(64))
  assert.equal(Object.keys(confirmationsFor({...current.packet,schema_version:2},current.platform_description)).length,9)
  assert.equal("platform_profile" in request.payload.review,false)
  assert.equal("wire_text" in request.payload.review,false)
})

test("each media action carries exact references, no model verdict or browser role", () => {
  const current = view()
  for (const action of ["prepare_media_revision", "attach_media_revision", "review_media_revision", "request_revision_checks", "approve_media_revision", "remove_media_revision", "cancel_approval"]) {
    const result = mediaCommand(current, action, reviewed, new Date("2026-10-11T12:00:00Z"))
    assert.deepEqual(result.targets, [current.target])
    assert.equal(result.expires_at, action === "remove_media_revision" ? "2026-10-11T12:05:00Z" : "2026-10-11T12:05:00.000Z")
    assert.equal(result.action, action)
    for (const forbidden of ["passed", "role", "grant_id", "check_packet", "png", "source", "cost_usd"]) assert.equal(forbidden in result.payload, false)
  }
  const request = mediaCommand(current, "request_revision_checks")
  current.target.content_revision++
  assert.equal(request.targets[0].content_revision, 2)
  assert.throws(()=>mediaCommand(current, "publish"))
})

test("component exposes five explicit confirmations and complete alt; edit/update hides old authority", () => {
  const current = view()
  const render = changes => renderToStaticMarkup(React.createElement(EditorMediaPanel, {
    view:current, role:"editor", imageUrl:"blob:invented", confirmations:{}, reason:"", setConfirmations(){}, setReason(){}, submit(){}, refresh(){}, ...changes,
  }))
  const html = render({})
  assert.equal((html.match(/type="checkbox"/g) || []).length, 5)
  assert.match(html, /Complete invented description, forecast qualifiers and date/)
  assert.match(html, /An invented source claim/)
  assert.match(html, /disabled=""[^>]*>Attach reviewed graphic/)
  assert.match(render({ role:"viewer", confirmations:reviewed.confirmations, reason:reviewed.reason }), /disabled=""[^>]*>Attach reviewed graphic/)
  const passed = { ...current, status:"attached", review_current:true, checks_status:"passed" }
  assert.match(render({ view:passed }), /disabled=""[^>]*>Park approval locally/)
  assert.doesNotMatch(render({ view:passed, role:"publisher" }), /disabled=""[^>]*>Park approval locally/)
  for (const code of ["media_source_expired", "native_renderer_unavailable"]){
    const unavailable = render({view:{...current,status:"unavailable",code,packet:null}})
    assert.match(unavailable, /Remove graphic/)
    assert.doesNotMatch(unavailable, /Prepare graphic|Attach reviewed|Park approval/)
  }
  const { draft_id, ...revision_identity } = current.target
  const draft = { id:draft_id, revision_identity, local_preview:true, type:"fire" }
  assert.equal(sameMediaTarget(current, draft), true)
  assert.equal(sameMediaTarget(current, { ...draft, revision_identity:{ ...revision_identity, decision_revision:4 } }), false)
  for (const state of [{ editing:true }, { updating:true }]) {
    const hidden = renderToStaticMarkup(React.createElement(EditorMedia, { draft, ...state }))
    assert.doesNotMatch(hidden, /<img|<input|Park approval|Attach reviewed/)
  }
})

test("local delivery readback distinguishes partial and unknown outcomes without sending controls", () => {
  const current = { ...view(), parked:true, delivery:{ scope:"local_http_fixture_v1", publication_approved:false,
    intents:[{intent_id:"invented-intent", current:false, stages:{ x:{upload:{status:"confirmed"},alt:{status:"confirmed"},create:{status:"unknown"}},bluesky:{upload:{status:"not_sent"},create:{status:"pending"}} }}] } }
  const html = renderToStaticMarkup(React.createElement(EditorMediaPanel, {view:current, role:"viewer", imageUrl:"blob:invented", confirmations:{}, reason:""}))
  assert.match(html, /X image upload: confirmed by the local test/)
  assert.match(html, /X post creation: outcome unknown; automatic retry blocked/)
  assert.match(html, /Bluesky image upload: not sent/)
  assert.match(html, /Bluesky post creation: waiting/)
  assert.match(html, /no longer current; no new delivery steps/)
  assert.match(html, /They do not authorize publishing/)
  assert.doesNotMatch(html, />Send|>Publish|>Retry delivery|>Reconcile/)
})

test("media proxy authenticates and confines PNG access to a draft-scoped reference", async () => {
  const saved = { ...process.env }, original = globalThis.fetch, calls = []
  process.env.NODE_ENV = "test"
  process.env.DASHBOARD_AUTH_DISABLED = "1"
  process.env.THEHEAT_LOCAL_COMMAND_URL = "http://127.0.0.1:3999"
  for (const key of Object.keys(process.env)) if (/(?:TOKEN|SECRET|PASSWORD|API_KEY)$/.test(key)) delete process.env[key]
  const png = new Uint8Array(40); png.set([137,80,78,71,13,10,26,10])
  globalThis.fetch = async (url, options) => { calls.push([String(url), options]); return new Response(png, { headers:{ "Content-Type":"image/png" } }) }
  const request = query => new Request(`http://127.0.0.1:3033/api/editor-media?${query}`, { headers:{ host:"127.0.0.1:3033", origin:"http://127.0.0.1:3033", authorization:"Basic "+Buffer.from("editor:invented").toString("base64") } })
  try {
    const response = await GET(request(`draftId=invented-draft&proposal=${sha}`))
    assert.equal(response.status, 200)
    assert.equal(response.headers.get("content-type"), "image/png")
    assert.equal(response.headers.get("cache-control"), "private, no-store")
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), png)
    assert.equal(calls[0][0], `http://127.0.0.1:3999/drafts/invented-draft/media/${sha}/preview.png`)
    assert.equal(calls[0][1].redirect, "error")
    calls.length = 0
    for (const query of [`draftId=..%2fforeign&proposal=${sha}`, "draftId=a&draftId=b", `draftId=a&proposal=${sha}&asset=preview.svg`, "draftId=a&proposal=http://evil.invalid"])
      assert.equal((await GET(request(query))).status, 400)
    assert.equal((await GET(new Request("http://127.0.0.1:3033/api/editor-media?draftId=a", { headers:{host:"127.0.0.1:3033"} }))).status, 401)
    assert.deepEqual(calls, [])
    delete process.env.THEHEAT_LOCAL_COMMAND_URL
    assert.equal((await GET(request("draftId=a"))).status, 503)
    assert.deepEqual(calls, [])
  } finally {
    globalThis.fetch = original
    for (const key of Object.keys(process.env)) if (!Object.hasOwn(saved,key)) delete process.env[key]
    Object.assign(process.env,saved)
  }
})

test("retained image loader bounds bytes and refuses stale or invalid responses", async () => {
  const original=globalThis.fetch
  const bytes=new Uint8Array(40);bytes.set([137,80,78,71,13,10,26,10])
  try {
    globalThis.fetch=async()=>new Response(bytes,{headers:{"Content-Type":"image/png"}})
    const blob=await retainedMediaBlob(view(),new AbortController().signal)
    assert.equal(blob.type,"image/png");assert.equal(blob.size,40)
    globalThis.fetch=async()=>new Response(bytes,{headers:{"Content-Type":"image/svg+xml"}})
    await assert.rejects(()=>retainedMediaBlob(view(),new AbortController().signal))
    globalThis.fetch=async()=>new Response(new Uint8Array(40),{headers:{"Content-Type":"image/png"}})
    await assert.rejects(()=>retainedMediaBlob(view(),new AbortController().signal))
    globalThis.fetch=async()=>new Response(new Uint8Array(8*1024*1024+1),{headers:{"Content-Type":"image/png"}})
    await assert.rejects(()=>retainedMediaBlob(view(),new AbortController().signal),/size limit/)
    const control=new AbortController();control.abort()
    globalThis.fetch=async()=>new Response(bytes,{headers:{"Content-Type":"image/png"}})
    await assert.rejects(()=>retainedMediaBlob(view(),control.signal),/cancelled/)
  } finally {globalThis.fetch=original}
})

test("failed media body cleanup preserves the primary error without an unhandled rejection", () => {
  const moduleURL = new URL("../lib/editor-media.js", import.meta.url).href
  const result = spawnSync(process.execPath, ["--unhandled-rejections=strict", "--input-type=module", "--eval", `
    import assert from "node:assert/strict";
    import { retainedMediaBlob } from ${JSON.stringify(moduleURL)};
    const view={draft_id:"invented-draft",preparation:{proposal_sha256:"a".repeat(64)}};
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    for(const primary of [new Error("Invented body failure"),new DOMException("Invented canceled body","AbortError")]) {
      globalThis.fetch=async()=>new Response(new ReadableStream({start(controller){controller.error(primary)}}),
        {headers:{"content-type":"image/png"}});
      await assert.rejects(()=>retainedMediaBlob(view,new AbortController().signal),error=>error===primary);
      await tick();
    }
    let canceled=0;
    globalThis.fetch=async()=>new Response(new ReadableStream({
      start(controller){controller.enqueue(new Uint8Array(8*1024*1024+1))},
      cancel(){canceled++;throw new Error("Invented cleanup failure")}
    }),{headers:{"content-type":"image/png"}});
    await assert.rejects(()=>retainedMediaBlob(view,new AbortController().signal),/size limit/);
    await tick();
    assert.equal(canceled,1);
  `], { encoding:"utf8", timeout:5000 })
  assert.ifError(result.error)
  assert.equal(result.status,0,result.stderr || result.stdout)
})


test("source MODIS wire is distinct from full retained detail and requires faithful confirmation", () => {
  const current=view()
  current.packet.media.alt_text="Complete retained source and map detail, unchanged."
  current.platform_description={record:{schema_version:2,derivation:"modis_source_projection_v1",description_sha256:"b".repeat(64)},wire_text:"Exact source-backed MODIS wire text.",status:"fits_local_limits"}
  const html=renderToStaticMarkup(React.createElement(EditorMediaPanel,{view:current,role:"publisher",imageUrl:"blob:invented",confirmations:{},reason:"",setConfirmations(){},setReason(){},submit(){},refresh(){}}))
  assert.match(html,/Exact source-backed MODIS wire text/)
  assert.match(html,/Complete retained source and map detail, unchanged/)
  assert.match(html,/every selected row and its scientific qualifications/)
  assert.match(html,/additional source and map detail/)
  assert.doesNotMatch(html,/full retained description is reused exactly/)
  assert.equal((html.match(/type="checkbox"/g)||[]).length,6)
  assert.match(html,/disabled=""[^>]*>Attach reviewed graphic/)
  assert.match(html,/faithfully describes this graphic and preserves its required qualifications/)
})
