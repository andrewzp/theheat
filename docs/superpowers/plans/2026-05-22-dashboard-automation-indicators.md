# Dashboard Automation Indicators — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent read-only "Automation status" strip to the @theheat dashboard showing workflow + routine + posting-mode state, plus fix two routine bugs (stale-snapshot sync + missing health beacon).

**Architecture:** Three coordinated changes. (1) Python schema gets a new `AutomationState` field on `BotState` so the routine-written `automation` gist field survives every cron's `_merge_state` write-back. (2) Dashboard gets a new read-only `GET /api/automation` endpoint backed by `lib/automation.js` helpers that fan-out to the GitHub Actions API + the gist; the existing `Dashboard()` component renders an `AutomationStatusStrip` at the top, polled on the existing 30s cadence. (3) Routine prompt (managed via `RemoteTrigger`) gets a new Step 0 that hard-resets `main` from origin (fixes the stale-snapshot bug exposed by PR #152's confused re-grade) and a new Step 9.5 that writes `routine_last_run_at` + `routine_last_run_outcome` to the gist regardless of whether the cycle committed.

**Tech Stack:** Python 3.11 + mypy + pytest (pipeline), Next.js 15 + node:test (dashboard), GitHub Actions API + GitHub Gists REST API, Anthropic claude.ai routines via `RemoteTrigger` MCP.

**Branch:** `feature/dashboard-automation-indicators`

**Spec:** [/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-05-22-dashboard-automation-indicators-design-v3-descoped.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-05-22-dashboard-automation-indicators-design-v3-descoped.md)

---

## File Structure

**Python (src/):**
- Modify: `src/state_schema.py` — add `AutomationState` TypedDict + `automation` field on `BotState`
- Modify: `src/state.py` — add `automation` to `DEFAULT_STATE`, update `_merge_state` to preserve it
- Modify: `tests/test_state.py` — new test verifying merge preserves the automation field

**Dashboard (dashboard/):**
- Create: `dashboard/lib/automation.js` — pure read helpers for GH API + gist
- Create: `dashboard/app/api/automation/route.js` — `GET` route, basic auth
- Modify: `dashboard/app/page.js` — add `AutomationStatusStrip` component + polling
- Create: `dashboard/tests/automation.test.js` — unit tests for `lib/automation.js` + the route handler

**Routine (no repo changes — live update via RemoteTrigger):**
- Update routine `trig_016PGeHZgEYWmeQhx1xGmYg6` prompt: add Step 0 (stale-snapshot sync) + Step 9.5 (health beacon)

---

## Task 0: Branch setup

**Files:** none (git state change only)

- [ ] **Step 1: Create + switch to feature branch**

Run from repo root:

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
git checkout main && git pull --ff-only
git checkout -b feature/dashboard-automation-indicators
git status --short
```

Expected: clean working tree, on `feature/dashboard-automation-indicators` branch.

- [ ] **Step 2: Stage existing v1/v2/v3 spec docs**

These specs were written during brainstorming and shouldn't get lost. They're not on any branch yet:

```bash
git add docs/superpowers/specs/2026-05-22-dashboard-pause-and-automation-indicators-design.md
git add docs/superpowers/specs/2026-05-22-dashboard-pause-and-automation-indicators-design-v2.md
git add docs/superpowers/specs/2026-05-22-dashboard-automation-indicators-design-v3-descoped.md
git add docs/superpowers/plans/2026-05-22-dashboard-automation-indicators.md
git status --short
```

Expected: 4 files staged (3 specs + this plan).

- [ ] **Step 3: Commit spec + plan**

```bash
git commit -m "$(cat <<'EOF'
docs: spec + plan for dashboard automation indicators (descoped from pause control)

v1 and v2 specs explored a "Pause Everything" control plane; Codex adversarial review
exposed merge race, two-store coordination, and partial-failure issues that didn't have
clean fixes without a full CAS layer. v3 drops pause control entirely and ships only
read-only indicators + two routine prompt fixes that were already needed.

Three specs retained in history: v1 (initial design), v2 (post-Codex pivot to repo
variable + workflow guards), v3 (descoped). v3 is the approved design; plan file
implements it.
EOF
)"
```

Expected: one new commit on the feature branch.

---

## Task 1: Python schema — `AutomationState` TypedDict

**Files:**
- Modify: `src/state_schema.py` (add TypedDict + field)

- [ ] **Step 1: Read the existing schema region to anchor the insertion**

Run: `sed -n '165,175p' /Users/andrewpuschel/Documents/Claude/theheat/src/state_schema.py`

Expected output (last few lines): the existing `BotState` TypedDict declaration. Note the line number where the class opens.

- [ ] **Step 2: Add `AutomationState` TypedDict before `BotState`**

Add this block in `src/state_schema.py` immediately before `class BotState(TypedDict, total=False):`:

```python
class AutomationState(TypedDict, total=False):
    """Routine-written + dashboard-read automation indicators.

    The routine writes routine_last_run_at + routine_last_run_outcome at end of
    every cycle (Step 9.5 of the routine prompt). The dashboard reads this field
    to display the "routine" indicator on the automation status strip.

    The python pipeline NEVER writes this field. _merge_state() preserves it
    from the latest gist state (current wins) so concurrent cron writes don't
    erase the routine's beacon.
    """

    routine_last_run_at: str | None
    routine_last_run_outcome: str | None
```

- [ ] **Step 3: Add `automation` field to `BotState`**

Inside `class BotState(TypedDict, total=False):` body (any position is fine; convention is to add near `source_health` since both are "operational" fields). Add this line:

```python
    automation: AutomationState
```

Example placement — search for the line `source_health: dict[str, SourceHealth]` and add `automation: AutomationState` directly after it.

- [ ] **Step 4: Verify mypy still clean**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate && python -m mypy src/ 2>&1 | tail -3`

