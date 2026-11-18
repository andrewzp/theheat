// Pure, JSX-free status helpers shared by the AutomationStrip component and its
// tests. Kept out of the component file so `node --test` can exercise the
// color/banner logic without a JSX loader.

import { reportTimestamp } from "./runtime-report.js"

export function postingStatePresentation(summary) {
  const unavailable = { status: "unavailable" }
  const fields = ["pending_count", "attention_required_count", "auto_scheduled_count", "manual_approved_count", "unresolved_send_count"]
  if (!summary || summary.schema_version !== 1 || summary.status !== "recorded"
      || !Number.isFinite(reportTimestamp(summary.checked_at))
      || fields.some(key => !Number.isSafeInteger(summary[key]) || summary[key] < 0)) return unavailable
  const total = fields.slice(1).reduce((sum, key) => sum + summary[key], 0)
  if (!Number.isSafeInteger(total) || total !== summary.pending_count) return unavailable
  return { status: "recorded", checked_at: summary.checked_at,
    ...Object.fromEntries(fields.map(key => [key, summary[key]])) }
}

// Run conclusions that mean the workflow is broken. Mirrors
// scripts/workflow_health.py FAILING_CONCLUSIONS — both must agree on what "red"
// means. A failed run renders RED (it used to render yellow, which is how a
// five-day voice-regression outage went unnoticed).
export const FAILING_CONCLUSIONS = new Set(["failure", "timed_out", "startup_failure"])

// A run we can draw a verdict from. Everything else (cancelled, neutral, skipped,
// in-progress) is noise we skip to reach the last real signal. Mirrors
// scripts/workflow_health.py DECISIVE_CONCLUSIONS.
export const DECISIVE_CONCLUSIONS = new Set([...FAILING_CONCLUSIONS, "success"])

// The most recent run with a decisive conclusion. Skips a newer cancelled/
// in-progress run so it cannot mask a real failure (the dashboard masking bug).
export function selectLatestDecisiveRun(runs) {
  const sorted = [...(runs || [])]
    .filter(Boolean)
    .sort((a, b) => (Date.parse(b?.created_at) || 0) - (Date.parse(a?.created_at) || 0))
  for (const run of sorted) {
    if (DECISIVE_CONCLUSIONS.has(run?.conclusion)) return run
  }
  return null
}

const ACTIVE_RUN_STATUSES = new Set(["queued", "in_progress", "waiting", "pending", "requested"])

function validRepository(value) {
  return typeof value === "string" && /^[A-Za-z0-9_][A-Za-z0-9_.-]*\/[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(value)
}

// A bounded metadata view, not proof of collection, process liveness or posting.
// Keep it separate from the last decisive result so activity cannot mask failure.
export function botWorkflowActivity(runs, { repository, branch, now = Date.now() }) {
  const unavailable = { status: "unavailable", window_size: null, runs: [] }
  if (!validRepository(repository) || typeof branch !== "string" || !branch ||
      !Array.isArray(runs) || runs.length > 10 || !Number.isFinite(now)) return unavailable
  const active = []
  const identities = new Set()
  for (const run of runs) {
    if (!run || typeof run !== "object" || Array.isArray(run)) return unavailable
    if (!Number.isSafeInteger(run.id) || run.id <= 0 || identities.has(run.id)) return unavailable
    identities.add(run.id)
    if ((run.head_branch !== undefined && run.head_branch !== branch) || run.event === "pull_request") return unavailable
    if (run.status === "completed") continue
    if (!ACTIVE_RUN_STATUSES.has(run.status) || run.head_branch !== branch ||
        !["schedule", "workflow_dispatch"].includes(run.event) ||
        typeof run.head_sha !== "string" || !/^[a-f0-9]{40}$/.test(run.head_sha) ||
        !Number.isFinite(reportTimestamp(run.created_at)) ||
        reportTimestamp(run.created_at) > now) return unavailable
    active.push({ id: run.id, status: run.status, event: run.event,
      head_branch: run.head_branch, head_sha: run.head_sha, created_at: run.created_at })
  }
  active.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id)
  return { status: active.length ? "reported" : "not_reported", repository, branch,
    window_size: runs.length, runs: active }
}

