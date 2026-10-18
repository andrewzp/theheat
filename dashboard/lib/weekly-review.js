import { feedbackRecord, feedbackTarget } from "./post-feedback.js"
import { fingerprint, textHash } from "./draft-revisions.js"
import { summarizeUsage } from "./usage-ledger.js"
import { buildProductHealth } from "./product-health.js"
import { reportTimestamp } from "./runtime-report.js"

const DAY = 86400000
const object = value => value && Object.getPrototypeOf(value) === Object.prototype
const fail = () => {throw new Error("weekly_review_input_unavailable")}
function time(value) {const t=reportTimestamp(value); return Number.isFinite(t) ? t : null}
function bounded(value, max) {
  try { if (Buffer.byteLength(JSON.stringify(value)) > max) fail(); fingerprint(value) } catch {fail()}
}
function unique(rows, key) {
  const values = new Map(), conflicts = new Set()
  for (const row of rows) {
    if (values.has(row[key]) && fingerprint(values.get(row[key])) !== fingerprint(row)) conflicts.add(row[key])
    else values.set(row[key], row)
  }
  return {rows:[...values].filter(([id]) => !conflicts.has(id)).map(([,row]) => row),conflicts:conflicts.size,duplicates:rows.length-values.size}
}

export function buildWeeklyReview({state, feedbackRecords = null, asOf}) {
  const end = time(asOf)
  if (!object(state) || !Array.isArray(state.drafts) || state.drafts.length > 1024 || end === null ||
      (feedbackRecords !== null && (!Array.isArray(feedbackRecords) || feedbackRecords.length > 1000))) fail()
  bounded(state,8*1024*1024);if(feedbackRecords!==null)bounded(feedbackRecords,8*1024*1024)
  const start=end-7*DAY, inWindow=t => t !== null && t >= start && t < end
  const issues={receipt_inventory_unavailable:object(state.publish_ledger)?0:1,invalid_draft_rows:0,duplicate_draft_ids:0,conflicting_draft_ids:0,unqualified_receipt_rows:0,
    undated_or_future_receipts:0,ambiguous_tweet_ids:0,invalid_opinions:0,duplicate_opinion_ids:0,conflicting_opinion_ids:0,stale_opinion_targets:0,undated_or_future_opinions:0,opinions_before_post:0}
  const suppliedDrafts=state.drafts.filter(d => {const valid=object(d)&&typeof d.id==="string"&&!!d.id;if(!valid)issues.invalid_draft_rows++;return valid})
  const deduped=unique(suppliedDrafts,"id");issues.duplicate_draft_ids=deduped.duplicates;issues.conflicting_draft_ids=deduped.conflicts
  const allTargets=[]
  for(const draft of deduped.rows){
    if(draft.status!=="posted"&&!draft.tweet_id)continue
    const target=feedbackTarget(draft,state)
    if(!target){issues.unqualified_receipt_rows++;continue}
    if(time(target.posted_at)===null||time(target.posted_at)>=end){issues.undated_or_future_receipts++;continue}
    allTargets.push({target,draft})
  }
  const claims=new Map()
  for(const draft of suppliedDrafts)if(typeof draft.tweet_id==="string"&&/^[0-9]{1,30}$/.test(draft.tweet_id)){
    if(!claims.has(draft.tweet_id))claims.set(draft.tweet_id,new Set());claims.get(draft.tweet_id).add(draft.id)
  }
  issues.ambiguous_tweet_ids=[...claims.values()].filter(ids=>ids.size>1).length
  const targets=allTargets.filter(({target})=>claims.get(target.tweet_id)?.size===1)
  const weekly=targets.filter(({target})=>inWindow(time(target.posted_at)))
  const targetMap=new Map(targets.map(({target})=>[fingerprint(target),target]))
  const opinionRows=(feedbackRecords||[]).filter(row=>object(row)&&typeof row.request_id==="string")
  issues.invalid_opinions=(feedbackRecords||[]).length-opinionRows.length
  const opinions=unique(opinionRows,"request_id");issues.duplicate_opinion_ids=opinions.duplicates;issues.conflicting_opinion_ids=opinions.conflicts
  const validOpinions=[]
  for(const row of opinions.rows){try{validOpinions.push(feedbackRecord(row))}catch{issues.invalid_opinions++}}
  const selected=[]
  for(const row of validOpinions){
    const t=time(row.received_at)
    if(t===null||t>=end){issues.undated_or_future_opinions++;continue}
    if(t<time(row.target.posted_at)){issues.opinions_before_post++;continue}
    if(!targetMap.has(fingerprint(row.target))){issues.stale_opinion_targets++;continue}
    if(inWindow(t))selected.push(row)
  }
  selected.sort((a,b)=>Date.parse(b.received_at)-Date.parse(a.received_at)||b.request_id.localeCompare(a.request_id))
  const latest=new Map();for(const row of selected)if(!latest.has(row.target.tweet_id))latest.set(row.target.tweet_id,row)
  const posts=weekly.map(({target,draft})=>{
    const opinion=latest.get(target.tweet_id)
    return {draft_id_sha256:textHash(target.draft_id),tweet_id:target.tweet_id,posted_at:target.posted_at,
      text_sha256:target.text_sha256,evidence_sha256:target.evidence_sha256,characters:[...target.text].length,
      authorship:draft.manual_override===true?"manual_or_edited":"unverified",
      editorial_opinion:opinion?{request_id:opinion.request_id,received_at:opinion.received_at,punch:opinion.punch,clarity:opinion.clarity,economy:opinion.economy,
        note_present:!!opinion.note.trim(),note_sha256:textHash(opinion.note)}:null}
  }).sort((a,b)=>Date.parse(b.posted_at)-Date.parse(a.posted_at)||a.tweet_id.localeCompare(b.tweet_id))
  const lengths=posts.map(p=>p.characters).sort((a,b)=>a-b),n=lengths.length
  const cost=summarizeUsage(state,{now:end}),health=buildProductHealth(state,{now:end})
  const costKeys=["coverage","pricing_coverage","known_cost_usd","legacy_estimate_usd","recorded_estimate_usd","recorded_calls","priced_calls","unpriced_calls","missing_usage_calls","legacy_calls","inconsistent_rows","excluded_rows"]
  const report={schema_version:1,kind:"weekly_retained_outcome_review",reader_contract:"retained_weekly_v1",as_of:new Date(end).toISOString(),
    window:{start:new Date(start).toISOString(),end:new Date(end).toISOString(),end_exclusive:true,hours:168},
    input_semantic_sha256:{state:fingerprint(state),feedback:feedbackRecords===null?null:fingerprint(feedbackRecords)},
    delivery:{scope:"Exact matching current draft and confirmed ledger receipts in supplied state; not independent public-page verification or complete account history.",
      inventory_status:issues.receipt_inventory_unavailable?"unavailable":
        ["invalid_draft_rows","duplicate_draft_ids","conflicting_draft_ids","unqualified_receipt_rows","undated_or_future_receipts","ambiguous_tweet_ids"].some(k=>issues[k]>0)?"partial":"retained_only",
      complete_account_inventory:false,all_account_post_count:null,count:posts.length,posts},
    copy:{scope:"Descriptive lengths of qualifying retained posts; brevity is not quality or factual correctness.",count:n,min_characters:n?lengths[0]:null,max_characters:n?lengths[n-1]:null,
      median_characters:n?(lengths[Math.floor((n-1)/2)]+lengths[Math.floor(n/2)])/2:null,
      manual_or_edited:posts.filter(p=>p.authorship==="manual_or_edited").length,verified_model_authorship:null,unverified_authorship:posts.filter(p=>p.authorship==="unverified").length},
    editorial_feedback:{status:feedbackRecords===null?"unavailable":"supplied_records_only",records_in_window:feedbackRecords===null?null:selected.length,
      posts_with_latest_opinion:feedbackRecords===null?null:latest.size,
      new_weekly_posts_with_opinion:feedbackRecords===null?null:posts.filter(p=>p.editorial_opinion!==null).length,
      older_posts_with_opinion:feedbackRecords===null?null:latest.size-posts.filter(p=>p.editorial_opinion!==null).length,
      scope:"Opinion timestamps use the review window; opinions on older posts have a separate denominator from new deliveries.",repeated_saves_not_independent_raters:true,
      unblinded:true,independent_human_benchmark:false,preference_result:null},
    cost_context:{...Object.fromEntries(costKeys.map(k=>[k,cost[k]])),period:"month_to_date_daily_buckets_not_weekly_total",month:new Date(end).toISOString().slice(0,7),
      scope:"Retained daily-bucket estimates; intra-day alignment and complete account charging are unknown. Historical prices are not refreshed.",
      weekly_total_usd:null,all_in_total_usd:null,provider_invoice_usd:null,cost_per_post_usd:null,budget_enforced:false},
    operational_context:{scope:"Existing retained projections retain their own windows; not a complete weekly census or health certificate.",
      milestones:Object.fromEntries(Object.entries(health.milestones).map(([k,v])=>[k,{status:v.status,at:v.at,age_hours:v.age_hours}])),
      queue:Object.fromEntries(["status","waiting_count","pending_count","approved_count","unresolved_publish_count","oldest_waiting_at","unknown_age_count"].map(k=>[k,health.queue[k]])),
      writer_retained_status:health.writer.status,last_writer_response_day:health.writer.last_recorded_call_day,
      last_recorded_failure:health.writer.last_failure?{at:health.writer.last_failure.at,stage:health.writer.last_failure.stage}:null,
      writer_access:"unverified",engagement_status:health.metrics.status,engagement_lift:null},
    exclusions:issues,
    decision:{promotion:"HOLD",automatic_changes:false,paid_experiment_performed:false,publication_authorized:false,
      reasons:["No qualified blinded model-copy comparison is supplied.","Unblinded editorial opinions and short manual posts do not establish model improvement.","Global opportunity recall and scientific truth are not measured here.","Weekly all-in cost, provider invoice and comparable post-age engagement remain unavailable."],
      next_step:"Use actual editorial feedback to prepare one evidence-qualified bounded experiment; keep current source, budget, approval and pause controls. Do not reopen closed experiments."}}
  return {...report,report_id:fingerprint(report)}
}

