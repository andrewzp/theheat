#!/usr/bin/env node
// Bounded explicit local snapshots -> the EXISTING weekly/outcome readers, unchanged.
// Reads only the two named files; never fetches, writes, or follows an input path.
// stdout is one JSON document with no raw post text; errors are a fixed message.
//   node scripts/private_review_inputs.mjs --state FILE [--feedback FILE] --as-of ISO
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { parseGistDocument } from "../dashboard/lib/lossless-gist.js"
import { buildWeeklyReview } from "../dashboard/lib/weekly-review.js"
import { postOutcomes } from "../dashboard/lib/post-outcomes.js"

const LIMIT = 8 * 1024 * 1024
const OUTPUT_LIMIT = 16 * 1024 * 1024
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : null
const id = value => typeof value === "string" && /^[A-Za-z0-9_.:-]{1,200}$/.test(value) ? value : null
const oneOf = (value, choices) => choices.includes(value) ? value : null
const identity = value => value && Number.isSafeInteger(value.content_revision) && value.content_revision >= 1
  && sha(value.text_sha256) && sha(value.evidence_sha256)
  ? { content_revision: value.content_revision, text_sha256: value.text_sha256, evidence_sha256: value.evidence_sha256 } : null

// The retained reader intentionally keeps malformed passive evidence. Never send
// those raw variants (or unavailable-record raw_data) to the default stdout.
function writerProjection(context) {
  const status = oneOf(context?.status, ["recorded", "unknown", "conflict"]) ?? "unknown"
  const variants = (context?.variants ?? []).map(row => ({ sha256: sha(row.sha256),
    status: oneOf(row.status, ["recorded", "unknown", "conflict"]) ?? "unknown" }))
  const payload = status === "recorded" && context.variants?.length === 1 ? context.variants[0].payload : null
  const writers = payload?.writer_observations ? Object.values(payload.writer_observations) : []
  const writer = writers.length === 1 ? writers[0] : null
  return { status, sha256: sha(context?.sha256), variants, actor_status: "unknown",
    text_comparison: oneOf(context?.text_comparison, ["matches", "differs"]),
    retained_different_text: typeof context?.retained_different_text === "boolean" ? context.retained_different_text : null,
    history_scope: oneOf(context?.history_scope, ["retained_incomplete"]),
    history_unavailable: typeof context?.history_unavailable === "boolean" ? context.history_unavailable : null,
    source_relation: oneOf(context?.source_relation, ["matches", "differs"]),
    writer: writer ? { event_id: id(writer.event_id), text_sha256: sha(writer.text_sha256),
      bundle_sha256: sha(writer.bundle_sha256), original_identity: identity(writer.original_identity) } : null,
    publication: payload ? { event_id: id(payload.event_id), intent_id: id(payload.intent_id),
      identity: identity(payload.identity), source_bundle_sha256: sha(payload.source_bundle_sha256) } : null }
}

function postProjection(post, weekly) {
  const source = post.publication_context?.source
  const authored = weekly.delivery.posts.find(row => row.tweet_id === post.tweet_id)
  return { tweet_id: post.tweet_id, revision_status: post.revision_status,
    published_text_sha256: post.published_text_sha256, text_available: post.text !== null,
    publication_context: { status: post.publication_context.status, type: id(post.publication_context.type),
      source: source ? { event_id: id(source.event_id), signal_kind: id(source.signal_kind),
        bundle_sha256: sha(source.bundle_sha256) } : null },
    writer_context: writerProjection(post.writer_context), authorship: authored?.authorship ?? null,
    qualified_weekly_receipt: !!authored, history_status: post.history_status,
    observations: post.observations.map(row => ({ id: row.id, kind: row.kind, association: row.association,
      collected_at: row.collected_at, post_age_seconds: row.post_age_seconds, age_status: row.age_status,
      counts: row.counts, conflict: row.conflict,
      ...(Object.hasOwn(row, "writer_context_status") ? { writer_context_status: row.writer_context_status,
        publication_context_sha256: row.publication_context_sha256 } : {}) })) }
}

function readBounded(file) {
  if (!path.isAbsolute(file) || fs.realpathSync(file) !== file) throw new Error("input_path")
  const stat = fs.lstatSync(file)
  if (!stat.isFile() || (stat.mode & 0o777) !== 0o600 || stat.uid !== process.getuid()) throw new Error("input_mode")
  const parent = fs.lstatSync(path.dirname(file))
  if (!parent.isDirectory() || (parent.mode & 0o777) !== 0o700 || parent.uid !== process.getuid()) throw new Error("input_mode")
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW)
  try {
    const opened = fs.fstatSync(fd)
    if (!opened.isFile() || opened.uid !== stat.uid || opened.dev !== stat.dev || opened.ino !== stat.ino ||
        (opened.mode & 0o777) !== 0o600 || opened.size > LIMIT) throw new Error("input_mode")
    const buffer = Buffer.alloc(LIMIT + 1)
    let count = 0
    while (count < buffer.length) {
      const n = fs.readSync(fd, buffer, count, buffer.length - count, null)
      if (!n) break
      count += n
    }
    if (count > LIMIT) throw new Error("input_limit")
    return parseGistDocument(new TextDecoder("utf-8", { fatal: true }).decode(buffer.subarray(0, count))).value
  } finally { fs.closeSync(fd) }
}

export function main(argv = process.argv.slice(2)) {
  try {
    const args = {}
    for (let i = 0; i < argv.length; i += 2) {
      const key = argv[i]
      if (!["--state", "--feedback", "--as-of"].includes(key) || args[key] || typeof argv[i + 1] !== "string" ||
          argv[i + 1].startsWith("--")) throw new Error("arguments")
      args[key] = argv[i + 1]
    }
    if (!args["--state"] || !args["--as-of"]) throw new Error("arguments")
    const state = readBounded(args["--state"])
    const feedback = args["--feedback"] ? readBounded(args["--feedback"]) : null
    if (feedback !== null && (Object.keys(feedback).length !== 1 || !Array.isArray(feedback.records))) throw new Error("feedback_input")
    const weekly = buildWeeklyReview({ state, feedbackRecords: feedback?.records ?? null, asOf: args["--as-of"] })
    const outcomes = postOutcomes(state, { now: Date.parse(weekly.as_of) })
    const posts = outcomes.posts.map(post => postProjection(post, weekly))
    const output = JSON.stringify({
      schema: "theheat.private-review-inputs/v1", as_of: weekly.as_of,
      readers: { weekly: "dashboard/lib/weekly-review.js#buildWeeklyReview", outcomes: "dashboard/lib/post-outcomes.js#postOutcomes" },
      feedback_supplied: feedback !== null, weekly, outcomes: { status: outcomes.status, posts },
    }) + "\n"
    if (Buffer.byteLength(output) > OUTPUT_LIMIT) throw new Error("output_limit")
    process.stdout.write(output)
    return 0
  } catch {
    process.stderr.write("Private review inputs unavailable: check explicit owner-only files and an aware clock. No live action was taken.\n")
    return 2
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) process.exitCode = main()
