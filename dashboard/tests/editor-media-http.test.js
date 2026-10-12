import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { createServer } from "node:http"
import { spawnSync } from "node:child_process"
import { Readable } from "node:stream"
import { mediaCommand, jointConfirmations } from "../lib/editor-media.js"
import { createDraftCommand } from "../lib/draft-command-request.js"
import { withCommandReference, abandonmentBody, saveCommandReference, readCommandReference, clearCommandReference } from "../lib/local-command-recovery.js"

test("actual authenticated HTTP → native package → review → fresh checks → one parked intent → edit", { skip:!process.env.THEHEAT_MEDIA_HTTP_CONFIG }, async () => {
  const file = process.env.THEHEAT_MEDIA_HTTP_CONFIG, config = JSON.parse(readFileSync(file))
  const prior = {...process.env}, actualFetch = globalThis.fetch
  process.env.NODE_ENV="test"; process.env.DASHBOARD_AUTH_DISABLED="1"; process.env.THEHEAT_LOCAL_COMMAND_URL=config.endpoint
  globalThis.fetch = (url, options) => {
    assert.ok([config.endpoint,config.origin].includes(new URL(url).origin), "External network refused")
    return actualFetch(url,options)
  }
  const routes = { "/api/editor-media":await import("../app/api/editor-media/route.js"), "/api/drafts":await import("../app/api/drafts/route.js"),
    "/api/local-command-recovery":await import("../app/api/local-command-recovery/route.js") }
  const server = createServer(async (incoming,outgoing) => {
    try {
      const request = new Request(config.origin+incoming.url, { method:incoming.method, headers:incoming.headers,
        ...(incoming.method==="POST"?{ body:Readable.toWeb(incoming), duplex:"half" }: {}) })
      const route = routes[new URL(request.url).pathname]
      const response = await route[incoming.method](request)
      outgoing.writeHead(response.status,Object.fromEntries(response.headers)); outgoing.end(Buffer.from(await response.arrayBuffer()))
    } catch { outgoing.writeHead(500); outgoing.end("failed") }
  })
  await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(Number(new URL(config.origin).port),"127.0.0.1",resolve)})
  async function request(path, body, role="editor") {
    const response = await actualFetch(config.origin+path,{ method:body?"POST":"GET", headers:{Origin:config.origin,
      Authorization:`Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`, "Content-Type":"application/json" }, ...(body?{body:JSON.stringify(body)}:{}) })
    return { status:response.status, body:response.headers.get("content-type")==="image/png" ? new Uint8Array(await response.arrayBuffer()) : await response.json() }
  }
  const mediaPath = `/api/editor-media?draftId=${config.draft_id}`
  function worker(operation,id) {
    const run=spawnSync(config.python,[config.child,file,operation,id],{cwd:config.root,env:prior,encoding:"utf8",timeout:60000})
    assert.equal(run.status,0,run.stdout+run.stderr)
    return JSON.parse(run.stdout.trim().split("\n").at(-1))
  }
  async function submit(command,role="editor") {
    const accepted=await request("/api/drafts",command,role)
    assert.equal(accepted.status,202,JSON.stringify(accepted.body))
    const recovery=await request(`/api/drafts?commandId=${command.command_id}`,null,role)
    assert.deepEqual(recovery.body.recoverable_command,command)
    assert.equal(recovery.body.status,"pending")
    const result=worker("consume",command.command_id)
    assert.notEqual(result.status,"rejected",JSON.stringify(result))
    assert.deepEqual(worker("consume",command.command_id),result)
    return result
  }
  try {
    let current=(await request(mediaPath)).body
    assert.equal(current.status,"ready",JSON.stringify(current))
    const prepare=mediaCommand(current,"prepare_media_revision",null,new Date(config.at))
    assert.equal((await request("/api/drafts",prepare,"viewer")).status,403)
    assert.equal((await submit(prepare)).status,"unchanged")
    current=(await request(mediaPath)).body
    assert.equal(current.status,"prepared")
    const pngPath=mediaPath+`&proposal=${current.preparation.proposal_sha256}`
    const png=await request(pngPath)
    assert.equal(png.status,200);assert.ok(png.body.length>1000)
    assert.equal((await request(`/api/editor-media?draftId=draft-1&proposal=${current.preparation.proposal_sha256}`)).status,409)
    assert.equal((await request(mediaPath+"&proposal="+"f".repeat(64))).status,409)
    await submit(mediaCommand(current,"attach_media_revision",{decision:"accept",confirmations:Object.fromEntries(Object.keys(jointConfirmations).map(k=>[k,true])),reason:"Reviewed actual invented source, PNG and alt together."},new Date(config.at)))
    current=(await request(mediaPath)).body
    assert.equal(current.review_current,true)
    const checks=mediaCommand(current,"request_revision_checks",null,new Date(config.at))
    await submit(checks)
    assert.equal((await request(mediaPath)).body.checks_status,"pending")
    for(const stage of ["deterministic","safety","fact_check","critic"]){
      const result=worker(stage,checks.command_id)
      assert.equal(result.outcome,"completed",JSON.stringify(result));assert.equal(result.checks.stages[stage],"passed")
    }
    current=(await request(mediaPath)).body
    assert.equal(current.checks_status,"passed")
    const approve=mediaCommand(current,"approve_media_revision",null,new Date(config.at))
    assert.equal((await request("/api/drafts",approve)).status,403)
    const result=await submit(approve,"publisher")
    assert.ok(result.publish_intent_id)
    assert.equal((await request(mediaPath)).body.parked,true)
    const draft=(await request("/api/drafts")).body.drafts.find(d=>d.id===config.draft_id)
    assert.equal(draft.status,"pending")
    const edit=createDraftCommand(draft,"edit",{editedText:"An edited invented weather statement."},new Date(config.at))
    await submit(edit)
    current=(await request(mediaPath)).body
    assert.equal(current.review_current,false);assert.equal(current.parked,false)
    assert.deepEqual((await request(pngPath)).body,png.body)
    assert.equal((await request(`/api/drafts?commandId=${approve.command_id}`)).body.recoverable_command,null)
    // Reload before any acceptance: only a digest-bearing reference survives.
    const latest=(await request("/api/drafts")).body
    const absent=createDraftCommand(latest.drafts.find(d=>d.id===config.draft_id),"edit",{editedText:"This must never be saved."},new Date(config.at))
    const saved=await withCommandReference({command:absent,draftId:config.draft_id,action:"edit"})
    const rows=new Map(),storage={setItem:(k,v)=>rows.set(k,v),getItem:k=>rows.get(k),removeItem:k=>rows.delete(k)}
    saveCommandReference(storage,"same-operator",saved)
    const reloaded=readCommandReference(storage,"same-operator"), body=abandonmentBody(reloaded)
    assert.equal(reloaded.command.payload,undefined)
    assert.equal((await request(`/api/drafts?commandId=${absent.command_id}`)).status,404)
    const path=`/api/local-command-recovery?commandId=${absent.command_id}`
    assert.equal((await request(path,body,"viewer")).status,403)
    assert.equal((await request("/api/drafts",{...absent,action:"abandon_submission",payload:body})).status,409)
    const closed=await request(path,body)
    assert.equal(closed.status,200,JSON.stringify(closed.body))
    assert.equal(closed.body.result.code,"submission_abandoned")
    assert.deepEqual((await request(path,body)).body,closed.body)
    assert.equal((await request(path,body,"publisher")).status,409)
    assert.equal((await request("/api/drafts",absent)).status,409)
    assert.deepEqual((await request("/api/drafts")).body,latest)
    clearCommandReference(storage,"same-operator")
    assert.equal(readCommandReference(storage,"same-operator"),null)
  } finally {
    await new Promise(resolve=>server.close(resolve));globalThis.fetch=actualFetch
    for(const key of Object.keys(process.env))if(!Object.hasOwn(prior,key))delete process.env[key]
    Object.assign(process.env,prior)
  }
})
