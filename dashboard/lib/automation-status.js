// Pure, JSX-free status helpers shared by the AutomationStrip component and its
// tests. Kept out of the component file so `node --test` can exercise the
// color/banner logic without a JSX loader.

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

// How long the self-heal routine's heartbeat may age before its dot goes red.
// Matches scripts/workflow_health.py SELFHEAL_MAX_AGE_H.
export const SELFHEAL_MAX_AGE_MS = 26 * 60 * 60 * 1000

// Economics P0.5: on red days the keyless gate writes outcome="pending" and
// the heal agent finalizes it. Pending past the healer's runtime budget means
// the healer died. Matches scripts/workflow_health.py SELFHEAL_PENDING_MAX_AGE_H.
export const SELFHEAL_PENDING_MAX_AGE_MS = 3 * 60 * 60 * 1000

export function dotColorForWorkflow(wf) {
  if (!wf) return "gray"
  if (wf.error) return "red"
  if (wf.state === "disabled_manually") return "gray"
  if (FAILING_CONCLUSIONS.has(wf.last_run_conclusion)) return "red"
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
  return workflows.filter((wf) => dotColorForWorkflow(wf) === "red")
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
