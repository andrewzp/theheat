# Dashboard Automation Indicators + Routine Fixes — Design v3 (Descoped)

**Date:** 2026-05-22
**Status:** Approved (operator descoped pause-control after Codex round 2)
**Supersedes:** v1, v2 in same directory. v1 + v2 retained for historical record because they document the pause-control design space we explored.

## What changed from v2

v2 tried to ship a "Pause Everything" control plane that paused 4 automations atomically. Two rounds of Codex adversarial review exposed:
- Merge-race + two-store coordination problems that don't have clean fixes without a full CAS layer
- A ~500-line spec touching python pipeline + 3 workflows + dashboard middleware + routine + new APIs
- Each fix introducing new edge cases

Operator descope: drop pause control entirely. The terminal command `gh workflow disable theheat-bot` already does the job in 2 seconds. Ship just the **read-only indicators** so the dashboard surfaces automation state without trying to drive it.

Two routine prompt fixes ride along because they're independent of the pause work and already needed:
- Step 0 (stale-snapshot bug fix) — the original "second bug" from operator's earlier ask
- Step 9.5 (routine health beacon) — gives the dashboard a fresh signal for the routine indicator

## In scope (this change)

1. **Dashboard `GET /api/automation`** — read-only endpoint returning state of the 3 workflows + the routine + posting-mode summary.
2. **Dashboard status strip component** — persistent strip at top of [/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/page.js](/Users/andrewpuschel/Documents/Claude/theheat/dashboard/app/page.js) showing 4 colored dots + last-run-ago timestamps + posting-mode pill.
3. **Routine prompt update (via RemoteTrigger)** —
   - Step 0: `git fetch + git reset --hard origin/main` to fix the stale-snapshot bug
   - Step 9.5: write `state.automation.routine_last_run_at` + `routine_last_run_outcome` to the gist at end of every cycle, regardless of whether it committed

## Out of scope (deferred)

- Pause/Resume button + control plane (descoped; revisit when single-operator constraint changes)
- Python pipeline pause checks (descoped with pause)
- Workflow `if:` guards (descoped with pause)
- Per-route middleware for destructive actions (descoped with pause)
- Auto-approve queue drain (descoped with pause)
- All v2 architectural fixes (descoped with pause)

## Data model

One field added to gist `state.json`, written by the routine only:

```json
{
  "automation": {
    "routine_last_run_at": "2026-05-22T15:04:58Z",
    "routine_last_run_outcome": "graded"
  }
}
```

Outcomes: `"graded"` | `"no-fresh-drafts"` | `"error"`. Missing-field semantics: if the field is absent, dashboard shows `"unknown"` for the routine indicator.

**Merge safety:** because the routine is the ONLY writer, and the dashboard READS only, there's no merge race. But the python pipeline (`_merge_state`) would still drop the field on its writes — same v1/v2 bug. To survive python cron writes, we add `automation` to `BotState` schema + `DEFAULT_STATE` + the `_merge_state` copy. **Current wins** for the automation field in the merge (python doesn't touch it, so we want to preserve whatever's in the latest gist state).

This is the smallest possible python change: 3 small edits, no new entry-point logic, no new behavior — just preserving a field the routine writes.

## Implementation

### Python (src/)

**`src/state_schema.py`** — add TypedDict + field:
```python
class AutomationState(TypedDict, total=False):
    routine_last_run_at: str | None
    routine_last_run_outcome: str | None

class BotState(TypedDict, total=False):
    # ... existing fields ...
    automation: AutomationState
```

**`src/state.py`** — add to `DEFAULT_STATE`:
```python
"automation": {
    "routine_last_run_at": None,
    "routine_last_run_outcome": None,
},
```

Update `_merge_state()` to copy `automation` with **current wins** semantics:
```python
# Automation field is routine-written + dashboard-read; cron never touches it.
# Preserve the latest gist value (current), not the run's in-memory snapshot.
merged["automation"] = deepcopy(
    base.get("automation", DEFAULT_STATE["automation"])
)
```

### Dashboard (dashboard/)

