#!/usr/bin/env node
// Read bounded local snapshots only; never fetch or mutate live state.
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { parseGistDocument } from "../dashboard/lib/lossless-gist.js"
import { buildWeeklyReview, weeklyReviewMarkdown } from "../dashboard/lib/weekly-review.js"

function readInput(file) {
  const fd=fs.openSync(file,"r")
  try {
    const buffer=Buffer.alloc(8*1024*1024+1)
    let count=0
    while(count<buffer.length){const n=fs.readSync(fd,buffer,count,buffer.length-count,null);if(!n)break;count+=n}
    if(count>=buffer.length)throw new Error("input_limit")
    return parseGistDocument(new TextDecoder("utf-8",{fatal:true}).decode(buffer.subarray(0,count))).value
  } finally {fs.closeSync(fd)}
}
export function main(argv=process.argv.slice(2)) {
  try {
    const args={}
    for(let i=0;i<argv.length;i+=2){const key=argv[i];if(!["--state","--feedback","--as-of","--output","--cost-reconciliation","--corrections"].includes(key)||args[key]||typeof argv[i+1]!=="string"||argv[i+1].startsWith("--"))throw new Error("arguments");args[key]=argv[i+1]}
    if(!args["--state"]||!args["--output"])throw new Error("arguments")
    const state=readInput(args["--state"]),feedback=args["--feedback"]?readInput(args["--feedback"]):null
    if(feedback!==null&&(Object.keys(feedback).length!==1||!Object.hasOwn(feedback,"records")||!Array.isArray(feedback.records)))throw new Error("feedback_input")
    const costReconciliation=args["--cost-reconciliation"]?readInput(args["--cost-reconciliation"]):null
    const correctionReport=args["--corrections"]?readInput(args["--corrections"]):null
    const report=buildWeeklyReview({state,feedbackRecords:feedback?.records??null,asOf:args["--as-of"]||new Date().toISOString(),costReconciliation,correctionReport})
    const directory=path.resolve(args["--output"]),base=`weekly-review-${report.as_of.slice(0,10)}-${report.report_id.slice(0,12)}`
    fs.mkdirSync(directory,{recursive:true,mode:0o700})
    const artifacts=[[path.join(directory,base+".json"),JSON.stringify(report,null,2)+"\n"],[path.join(directory,base+".md"),weeklyReviewMarkdown(report)]]
    // Check all existing files before writing. Never overwrite divergent output.
    for(const [file,content]of artifacts)if(fs.existsSync(file)&&fs.readFileSync(file,"utf8")!==content)throw new Error("output_conflict")
    for(const [file,content]of artifacts){try{fs.writeFileSync(file,content,{flag:"wx",mode:0o600})}catch(error){if(error.code!=="EEXIST"||fs.readFileSync(file,"utf8")!==content)throw error}}
    process.stdout.write(JSON.stringify({report_id:report.report_id,json:artifacts[0][0],markdown:artifacts[1][0],scope:"retained_only",promotion:"HOLD"})+"\n")
    return 0
  } catch {process.stderr.write("Weekly review unavailable: check bounded local inputs, aware clock and output directory. No live action was taken.\n");return 2}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)process.exitCode=main()