export function botActivityPresentation(activity) {
  const unavailable = { message: "Bot workflow activity unavailable.", runs: [], checked_at: null }
  if (!activity || !Number.isInteger(activity.window_size) || activity.window_size < 0 ||
      activity.window_size > 10 || !Array.isArray(activity.runs) ||
      activity.runs.length > activity.window_size ||
      !Number.isFinite(reportTimestamp(activity.checked_at))) return unavailable
  // This is the server's bounded observation. A laptop's clock must not hide
  // a valid reported handle; raw future run times are refused on the server.
  const checked = botWorkflowActivity(activity.runs, {
    repository: activity.repository, branch: activity.branch, now: reportTimestamp(activity.checked_at),
  })
  if (checked.status === "unavailable") return unavailable
  if (activity.status === "not_reported" && checked.runs.length === 0) {
    return { message: activity.window_size
      ? `No queued or running bot workflow reported in the latest ${activity.window_size} returned runs.`
      : "No bot workflow runs returned by the latest check.", runs: [], checked_at: activity.checked_at }
  }
  if (activity.status !== "reported" || checked.runs.length === 0) return unavailable
  return { message: "Reported bot workflow activity:", checked_at: activity.checked_at,
    runs: checked.runs.map((run) => ({
    ...run, label: run.status === "in_progress" ? "running" : run.status,
    href: `https://github.com/${checked.repository}/actions/runs/${run.id}`,
  })) }
}

// How long the self-heal routine's heartbeat may age before its dot goes red.
// Matches scripts/workflow_health.py SELFHEAL_MAX_AGE_H.
export const SELFHEAL_MAX_AGE_MS = 26 * 60 * 60 * 1000

// Economics P0.5: on red days the keyless gate writes outcome="pending" and
// the heal agent finalizes it. Pending past the healer's runtime budget means
// the healer died. Matches scripts/workflow_health.py SELFHEAL_PENDING_MAX_AGE_H.
export const SELFHEAL_PENDING_MAX_AGE_MS = 3 * 60 * 60 * 1000

export function isBotWorkflow(wf) {
  return wf?.name === "theheat-bot" && wf?.file === "bot.yml"
}

export function recordedBotLaneStarts(runHistory, now = Date.now()) {
  let alerts = -Infinity
  let dueSender = -Infinity
  for (const run of Array.isArray(runHistory) ? runHistory : []) {
    if (run?.configuration_only === true || run?.collection_paused === true) continue
    const started = reportTimestamp(run?.started_at)
    if (!Number.isFinite(started) || started > now) continue
    if (run.mode === "alerts" || run.mode === "both") alerts = Math.max(alerts, started)
    if (run.mode === "auto_publish_due") dueSender = Math.max(dueSender, started)
  }
  return {
    alerts: Number.isFinite(alerts) ? new Date(alerts).toISOString() : null,
    dueSender: Number.isFinite(dueSender) ? new Date(dueSender).toISOString() : null,
  }
}

export function collectionPauseSummary(status) {
  const pause = status?.collection_pause?.status
  const configured = pause === "configured"
  const known = configured || pause === "not_configured"
  const dashboardPaused = status?.dashboard_generation_pause === true
  return {
    collection: configured
      ? "Collection pause configured; saved source data may be old."
      : known
        ? "Collection pause not configured; current collection is not confirmed."
        : "Collection pause unknown; saved workflow results do not confirm current collection.",
    dashboard: dashboardPaused
      ? "Dashboard generation pause configured."
      : "Dashboard generation pause not configured.",
    mismatch: known && configured !== dashboardPaused,
  }
}

export function dotColorForWorkflow(wf, collectionPause) {
  if (!wf) return "gray"
  if (wf.error) return "red"
  if (wf.state === "disabled_manually") return "gray"
  if (FAILING_CONCLUSIONS.has(wf.last_run_conclusion)) return "red"
  if (isBotWorkflow(wf) && collectionPause?.status === "configured") return "gray"
  if (wf.last_run_conclusion === "success") return "green"
  // No decisive conclusion (cancelled / in-progress / never-run) → gray, NOT
  // green. Painting it green would let a real failure hide behind a newer
  // cancelled run.
  return "gray"
}

// The workflows that should trigger the loud banner: anything whose dot is red
// (a failing conclusion or a fetch error).
export function failingWorkflows(status) {
  const workflows = status?.workflows || []
  return workflows.filter((wf) => dotColorForWorkflow(wf, status?.collection_pause) === "red")
}

// Self-heal routine heartbeat dot. A MISSING beacon is gray (routine may not be
// configured yet — no rollout noise, matching the observer's "missing = quiet"
// rule). A beacon that EXISTS but is stale is RED — the watcher died, and that
// must be loud. A "pending" beacon (gate found red, heal dispatched) is yellow
// while the healer could still be running, RED once stuck past its runtime
// budget — a fresh morning gate write must not mask a dead healer. A fresh
// finalized beacon is green, or yellow if its last outcome errored.
export function dotColorForSelfHeal(beacon, now = Date.now()) {
  const runAt = beacon?.run_at ? Date.parse(beacon.run_at) : NaN
  if (Number.isNaN(runAt)) return "gray"
  if (now - runAt > SELFHEAL_MAX_AGE_MS) return "red"
  if (beacon?.outcome === "pending") {
    return now - runAt > SELFHEAL_PENDING_MAX_AGE_MS ? "red" : "yellow"
  }
  if (beacon?.outcome === "error") return "yellow"
  return "green"
}
