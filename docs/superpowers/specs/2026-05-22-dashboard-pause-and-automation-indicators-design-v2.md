# Dashboard "Pause Everything" + Automation Indicators — Design v2

**Date:** 2026-05-22
**Status:** Draft — supersedes v1 after Codex adversarial review revealed 11 findings
**Diff vs v1:** Architecture pivot from "disable workflows via GH API" to "repo variable + workflow `if:` guards + python sentinel check + dashboard middleware". Eight P1 findings addressed.

## Goal (unchanged from v1)

A single dashboard control that pauses every unattended automation in the theheat system, plus persistent indicators showing the state of each. Replaces the current "Andrew remembers to run `gh workflow disable theheat-bot && gh workflow disable voice-regression` from the terminal" pattern.

## What changed since v1

Codex's adversarial review surfaced eight P1 issues with v1's "disable-via-GH-API + gist sentinel for routine" approach:

| v1 problem | v2 fix |
|---|---|
| `_merge_state()` would silently drop the `automation` gist field on every cron write | Add `automation` to `BotState` + `DEFAULT_STATE` + `_merge_state` copy block |
| Bot workflow doesn't read the sentinel; partial pause failure leaves bot firing | Python pipeline checks pause state at every entry point + workflow `if:` guard |
| Resume blindly re-enables workflows; loses pre-pause baseline | No longer applicable — we never disable workflows (use repo variable instead) |
| `pathlib.Path("$GIST_DIR/state.json")` literal in Python — won't expand | Move the sentinel check to bash before the Python block |
| `process_due_drafts()` posts in-flight even after pause | Add per-iteration pause check inside the posting loop |
| Resume drains auto-approve backlog | On resume, push every pending draft's `auto_approve_at` forward by the original delay |
| Other dashboard destructive routes don't check sentinel | Add a thin auth-style middleware to short-circuit when paused |
| Disabling `bot.yml` also disabled PR test triggers | Don't disable workflows; use job-level `if:` guard tied to repo variable |
| Step 0 `git checkout main` brittleness under `set -e` | Use `git fetch + git checkout -B main origin/main` (force re-create) |
| `daily-plan-current` last-commit-time is weak proxy for routine health | Routine writes `state.automation.routine_last_run_at` every cycle |

## What "everything" covers

Four automations, paused by three coordinated mechanisms (belt + suspenders):

| Automation | Cadence | Layer 1 (brake) | Layer 2 (defense) |
|---|---|---|---|
| `theheat-bot` workflow | 6×/day cron + PR + dispatch | Job-level `if: github.event_name != 'schedule' \|\| vars.AUTOMATION_PAUSED != '1'` skips scheduled runs but keeps PR + dispatch alive | Python pipeline checks `state.automation.paused` at top of each entry point |
| `voice-regression` workflow | nightly + PR label | Same `if:` guard pattern (skip schedule, keep PR label) | n/a (workflow runs pytest, no LLM) |
| `refresh-thresholds` workflow | weekly cron | Same `if:` guard pattern | Python module checks pause sentinel before recalibrating |
| Daily-plan Claude routine | daily 15:00 UTC | Routine checks `state.automation.paused` at new Step 1.5 | (only one layer — routine is the only enforcement point) |

## Source of truth

Two coordinated stores, each authoritative for its own concern:

- **GitHub repo variable `AUTOMATION_PAUSED`** — `"1"` or unset. Read by workflow `if:` guards. Written by dashboard via `PATCH /repos/{repo}/actions/variables/AUTOMATION_PAUSED`. Cheap to read inside workflow YAML; doesn't need a network call from python.
- **Gist `state.automation`** — the operator-facing record (who paused, when, why) and the routine + python sentinel. Source of truth for "what should the dashboard show". Written by dashboard on pause/resume; read by routine, python pipeline, and dashboard.

**Why two stores instead of one:** workflow YAML can read repo variables natively (no python boot); the gist sentinel survives across all the other code paths and provides the audit trail. They MUST stay consistent — the dashboard writes both atomically (best-effort; if one fails, the dashboard surfaces a partial-failure warning).

## Data model

New top-level field on the gist's `state.json`:

```json
{
  "automation": {
    "paused": false,
    "paused_at": null,
    "paused_by": null,
    "paused_reason": null,
    "routine_last_run_at": null,
    "routine_last_run_outcome": null
  }
}
```

