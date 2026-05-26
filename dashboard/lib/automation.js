import { readStateStore } from "./state-store.js"

const DEFAULT_PRODUCTION_BRANCH = "main"
const DEFAULT_BEACON_BRANCH = "beacon-current"
const DEFAULT_BEACON_PATH = "beacon.json"

const WORKFLOWS = [
  { name: "theheat-bot", file: "bot.yml" },
  { name: "voice-regression", file: "voice-regression.yml" },
  { name: "refresh-thresholds", file: "refresh-thresholds.yml" },
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

function beaconBranch() {
  return process.env.THEHEAT_BEACON_BRANCH || DEFAULT_BEACON_BRANCH
}

function beaconPath() {
  return process.env.THEHEAT_BEACON_PATH || DEFAULT_BEACON_PATH
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
  const params = new URLSearchParams({
    branch: productionBranch(),
    per_page: "1",
  })
  const url = `https://api.github.com/repos/${repo()}/actions/workflows/${file}/runs?${params.toString()}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (!res.ok) {
    throw new Error(`fetchWorkflowLastRun(${file}) failed: ${res.status}`)
  }
  const data = await res.json()
  const runs = data.workflow_runs || []
  if (runs.length === 0) return null
  const r = runs[0]
  return {
    id: r.id,
    status: r.status,
    conclusion: r.conclusion,
    created_at: r.created_at,
  }
}

export async function readRoutineBeacon() {
  // Reads beacon.json from a dedicated `beacon-current` branch in the repo.
  // The routine writes this every cycle in Step 9.5 of its prompt via the
  // Contents API, which uses `repo` scope (already held by the routine's
  // stored token). The earlier gist-based path required `gist:write` scope
  // that the CCR environment's token didn't have, so beacon writes silently
  // failed and the dashboard's routine dot stayed gray. Moving to a repo
  // branch eliminates the scope-mismatch problem entirely.
  //
  // 404 is treated as "no beacon yet" (gray dot) — same as the prior empty-
  // gist-file behavior. Non-404 non-OK throws so callers can surface the
  // failure as an error state.
  if (!process.env.GITHUB_TOKEN) {
    return null
  }
  const url = `https://api.github.com/repos/${repo()}/contents/${beaconPath()}?ref=${beaconBranch()}`
  const res = await fetch(url, {
    headers: { ...ghHeaders(), Accept: "application/vnd.github.v3.raw" },
  })
  if (res.status === 404) return null
  if (!res.ok) {
    throw new Error(`readRoutineBeacon: contents read failed: ${res.status}`)
  }
  const content = await res.text()
  if (!content) return null
  try {
    return JSON.parse(content)
  } catch {
    return null
  }
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
  const [workflows, beacon, postingMode] = await Promise.all([
    Promise.all(WORKFLOWS.map(fetchWorkflowFull)),
    readRoutineBeacon().catch(() => null),
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
    posting_mode_summary: postingMode.posting_mode_summary,
    posting_mode_error: postingMode.posting_mode_error,
  }
}
