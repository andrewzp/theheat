import test from "node:test"
import assert from "node:assert/strict"
import { draftIdentity } from "../lib/draft-revisions.js"
import { feedbackTarget, feedbackInput, readPostFeedback, savePostFeedback } from "../lib/post-feedback.js"
import { GET, POST } from "../app/api/post-feedback/route.js"
import { renderToStaticMarkup } from "react-dom/server"
import React from "react"
import PostFeedback from "../app/components/PostFeedback.js"

const id = "b6f74042-dcc1-42e5-bc76-eab95ff9bc5a"
function fixture() {
  const draft = {id:"synthetic-post",event_id:"synthetic-event",status:"posted",publish_outcome:"confirmed",tweet_id:"1234567890",text:"Invented example: a storm closes the island’s ferry routes.",content_revision:1,posted_at:"2026-10-17T12:00:00.000Z",review_context:{source:"invented fixture only"}}
  const receipt = {...draftIdentity(draft),text:draft.text,tweet_id:draft.tweet_id,phase:"confirmed",intent_id:"10a97d68-2e51-4998-92ed-f830863f7218"}
  return {drafts:[draft],publish_ledger:{[draft.event_id]:receipt},unrelated:{huge_number:1.25}}
}
function ballot(state = fixture()) { return {request_id:id,target:feedbackTarget(state.drafts[0],state),punch:4,clarity:5,economy:3,note:"Lead with the interruption to daily life.",own_rating:true} }
function record(input = ballot()) {return {...input,schema_version:1,kind:"dashboard_editorial_opinion",received_at:"2026-10-18T09:00:00.000Z"}}
function fileName(requestId = id) {return `editorial-feedback-${requestId}.json`}
async function store(run, {state = fixture(), files = {}, publicGist = false, mode = "ok"} = {}) {
  Object.assign(process.env,{NODE_ENV:"production",DASHBOARD_USERNAME:"editor",DASHBOARD_PASSWORD:"invented-test-only",THEHEAT_STATE_BACKEND:"gist",THEHEAT_DB_PATH:"",GIST_ID:"fixture_state",THEHEAT_FEEDBACK_GIST_ID:"fixture_feedback",GITHUB_TOKEN:"fixture_token"})
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  const original = globalThis.fetch, calls = [], stateArchive={"state.json":{content:JSON.stringify(state)}}, archive = {...structuredClone(files)}
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url,options})
    if (url === "https://gist.githubusercontent.com/fixture/raw/state.json") return new Response(JSON.stringify(state))
    if (url === "https://api.github.com/gists/fixture_state") {
      assert.notEqual(options.method,"PATCH");return Response.json({public:true,files:stateArchive})
    }
    assert.equal(url,"https://api.github.com/gists/fixture_feedback")
    assert.equal(options.redirect,"error")
    if (options.method === "PATCH") {
      const patch = JSON.parse(options.body)
      assert.deepEqual(Object.keys(patch),["files"])
      assert.equal(Object.keys(patch.files).length,1)
      const name = Object.keys(patch.files)[0]
      assert.ok(name.startsWith("editorial-feedback-"))
      if (mode === "reject") return new Response("provider token body not exposed",{status:403})
      if (mode !== "drop") Object.assign(archive,structuredClone(patch.files))
      if (mode === "lost_response") throw new Error("provider secret exception")
      return Response.json({})
    }
    return Response.json({public:publicGist, files:archive})
  }
  try {return await run({calls,archive,state,stateArchive})} finally {globalThis.fetch = original}
}
function request(body, options = {}) {
  return new Request("https://dashboard.example/api/post-feedback",{method:"POST",headers:{authorization:`Basic ${btoa("editor:invented-test-only")}`,origin:"https://dashboard.example","content-type":"application/json",...options.headers},body:typeof body === "string" ? body : JSON.stringify(body)})
}
const get = query => new Request(`https://dashboard.example/api/post-feedback${query || ""}`,{headers:{authorization:`Basic ${btoa("editor:invented-test-only")}`}})

