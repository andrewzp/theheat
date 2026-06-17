// Pure, JSX-free status helpers shared by the AutomationStrip component and its
// tests. Kept out of the component file so `node --test` can exercise the
// color/banner logic without a JSX loader.

// Run conclusions that mean the workflow is broken. Mirrors
// scripts/workflow_health.py FAILING_CONCLUSIONS — both must agree on what "red"
// means. A failed run renders RED (it used to render yellow, which is how a
// five-day voice-regression outage went unnoticed).
export const FAILING_CONCLUSIONS = new Set(["failure", "timed_out", "startup_failure"])

// How long the self-heal routine's heartbeat may age before its dot goes red.
// Matches scripts/workflow_health.py SELFHEAL_MAX_AGE_H.
export const SELFHEAL_MAX_AGE_MS = 26 * 60 * 60 * 1000

export function dotColorForWorkflow(wf) {
  if (!wf) return "gray"
  if (wf.error) return "red"
  if (wf.state === "disabled_manually") return "gray"
  if (FAILING_CONCLUSIONS.has(wf.last_run_conclusion)) return "red"
  if (wf.state === "active" && wf.last_run_conclusion === "success") return "green"
  if (wf.state === "active") return "green"
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
// must be loud. A fresh beacon is green, or yellow if its last outcome errored.
export function dotColorForSelfHeal(beacon, now = Date.now()) {
  const runAt = beacon?.run_at ? Date.parse(beacon.run_at) : NaN
  if (Number.isNaN(runAt)) return "gray"
  if (now - runAt > SELFHEAL_MAX_AGE_MS) return "red"
  if (beacon?.outcome === "error") return "yellow"
  return "green"
}
