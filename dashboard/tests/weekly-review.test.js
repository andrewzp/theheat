import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { draftIdentity } from "../lib/draft-revisions.js"
import { feedbackTarget } from "../lib/post-feedback.js"
import { buildWeeklyReview,weeklyReviewMarkdown } from "../lib/weekly-review.js"
const asOf="2026-10-18T12:00:00.000Z"
function state(){
 const d={id:"invented-draft",event_id:"invented-event",status:"posted",publish_outcome:"confirmed",tweet_id:"1234567890",text:"PRIVATE INVENTED SENTENCE: a storm closes the ferry.",content_revision:1,manual_override:true,posted_at:"2026-10-17T12:00:00.000Z",review_context:{source:"PRIVATE SOURCE TEXT"}}
 return {drafts:[d],publish_ledger:{[d.event_id]:{...draftIdentity(d),text:d.text,tweet_id:d.tweet_id,phase:"confirmed",intent_id:"10a97d68-2e51-4998-92ed-f830863f7218"}}}
}
function opinion(s=state(),id="b6f74042-dcc1-42e5-bc76-eab95ff9bc5a"){
 return {request_id:id,target:feedbackTarget(s.drafts[0],s),punch:4,clarity:5,economy:3,note:"PRIVATE OPINION NOTE",own_rating:true,schema_version:1,kind:"dashboard_editorial_opinion",received_at:"2026-10-17T13:00:00.000Z"}
}
function build(s=state(),records=null){return buildWeeklyReview({state:s,feedbackRecords:records,asOf})}
test("exact receipt, descriptive copy and unavailable feedback/cost never become quality/cap claims",()=>{
 const s=state(),before=structuredClone(s),r=build(s)
 assert.equal(r.delivery.count,1);assert.equal(r.copy.median_characters,[...s.drafts[0].text].length)
 assert.equal(r.copy.manual_or_edited,1);assert.equal(r.copy.verified_model_authorship,null)
 assert.equal(r.editorial_feedback.status,"unavailable");assert.equal(r.editorial_feedback.records_in_window,null)
 assert.equal(r.cost_context.weekly_total_usd,null);assert.equal(r.cost_context.known_cost_usd,null)
 assert.equal(r.cost_context.budget_enforced,false);assert.equal(r.decision.promotion,"HOLD");assert.deepEqual(s,before)
})
test("explicit empty feedback is an observed supplied zero, not missing",()=>{const r=build(state(),[]);assert.equal(r.editorial_feedback.records_in_window,0);assert.equal(r.editorial_feedback.status,"supplied_records_only")})
for(const [at,expected]of [["2026-10-11T11:59:59.999Z",0],["2026-10-11T12:00:00.000Z",1],["2026-10-18T11:59:59.999Z",1],[asOf,0],["2026-10-18T12:00:00.001Z",0],["2026-10-18T13:00:00+01:00",0],["2026-10-18T12:30:00+01:00",1],["2026-02-30T00:00:00Z",0]])test(`strict half-open weekly timestamp ${at}`,()=>{const s=state();s.drafts[0].posted_at=at;assert.equal(build(s).delivery.count,expected)})
for(const clock of [null,"not a date","2026-10-18T12:00:00","2026-02-30T00:00:00Z",true])test("invalid/naive clock refuses",()=>assert.throws(()=>buildWeeklyReview({state:state(),asOf:clock})))
test("unknown/changed/legacy receipts never count",()=>{for(const alter of [s=>s.drafts[0].publish_outcome="unknown",s=>s.drafts[0].text+="changed",s=>delete s.publish_ledger,s=>delete s.publish_ledger["invented-event"].text_sha256]){const s=state();alter(s);assert.equal(build(s).delivery.count,0)}})
test("identical draft duplicate deduplicates; conflicting ID excludes entire ID",()=>{const s=state();s.drafts.push(structuredClone(s.drafts[0]));assert.equal(build(s).delivery.count,1);s.drafts[1].text+="different";assert.equal(build(s).delivery.count,0);assert.equal(build(s).exclusions.conflicting_draft_ids,1)})
test("a second draft claiming same X ID cannot inflate or silently choose a winner",()=>{const s=state();s.drafts.push({...s.drafts[0],id:"other",text:"conflicting sentence"});assert.equal(build(s).delivery.count,0);assert.equal(build(s).exclusions.ambiguous_tweet_ids,1)})
test("explicit bound opinion displayed once; exact duplicate not independent",()=>{const s=state(),record=opinion(s),r=build(s,[record,record]);assert.equal(r.editorial_feedback.records_in_window,1);assert.equal(r.exclusions.duplicate_opinion_ids,1);assert.equal(r.delivery.posts[0].editorial_opinion.punch,4);assert.equal(r.editorial_feedback.preference_result,null)})
test("conflicting ID including an invalid-schema record excludes both",()=>{const o=opinion();for(const changed of [{...o,punch:1},{...o,extra:"tamper"}]){const r=build(state(),[o,changed]);assert.equal(r.editorial_feedback.records_in_window,0);assert.equal(r.exclusions.conflicting_opinion_ids,1)}})
test("latest explicit opinion per post, repeated saves never become independent raters",()=>{const a=opinion(),b={...opinion(state(),"c6f74042-dcc1-42e5-bc76-eab95ff9bc5a"),punch:2,received_at:"2026-10-17T14:00:00.000Z"};const r=build(state(),[a,b]);assert.equal(r.editorial_feedback.records_in_window,2);assert.equal(r.editorial_feedback.posts_with_latest_opinion,1);assert.equal(r.delivery.posts[0].editorial_opinion.punch,2)})
test("stale/opinion-before-post/future/malformed feedback is excluded",()=>{const o=opinion();for(const altered of [{...o,target:{...o.target,posted_at:"2026-10-17T11:00:00Z"}},{...o,received_at:"2026-10-17T10:00:00Z"},{...o,received_at:asOf},{...o,punch:true}])assert.equal(build(state(),[altered]).editorial_feedback.records_in_window,0)})
test("neither JSON nor Markdown leaks raw tweet, note, source or provider error text",()=>{const s=state();s.errors=[{msg:"PRIVATE PROVIDER EXCEPTION"}];const r=build(s,[opinion(s)]);const text=JSON.stringify(r)+weeklyReviewMarkdown(r);for(const privateText of [s.drafts[0].text,"PRIVATE OPINION NOTE","PRIVATE SOURCE TEXT","PRIVATE PROVIDER EXCEPTION"])assert.ok(!text.includes(privateText))})
test("month context retains partial/unpriced usage; never divide it by weekly posts",()=>{const s=state();s.llm_usage={"2026-10-18":{writer:{usd:0.1,calls:2,priced_calls:1,unpriced_calls:1,missing_usage_calls:0,priced_usd:0.1}}};const r=build(s,[]);assert.equal(r.cost_context.known_cost_usd,0.1);assert.equal(r.cost_context.unpriced_calls,1);assert.equal(r.cost_context.pricing_coverage,"partial");assert.equal(r.cost_context.cost_per_post_usd,null);assert.equal(r.cost_context.period,"month_to_date_daily_buckets_not_weekly_total")})
test("finite JSON and row bounds refuse before projections",()=>{for(const input of [{state:{...state(),drafts:Array(1025).fill({})},asOf},{state:state(),asOf,feedbackRecords:Array(1001).fill({})},{state:{...state(),bad:NaN},asOf}])assert.throws(()=>buildWeeklyReview(input))})
test("report id and Markdown reproducible with fixed supplied clock/input",()=>{const a=build(state(),[]),b=build(state(),[]);assert.deepEqual(a,b);assert.equal(weeklyReviewMarkdown(a),weeklyReviewMarkdown(b))})
test("local CLI repeats idempotently, protects output bytes and sanitizes bad input",()=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),"theheat-weekly-"));
 try{
  const input=path.join(directory,"input.json"),feedback=path.join(directory,"feedback.json"),output=path.join(directory,"reports");fs.writeFileSync(input,JSON.stringify(state()));fs.writeFileSync(feedback,JSON.stringify({records:[]}));
  const args=[new URL("../../scripts/weekly_review.mjs",import.meta.url).pathname,"--state",input,"--feedback",feedback,"--as-of",asOf,"--output",output];
  const run=()=>spawnSync(process.execPath,args,{encoding:"utf8"});const first=run();assert.equal(first.status,0,first.stderr);const second=run();assert.equal(second.status,0,second.stderr);assert.equal(first.stdout,second.stdout)
  const receipt=JSON.parse(first.stdout);assert.equal(fs.statSync(receipt.json).mode&0o777,0o600)
  fs.writeFileSync(receipt.json,"preserve me");assert.equal(run().status,2);assert.equal(fs.readFileSync(receipt.json,"utf8"),"preserve me")
  fs.writeFileSync(input,'{"drafts":[],"drafts":[]}');assert.equal(run().status,2);assert.ok(!run().stderr.includes(input))
 }finally{fs.rmSync(directory,{recursive:true,force:true})}
})