export function weeklyReviewMarkdown(report){
  const show=v=>v===null||v===undefined?"Unknown":String(v)
  return `# TheHeat retained weekly outcome review\n\n${report.window.start} to ${report.window.end} (end exclusive).\n\n`+
    `| Retained outcome | Result |\n| --- | --- |\n| Exact receipt-bound posts | ${report.delivery.count} |\n| Median characters (descriptive only) | ${show(report.copy.median_characters)} |\n| Manual or edited posts | ${report.copy.manual_or_edited} |\n| Verified model authorship | ${show(report.copy.verified_model_authorship)} |\n| Explicit opinions in supplied window | ${show(report.editorial_feedback.records_in_window)} |\n| Feedback availability | ${report.editorial_feedback.status} |\n| Comparable engagement lift | Unknown |\n| Weekly all-in cost and cost per post | Unknown |\n\n`+
    `Cost context is a separate month-to-date retained estimate (${report.cost_context.month}), not a weekly bill. Known priced subtotal: ${show(report.cost_context.known_cost_usd)} USD; unpriced responses: ${show(report.cost_context.unpriced_calls)}. Provider invoice and complete monthly cap are unverified.\n\n`+
    `Promotion: **HOLD**. ${report.decision.reasons.join(" ")}\n\n${report.decision.next_step}\n\n`+
    `Missing telemetry is unknown, not zero. Saved receipts are not independent public-page verification; retained history is incomplete. No raw tweet or note text is reproduced. Report ${report.report_id}.\n`
}
