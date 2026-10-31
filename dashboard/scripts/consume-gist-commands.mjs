#!/usr/bin/env node
// P00c consumer CLI, run only by a job of the `theheat-bot` concurrency group (gist-commands.yml
// `consume`, bot.yml `commands-before`/`commands-after`). Usage:
//   node scripts/consume-gist-commands.mjs --inbox <dir> --report <file>
// The inbox holds one directory per admitted artifact (command.json + admission.json), fetched by
// scripts/gist_command_inbox.py. Refusals are results, not failures; a read/PATCH failure or a
// failed follow-up dispatch exits non-zero so the run is visibly red (nothing is synthesized).
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import path from "node:path"
import { consumeGistCommands, dispatchFollowups, MAX_COMMANDS_PER_DRAIN } from "../lib/gist-command-consumer.js"

function option(name) {
  const index = process.argv.indexOf(name)
  return index > 0 ? process.argv[index + 1] : null
}

const inbox = option("--inbox"), reportPath = option("--report")
if (!inbox || !reportPath) { console.error("usage: consume-gist-commands.mjs --inbox <dir> --report <file>"); process.exit(64) }
const entries = []
if (existsSync(inbox)) {
  for (const name of readdirSync(inbox).sort().slice(0, MAX_COMMANDS_PER_DRAIN * 4)) {
    const dir = path.join(inbox, name)
    if (!statSync(dir).isDirectory()) continue
    try {
      const raw = readFileSync(path.join(dir, "command.json"), "utf8")
      const admission = JSON.parse(readFileSync(path.join(dir, "admission.json"), "utf8"))
      entries.push({ raw, admission, source: name })
    } catch { entries.push({ raw: "", admission: null, source: name }) }
  }
}
let report
try {
  report = await consumeGistCommands(entries)
} catch (error) {
  writeFileSync(reportPath, JSON.stringify({ status: "failed", code: typeof error?.code === "string" ? error.code : "consumer_failed" }) + "\n")
  console.error(`[gist-consumer] failed: ${typeof error?.code === "string" ? error.code : error?.name || "error"}`)
  process.exit(2)
}
let exit = 0
if (report.followups.length) {
  report.dispatches = await dispatchFollowups(report.followups, { token: process.env.GH_DISPATCH_TOKEN,
    repo: process.env.GITHUB_REPOSITORY || "andrewzp/theheat" })
  if (report.dispatches.some(row => row.status !== "dispatched")) exit = 3
}
// The report names ids and codes only; draft text stays out of logs and artifacts.
const summary = { ...report, followups: report.followups.map(({ command_id, draft_id, publish_intent_id }) => ({ command_id, draft_id, publish_intent_id })) }
writeFileSync(reportPath, JSON.stringify({ status: "consumed", ...summary }) + "\n")
console.log(`[gist-consumer] applied=${report.applied.length} refused=${report.refused.length} duplicates=${report.duplicates.length} reused=${report.reused.length} invalid=${report.invalid.length} state_patches=${report.state_patches} feedback_patches=${report.feedback_patches}`)
process.exit(exit)