test("older-post opinions do not become new weekly deliveries",()=>{const s=state();s.drafts[0].posted_at="2026-10-10T12:00:00Z";const r=build(s,[opinion(s)]);assert.equal(r.delivery.count,0);assert.equal(r.editorial_feedback.records_in_window,1);assert.equal(r.editorial_feedback.new_weekly_posts_with_opinion,0);assert.equal(r.editorial_feedback.older_posts_with_opinion,1)})
test("equivalent aware clocks normalize to identical report",()=>assert.deepEqual(build(),buildWeeklyReview({state:state(),asOf:"2026-10-18T13:00:00+01:00"})))
test("pure review never uses fetch and never emits recorded failure reasons",()=>{const original=globalThis.fetch;let calls=0;globalThis.fetch=()=>{calls++;throw new Error("network forbidden")};try{const s=state();s.suppressions=[{stage:"pipeline_error",ts:"2026-10-17T10:00:00Z",reasons:["PRIVATE FAILURE BODY"]}];const r=build(s);assert.equal(r.operational_context.last_recorded_failure.stage,"pipeline_error");assert.ok(!JSON.stringify(r).includes("PRIVATE FAILURE BODY"));assert.equal(calls,0)}finally{globalThis.fetch=original}})
test("inconsistent retained money stays unknown",()=>{const s=state();s.llm_usage={"2026-10-18":{bad:{usd:1,calls:true,priced_calls:1,unpriced_calls:0,missing_usage_calls:0,priced_usd:1}}};const r=build(s);assert.equal(r.cost_context.pricing_coverage,"inconsistent");assert.equal(r.cost_context.known_cost_usd,null)})
