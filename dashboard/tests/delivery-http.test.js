import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

test("retained delivery readback uses authenticated draft-scoped HTTP and exposes no execution route", { skip:!process.env.THEHEAT_DELIVERY_HTTP_CONFIG }, async () => {
  const config=JSON.parse(readFileSync(process.env.THEHEAT_DELIVERY_HTTP_CONFIG))
  const prior={...process.env}, actualFetch=globalThis.fetch
  process.env.NODE_ENV="test"; process.env.THEHEAT_LOCAL_COMMAND_URL=config.endpoint
  globalThis.fetch=(url,options)=>{
    assert.equal(new URL(url).origin,config.endpoint,"External network refused")
    return actualFetch(url,options)
  }
  const route=await import("../app/api/editor-media/route.js")
  function request(query=`draftId=${config.draft_id}`,role="viewer",headers={}) {
    return route.GET(new Request(`${config.origin}/api/editor-media?${query}`,{headers:{Origin:config.origin,Host:new URL(config.origin).host,
      Authorization:`Basic ${Buffer.from(`${role}:invented-${role}`).toString("base64")}`,...headers}}))
  }
  try {
    for(const role of ["viewer","editor","publisher"]) {
      const response=await request(undefined,role)
      assert.equal(response.status,200,await response.clone().text())
      assert.equal(response.headers.get("cache-control"),"private, no-store")
      const body=await response.json()
      assert.deepEqual(body.delivery,config.expected)
      assert.equal(body.delivery.publication_approved,false)
      assert.equal(body.delivery.intents[0].stages.x.create.status,"unknown")
      assert.equal(body.delivery.intents[0].stages.bluesky.create.status,"confirmed")
      assert.equal(JSON.stringify(body.delivery).includes("body_base64"),false)
    }
    assert.equal((await request(undefined,"invalid")).status,401)
    assert.equal((await request(undefined,"viewer",{Origin:"http://evil.invalid"})).status,403)
    assert.equal((await request("draftId=absent-invented-draft")).status,409)
    assert.equal((await request(`draftId=${config.draft_id}&execute=1`)).status,400)
    assert.equal((await request(`draftId=${config.draft_id}&artifact=${"f".repeat(64)}`)).status,400)
    assert.equal(route.POST,undefined)
  } finally {
    globalThis.fetch=actualFetch
    for(const key of Object.keys(process.env)) if(!(key in prior)) delete process.env[key]
    Object.assign(process.env,prior)
  }
})
