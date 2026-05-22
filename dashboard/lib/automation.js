import { readStateStore } from "./state-store.js"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = process.env.THEHEAT_REPO || "andrewzp/theheat"
const GIST_ID = process.env.GIST_ID || ""

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
  return {
    Authorization: `token ${GITHUB_TOKEN}`,
    Accept: "application/vnd.github.v3+json",
  }
}

export async function fetchWorkflowState(file) {
  if (!GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN not configured")
  }
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${file}`
  const res = await fetch(url, { headers: ghHeaders() })
  if (!res.ok) {
    throw new Error(`fetchWorkflowState(${file}) failed: ${res.status}`)
  }
  const data = await res.json()
  return { state: data.state, updated_at: data.updated_at }
}

export async function fetchWorkflowLastRun(file) {
  if (!GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN not configured")
  }
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${file}/runs?per_page=1`
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
  if (!GITHUB_TOKEN || !GIST_ID) {
    return null
  }
  const url = `https://api.github.com/gists/${GIST_ID}`
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

export async function getAutomationStatus() {
  const [workflows, beacon, stateRecord] = await Promise.all([
    Promise.all(WORKFLOWS.map(fetchWorkflowFull)),
    readRoutineBeacon().catch(() => null),
    readStateStore().catch(() => null),
  ])

  const drafts = stateRecord?.state?.drafts ?? stateRecord?.drafts ?? []
  const posting_mode_summary = summarizePostingModes(drafts)

  return {
    workflows,
    routine: {
      name: ROUTINE.name,
      cron: ROUTINE.cron,
      last_run_at: beacon?.routine_last_run_at ?? null,
      last_run_outcome: beacon?.routine_last_run_outcome ?? null,
    },
    posting_mode_summary,
  }
}