test("confirmed receipt joins exact published revision and text", () => {
  const state = fixture(), target = feedbackTarget(state.drafts[0],state)
  assert.equal(target.tweet_id,"1234567890"); assert.equal(target.text,state.drafts[0].text)
  assert.equal(target.text_sha256,draftIdentity(state.drafts[0]).text_sha256)
})
for (const change of [
  s => {s.drafts[0].status="pending"}, s => {delete s.drafts[0].publish_outcome},
  s => {s.drafts[0].publish_outcome="unknown"}, s => {s.drafts[0].text+=" changed"},
  s => {s.drafts[0].content_revision++}, s => {s.drafts[0].review_context.source="changed"},
  s => {s.drafts[0].tweet_id="999"}, s => {s.drafts[0].revision_conflicts=[{}]},
  s => {s.publish_ledger={}}, s => {s.publish_ledger["synthetic-event"].phase="unknown"},
  s => {s.publish_ledger["synthetic-event"].attempt_conflicts=[{}]},
  s => {delete s.publish_ledger["synthetic-event"].text_sha256},
]) test(`legacy/changed/unknown receipt cannot rate: ${change}`, () => {
  const state=fixture(); change(state); assert.equal(feedbackTarget(state.drafts[0],state),null)
})
for (const [key,value] of [["punch",true],["clarity",0],["economy",6],["punch",1.5],["punch","5"],["own_rating",false],["request_id","bad"],["note","x".repeat(501)],["note","\ud800"]]) test(`invalid explicit rating ${key}/${String(value).slice(0,20)}`, () => {
  const input=ballot(); input[key]=value; assert.throws(() => feedbackInput(input),e => e.code === "invalid_feedback")
})
test("absent/extra fields and missing scores never default to a rating", () => {
  for (const input of [{...ballot(),extra:1},Object.fromEntries(Object.entries(ballot()).filter(([k])=>k!=="punch")),{...ballot(),target:{...ballot().target,extra:1}}]) assert.throws(()=>feedbackInput(input))
})
test("one immutable auxiliary file, no draft/ledger/control rewrite, readback and idempotent acknowledgement",async () => store(async ({calls,stateArchive}) => {
  const before = structuredClone(stateArchive["state.json"])
  const result = await savePostFeedback(ballot())
  assert.equal(result.record.kind,"dashboard_editorial_opinion"); assert.equal(result.already_saved,false)
  assert.deepEqual(stateArchive["state.json"],before)
  const again=await savePostFeedback(ballot()); assert.equal(again.already_saved,true)
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,1)
  const read=await readPostFeedback(id)
  assert.equal(read.posts[0].ratings.length,1);assert.equal(read.request.request_id,id)
  assert.equal(read.independent_human_benchmark,false); assert.equal(read.remaining,99)
}))
test("request ID cannot be reused for changed content",async () => store(async ({calls}) => {
  await savePostFeedback(ballot()); await assert.rejects(()=>savePostFeedback({...ballot(),punch:1}),e=>e.code==="feedback_id_conflict")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,1)
}))
test("stale target refused before any write",async () => store(async ({calls}) => {
  const input=ballot();input.target.evidence_sha256="0".repeat(64);await assert.rejects(()=>savePostFeedback(input),e=>e.code==="post_changed")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,0)
}))
for (const mode of ["reject","drop","lost_response"]) test(`uncertain ${mode} never retries write; exact ID lookup recovers actual result`,async () => store(async ({calls}) => {
  await assert.rejects(()=>savePostFeedback(ballot()),e=>e.code==="feedback_write_uncertain")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,1)
  const result=await readPostFeedback(id);assert.equal(!!result.request,mode==="lost_response")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,1)
},{mode}))
for (const file of [{content:"not json"},{content:JSON.stringify(record()),truncated:true},{content:JSON.stringify({...record(),kind:"human_gold"})},{content:"x".repeat(8193)}]) test("corrupt/truncated archive fails closed",async () => store(async ({calls}) => {
  await assert.rejects(()=>savePostFeedback(ballot()),e=>e.code==="feedback_store_unavailable")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,0)
},{files:{[fileName()]:file}}))
test("public feedback Gist cannot receive private opinions",async () => store(async ({calls})=>{
  await assert.rejects(()=>savePostFeedback(ballot())); assert.equal(calls.filter(c=>c.options.method==="PATCH").length,0)
},{publicGist:true}))
test("capacity bounded without rewriting old files",async () => {
  const files={}
  for(let n=0;n<100;n++){const request_id=`${n.toString(16).padStart(8,"0")}-dcc1-42e5-bc76-eab95ff9bc5a`;files[fileName(request_id)]={content:JSON.stringify(record({...ballot(),request_id}))}}
  await store(async({calls})=>{await assert.rejects(()=>savePostFeedback(ballot()),e=>e.code==="feedback_capacity");assert.equal(calls.filter(c=>c.options.method==="PATCH").length,0)},{files})
})
test("changed current post never inherits old feedback",async () => {
  const state=fixture();state.drafts[0].posted_at="2026-10-18T09:01:00.000Z"
  await store(async()=>assert.equal((await readPostFeedback()).posts[0].ratings.length,0),{state,files:{[fileName()]:{content:JSON.stringify(record())}}})
})
test("auth precedes reads and same-origin JSON precedes writes",async () => store(async ({calls})=>{
  assert.equal((await GET(new Request("https://dashboard.example/api/post-feedback"))).status,401)
  for(const headers of [{origin:"https://other.example"},{origin:"null"},{"sec-fetch-site":"cross-site"},{origin:""}]) assert.equal((await POST(request(ballot(),{headers}))).status,403)
  for(const body of ["{", "x".repeat(8193), JSON.stringify({...ballot(),punch:true})]) assert.equal((await POST(request(body))).status,400)
  assert.equal(calls.length,0)
  const saved=await POST(request(ballot()));assert.equal(saved.status,200);assert.equal(saved.headers.get("cache-control"),"private, no-store")
  assert.equal((await GET(get())).status,200)
}))
test("experimental command/SQLite modes never touch Gist feedback",async()=>store(async({calls})=>{
  process.env.THEHEAT_STATE_BACKEND="sqlite";assert.equal((await GET(get())).status,503)
  assert.equal((await POST(request(ballot()))).status,503);assert.equal(calls.length,0)
}))
test("truncated state uses fixed unauthenticated GitHub raw origin only",async()=>store(async({stateArchive,calls,state})=>{
  stateArchive["state.json"]={truncated:true,raw_url:"https://gist.githubusercontent.com/fixture/raw/state.json"}
  assert.equal((await readPostFeedback()).posts.length,1)
  const raw=calls.find(c=>c.url.includes("gist.githubusercontent.com"));assert.equal(raw.options.headers,undefined)
  stateArchive["state.json"].raw_url="https://evil.example/private";await assert.rejects(()=>readPostFeedback());
  assert.ok(calls.every(c=>!c.url.includes("evil.example")));assert.equal(state.drafts[0].text,fixture().drafts[0].text)
}))
test("disabled local feedback renders no fake ratings or posting control",()=>{
  const html=renderToStaticMarkup(React.createElement(PostFeedback,{enabled:false}))
  assert.match(html,/editorial opinion/);assert.match(html,/production dashboard/)
  assert.doesNotMatch(html,/Approve|Save editorial feedback|<select/)
})

