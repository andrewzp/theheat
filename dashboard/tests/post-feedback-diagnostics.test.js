import test from "node:test"
import assert from "node:assert/strict"
import { draftIdentity } from "../lib/draft-revisions.js"
import { FeedbackError, feedbackDiagnostic } from "../lib/post-feedback.js"
import { GET, POST } from "../app/api/post-feedback/route.js"

const SECRET = "invented-upstream-secret-must-never-appear"
const auth = {authorization:`Basic ${btoa("editor:invented-test-only")}`}
function fixture() {
  const draft = {id:"invented-post",event_id:"invented-event",status:"posted",publish_outcome:"confirmed",tweet_id:"1234567890",text:"Invented example: floodwater closes the island’s road.",content_revision:1,posted_at:"2026-10-18T08:00:00Z",review_context:{source:"invented fixture"}}
  return {drafts:[draft],publish_ledger:{[draft.event_id]:{...draftIdentity(draft),text:draft.text,tweet_id:draft.tweet_id,phase:"confirmed",intent_id:"10a97d68-2e51-4998-92ed-f830863f7218"}}}
}
const archive = () => Response.json({public:false,files:{}})
const state = () => Response.json({public:true,files:{"state.json":{content:JSON.stringify(fixture())}}})
const raw = (url = "https://gist.githubusercontent.com/invented/raw/state.json") => Response.json({files:{"state.json":{truncated:true,raw_url:url}}})

async function run(responses, {configure, loggerThrows = false, request, expected = 503} = {}) {
  const priorEnv = {...process.env}, priorFetch = globalThis.fetch, priorWarn = console.warn
  const calls = [], logs = []
  Object.assign(process.env,{NODE_ENV:"production",DASHBOARD_AUTH_DISABLED:"0",DASHBOARD_USERNAME:"editor",DASHBOARD_PASSWORD:"invented-test-only",THEHEAT_STATE_BACKEND:"gist",THEHEAT_DB_PATH:"",GIST_ID:"fixture_state",THEHEAT_FEEDBACK_GIST_ID:"fixture_feedback",GITHUB_TOKEN:SECRET})
  delete process.env.THEHEAT_LOCAL_COMMAND_URL
  configure?.()
  globalThis.fetch = async (url, options = {}) => {
    assert.equal(options.method || "GET", "GET", "diagnostic reads must not write")
    assert.equal(options.redirect, "error")
    calls.push({url, options})
    assert.ok(calls.length <= responses.length, "no additional request or retry")
    const value = responses[calls.length - 1]
    if (value instanceof Error) throw value
    return value
  }
  console.warn = (...args) => {logs.push(args); if(loggerThrows) throw new Error(SECRET)}
  try {
    const response = request ? await request() : await GET(new Request("https://dashboard.example/api/post-feedback",{headers:auth}))
    assert.equal(response.status, expected)
    const body = response.headers.get("content-type")?.includes("application/json") ? await response.json() : await response.text()
    if(expected === 503) assert.deepEqual(body,{code:"feedback_store_unavailable"})
    assert.ok(!JSON.stringify(logs).includes(SECRET), "logs must not disclose exception, body or credential data")
    return {body, calls, logs:logs.map(args => {assert.equal(args.length,1); return JSON.parse(args[0])})}
  } finally {
    globalThis.fetch = priorFetch; console.warn = priorWarn
    for(const name of Object.keys(process.env)) if(!Object.hasOwn(priorEnv,name)) delete process.env[name]
    Object.assign(process.env,priorEnv)
  }
}

function diagnostic(result, stage, reason, status = null) {
  assert.deepEqual(result.logs,[{event:"theheat_feedback_store_unavailable",stage,reason,http_status:status}])
}

