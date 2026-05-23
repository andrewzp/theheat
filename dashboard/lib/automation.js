import { readStateStore } from "./state-store.js"

const DEFAULT_PRODUCTION_BRANCH = "main"

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

function gistId() {
  return process.env.GIST_ID || ""
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
  // Reads routine_beacon.json from the gist (separate file from state.json).
  // The routine writes this every cycle in Step 9.5 of its prompt. ~150 bytes
  // per write, so the gist API's 1MB truncation never applies — we don't need
  // the git-clone path the routine itself uses for state.json reads.
  //
  // Living in a separate file (not state.json) eliminates the lost-update race
  // where a routine PATCH would overwrite a concurrent python cron write.
  if (!process.env.GITHUB_TOKEN || !gistId()) {
    return null
  }
  const url = `https://api.github.com/gists/${gistId()}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (!res.ok) {
    throw new Error(`readRoutineBeacon: gist read failed: ${res.status}`)
  }
  const data = await res.json()
  const content = data.files?.["routine_beacon.json"]?.content
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
