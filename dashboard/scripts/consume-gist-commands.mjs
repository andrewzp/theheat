#!/usr/bin/env node
// P00c consumer CLI, run only by a job of the `theheat-bot` concurrency group (gist-commands.yml
// `consume`, bot.yml `commands-before`/`commands-after`). Usage:
//   node scripts/consume-gist-commands.mjs --inbox <dir> --report <file>
// The inbox holds one directory `<command_id>-<artifact_id>` per admitted artifact (command.json +
// admission.json), fetched by scripts/gist_command_inbox.py. Steps (ROUTE-CONTRACT-v2 §4–§5):
// consume (one PATCH) → durable sender outbox (persist before/after each dispatch) → acknowledge
// (delete only artifacts a fresh Gist read shows as terminal). Refusals are results, not failures.
// The report, console and job summary carry ids, counts and codes only: never plaintext.
import { appendFileSync, existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import path from "node:path"
import { acknowledgeArtifacts, consumeGistCommands, MAX_COMMANDS_PER_DRAIN, recordSettledRuns, runSenderOutbox, settledRunsFrom } from "../lib/gist-command-consumer.js"

const DIR = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-([0-9]{1,18})$/
const CODE = /^[a-z0-9_]{1,64}$/
function option(name) {
  const index = process.argv.indexOf(name)
  return index > 0 ? process.argv[index + 1] : null
}
const codeOf = error => typeof error?.code === "string" && CODE.test(error.code) ? error.code : "consumer_failed"

const inbox = option("--inbox"), reportPath = option("--report")
if (!inbox || !reportPath) { console.error("usage: consume-gist-commands.mjs --inbox <dir> --report <file>"); process.exit(64) }
const entries = []
// The inbox's manifest names each artifact's producing gist-commands run (the continuation key).
let manifest = {}
try { manifest = JSON.parse(readFileSync(path.join(inbox, "manifest.json"), "utf8")) } catch { manifest = {} }
if (existsSync(inbox)) {
  for (const name of readdirSync(inbox).sort().slice(0, MAX_COMMANDS_PER_DRAIN * 4)) {
    const dir = path.join(inbox, name)
    if (!statSync(dir).isDirectory()) continue
    const match = DIR.exec(name)
    const artifact_id = match ? Number(match[2]) : null
    const origin = manifest[name] && manifest[name].artifact_id === artifact_id ? manifest[name] : {}
    const run_id = Number.isSafeInteger(origin.run_id) ? origin.run_id : null, run_created_at = origin.run_created_at ?? null
    try {
      const raw = readFileSync(path.join(dir, "command.json"), "utf8")
      const admission = JSON.parse(readFileSync(path.join(dir, "admission.json"), "utf8"))
      entries.push({ raw, admission, source: name, artifact_id, run_id, run_created_at })
    } catch { entries.push({ raw: "", admission: null, source: name, artifact_id, run_id, run_created_at }) }
  }
}
// The inbox scan's own report (scripts/gist_command_inbox.py): an incomplete scan is made visible.
let scan = null
try { scan = JSON.parse(readFileSync(path.join(inbox, "scan.json"), "utf8")) } catch { scan = null }
const repo = process.env.GITHUB_REPOSITORY || "andrewzp/theheat"
const token = process.env.GH_DISPATCH_TOKEN
let report
try {
  report = await consumeGistCommands(entries)
} catch (error) {
  writeFileSync(reportPath, JSON.stringify({ status: "failed", code: codeOf(error) }) + "\n")
  console.error(`[gist-consumer] failed: ${codeOf(error)}`)
  process.exit(2)
}
let exit = 0
// Only when the results file holds a non-terminal sender entry (read in the consume step above).
let outbox = { status: "idle", changes: [], dispatches: [] }
if (report.outbox_active > 0) {
  try { outbox = await runSenderOutbox({ token, repo }) } catch (error) { outbox = { status: "failed", code: codeOf(error) }; exit = 3 }
}
if ((outbox.dispatches || []).some(row => row.state !== "dispatched")) exit = 3
let acknowledged = { deleted: [], failed: [] }
if (entries.some(row => row.artifact_id !== null)) {
  try { acknowledged = await acknowledgeArtifacts(entries, { token, repo }) } catch (error) { acknowledged = { status: "failed", code: codeOf(error), deleted: [], failed: [] } }
}
// Inbox continuation (root checkpoint R1): runs whose command artifacts are all acknowledged, and runs
// that completed without one, are recorded settled and never examined again.
let settled = { recorded: 0 }
try {
  const incompleteRuns = new Set(scan?.incomplete_artifact_runs ?? [])
  const examined = entries.filter(entry => !incompleteRuns.has(entry.run_id))
  settled = await recordSettledRuns(settledRunsFrom(examined, acknowledged.deleted, scan?.empty_completed_runs ?? []),
    { discovery: scan?.discovery_cursor })
}
catch (error) { settled = { status: "failed", code: codeOf(error) }; exit = 3 }
// Configuration that leaves commands pending (no/other seal key, legacy writer credential) is visible.
// Every skip leaves a command unconsumed (configuration, capacity): always visible, never silent.
const VISIBLE_SKIPS = ["command_seal_key_missing", "command_seal_key_invalid", "command_seal_key_unknown", "route_writer_credential_legacy",
  "route_legacy_credentials_present", "command_results_capacity", "control_results_capacity", "route_control_key_missing",
  "route_control_key_invalid", "route_control_key_unknown"]
if (report.skipped.some(row => VISIBLE_SKIPS.includes(row.code))) exit = 3
if (!["ok", "idle", "route_not_active"].includes(outbox.status)) exit = 3
if (scan && scan.scan_complete === false) exit = 3
writeFileSync(reportPath, JSON.stringify({ status: "consumed", ...report, outbox, acknowledged, settled, scan }) + "\n")
const line = `[gist-consumer] applied=${report.applied.length} refused=${report.refused.length} duplicates=${report.duplicates.length} reused=${report.reused.length} rejected=${report.rejected.length} invalid=${report.invalid.length} skipped=${report.skipped.length} deferred=${report.deferred} state_patches=${report.state_patches} feedback_patches=${report.feedback_patches} outbox=${outbox.status} dispatches=${(outbox.dispatches || []).length} acknowledged=${acknowledged.deleted.length} scan_complete=${scan ? scan.scan_complete : "unknown"}`
console.log(line)
if (process.env.GITHUB_STEP_SUMMARY) {
  const rows = [...report.applied.map(row => `| ${row.command_id} | applied | |`), ...report.refused.map(row => `| ${row.command_id} | refused | ${row.code} |`),
    ...(outbox.changes || []).map(row => `| intent ${row.publish_intent_id} | outbox ${row.to} | ${row.code ?? ""} |`)]
  try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, `### Gist commands\n\n\`${line}\`\n\n| id | outcome | code |\n|---|---|---|\n${rows.join("\n")}\n`) } catch { /* summary is informational */ }
}
process.exit(exit)