**`dashboard/lib/automation.js`** (new) — pure read helpers:
- `fetchWorkflowState(file)` — GH API: `GET /repos/{repo}/actions/workflows/{file}`, returns `{state, updated_at}`
- `fetchWorkflowLastRun(file)` — GH API: `GET /repos/{repo}/actions/workflows/{file}/runs?per_page=1`, returns `{id, status, conclusion, created_at}`
- `readAutomationField()` — reads gist (via existing `readGistState` helper from `lib/state-store.js`), returns `state.automation` or `null`
- `getAutomationStatus()` — calls the above in parallel, computes posting-mode summary, returns combined shape

**`dashboard/app/api/automation/route.js`** (new) — GET only, Basic auth:
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
    return Response.json({ error: e.message }, { status: 500 })
  }
}
```

Response shape:
```json
{
  "workflows": [
    {"name": "theheat-bot", "file": "bot.yml", "state": "disabled_manually", "last_run_at": "2026-05-19T12:24:14Z", "last_run_conclusion": "success"},
    {"name": "voice-regression", "file": "voice-regression.yml", "state": "disabled_manually", "last_run_at": "2026-05-19T11:55:21Z", "last_run_conclusion": "failure"},
    {"name": "refresh-thresholds", "file": "refresh-thresholds.yml", "state": "active", "last_run_at": "...", "last_run_conclusion": "success"}
  ],
  "routine": {
    "name": "TheHeat daily plan refinement (15:00 UTC)",
    "last_run_at": "2026-05-22T15:04:58Z",
    "last_run_outcome": "graded",
    "next_fire_at_local": "computed client-side from cron 0 15 * * *"
  },
  "posting_mode_summary": {
    "manual_only_count": 5,
    "armed_auto_count": 0,
    "suggested_count": 0
  }
}
```

**`dashboard/app/page.js`** — add `AutomationStatusStrip` component, rendered at top of the dashboard (above the existing tab nav). Refreshes on the existing 30s polling cadence (extend the existing `useEffect` that polls source-health to also poll `/api/automation`).

Layout (left → right):
- Title: `Automation`
- 4 dots: `bot` | `voice-regression` | `refresh-thresholds` | `routine`
  - Green: workflow state = "active" AND last_run_conclusion = "success" (or routine outcome = "graded" or "no-fresh-drafts")
  - Yellow: workflow active AND last_run_conclusion = "failure" (or routine outcome = "error")
  - Gray: workflow state = "disabled_manually" (or routine last_run_at missing / stale > 25h)
  - Red: API error reading state
- Each dot has a hover tooltip with name + last-run-ago + last-run-conclusion
- Posting-mode pill: `5 manual / 0 auto / 0 suggested`

No buttons. No actions. Read-only.

### Routine (via RemoteTrigger update)

Two new steps inserted into the existing routine prompt. Steps 1–9 of the existing prompt remain unchanged.

**Step 0 (new, before existing Step 1) — stale-snapshot sync:**

```bash
0. Sync to current main. The CCR environment can reuse a stale git checkout across runs.

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

This handles:
- Fresh CCR env (clone is current): no-op, just confirms main
- Stale CCR env (clone is N days behind): fetch + reset --hard catches up
- Prior cycle left HEAD on `daily-plan-current`: `checkout main` succeeds, reset moves it to origin/main
- Prior cycle left dirty tracked files: `git checkout main` may fail under `set -e` → fallback to `git checkout -B main origin/main` which force-creates main even with dirty working tree; the subsequent `reset --hard` cleans up
- Prior cycle left untracked files: `git clean -fd` removes them

**Step 9.5 (new, after Step 9 prints summary) — health beacon:**