function archiveFiles(count) {
  return Object.fromEntries(Array.from({length:count},(_,n)=>{const request_id=`${n.toString(16).padStart(8,"0")}-dcc1-42e5-bc76-eab95ff9bc5a`;return [fileName(request_id),{content:JSON.stringify(record({...ballot(),request_id}))}]}))
}
test("interleaved writers at 99 preserve 101 readable receipts and refuse later writes",async()=>store(async({calls})=>{
  const second={...ballot(),request_id:"c6f74042-dcc1-42e5-bc76-eab95ff9bc5a"}
  const results=await Promise.all([savePostFeedback(ballot()),savePostFeedback(second)])
  assert.equal(results.length,2)
  const recovered=await readPostFeedback(id);assert.equal(recovered.request.request_id,id)
  assert.equal(recovered.posts[0].ratings.length,101);assert.equal(recovered.remaining,0)
  assert.equal((await readPostFeedback(second.request_id)).request.request_id,second.request_id)
  await assert.rejects(()=>savePostFeedback({...ballot(),request_id:"d6f74042-dcc1-42e5-bc76-eab95ff9bc5a"}),e=>e.code==="feedback_capacity")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,2)
},{files:archiveFiles(99)}))
test("exact request recovery survives the bounded full-archive read limit",async()=>store(async({calls})=>{
  await assert.rejects(()=>readPostFeedback(),e=>e.code==="feedback_capacity")
  const request_id="00000000-dcc1-42e5-bc76-eab95ff9bc5a"
  assert.equal((await readPostFeedback(request_id)).request.request_id,request_id)
  await assert.rejects(()=>savePostFeedback(ballot()),e=>e.code==="feedback_capacity")
  assert.equal(calls.filter(c=>c.options.method==="PATCH").length,0)
},{files:archiveFiles(1001)}))

test("public production state remains read-only; feedback requires its own configured secret archive",async()=>store(async({calls})=>{
  delete process.env.THEHEAT_FEEDBACK_GIST_ID
  await assert.rejects(()=>savePostFeedback(ballot()),e=>e.code==="feedback_store_unavailable")
  assert.equal(calls.length,0)
}))