When pausing: set `paused: true` + the audit fields. When resuming: set `paused: false`, clear audit fields (preserve `routine_last_run_*` — those are the routine's own writes).

**`routine_last_run_at` + `routine_last_run_outcome`** are written by the routine at the END of every cycle (whether it graded or paused-skipped). Outcomes: `"graded"`, `"paused-skip"`, `"no-fresh-drafts"`, `"error"`.

**Missing-field semantics:** if `automation` is absent (older gist state from before this change), treat as `paused: false` with all other fields `null`. The first dashboard write creates the field via `_merge_state` (now that `automation` is in the schema).

## Python pipeline changes

### `src/state_schema.py`

Add a new TypedDict + field on `BotState`:

```python
class AutomationState(TypedDict, total=False):
    paused: bool
    paused_at: str | None
    paused_by: str | None
    paused_reason: str | None
    routine_last_run_at: str | None
    routine_last_run_outcome: str | None

class BotState(TypedDict, total=False):
    # ... existing fields ...
    automation: AutomationState
```

### `src/state.py`

Add `automation` to `DEFAULT_STATE` (line ~35):

```python
DEFAULT_STATE: BotState = {
    # ... existing fields ...
    "automation": {
        "paused": False,
        "paused_at": None,
        "paused_by": None,
        "paused_reason": None,
        "routine_last_run_at": None,
        "routine_last_run_outcome": None,
    },
}
```

Update `_merge_state()` (line ~574) to copy `automation` with this merge rule: **incoming wins**. Reason: the dashboard's pause write is "incoming" relative to a concurrent cron's read-modify-write; if base wins, the cron silently un-pauses. Cron writes don't touch `automation` (only the dashboard does), so "incoming wins" effectively means "the dashboard's write is preserved".

```python
merged["automation"] = deepcopy(
    next_state.get("automation", base.get("automation", DEFAULT_STATE["automation"]))
)
```

### New module `src/orchestrator/automation_guard.py`

Shared helper to check the pause sentinel from any python entry point:

```python
def is_paused(bot_state: BotState) -> bool:
    return bool(bot_state.get("automation", {}).get("paused", False))

def assert_not_paused_or_exit(bot_state: BotState, *, run_kind: str) -> None:
    """If paused, log and sys.exit(0). Used at top of every entry point."""
    if is_paused(bot_state):
        a = bot_state["automation"]
        log.info(
            "Automation paused since %s by %s — exiting %s cleanly",
            a.get("paused_at"), a.get("paused_by"), run_kind,
        )
        sys.exit(0)
```

### Entry-point checks

Add `assert_not_paused_or_exit()` at the very top of:
- `src/orchestrator/cli.py` `run_alerts()`, `run_leaderboard()`, `run_auto_publish_due()` — before any data fetch
- `src/orchestrator/posting.py` `process_due_drafts()` — at function entry AND inside the post loop before each `_post_draft()` call (so a pause mid-loop stops further posting; in-flight individual posts still complete)

The mid-loop check is the key fix for Codex's "in-flight post" finding. Reading the gist mid-loop is one extra HTTP call per draft, but the loop only fires when there are due drafts — typically a small N. Acceptable cost.

## Workflow changes

### `bot.yml`

Add job-level `if:` guard:

```yaml
jobs:
  bot:
    if: github.event_name != 'schedule' || vars.AUTOMATION_PAUSED != '1'
    runs-on: ubuntu-latest
    steps:
      # ... existing steps ...
```

When `AUTOMATION_PAUSED == "1"`:
- Scheduled cron runs: job skipped (no compute)
- PR runs: job runs (PR tests stay alive)
- `workflow_dispatch` runs: job runs (manual dispatch overrides pause, matching CLI behavior)

### `voice-regression.yml` + `refresh-thresholds.yml`

Same `if:` guard pattern. For voice-regression, "non-schedule" triggers (PR label) bypass the pause.

For refresh-thresholds, the workflow has only a `schedule` trigger today — the guard reduces to `if: vars.AUTOMATION_PAUSED != '1'`. Simpler.

### Manual override

Dispatch (`workflow_dispatch`) bypasses the guard. Reasoning: if you're paused but explicitly clicking "Run bot now" in the dashboard, you intend it. The python pipeline's `assert_not_paused_or_exit()` is the second-layer brake — it WILL still exit if the gist sentinel is set. To override the gist sentinel too, the operator must resume first. (Documented behavior: pause + dispatch = no-op for cron-style runs because python exits early.)

## Dashboard changes

### `lib/automation.js` (new)

Shared helper module:

```javascript
// GH API
export async function getRepoVariable(name)
export async function setRepoVariable(name, value)
export async function deleteRepoVariable(name)
export async function fetchWorkflowLastRun(file)

// Gist
export async function readAutomationState()  // wraps the existing readGistState helper
export async function writeAutomationState(patch)  // read-modify-write on state.automation only

// Combined
export async function pauseAll({ paused_by, paused_reason })  // sets repo var + writes gist
export async function resumeAll({ resumed_by })  // unsets repo var + writes gist + drains auto_approve queue
export async function getAutomationStatus()  // reads both stores + returns combined view
```

### `GET /api/automation` (new)

Returns the combined state shape from `getAutomationStatus()`:

```json
{
  "paused": true,
  "paused_at": "2026-05-22T22:30:00Z",
  "paused_by": "dashboard",
  "paused_reason": "Pre-0.10 verification window",
  "repo_variable_value": "1",
  "workflows": [
    {"name": "theheat-bot", "file": "bot.yml", "state": "active", "last_run_at": "...", "last_run_conclusion": "skipped"},
    {"name": "voice-regression", "file": "voice-regression.yml", "state": "active", "last_run_at": "...", "last_run_conclusion": "skipped"},
    {"name": "refresh-thresholds", "file": "refresh-thresholds.yml", "state": "active", "last_run_at": "...", "last_run_conclusion": "skipped"}
  ],
  "routine": {
    "name": "TheHeat daily plan refinement (15:00 UTC)",
    "last_run_at": "2026-05-22T15:04:58Z",
    "last_run_outcome": "graded",
    "next_fire_at": "2026-05-23T15:07:47Z"
  },
  "posting_mode_summary": {
    "manual_only_count": 5,
    "armed_auto_count": 0,
    "suggested_count": 0
  }
}
```

Note: `workflows[].state` is always `"active"` in the new architecture because we don't disable workflows. The `paused` boolean at top + `last_run_conclusion: "skipped"` is what tells the operator "scheduled runs are being skipped". The dot color in the UI is computed from `(paused, last_run_conclusion)`.

### `POST /api/automation` (new)

Body: `{"action": "pause" | "resume", "reason": "optional string"}`.

**Pause flow:**
1. Validate input.
2. `setRepoVariable("AUTOMATION_PAUSED", "1")` — primary brake.
3. Read gist → patch `automation` → write gist (single read-modify-write on the gist's full state.json, but only the `automation` field changes).
4. Return per-step result + combined state.

**Resume flow:**
1. `deleteRepoVariable("AUTOMATION_PAUSED")` — re-enables scheduled runs.
2. Read gist → patch `automation.paused = false` (clear audit fields, preserve routine_last_run_*).
3. **Drain stale auto-approve queue:** for every pending draft, if `auto_approve_at` falls within `(paused_at, now)`, push it forward by `(now - auto_approve_at)`. So if a draft was 2 hours from auto-approval when paused and we resume 5 hours later, the draft now has 2 hours to wait again — same delay it would have had if pause never happened. Atomic: do this in the same gist write as step 2.
4. Return combined state.

**Partial-failure semantics:** if step 2 fails after step 1 succeeds (or vice versa), return HTTP 207 + `partial: true`. The UI shows a yellow warning. Operator can retry. The system is in a knowable inconsistent state (repo var + gist out of sync), but both layers fail safe (if either is set, the system behaves paused; only when BOTH are clear does normal operation resume — see "Defensive read combine" below).

**Defensive read combine:** workflows trust the repo var (Layer 1). Python pipeline trusts the gist (Layer 2). On partial failure, the most-pessimistic interpretation wins (paused). To fully resume, the operator must retry until both stores agree.

### `lib/automation-middleware.js` (new)

A thin middleware applied to destructive routes (`/api/trigger`, `/api/post`, `/api/drafts` for approve + auto_approve actions, `/api/generate`). On each request, reads the gist sentinel and short-circuits with `409 Conflict` + `{error: "automation paused", paused_at, paused_by}` if `automation.paused` is true. Read-only routes (`/api/state`, `/api/source-health`, `/api/suppressions`, `/api/automation` GET, `/api/drafts` GET + reject action) are NOT gated — operator can still observe state and reject stale drafts while paused.

Caching: middleware caches the gist read for 5 seconds per Node process to avoid hammering the gist on every API call. Acceptable staleness for a pause signal.

### Status strip component (new)

Lives at top of `app/page.js`, always visible. Layout:

- Title: `Automation`
- 4 dots: `bot` | `voice-regression` | `refresh-thresholds` | `routine`. Color from `(paused, last_run_outcome)`:
  - Green: not paused AND last run succeeded
  - Yellow: not paused AND last run failed
  - Gray: paused (regardless of last run)
  - Red: error reading state
- Posting-mode pill: `5 manual / 0 auto / 0 suggested`
- Spacer
- Pause/Resume button (red when any dot is green; gray "Resume" when all gray)
- Last-action timestamp: `Paused 2h ago — "reason"`

### Pause confirmation modal

- Lists what will be paused (the 4 automations + the destructive API routes)
- Reason textarea, max 280 chars
- Cancel + Pause buttons (Pause is destructive style)

### Resume confirmation modal

- Lists what resumes
- Mentions the auto-approve queue drain: "Drafts whose auto-approval was due during the pause window will get their original delay refreshed."
- Cancel + Resume

### Polling

30s interval (existing dashboard cadence). After Pause/Resume click, optimistic update: dots flip to target color immediately, with subtle pulsing border indicating "syncing". Reconcile on the next poll. On error, rollback + toast.

## Routine prompt changes

### Step 0 (new, before existing Step 1) — stale-snapshot sync

Replaces v1's brittle `git checkout main`:

```bash
0. Sync to current main. The CCR environment can reuse a stale git checkout
   across runs.

   ```bash
   set -e
   _REPO_TOP="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   cd "$_REPO_TOP"
   git fetch origin main
   # Force re-create main from origin; survives dirty working tree.
   git checkout -B main origin/main
   git clean -fd
   ```
```

The `-B` flag force-creates the branch — works whether current HEAD is on `main`, `daily-plan-current`, or detached.

### Step 1.5 (new, after Step 1 reads gist) — pause sentinel

Replaces v1's broken Python-with-`$GIST_DIR` snippet. Moves the sentinel check entirely to bash (no Python env-var interpolation gotcha):

```bash
1.5. **Honor the dashboard pause sentinel.** The gist's state.automation.paused
     field is the canonical pause signal. If true, write a "paused-skip" outcome
     to the gist, then exit cleanly without committing anything.

     ```bash
     IS_PAUSED=$(jq -r '.automation.paused // false' "$GIST_DIR/state.json")
     if [ "$IS_PAUSED" = "true" ]; then
       PAUSED_AT=$(jq -r '.automation.paused_at // "unknown"' "$GIST_DIR/state.json")
       REASON=$(jq -r '.automation.paused_reason // "no reason given"' "$GIST_DIR/state.json")
       echo "PAUSED since $PAUSED_AT — $REASON. Writing paused-skip outcome and exiting." >&2
       NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
       # Write routine_last_run_at + outcome=paused-skip back to the gist.
       # Use jq to update only the routine fields; preserve everything else.
       UPDATED=$(jq --arg now "$NOW" '.automation.routine_last_run_at = $now | .automation.routine_last_run_outcome = "paused-skip"' "$GIST_DIR/state.json")
       echo "$UPDATED" > /tmp/state-updated.json
       gh api -X PATCH "gists/06c02c97ffc0d11458687f1ed998d9e5" \
         --input <(jq -n --arg c "$UPDATED" '{files: {"state.json": {content: $c}}}') \
         > /dev/null
       exit 0
     fi
     ```
```

### End-of-routine bookkeeping (new Step 9.5)

After the existing Step 9 (print summary), before exit:

```bash
9.5. **Write routine health beacon.** Regardless of grading outcome, write
     state.automation.routine_last_run_at and routine_last_run_outcome to the
     gist so the dashboard can show fresh routine status (not just last-commit-time
     of daily-plan-current).

     ```bash
     OUTCOME="graded"  # or "no-fresh-drafts" if 0 drafts graded, or "error" if anything failed
     NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
     # Read latest gist (post-PR-create), update routine fields, write back.
     GIST_LATEST_DIR=$(mktemp -d)
     git clone --depth=1 https://gist.github.com/06c02c97ffc0d11458687f1ed998d9e5.git "$GIST_LATEST_DIR"
     UPDATED=$(jq --arg now "$NOW" --arg outcome "$OUTCOME" '
       .automation.routine_last_run_at = $now |
       .automation.routine_last_run_outcome = $outcome
     ' "$GIST_LATEST_DIR/state.json")
     gh api -X PATCH "gists/06c02c97ffc0d11458687f1ed998d9e5" \
       --input <(jq -n --arg c "$UPDATED" '{files: {"state.json": {content: $c}}}') \
       > /dev/null
     ```
```

## Error handling matrix

| Failure | Behavior |
|---|---|
| GH API down during Pause (repo variable set fails) | Gist sentinel still gets written. Workflows still fire on schedule but python pipeline exits early (Layer 2 catches it). UI shows `partial: true`. |
| Gist write fails during Pause (repo variable set succeeded) | Workflows skip scheduled runs (Layer 1 active). Routine + python check the gist — without the sentinel, they think automation is unpaused, but Layer 1 prevents scheduled invocation. Result: scheduled runs paused, manual dispatch + PR runs proceed. UI shows partial warning. |
| Both layers set, then a cron run starts (race) | Workflow `if:` guard skips the job. Python pipeline never invoked. No conflict possible. |
| Pause during in-flight `process_due_drafts()` loop | The pre-loop check skips the function entirely. Inside-loop check halts before next post. In-flight individual post completes (network in-flight). At most one extra post slips through. |
| Concurrent dashboard tab Pause + Resume | Last write wins on the gist. Repo variable updates non-atomic relative to gist; defensive read-combine ensures most-pessimistic wins until both agree. |
| Routine clone fails (gist down) | Routine exits with non-zero from Step 2 — same as today. No new failure mode. |
| Routine sentinel-check fails (gist response invalid JSON) | `jq` exits non-zero under `set -e`; routine fails. Same behavior as today's gist-read failures. Acceptable. |
| `_merge_state` race during pause | Incoming wins → dashboard's pause write is preserved. |
| Resume + concurrent draft auto-approval cron | Drain step pushes auto_approve_at forward; the cron sees forwarded timestamps. No double-post. |

## Testing

- Unit: `src/orchestrator/automation_guard.py` + `_merge_state` change (verify `automation` field survives a round-trip merge).
- Unit: `lib/automation.js` (mocked gh CLI + fetch). Cover repo-var set/unset, gist read-modify-write, auto-approve drain logic.
- Unit: dashboard middleware (mock state, verify 409 on paused destructive routes, 200 on read-only routes).
- Integration: pause → trigger workflow_dispatch → verify python exits early. Pause → wait for next scheduled cron → verify job skipped via `if:`. Resume → verify next cron processes normally.
- Manual: status strip across 4 state combos (all running / paused / mid-pause-partial / error).

## Out of scope

- Per-workflow granular pause toggles (deferred)
- Audit log of pause/resume events beyond last one (deferred)
- Auto-resume on schedule (deferred)
- Pause from CLI / Slack (deferred)
- Pausing already-running individual posts (the in-loop check is good enough; canceling an in-flight twitter post mid-call is risky)
- Stronger auth than Basic on the control plane (deferred; single-operator system)

## Migration notes

- First deploy: the gist `state.automation` field doesn't exist yet. `_merge_state` will create it from `DEFAULT_STATE` on the next cron write. Dashboard's `getAutomationStatus()` handles the missing-field case by defaulting to `paused: false`.
- Workflow `if:` guards are no-ops until `vars.AUTOMATION_PAUSED` is set, so they can deploy ahead of the dashboard.
- Python entry-point checks are no-ops until `state.automation.paused` is true, so they can deploy ahead of the dashboard.
- Order of deploy: python + workflow changes first (additive, no-ops without a sentinel) → dashboard changes second (introduces the sentinel-setting UI) → routine prompt last (via RemoteTrigger, separate from repo deploys).
