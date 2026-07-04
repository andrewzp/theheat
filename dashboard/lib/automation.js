import { readStateStore } from "./state-store.js"
import { selectLatestDecisiveRun } from "./automation-status.js"

const DEFAULT_PRODUCTION_BRANCH = "main"
const ROUTINE_BEACON_VARIABLE = "ROUTINE_BEACON"
const SELFHEAL_BEACON_VARIABLE = "SELFHEAL_BEACON"

// Kept in lockstep with scripts/workflow_health.py MONITORED_WORKFLOWS — both
// monitor the same five scheduled workflows.
const WORKFLOWS = [
  { name: "theheat-bot", file: "bot.yml" },
  { name: "voice-regression", file: "voice-regression.yml" },
  { name: "refresh-thresholds", file: "refresh-thresholds.yml" },
  { name: "source-health-sentinel", file: "source-health-sentinel.yml" },
  { name: "time-travel-canary", file: "time-travel-canary.yml" },
]

const ROUTINE = {
  name: "TheHeat daily plan refinement (15:00 UTC)",
  cron: "0 15 * * *",
}

function ghHeaders() {
  const githubToken = process.env.GITHUB_TOKEN || ""
  return {
    ...(githubToken ? { Authorization: `token ${githubToken}` } : {}),
    Accept: "application/vnd.github.v3+json",
  }
}

function repo() {
  return process.env.THEHEAT_REPO || "andrewzp/theheat"
}

function productionBranch() {
  return process.env.THEHEAT_AUTOMATION_BRANCH || DEFAULT_PRODUCTION_BRANCH
}

export async function fetchWorkflowState(file) {
  if (!process.env.GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN not configured")
  }
  const url = `https://api.github.com/repos/${repo()}/actions/workflows/${file}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (!res.ok) {
    throw new Error(`fetchWorkflowState(${file}) failed: ${res.status}`)
  }
  const data = await res.json()
  return { state: data.state, updated_at: data.updated_at }
}

export async function fetchWorkflowLastRun(file) {
  if (!process.env.GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN not configured")
  }
  // Fetch a small window (not per_page=1) and pick the latest DECISIVE run, so a
  // newer cancelled/in-progress run can't mask a real failure — mirrors the
  // Python observer's select_latest_decisive_run.
  const params = new URLSearchParams({
    branch: productionBranch(),
    per_page: "10",
    exclude_pull_requests: "true",
  })
  const url = `https://api.github.com/repos/${repo()}/actions/workflows/${file}/runs?${params.toString()}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (!res.ok) {
    throw new Error(`fetchWorkflowLastRun(${file}) failed: ${res.status}`)
  }
  const data = await res.json()
  const runs = data.workflow_runs || []
  if (runs.length === 0) return null
  const decisive = selectLatestDecisiveRun(runs)
  const r = decisive || runs[0]
  return {
    id: r.id,
    status: r.status,
    // null when no decisive run in the window → dot renders gray, not green.
    conclusion: decisive ? r.conclusion : null,
    created_at: r.created_at,
  }
}

async function readBeaconVariable(name, label) {
  if (!process.env.GITHUB_TOKEN) return null
  const url = `https://api.github.com/repos/${repo()}/actions/variables/${name}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (res.status === 404) return null
  if (!res.ok) {
    throw new Error(`${label}: variable read failed: ${res.status}`)
  }
  const { value } = await res.json()
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

export async function readRoutineBeacon() {
  // Reads the ROUTINE_BEACON repository variable. The routine writes it
  // each cycle via `gh variable set` in Step 9.5 — uses the routine's
  // existing `repo` scope, sidestepping the gist:write scope mismatch
  // that broke the prior gist-based beacon.
  return readBeaconVariable(ROUTINE_BEACON_VARIABLE, "readRoutineBeacon")
}

export async function readSelfHealBeacon() {
  // Reads the SELFHEAL_BEACON repository variable, written by the daily
  // workflow-self-heal routine at the end of each run. A 404 (never set) is a
  // null beacon, not an error — the dashboard renders it gray, matching the
  // observer's "missing beacon = quiet" rule.
  return readBeaconVariable(SELFHEAL_BEACON_VARIABLE, "readSelfHealBeacon")
}

function summarizePostingModes(drafts) {
  const summary = { manual_only_count: 0, armed_auto_count: 0, suggested_count: 0 }
  for (const d of drafts || []) {
    if (d?.status !== "pending") continue
    const mode = d?.approval_policy?.mode
    if (mode === "manual_only") summary.manual_only_count++
    else if (mode === "armed_auto") summary.armed_auto_count++
    else if (mode === "suggested_auto") summary.suggested_count++
  }
  return summary
}

async function fetchWorkflowFull(spec) {
  let workflowState = null
  let lastRun = null
  let error = null
  try {
    workflowState = await fetchWorkflowState(spec.file)
  } catch (e) {
    error = e.message
  }
  try {
    lastRun = await fetchWorkflowLastRun(spec.file)
  } catch (e) {
    error = error || e.message
  }
  return {
    name: spec.name,
    file: spec.file,
    state: workflowState?.state ?? "unknown",
    last_run_at: lastRun?.created_at ?? null,
    last_run_conclusion: lastRun?.conclusion ?? null,
    error,
  }
}

async function readPostingModeSummary() {
  try {
    const stateRecord = await readStateStore()
    const drafts = stateRecord?.state?.drafts ?? stateRecord?.drafts ?? []
    return {
      posting_mode_summary: summarizePostingModes(drafts),
      posting_mode_error: null,
    }
  } catch (e) {
    return {
      posting_mode_summary: null,
      posting_mode_error: e?.message || String(e),
    }
  }
}

export async function getAutomationStatus() {
  const [workflows, beacon, selfHealBeacon, postingMode] = await Promise.all([
    Promise.all(WORKFLOWS.map(fetchWorkflowFull)),
    readRoutineBeacon().catch(() => null),
    readSelfHealBeacon().catch(() => null),
    readPostingModeSummary(),
  ])

  return {
    workflows,
    routine: {
      name: ROUTINE.name,
      cron: ROUTINE.cron,
      last_run_at: beacon?.routine_last_run_at ?? null,
      last_run_outcome: beacon?.routine_last_run_outcome ?? null,
    },
    self_heal: {
      // Written by the daily workflow-self-heal routine. run_at/outcome mirror
      // the SELFHEAL_BEACON shape the routine writes.
      last_run_at: selfHealBeacon?.run_at ?? null,
      last_run_outcome: selfHealBeacon?.outcome ?? null,
      failing: selfHealBeacon?.failing ?? null,
      fixed: selfHealBeacon?.fixed ?? null,
    },
    posting_mode_summary: postingMode.posting_mode_summary,
    posting_mode_error: postingMode.posting_mode_error,
  }
}