test("missing feedback configuration logs only a fixed stage and performs no read",async()=>{
  const result = await run([],{configure:()=>delete process.env.THEHEAT_FEEDBACK_GIST_ID})
  diagnostic(result,"configuration","missing_or_invalid");assert.equal(result.calls.length,0)
})
for(const status of [401,403,404,429,503]) test(`archive HTTP ${status} identifies the failed read without its body`,async()=>{
  const result=await run([new Response(SECRET,{status})])
  diagnostic(result,"feedback_archive","http_error",status);assert.equal(result.calls.length,1)
})
test("state metadata refusal is distinct from feedback archive access",async()=>{
  const result=await run([archive(),new Response(SECRET,{status:403})])
  diagnostic(result,"production_state_metadata","http_error",403);assert.equal(result.calls.length,2)
})
for(const [stage, prefix] of [["feedback_archive",()=>[]],["production_state_metadata",()=>[archive()]],["production_state_raw",()=>[archive(),raw()]]]) {
  test(`${stage} network failure does not log the exception or retry`,async()=>{
    const result=await run([...prefix(),new Error(SECRET)])
    diagnostic(result,stage,"request_failed");assert.equal(result.calls.length,prefix().length+1)
  })
}
test("public feedback archive remains refused and does not read production state",async()=>{
  const result=await run([Response.json({public:true,files:{}})])
  diagnostic(result,"feedback_archive","not_private");assert.equal(result.calls.length,1)
})
test("malformed archive JSON and document shape are separate from access failure",async()=>{
  diagnostic(await run([new Response(SECRET)]),"feedback_archive","invalid_json")
  diagnostic(await run([Response.json(null)]),"feedback_archive","invalid_document")
})
test("malformed metadata and absent state file remain refused with safe stages",async()=>{
  diagnostic(await run([archive(),new Response(SECRET)]),"production_state_metadata","invalid_json")
  diagnostic(await run([archive(),Response.json(null)]),"production_state_metadata","invalid_document")
  diagnostic(await run([archive(),Response.json({files:{}})]),"production_state_metadata","missing_state_file")
})
test("corrupt feedback data logs neither ratings nor provider-supplied filenames",async()=>{
  const result=await run([Response.json({public:false,files:{["editorial-feedback-"+SECRET]:{content:SECRET}}})])
  diagnostic(result,"feedback_records","invalid_document");assert.equal(result.calls.length,1)
})
test("invalid raw origin cannot trigger a third request or leak the URL",async()=>{
  const result=await run([archive(),raw("https://"+SECRET+".invalid/private")])
  diagnostic(result,"production_state_raw","invalid_raw_origin");assert.equal(result.calls.length,2)
})
test("raw refusal retains HTTP status, no forwarded credentials and no redirect",async()=>{
  const result=await run([archive(),raw(),new Response(SECRET,{status:302,headers:{Location:"https://example.invalid/private"}})])
  diagnostic(result,"production_state_raw","http_error",302)
  assert.equal(result.calls.length,3);assert.equal(result.calls[2].options.headers,undefined)
})
test("strict state parser refusal stays a failure without logging retained values",async()=>{
  const invalid='{"drafts":[],"retained_value":9007199254740993}'
  const result=await run([archive(),Response.json({files:{"state.json":{content:invalid}}})])
  diagnostic(result,"production_state_document","invalid_document");assert.equal(result.calls.length,2)
})
test("invalid raw UTF8 is a bounded read failure, not a parser fallback",async()=>{
  diagnostic(await run([archive(),raw(),new Response(new Uint8Array([255]))]),"production_state_raw","response_unreadable")
})
test("a failing response stream does not leak its exception",async()=>{
  const body=new ReadableStream({start(controller){controller.error(new Error(SECRET))}})
  diagnostic(await run([new Response(body)]),"feedback_archive","response_unreadable")
})
test("logger failure cannot replace the response or repeat a read",async()=>{
  const result=await run([new Response(SECRET,{status:403})],{loggerThrows:true})
  diagnostic(result,"feedback_archive","http_error",403);assert.equal(result.calls.length,1)
})
test("auth and cross-origin refusal precede both storage reads and logging",async()=>{
  const unauth=await run([],{expected:401,request:()=>GET(new Request("https://dashboard.example/api/post-feedback"))})
  assert.equal(unauth.calls.length,0);assert.equal(unauth.logs.length,0)
  const cross=await run([],{expected:403,request:()=>POST(new Request("https://dashboard.example/api/post-feedback",{method:"POST",headers:{...auth,origin:"https://elsewhere.invalid","content-type":"application/json"},body:"{}"}))})
  assert.equal(cross.calls.length,0);assert.equal(cross.logs.length,0)
})
test("a successful exact-receipt read adds no error log or extra request",async()=>{
  const result=await run([archive(),state()],{expected:200})
  assert.equal(result.body.posts.length,1);assert.equal(result.body.posts[0].ratings.length,0)
  assert.equal(result.calls.length,2);assert.equal(result.logs.length,0)
})
test("untrusted diagnostic fields never become operator log content",()=>{
  const good={stage:"feedback_archive",reason:"http_error",http_status:403}
  for(const changed of [{...good,stage:SECRET},{...good,reason:SECRET},{...good,http_status:SECRET},{...good,http_status:600},{...good,extra:SECRET}]) {
    assert.equal(feedbackDiagnostic(new FeedbackError("feedback_store_unavailable",503,changed)),null)
  }
  assert.equal(feedbackDiagnostic(new Error(SECRET)),null)
  assert.equal(feedbackDiagnostic(new FeedbackError("feedback_write_uncertain",503,good)),null)
  assert.deepEqual(feedbackDiagnostic(new FeedbackError("feedback_store_unavailable",503,good)),good)
})