```bash
9.5. Write the routine health beacon so the dashboard knows when this cycle ran
     and whether it succeeded.

     ```bash
     OUTCOME="${ROUTINE_OUTCOME:-no-fresh-drafts}"  # graded | no-fresh-drafts | error
     case "$OUTCOME" in
       graded|no-fresh-drafts|error) ;;
       *) OUTCOME="error" ;;
     esac
     NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

     # Clone latest gist (avoids API truncation; ~1.6MB file)
     BEACON_DIR=$(mktemp -d)
     if ! git clone --depth=1 https://gist.github.com/06c02c97ffc0d11458687f1ed998d9e5.git "$BEACON_DIR" 2>/dev/null; then
       echo "WARN: beacon skipped — could not clone gist" >&2
       exit 0  # Don't fail the cycle on beacon-write failure
     fi

     # Update only the automation field; preserve everything else.
     UPDATED_PATH="$BEACON_DIR/state-updated.json"
     jq --arg now "$NOW" --arg outcome "$OUTCOME" '
       .automation = (.automation // {}) |
       .automation.routine_last_run_at = $now |
       .automation.routine_last_run_outcome = $outcome
     ' "$BEACON_DIR/state.json" > "$UPDATED_PATH"

     # Write back. The state file is ~1.6MB so we pass it via a payload file
     # (not --arg, which hits ARG_MAX) and let gh handle the upload.
     PAYLOAD_PATH="$BEACON_DIR/patch-payload.json"
     jq -n --rawfile c "$UPDATED_PATH" '{files: {"state.json": {content: $c}}}' > "$PAYLOAD_PATH"

     if ! gh api -X PATCH "gists/06c02c97ffc0d11458687f1ed998d9e5" --input "$PAYLOAD_PATH" > /dev/null 2>&1; then
       echo "WARN: beacon write failed (likely gist:write scope missing); cycle output unaffected" >&2
       exit 0  # Don't fail the cycle on beacon-write failure
     fi

     echo "Beacon written: routine_last_run_at=$NOW outcome=$OUTCOME" >&2
     ```
```

Beacon is **best-effort**: write failure prints a warning but doesn't fail the cycle. The PR creation in Step 8 has already happened; the beacon is just a dashboard convenience.

Outcomes:
- `graded` — at least one fresh draft was graded
- `no-fresh-drafts` — queue had no new drafts to grade (carry-overs only)
- `error` — set inside an error trap if Step 1.5 raised (gist read failure, etc.)

## Tests

- **Unit (`lib/automation.test.js`):** test `fetchWorkflowState` + `fetchWorkflowLastRun` with mocked `fetch` and a stub `GITHUB_TOKEN`. Test `readAutomationField` with mocked `readGistState`. Test `getAutomationStatus` composition.
- **Unit (`tests/test_state.py`):** test `_merge_state` preserves an `automation` field across a merge. Test `DEFAULT_STATE` includes `automation`.
- **Manual:** load dashboard, confirm the strip renders with the 4 dots. Force one workflow to a failure state (re-trigger), confirm yellow dot. Confirm tooltips show last-run-ago.

## Migration / rollout

1. Land python schema + merge change first (no observable behavior change; the `automation` field just survives merges now).
2. Land dashboard changes second (status strip starts showing data immediately; workflow + posting-mode info is reliable; routine info shows "unknown" until next routine cycle).
3. Update routine prompt last (Step 0 + Step 9.5) via RemoteTrigger. Next routine cycle (tomorrow 15:00 UTC) writes the first beacon; dashboard begins showing fresh routine status.

## Error handling

| Failure | Behavior |
|---|---|
| GH API down when dashboard reads workflows | API returns 500; UI shows red dot + error toast; user retries on next 30s poll |
| Gist down when dashboard reads automation field | Routine indicator shows "unknown"; other indicators unaffected (workflows still readable via GH API) |
| Routine fails to write beacon (gist:write missing) | Routine logs warning, cycle completes normally; dashboard shows stale `last_run_at` until next successful cycle |
| Workflow last-run query returns 0 runs | UI shows "never ran" |
| `_merge_state` rolls back during a cron-during-pause | Not possible — pause is descoped; cron always writes back; current-wins on automation field preserves the routine's most recent beacon |

## Open items deferred to a future ticket

- Pause/Resume button + control plane (whole v2 design space)
- Per-workflow last-N-runs sparkline
- Routine "next fire at" displayed in operator's local timezone (the 15:00 UTC cron has a deterministic next-fire; cheap to add later)
- Workflow trigger button for manual dispatch from the strip (already exists in the existing CommandDeckCard; no need to duplicate)