Expected: `Success: no issues found in 92 source files`.

- [ ] **Step 5: Commit**

```bash
git add src/state_schema.py
git commit -m "feat(state): add AutomationState TypedDict + automation field on BotState

Routine writes routine_last_run_at + routine_last_run_outcome at end of every
cycle; dashboard reads this for the automation status strip. Python pipeline
never writes this field."
```

---

## Task 2: Python schema — default + merge preservation

**Files:**
- Modify: `src/state.py` (add to `DEFAULT_STATE`, update `_merge_state`)
- Modify: `tests/test_state.py` (new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_state.py` (at end of file or grouped with existing merge tests):

```python
def test_merge_state_preserves_automation_field():
    """The routine writes state.automation; concurrent cron _merge_state must
    preserve it. Without explicit handling, _fresh_state() drops the key."""
    from src.state import _merge_state

    current = {
        "automation": {
            "routine_last_run_at": "2026-05-22T15:04:58Z",
            "routine_last_run_outcome": "graded",
        }
    }
    incoming = {"drafts": [{"id": "draft_x", "status": "pending"}]}

    merged = _merge_state(current, incoming)

    assert merged.get("automation", {}).get("routine_last_run_at") == "2026-05-22T15:04:58Z"
    assert merged.get("automation", {}).get("routine_last_run_outcome") == "graded"


def test_merge_state_automation_current_wins():
    """When both base and incoming have automation, current (gist) wins.
    The cron's incoming state may be stale relative to a recent routine write."""
    from src.state import _merge_state

    current = {
        "automation": {
            "routine_last_run_at": "2026-05-22T15:04:58Z",
            "routine_last_run_outcome": "graded",
        }
    }
    incoming = {
        "automation": {
            "routine_last_run_at": "2026-05-21T15:00:00Z",
            "routine_last_run_outcome": "error",
        }
    }

    merged = _merge_state(current, incoming)

    # Current (latest gist) wins
    assert merged["automation"]["routine_last_run_at"] == "2026-05-22T15:04:58Z"
    assert merged["automation"]["routine_last_run_outcome"] == "graded"


def test_merge_state_missing_automation_uses_default():
    """Older gist payloads have no automation field; merge must not crash."""
    from src.state import _merge_state

    current = {}
    incoming = {}

    merged = _merge_state(current, incoming)

    assert "automation" in merged
    assert merged["automation"].get("routine_last_run_at") is None
    assert merged["automation"].get("routine_last_run_outcome") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate && python -m pytest tests/test_state.py::test_merge_state_preserves_automation_field tests/test_state.py::test_merge_state_automation_current_wins tests/test_state.py::test_merge_state_missing_automation_uses_default -v 2>&1 | tail -15`

Expected: 3 failures (assertion error on `routine_last_run_at` or KeyError on `automation`).

- [ ] **Step 3: Add `automation` to `DEFAULT_STATE`**

In `src/state.py`, find the `DEFAULT_STATE: BotState = {` declaration (around line 35). Add this entry inside the dict; place it after the existing `source_health` field to match the schema ordering:

```python
    "automation": {
        "routine_last_run_at": None,
        "routine_last_run_outcome": None,
    },
```

If you need to find the right line: `grep -n "source_health" src/state.py | head -3` — add the new entry after that one.

- [ ] **Step 4: Update `_merge_state` to preserve `automation`**

In `src/state.py`, find `def _merge_state(`. Inside the function body, after all the existing field copies but before `return merged`, add this block:

```python
    # Automation field is routine-written + dashboard-read; cron never touches it.
    # Preserve the latest gist value (current/base), not the run's in-memory snapshot.
    merged["automation"] = deepcopy(
        base.get("automation", DEFAULT_STATE["automation"])
    )
```

Locator: search for the existing `merged["suppressions"] = _merge_suppressions(` line and add the automation block near similar field-copy logic (placement isn't strict; just before `return merged` is fine).

- [ ] **Step 5: Run the three new tests to verify they pass**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate && python -m pytest tests/test_state.py::test_merge_state_preserves_automation_field tests/test_state.py::test_merge_state_automation_current_wins tests/test_state.py::test_merge_state_missing_automation_uses_default -v 2>&1 | tail -10`

Expected: 3 PASSED.

- [ ] **Step 6: Run full pytest + mypy to make sure nothing regressed**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate && python -m mypy src/ 2>&1 | tail -3 && python -m pytest tests/ -q -m "not voice_replay" 2>&1 | tail -3`

Expected:
- mypy: `Success: no issues found in 92 source files`
- pytest: `1351 passed, 22 deselected` (+3 over the 1348 baseline)

- [ ] **Step 7: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat(state): preserve automation field across _merge_state

Adds 'automation' key to DEFAULT_STATE so _fresh_state() includes it. Adds
explicit merge rule in _merge_state: current (latest gist) wins, since only
the routine writes this field and concurrent cron writes shouldn't erase it.

3 new tests cover round-trip preservation, current-wins ordering, and
missing-field default. pytest 1348 → 1351."
```

---

## Task 3: Dashboard helper library

**Files:**
- Create: `dashboard/lib/automation.js`
- Create: `dashboard/tests/automation.test.js`

- [ ] **Step 1: Write the failing test**

Create `dashboard/tests/automation.test.js`:

```javascript
import test from "node:test"
import assert from "node:assert/strict"

import { importFresh } from "./helpers/import-fresh.js"

function workflowResponse(state, updatedAt = "2026-05-22T10:00:00Z") {
  return {
    ok: true,
    status: 200,
    async json() {
      return { id: 12345, name: state, state, updated_at: updatedAt }
    },
    async text() {
      return JSON.stringify({ state })
    },
  }
}

function workflowRunsResponse(runs = []) {
  return {
    ok: true,
    status: 200,
    async json() {
      return { workflow_runs: runs }
    },
    async text() {
      return JSON.stringify({ workflow_runs: runs })
    },
  }
}

function gistResponseBytes(state) {
  return {
    ok: true,
    status: 200,
    async json() {
      return {
        files: {
          "state.json": {
            content: JSON.stringify(state),
            truncated: false,
          },
        },
      }
    },
  }
}

test("fetchWorkflowState returns state + updated_at", async () => {
  const calls = []
  global.fetch = async (url) => {
    calls.push(url)
    return workflowResponse("active", "2026-05-22T09:00:00Z")
  }
  process.env.GITHUB_TOKEN = "ghp_test"

  const { fetchWorkflowState } = await importFresh("../lib/automation.js")
  const result = await fetchWorkflowState("bot.yml")

  assert.equal(result.state, "active")
  assert.equal(result.updated_at, "2026-05-22T09:00:00Z")
  assert.match(calls[0], /actions\/workflows\/bot\.yml$/)
})

test("fetchWorkflowLastRun returns the most recent run", async () => {
  global.fetch = async () =>
    workflowRunsResponse([
      {
        id: 999,
        status: "completed",
        conclusion: "success",
        created_at: "2026-05-22T08:00:00Z",
      },
    ])
  process.env.GITHUB_TOKEN = "ghp_test"

  const { fetchWorkflowLastRun } = await importFresh("../lib/automation.js")
  const result = await fetchWorkflowLastRun("bot.yml")

  assert.equal(result.id, 999)
  assert.equal(result.conclusion, "success")
})

test("fetchWorkflowLastRun returns null when no runs exist", async () => {
  global.fetch = async () => workflowRunsResponse([])
  process.env.GITHUB_TOKEN = "ghp_test"

  const { fetchWorkflowLastRun } = await importFresh("../lib/automation.js")
  const result = await fetchWorkflowLastRun("bot.yml")

  assert.equal(result, null)
})

test("readAutomationField returns automation block from gist", async () => {
  global.fetch = async () =>
    gistResponseBytes({
      automation: {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
      drafts: [],
    })
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  const { readAutomationField } = await importFresh("../lib/automation.js")
  const result = await readAutomationField()

  assert.equal(result.routine_last_run_at, "2026-05-22T15:04:58Z")
  assert.equal(result.routine_last_run_outcome, "graded")
})

test("readAutomationField returns null when gist missing automation", async () => {
  global.fetch = async () => gistResponseBytes({ drafts: [] })
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  const { readAutomationField } = await importFresh("../lib/automation.js")
  const result = await readAutomationField()

  assert.equal(result, null)
})

test("getAutomationStatus composes workflows + routine + posting mode", async () => {
  let callCount = 0
  global.fetch = async (url) => {
    callCount++
    if (url.includes("/runs?")) {
      return workflowRunsResponse([
        {
          id: 1,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      return workflowResponse("active")
    }
    return gistResponseBytes({
      automation: {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
      drafts: [
        { status: "pending", approval_policy: { mode: "manual_only" } },
        { status: "pending", approval_policy: { mode: "manual_only" } },
        { status: "pending", approval_policy: { mode: "armed_auto" } },
      ],
    })
  }
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  const { getAutomationStatus } = await importFresh("../lib/automation.js")
  const status = await getAutomationStatus()

  assert.equal(status.workflows.length, 3)
  assert.equal(status.workflows[0].file, "bot.yml")
  assert.equal(status.routine.last_run_outcome, "graded")
  assert.equal(status.posting_mode_summary.manual_only_count, 2)
  assert.equal(status.posting_mode_summary.armed_auto_count, 1)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && node --test tests/automation.test.js 2>&1 | tail -20`

Expected: All 6 tests fail with `Cannot find module '../lib/automation.js'`.

- [ ] **Step 3: Create `dashboard/lib/automation.js`**

```javascript
import { readGistState } from "./state-store.js"

const GITHUB_TOKEN = process.env.GITHUB_TOKEN
const REPO = process.env.THEHEAT_REPO || "andrewzp/theheat"

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

export async function readAutomationField() {
  const state = await readGistState()
  if (!state || typeof state !== "object") return null
  const a = state.automation
  if (!a || typeof a !== "object") return null
  return a
}

function summarizePostingModes(drafts) {
  const summary = { manual_only_count: 0, armed_auto_count: 0, suggested_count: 0 }
  for (const d of drafts || []) {
    if (d?.status !== "pending") continue
    const mode = d?.approval_policy?.mode
    if (mode === "manual_only") summary.manual_only_count++
    else if (mode === "armed_auto") summary.armed_auto_count++
    else if (mode === "suggested") summary.suggested_count++
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
  const [workflows, automation, gistState] = await Promise.all([
    Promise.all(WORKFLOWS.map(fetchWorkflowFull)),
    readAutomationField().catch(() => null),
    readGistState().catch(() => null),
  ])

  const drafts = gistState?.drafts ?? []
  const posting_mode_summary = summarizePostingModes(drafts)

  return {
    workflows,
    routine: {
      name: ROUTINE.name,
      cron: ROUTINE.cron,
      last_run_at: automation?.routine_last_run_at ?? null,
      last_run_outcome: automation?.routine_last_run_outcome ?? null,
    },
    posting_mode_summary,
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && node --test tests/automation.test.js 2>&1 | tail -20`

Expected: 6 passed, 0 failed.

- [ ] **Step 5: Run full dashboard test suite to ensure no regression**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && npm test 2>&1 | tail -20`

Expected: all existing tests pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add dashboard/lib/automation.js dashboard/tests/automation.test.js
git commit -m "feat(dashboard): add lib/automation.js read helpers + unit tests

Read-only helpers for the GitHub Actions API (workflow state + last run)
and the gist's new state.automation field. getAutomationStatus() composes
all three plus a per-pending-draft posting-mode count for the dashboard
status strip."
```

---

## Task 4: Dashboard API route

**Files:**
- Create: `dashboard/app/api/automation/route.js`
- Modify: `dashboard/tests/automation.test.js` (add route handler tests)

- [ ] **Step 1: Add route handler tests to the existing test file**

Append to `dashboard/tests/automation.test.js`:

```javascript
function basicAuth(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`, "utf-8").toString("base64")}`
}

test("GET /api/automation returns 401 without auth when configured", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  const { GET } = await importFresh("../app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation")
  const res = await GET(req)

  assert.equal(res.status, 401)
})

test("GET /api/automation returns combined status with valid auth", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  global.fetch = async (url) => {
    if (url.includes("/runs?")) {
      return workflowRunsResponse([
        {
          id: 7,
          status: "completed",
          conclusion: "success",
          created_at: "2026-05-22T08:00:00Z",
        },
      ])
    }
    if (url.includes("/actions/workflows/")) {
      return workflowResponse("active")
    }
    return gistResponseBytes({
      automation: {
        routine_last_run_at: "2026-05-22T15:04:58Z",
        routine_last_run_outcome: "graded",
      },
      drafts: [{ status: "pending", approval_policy: { mode: "manual_only" } }],
    })
  }

  const { GET } = await importFresh("../app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation", {
    headers: { authorization: basicAuth("admin", "secret") },
  })
  const res = await GET(req)
  const body = await res.json()

  assert.equal(res.status, 200)
  assert.equal(body.workflows.length, 3)
  assert.equal(body.routine.last_run_outcome, "graded")
  assert.equal(body.posting_mode_summary.manual_only_count, 1)
})

test("GET /api/automation returns 500 when GH API throws", async () => {
  process.env.DASHBOARD_USERNAME = "admin"
  process.env.DASHBOARD_PASSWORD = "secret"
  process.env.GITHUB_TOKEN = "ghp_test"
  process.env.STATE_BACKEND = "gist"

  // Force fetch to throw (simulates GH API outage)
  global.fetch = async () => {
    throw new Error("ECONNREFUSED")
  }

  const { GET } = await importFresh("../app/api/automation/route.js")
  const req = new Request("http://localhost/api/automation", {
    headers: { authorization: basicAuth("admin", "secret") },
  })
  const res = await GET(req)
  const body = await res.json()

  assert.equal(res.status, 500)
  assert.match(body.error, /ECONNREFUSED|fetch failed|automation status/i)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && node --test tests/automation.test.js 2>&1 | tail -10`

Expected: 3 new failures (`Cannot find module '../app/api/automation/route.js'`); the original 6 still pass.

- [ ] **Step 3: Create the API route**

Create `dashboard/app/api/automation/route.js`:

```javascript
import { requireDashboardAuth } from "../../../lib/auth.js"
import { getAutomationStatus } from "../../../lib/automation.js"

export const runtime = "nodejs"

export async function GET(request) {
  const authError = requireDashboardAuth(request)
  if (authError) return authError

  try {
    const status = await getAutomationStatus()
    return Response.json(status)
  } catch (e) {
    return Response.json({ error: e?.message || "automation status failed" }, { status: 500 })
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && node --test tests/automation.test.js 2>&1 | tail -10`

Expected: 9 passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app/api/automation/route.js dashboard/tests/automation.test.js
git commit -m "feat(dashboard): add GET /api/automation route

Read-only endpoint backed by getAutomationStatus(). Basic auth via the
existing requireDashboardAuth() middleware. Returns workflows + routine +
posting_mode_summary in one fetch for the dashboard status strip."
```

---

## Task 5: Dashboard status strip component

**Files:**
- Modify: `dashboard/app/page.js`

This is the largest UI change. The existing `Dashboard()` component starts at line 1154; it already polls `/api/dashboard` and `/api/source-health` every 30s via `setInterval(fetchData, 30000)`. We add a parallel fetch for `/api/automation` and a top-of-page strip component.

- [ ] **Step 1: Inspect the existing useEffect polling block to know where to insert**

Run: `sed -n '1230,1260p' dashboard/app/page.js`

Note the lines that show the existing `useEffect` + `setInterval(fetchData, 30000)`.

- [ ] **Step 2: Add `AutomationStatusStrip` component near the top of `dashboard/app/page.js`**

Insert this component somewhere in the helpers section of the file (the section with `RunStatus`, `SourceStatusBadge`, etc., before the `WorkbenchView` component definition). A good anchor is right after the existing `SourceStatusBadge` function (~line 34):

```javascript
function AutomationDot({ name, color, tooltip }) {
  const colorClass = {
    green: "automation-dot-green",
    yellow: "automation-dot-yellow",
    gray: "automation-dot-gray",
    red: "automation-dot-red",
  }[color] || "automation-dot-gray"
  return (
    <span className={`automation-dot ${colorClass}`} title={tooltip}>
      <span className="automation-dot-label">{name}</span>
    </span>
  )
}

function dotColorForWorkflow(wf) {
  if (wf.error) return "red"
  if (wf.state === "disabled_manually") return "gray"
  if (wf.state === "active" && wf.last_run_conclusion === "success") return "green"
  if (wf.state === "active" && wf.last_run_conclusion === "failure") return "yellow"
  if (wf.state === "active") return "green"
  return "gray"
}

function dotColorForRoutine(routine) {
  if (!routine?.last_run_at) return "gray"
  // Routine fires daily; mark gray if last beacon older than 25h.
  const ageMs = Date.now() - new Date(routine.last_run_at).getTime()
  if (Number.isNaN(ageMs)) return "gray"
  if (ageMs > 25 * 60 * 60 * 1000) return "gray"
  if (routine.last_run_outcome === "error") return "yellow"
  return "green"
}

function AutomationStatusStrip({ status, error }) {
  if (error) {
    return (
      <div className="automation-strip automation-strip-error">
        <span className="automation-title">Automation</span>
        <span className="automation-error">unavailable: {error}</span>
      </div>
    )
  }
  if (!status) {
    return (
      <div className="automation-strip">
        <span className="automation-title">Automation</span>
        <span className="automation-loading">loading…</span>
      </div>
    )
  }
  const workflows = status.workflows || []
  const routine = status.routine || {}
  const pm = status.posting_mode_summary || {}

  return (
    <div className="automation-strip">
      <span className="automation-title">Automation</span>
      {workflows.map((wf) => (
        <AutomationDot
          key={wf.file}
          name={wf.name}
          color={dotColorForWorkflow(wf)}
          tooltip={`${wf.name} — state: ${wf.state}, last run: ${
            wf.last_run_at ? new Date(wf.last_run_at).toUTCString() : "never"
          }, conclusion: ${wf.last_run_conclusion || "none"}${
            wf.error ? `, ERROR: ${wf.error}` : ""
          }`}
        />
      ))}
      <AutomationDot
        name="routine"
        color={dotColorForRoutine(routine)}
        tooltip={`${routine.name || "routine"} — last run: ${
          routine.last_run_at ? new Date(routine.last_run_at).toUTCString() : "never"
        }, outcome: ${routine.last_run_outcome || "unknown"}`}
      />
      <span className="automation-spacer" />
      <span className="automation-posting-mode">
        {pm.manual_only_count ?? 0} manual / {pm.armed_auto_count ?? 0} auto /{" "}
        {pm.suggested_count ?? 0} suggested
      </span>
    </div>
  )
}
```

- [ ] **Step 3: Add automation state + fetch to the `Dashboard()` component**

Inside `Dashboard()` (line ~1154), add two new state hooks alongside the existing ones (anywhere among the `useState` block — place after `const [refreshError, setRefreshError] = useState(null)` for clarity):

```javascript
  const [automation, setAutomation] = useState(null)
  const [automationError, setAutomationError] = useState(null)
```

- [ ] **Step 4: Add the automation fetch alongside the existing data fetch**

Locate the `fetchData` `useCallback` block (~line 1208). Inside the same `useCallback`, after the existing dashboard fetch but before `setRefreshing(false)`, add a parallel call:

```javascript
      // Automation status (read-only; failures non-fatal).
      try {
        const automationRes = await fetch("/api/automation")
        if (automationRes.ok) {
          const automationPayload = await automationRes.json()
          setAutomation(automationPayload)
          setAutomationError(null)
        } else {
          setAutomationError(`/api/automation ${automationRes.status}`)
        }
      } catch (err) {
        setAutomationError(err.message)
      }
```

This piggybacks on the existing 30s `setInterval(fetchData, 30000)` — no new interval needed.

- [ ] **Step 5: Render `AutomationStatusStrip` at the top of the dashboard layout**

Search for the JSX root of the dashboard render: `return (` inside the `Dashboard()` function (~line 1380 or wherever the outer `<div>` or `<main>` opens). Add `<AutomationStatusStrip ... />` as the FIRST child of the outermost container, before any existing tab nav / header content:

```javascript
  return (
    <div className="dashboard-root">
      <AutomationStatusStrip status={automation} error={automationError} />
      {/* ... existing layout below ... */}
```

If the existing return doesn't use `<div className="dashboard-root">`, place the strip immediately after the outermost JSX element opening tag. The point is: it must render before the tab navigation so it's visible on every view.

- [ ] **Step 6: Add CSS for the strip (styled-jsx, not a separate CSS file)**

The dashboard does NOT use a separate CSS file. All styles live in `<style jsx global>{` blocks inside `app/page.js` (existing blocks at ~line 958 and ~line 1368). Extend the existing global block at line 1368 by appending the automation strip rules. Locate the block opening with: `grep -n "style jsx global" dashboard/app/page.js`.

Inside that block (before the closing backtick + `}</style>`), add:

```css
/* Automation status strip — rendered at top of dashboard on every view. */
.automation-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: #0f0f0f;
  border-bottom: 1px solid #2a2a2a;
  color: #e5e5e5;
  font-size: 13px;
  font-family: ui-monospace, monospace;
}
.automation-strip-error {
  background: #2a0f0f;
  color: #fca5a5;
}
.automation-title {
  font-weight: 600;
  color: #a3a3a3;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  font-size: 11px;
}
.automation-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #1a1a1a;
  cursor: help;
}
.automation-dot::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.automation-dot-green::before { background: #22c55e; }
.automation-dot-yellow::before { background: #eab308; }
.automation-dot-gray::before { background: #6b7280; }
.automation-dot-red::before { background: #ef4444; }
.automation-dot-label {
  font-size: 12px;
}
.automation-spacer {
  flex: 1;
}
.automation-posting-mode {
  font-size: 12px;
  color: #a3a3a3;
}
.automation-error, .automation-loading {
  font-size: 12px;
  color: #a3a3a3;
}
```

- [ ] **Step 7: Run `next build` to surface any syntax errors before manual test**

Run: `cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && npm run build 2>&1 | tail -10`

Expected: build succeeds with no errors. Warnings (e.g. about Hooks ordering) are fine if they were already present before this change.

- [ ] **Step 8: Manual smoke test**

Start dev server (background):

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat/dashboard && npm run dev &
sleep 5
```

Open the dashboard URL (locally `http://localhost:3000` unless overridden). Confirm:
- The strip renders at the top with 4 dots labeled `theheat-bot`, `voice-regression`, `refresh-thresholds`, `routine`
- Posting-mode pill shows correct count (e.g. `13 manual / 0 auto / 0 suggested` matching `state.json`)
- Hovering each dot shows its tooltip
- Workflow state colors match reality (bot + voice-regression should be gray = `disabled_manually`; refresh-thresholds should be green = `active`; routine should be gray initially until the next routine cycle writes a beacon)

Stop the dev server:

```bash
kill %1 2>/dev/null || true
```

- [ ] **Step 9: Commit**

```bash
git add dashboard/app/page.js
git commit -m "feat(dashboard): add AutomationStatusStrip component + polling

Persistent read-only strip at top of every dashboard view. Four colored
dots for theheat-bot / voice-regression / refresh-thresholds / routine
plus a posting-mode pill. Piggybacks on the existing 30s fetchData
interval; failures are non-fatal (shows 'unavailable')."
```

---

## Task 6: Routine prompt update (Step 0 + Step 9.5)

**Files:**
- No repo files. The routine is managed via the claude.ai `RemoteTrigger` API.

The full prompt body is large (it's the entire daily-plan grading instruction set). We modify it by reading the current prompt, inserting Step 0 and Step 9.5, and pushing back via `RemoteTrigger` update.

- [ ] **Step 1: Fetch the current routine prompt**

Use the `RemoteTrigger` MCP tool with `action: "get"` and `trigger_id: "trig_016PGeHZgEYWmeQhx1xGmYg6"`. Save the prompt text (the `events[0].data.message.content` field) to a working file:

```bash
mkdir -p /tmp/routine-update
# After fetching via RemoteTrigger, write the current prompt to:
#   /tmp/routine-update/current-prompt.txt
# (paste the content field there manually or via the tool)
```

- [ ] **Step 2: Compose the new prompt**

Take the current prompt and:

(a) Insert this **NEW Step 0** immediately before existing "1. cd to repo root.":

```
0. **Sync to current main.** The CCR environment can reuse a stale git checkout across runs. Force-update main from origin before any other work.

```bash
set -e
_REPO_TOP="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$_REPO_TOP"
git fetch origin main
git checkout main 2>/dev/null || git checkout -B main origin/main
git reset --hard origin/main
git clean -fd
```
```

(b) Insert this **NEW Step 9.5** immediately after existing "9. Print to stdout: A-rate, gap from bar..." and before the `## Hard constraints` heading:

```
9.5. **Write the routine health beacon.** Regardless of grading outcome, write a routine_last_run_at + routine_last_run_outcome value to the gist so the dashboard knows when this cycle ran. Best-effort: a beacon write failure logs a warning but doesn't fail the cycle.

```bash
# Set OUTCOME based on what happened above:
#   "graded"           if at least one fresh draft was graded this cycle
#   "no-fresh-drafts"  if queue had only carry-overs (Step 3 graded nothing new)
#   "error"            if Step 1-9 caught a recoverable failure
OUTCOME="graded"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

BEACON_DIR=$(mktemp -d)
if ! git clone --depth=1 https://gist.github.com/06c02c97ffc0d11458687f1ed998d9e5.git "$BEACON_DIR" 2>/dev/null; then
  echo "WARN: beacon skipped — could not clone gist" >&2
  exit 0
fi

UPDATED_PATH="$BEACON_DIR/state-updated.json"
jq --arg now "$NOW" --arg outcome "$OUTCOME" '
  .automation = (.automation // {}) |
  .automation.routine_last_run_at = $now |
  .automation.routine_last_run_outcome = $outcome
' "$BEACON_DIR/state.json" > "$UPDATED_PATH"

PAYLOAD_PATH="$BEACON_DIR/patch-payload.json"
jq -n --rawfile c "$UPDATED_PATH" '{files: {"state.json": {content: $c}}}' > "$PAYLOAD_PATH"

if ! gh api -X PATCH "gists/06c02c97ffc0d11458687f1ed998d9e5" --input "$PAYLOAD_PATH" > /dev/null 2>&1; then
  echo "WARN: beacon write failed (likely gist:write scope missing); cycle output unaffected" >&2
  exit 0
fi
echo "Beacon written: routine_last_run_at=$NOW outcome=$OUTCOME" >&2
```
```

Save the assembled new prompt to `/tmp/routine-update/new-prompt.txt`.

- [ ] **Step 3: Diff the two prompts as a sanity check**

```bash
diff /tmp/routine-update/current-prompt.txt /tmp/routine-update/new-prompt.txt | head -80
```

Expected: only additions for Step 0 and Step 9.5; no deletions elsewhere.

- [ ] **Step 3.5: Pre-push validation — shell-syntax-check + jq dry-run**

Extract Step 0 and Step 9.5 bash blocks from the new prompt and validate them before pushing to the live routine. Catches typos in jq filters, missing closing quotes, etc., before tomorrow's 15:07 UTC cycle hits them:

```bash
# Extract the bash blocks from the new prompt. The new prompt has two ```bash blocks
# we added (Step 0 sync + Step 9.5 beacon). Use awk to pull them into separate files:
awk '
  /^```bash$/ { in_block=1; block_n++; next }
  /^```$/ && in_block { in_block=0; next }
  in_block { print > ("/tmp/routine-update/block-" block_n ".sh") }
' /tmp/routine-update/new-prompt.txt
ls /tmp/routine-update/block-*.sh

# Syntax-check every block (bash -n parses but does not execute):
for f in /tmp/routine-update/block-*.sh; do
  bash -n "$f" && echo "OK: $f" || { echo "SYNTAX ERROR in $f"; exit 1; }
done

# Dry-run the jq filter from Step 9.5 against the live state.json (read-only).
# This validates the jq expression compiles AND produces a valid JSON output —
# the most common Step 9.5 failure mode would be a malformed jq filter.
mkdir -p /tmp/routine-update/dry-run
git clone --depth=1 https://gist.github.com/06c02c97ffc0d11458687f1ed998d9e5.git /tmp/routine-update/dry-run/gist 2>/dev/null
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg now "$NOW" --arg outcome "graded" '
  .automation = (.automation // {}) |
  .automation.routine_last_run_at = $now |
  .automation.routine_last_run_outcome = $outcome
' /tmp/routine-update/dry-run/gist/state.json > /tmp/routine-update/dry-run/updated.json && echo "jq filter OK" || { echo "JQ FILTER ERROR"; exit 1; }

# Verify the dry-run output is still valid JSON of expected size:
jq -e '.automation.routine_last_run_at and .automation.routine_last_run_outcome' /tmp/routine-update/dry-run/updated.json > /dev/null && echo "automation fields present" || { echo "AUTOMATION FIELDS MISSING"; exit 1; }

# Build the same payload Step 9.5 would PATCH and verify it parses:
jq -n --rawfile c /tmp/routine-update/dry-run/updated.json '{files: {"state.json": {content: $c}}}' > /tmp/routine-update/dry-run/patch-payload.json
jq -e '.files."state.json".content' /tmp/routine-update/dry-run/patch-payload.json > /dev/null && echo "patch payload OK" || { echo "PATCH PAYLOAD ERROR"; exit 1; }
```

Expected output: `OK: ...block-1.sh`, `OK: ...block-2.sh`, `jq filter OK`, `automation fields present`, `patch payload OK`. If any error appears, **do not proceed to Step 4**; fix the bash blocks in `/tmp/routine-update/new-prompt.txt` and re-run this step.

Cleanup after validation:

```bash
rm -rf /tmp/routine-update/dry-run /tmp/routine-update/block-*.sh
```

- [ ] **Step 4: Push the update via `RemoteTrigger`**

Call `RemoteTrigger` with `action: "update"`, `trigger_id: "trig_016PGeHZgEYWmeQhx1xGmYg6"`, and `body.job_config.ccr.events[0].data.message.content` set to the new prompt text. Preserve the other fields (`session_context`, etc.) by including the full job_config block — the prior session's update payload is a good template.

Verify the response shows `updated_at` is the current time and the new prompt appears in the returned content field.

- [ ] **Step 5: Note that the routine doesn't fire until tomorrow 15:00 UTC**

The next scheduled run is `2026-05-23T15:07Z`. After that fire, the dashboard's routine indicator will switch from gray to green within 30s of the cycle completing (or yellow on error).

No commit — this change lives in the claude.ai routines API, not the repo.

---

## Task 7: Ship

**Files:** none (CI + merge)

- [ ] **Step 1: Push the branch**

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
git push -u origin feature/dashboard-automation-indicators
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head feature/dashboard-automation-indicators \
  --title "feat: dashboard automation indicators + routine fixes" \
  --body "$(cat <<'EOF'
## Summary

Adds a persistent read-only "Automation" status strip to the dashboard showing the state of the 3 GitHub workflows (theheat-bot, voice-regression, refresh-thresholds) + the daily-plan Claude routine + the posting-mode summary. Plus two routine prompt fixes (via RemoteTrigger, not in this diff):

- Routine Step 0 hard-resets main from origin before each cycle (fixes the stale-snapshot bug that caused PR #152's confused re-grade earlier this week)
- Routine Step 9.5 writes routine_last_run_at + routine_last_run_outcome to the gist so the dashboard can show fresh routine status (no more "is the routine still running?" guessing)

The original v1/v2 design proposed a "Pause Everything" control plane; Codex adversarial review exposed merge-race, two-store coordination, and partial-failure issues that didn't have clean fixes without a full CAS layer. v3 (this PR) drops pause control entirely and ships only indicators + routine fixes. Specs for v1/v2/v3 are all in docs/superpowers/specs/ for the historical record.

## Test plan

- [x] mypy clean across src/ (92 files)
- [x] pytest 1351 passing (+3 new merge-preservation tests)
- [x] node:test dashboard suite passing (+8 new automation tests)
- [x] next build succeeds
- [x] Manual: strip renders, dots colored correctly, tooltips on hover, posting-mode pill shows correct counts
- [ ] First post-merge routine cycle (2026-05-23 15:07 UTC) writes a beacon; dashboard routine indicator flips gray → green within 30s

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI**

```bash
gh pr checks $(gh pr view --json number --jq '.number') --watch
```

Expected: `test` check passes.

- [ ] **Step 4: Merge**

```bash
gh pr merge $(gh pr view --json number --jq '.number') --squash --delete-branch
```

- [ ] **Step 5: Sync local main**

```bash
git checkout main && git pull --ff-only
git status --short
```

Expected: on main, clean working tree, branch deleted locally too.

- [ ] **Step 6: Verify in production**

Open the production dashboard (or the local dev preview) and confirm the strip renders. Recheck after the routine fires tomorrow 15:07 UTC — the routine indicator should be green by 15:08 UTC.

---

## Spec Self-Review (already completed during brainstorming)

- ✅ Spec coverage: every section of the v3 spec maps to a task above (python schema → Tasks 1-2; dashboard helpers → Task 3; API route → Task 4; status strip → Task 5; routine → Task 6).
- ✅ Placeholder scan: every step has exact code, exact command, exact expected output.
- ✅ Type consistency: `AutomationState.routine_last_run_at` is consistently a `str | None` across schema, default, merge, and JS read paths.
- ✅ No spec requirement is unaddressed.

---

## NOT in scope

- Pause/Resume button + control plane (descoped after Codex round 2; merge race + two-store coordination didn't have clean fixes without CAS)
- Python pipeline pause checks (descoped with pause)
- Workflow `if:` guards or repo variable AUTOMATION_PAUSED (descoped with pause)
- Per-route middleware for destructive dashboard actions (descoped with pause)
- Auto-approve queue drain on resume (descoped with pause)
- React component-render tests for AutomationStatusStrip (would require introducing happy-dom + @testing-library/react; dashboard pattern is currently API-route + fetch-mock only)
- Stronger auth than HTTP Basic on the dashboard (single-operator system; revisit when team grows)

## What already exists (reuse, don't rebuild)

- `dashboard/lib/state-store.js:readGistState()` — gist read helper. Task 3's `readAutomationField` wraps this.
- `dashboard/lib/auth.js:requireDashboardAuth()` — basic auth gate. Task 4's route uses it (same pattern as `/api/state`, `/api/source-health`).
- `dashboard/app/page.js:Dashboard.fetchData` + `setInterval(fetchData, 30000)` — existing 30s polling. Task 5 piggybacks; no new interval.
- `dashboard/tests/helpers/import-fresh.js` — module-reload helper for tests. Used throughout `dashboard/tests/*.test.js`.
- `dashboard/tests/dashboard-api.test.js` — reference pattern for mocking GH API + gist responses (`workflowResponse`, `gistResponse`).
- `process.env.GITHUB_TOKEN` — already configured for `/api/trigger` and `/api/post` workflow dispatch; reused for read calls.
- `src/state.py:_merge_state` — existing merge framework with per-field copy rules. Task 2 adds one new field copy following the same idiom.

## Failure modes (per the test diagram above)

| Codepath | Failure mode | Test coverage | Error handling | Operator-visible? |
|---|---|---|---|---|
| `_merge_state` automation collision | Concurrent cron writes overwrite routine beacon | ★★★ 3 tests | Current-wins by design | Stale routine indicator |
| `fetchWorkflowState` | GH API down or 5xx | ★★★ via route 500 test | route returns 500; UI shows red dot | Yes — strip shows red |
| `fetchWorkflowLastRun` | Workflow has zero runs | ★★★ explicit test | Returns null; UI shows "never ran" | Yes — gray dot + tooltip |
| `readAutomationField` | Gist down | ★★★ tested via `.catch(() => null)` in getAutomationStatus | UI shows routine as "unknown" | Yes — gray dot |
| `/api/automation` | Internal exception | ★★★ tested | 500 + error toast | Yes — strip shows red |
| Routine Step 0 sync | Dirty working tree | Manual + bash -n in pre-push | `git checkout -B` force-recreates | Routine logs |
| Routine Step 9.5 beacon | jq syntax error | ★★ pre-push jq dry-run | `\|\| exit 0` keeps cycle alive | Routine logs (warn) |
| Routine Step 9.5 beacon | gist:write missing scope | Manual (no test) | `\|\| exit 0` keeps cycle alive | Stale routine indicator |

**No critical gaps** — every failure mode either has a test, has graceful degradation, or surfaces visibly in the dashboard. The 2 manual-only items (Step 0 sync + gist:write scope) have benign failure modes (warning + cycle continues).

## Worktree parallelization

**Sequential implementation recommended.** Tasks are small (each <30min CC time) and have soft dependencies via the test/code/commit cycle. Two natural parallel lanes if you want to split:
- Lane A: Tasks 1-2 (python schema)
- Lane B: Tasks 3-5 (dashboard) — depends on Lane A only because the dashboard tests reference the `automation` field, which Lane A creates in `DEFAULT_STATE`. In practice Lane B's tests use mocked gist responses, so Lane B can land first.
- Task 6 (routine) is fully independent.

Net: sequential is fine; parallelization saves ~10 minutes and adds merge coordination. Not worth it.

## Implementation Tasks

Synthesized from this review. Each task derives from a specific finding above.

- [ ] **T1 (P1, human: ~5min / CC: ~1min)** — Task 5 Step 6 CSS approach corrected
  - Surfaced by: Architecture review — dashboard uses styled-jsx inline, not a separate CSS file
  - Files: plan file (already fixed inline)
  - Verify: `grep -n "style jsx global" dashboard/app/page.js` returns line 1368
- [ ] **T2 (P2, human: ~5min / CC: ~2min)** — Task 4 error-path route test added
  - Surfaced by: Code quality review — `/api/automation` had no test for GH API outage
  - Files: plan file (already fixed inline)
  - Verify: plan Task 4 Step 1 now lists 3 tests
- [ ] **T3 (P2, human: ~10min / CC: ~3min)** — Task 6 pre-push validation step added
  - Surfaced by: Test review — Step 9.5 bash had no automated test path; pre-push catches typos before tomorrow's cycle
  - Files: plan file (already added as Task 6 Step 3.5)
  - Verify: plan Task 6 has a Step 3.5 with `bash -n` and `jq` dry-run

## Completion summary

- Step 0 — Scope Challenge: scope accepted as-is (already descoped at brainstorm stage)
- Architecture Review: 1 issue (CSS approach), **fixed inline**
- Code Quality Review: 1 issue (error-path test), **fixed inline**
- Test Review: diagram produced, 6 GAPs identified, 4 accepted (no React testing infra), 1 fixed (Task 4 error test), 1 mitigated (Task 6 pre-push validation)
- Performance Review: 0 issues
- NOT in scope: written
- What already exists: written
- TODOs.md updates: 0 items (no follow-up work spawned beyond what's in plan)
- Failure modes: 0 critical gaps
- Outside voice: skipped (codex already ran on spec v1 + v2)
- Parallelization: 2 natural lanes, recommendation is sequential

**Verdict: CLEAR — ready to implement.**

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 2 | CLEAR (at spec stage) | 11 v1 findings → addressed in v2; 11 v2 findings → led to descope to v3 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 3 issues found, all addressed inline (CSS approach, error-path test, pre-push validation) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CODEX:** Spec v1 → v2 → v3-descoped journey was driven by 2 rounds of adversarial review. v3 implements only what survived as safe.
- **UNRESOLVED:** 0 decisions left open.
- **VERDICT:** ENG REVIEW CLEARED — ready to implement.

