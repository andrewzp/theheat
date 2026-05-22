# Dashboard "Pause Everything" + Automation Indicators — Design

**Date:** 2026-05-22
**Status:** Draft — awaiting Codex adversarial review + operator approval
**Companion:** Routine prompt fix (stale-snapshot bug) lands in same change set.

## Goal

A single dashboard control that pauses every unattended automation in the theheat system, plus persistent indicators showing the state of each. Replaces the current "Andrew remembers to run `gh workflow disable theheat-bot && gh workflow disable voice-regression` from the terminal" pattern.

## What "everything" covers

| Automation | Cadence | Pause mechanism |
|---|---|---|
| `theheat-bot` workflow | 6×/day (cron) + workflow_dispatch | GH Actions API: `PUT /repos/{repo}/actions/workflows/bot.yml/disable` |
| `voice-regression` workflow | nightly | GH Actions API: same endpoint, voice-regression.yml |
| `refresh-thresholds` workflow | weekly | GH Actions API: same endpoint, refresh-thresholds.yml |
| Daily-plan Claude routine | daily 15:00 UTC | Gist sentinel: `state.automation.paused = true` (routine checks at Step 1, exits early) |

## Data model

New top-level field on the gist's `state.json`:

```json
{
  "automation": {
    "paused": false,
    "paused_at": null,
    "paused_by": null,
    "paused_reason": null
  }
}
```

When pausing:
- `paused: true`
- `paused_at`: ISO 8601 UTC
- `paused_by`: `"dashboard"` (only writer for now; future writers might be `"routine"` or `"workflow"`)
- `paused_reason`: optional free-text from a textarea on the confirm modal

When resuming: set `paused: false`, clear the other three.

**Missing-field semantics:** If `automation` is absent (older gist state), treat as `paused: false`. The dashboard's first write creates the field.

**Concurrency:** Only the dashboard writes the `automation` field. Other gist writers (bot pipeline, refresh-thresholds, the routine itself) read it but never touch it. Lost-update risk is bounded — at most the operator's last click is the source of truth.

## Server APIs

### `GET /api/automation`

Returns combined state:

```json
{
  "paused": true,
  "paused_at": "2026-05-22T22:30:00Z",
  "paused_by": "dashboard",
  "paused_reason": "Pre-0.10 verification window",
  "workflows": [
    {"name": "theheat-bot", "file": "bot.yml", "state": "disabled_manually", "last_run_at": "2026-05-19T12:24:14Z", "last_run_conclusion": "success"},
    {"name": "voice-regression", "file": "voice-regression.yml", "state": "disabled_manually", "last_run_at": "2026-05-19T11:55:21Z", "last_run_conclusion": "failure"},
    {"name": "refresh-thresholds", "file": "refresh-thresholds.yml", "state": "active", "last_run_at": "...", "last_run_conclusion": "success"}
  ],
  "routine": {
    "id": "trig_016PGeHZgEYWmeQhx1xGmYg6",
    "name": "TheHeat daily plan refinement (15:00 UTC)",
    "paused": true,
    "last_fired_at": "2026-05-22T15:04:58Z",
    "next_fire_at": "2026-05-23T15:07:47Z",
    "note": "Routine schedule is not touched by dashboard pause. Routine still fires on cron but exits at Step 1 when state.automation.paused is true."
  },
  "posting_mode_summary": {
    "manual_only_count": 5,
    "armed_auto_count": 0,
    "suggested_count": 0
  }
}
```

The routine fields are best-effort. We can't query the claude.ai routines API from the dashboard (user-OAuth). For `last_fired_at` and `next_fire_at`, we store the trigger ID and schedule expression in dashboard env (`THEHEAT_ROUTINE_ID`, `THEHEAT_ROUTINE_CRON="0 15 * * *"`) and compute next-fire client-side from the cron expression. For "did the routine fire successfully", we look at the rolling `daily-plan-current` branch's last-commit time as a proxy — if the routine is firing, that branch gets updated daily.

### `POST /api/automation`

Body: `{"action": "pause" | "resume", "reason": "optional string"}`.

**Pause flow:**
1. Validate input (action enum, reason length ≤ 280).
2. For each of `bot.yml`, `voice-regression.yml`, `refresh-thresholds.yml`: call `PUT /repos/andrewzp/theheat/actions/workflows/{file}/disable`. Collect per-workflow result.
3. Read gist state.json via git-clone path (handles the 1 MB API truncation).
4. Patch `state.automation = {paused: true, paused_at, paused_by: "dashboard", paused_reason: reason}`.
5. Write gist via `PATCH /gists/{id}` with the full new state.json.
6. Return per-step results to client. If any step failed: HTTP 207 (Multi-Status) with `partial: true` + per-step status.

**Resume flow:**
1. For each workflow file: call `PUT /repos/andrewzp/theheat/actions/workflows/{file}/enable`.
2. Read gist, patch `state.automation = {paused: false, paused_at: null, paused_by: null, paused_reason: null}`.
3. Write gist.
4. Return per-step results.

**Partial-failure semantics:** If pause step 2 partially succeeds (e.g., bot.yml disabled but voice-regression failed), DON'T roll back. The system tolerates "some paused, some active" — the indicator strip will reflect the actual state on next poll. The response includes `partial: true` and the client renders a yellow warning banner with retry button.

**Idempotency:** Disabling an already-disabled workflow returns 204 from GH. Enabling an already-enabled workflow returns 204. So Pause + Pause is safe; Resume + Resume is safe. The gist write is also idempotent — same payload, same result.

**Auth:** Basic auth (existing pattern). Both routes require it.

### `lib/automation.js`

Shared helper module:
- `fetchWorkflowState(file)` — GH API call, parses `state` + `updated_at`
- `fetchWorkflowLastRun(file)` — GH API call to `/actions/workflows/{file}/runs?per_page=1`
- `disableWorkflow(file)` / `enableWorkflow(file)` — POST endpoints
- `readGistAutomation()` — git-clone path, returns `state.automation` (defaults to `{paused: false}` if absent)
- `writeGistAutomation(patch)` — read-modify-write the gist

## Client UI

### Status strip component (new)

Lives at the top of `app/page.js`, above the existing tab navigation. Always visible across all views.

Layout (left → right):
- Title: `Automation`
- 4 status dots, each with a label tooltip on hover:
  - `bot` — green=active, gray=disabled_manually, red=disabled_inactivity, yellow=last_run_failed
  - `voice-regression` — same color rules
  - `refresh-thresholds` — same color rules
  - `routine` — green=active+unpaused, gray=paused (via gist sentinel), yellow=last cycle had no commit (might indicate routine isn't firing)
- Posting-mode pill: `5 manual / 0 auto / 0 suggested` (read from `posting_mode_summary`)
- Spacer
- **Pause Everything** button (red when active state has any green dot; gray + label "Resume" when all paused)
- Last-action timestamp: `Paused 2h ago by dashboard — "Pre-0.10 verification"` (if applicable)

### Pause confirmation modal

Click Pause → modal with:
- Title: "Pause all automation?"
- List of what will be paused (the 4 automations)
- Optional reason textarea (max 280 chars; saved to `state.automation.paused_reason`)
- Buttons: `Cancel` (default) + `Pause everything` (destructive style)

### Resume confirmation

Click Resume → confirm modal (lighter weight than pause):
- Title: "Resume all automation?"
- "Next cron will fire on its own schedule. The first run will be a clean exercise of the pipeline."
- Buttons: `Cancel` + `Resume`

### Polling

Status strip refreshes on the same 30s interval the existing dashboard uses. After a Pause/Resume click, optimistic update: immediately flip the dot colors based on the request, mark with a subtle "syncing" indicator (animated dot border), then reconcile against the server response. On error, roll back optimistic state + show toast.

### Visual indicators (the "everything has an indicator" requirement)

Beyond the 4 dots in the strip, the existing dashboard cards already surface much of what Andrew asked for. The change adds a small badge on each existing card showing the automation state ALONGSIDE the data:
- `Pipeline` tab: badge "paused" if `state.automation.paused` is true, masking the misleading "next run in 23m" footer
- `Sources` tab: per-source "last update" times remain unchanged; refresh-thresholds state already implicit in the data
- `Health` page: explicit "Routine status: paused (since 2h ago)" line at the top
- Posting-mode pills on draft cards stay where they are — the strip's summary is just an aggregate

## Routine prompt changes (companion)

Two updates, applied via `RemoteTrigger` update:

### Fix 1: stale-snapshot bug (new Step 0)

Insert before existing Step 1:

```
0. Sync to current main before doing anything else. The CCR environment can
   reuse a stale git checkout across runs.

   ```bash
   set -e
   cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   git fetch origin main
   git checkout main
   git reset --hard origin/main
   git clean -fd
   ```
```

### Fix 2: pause-aware exit (new Step 1.5)

After existing Step 1 (read pending drafts from gist), check the sentinel:

```
1.5. **Honor the dashboard pause sentinel.** The gist's state.automation.paused
     field is the canonical pause signal. If true, exit immediately without
     writing anything.

     ```python
     import json, pathlib, sys
     state = json.loads(pathlib.Path("$GIST_DIR/state.json").read_text())
     if state.get("automation", {}).get("paused", False):
         paused_at = state["automation"].get("paused_at", "?")
         reason = state["automation"].get("paused_reason", "no reason given")
         print(f"PAUSED since {paused_at} — {reason}. Exiting cleanly without commit.", file=sys.stderr)
         sys.exit(0)
     ```
```

The routine continues with Step 2 normally if `paused` is false or the field is missing.

## Error handling

| Failure | Behavior |
|---|---|
| GH API down during Pause | Disable calls fail; gist sentinel still gets written. Routine pauses. Workflows keep firing until GH API recovers — operator must retry Pause. UI shows `partial: true` warning. |
| Gist write fails during Pause | Workflows disabled successfully; gist sentinel not written. Routine continues firing (until operator re-pauses). UI shows partial warning + retry button. |
| Workflow already in target state | GH returns 204; treated as success. |
| Gist's `automation` field missing | Treated as `paused: false`. First Pause creates the field. |
| Concurrent Pause + Resume from two browser tabs | Last write wins. Indicators reconcile on next 30s poll. |
| Routine fires during Pause | Routine reads gist → sees paused → exits at Step 1.5. CCR run consumes ~10s of compute, $0 LLM. |
| Routine reads stale gist (>1MB truncated by API) | Routine uses git-clone path per existing Step 2 design — sees full state. |

## Testing

- Unit: `lib/automation.js` helpers (mocked fetch). Cover the GH API parse + the gist read-modify-write path.
- Unit: `POST /api/automation` route — pause/resume action handling, validation, partial-failure response shape.
- Integration: e2e against a test gist + a fork of the workflow repo. Pause → verify all 4 disabled. Resume → verify all 4 enabled. Pause then trigger routine via dispatch → verify routine exits at Step 1.5.
- Manual: status strip rendering across the 4 state combinations (all paused / all active / mixed / one failed).

## Out of scope

- Per-workflow granular pause toggles (deferred; can add later if needed)
- Audit log of pause/resume events beyond the latest one in `state.automation.paused_at` (deferred; gist isn't a great audit log anyway)
- Auto-resume on a schedule (e.g., "pause for 4 hours") — deferred
- Pause from CLI or via Slack — deferred
- Pausing in-flight runs (only future runs are blocked)

## Open question for Codex review

- Should the routine ALSO honor a sentinel for the stale-snapshot fix — i.e., write a commit-SHA marker to the gist on Step 0 to detect "I'm running from a SHA that's behind main"? Currently the fix just does `git reset --hard origin/main` which makes the routine self-healing without needing a sentinel. Leaning toward no, but flag-worthy.
- Should `refresh-thresholds` actually be paused? It's data-only (recalibrates score thresholds from historical data). Pausing it freezes thresholds at last-calibration values, which during a longer pause could drift from current conditions. Counter: a frozen threshold is no worse than the current pause state already produces. Leaning include.
- Should we gate the Pause button behind something stronger than basic auth (e.g., a separate "control plane" password)? Risk: someone with dashboard view access accidentally pauses production. Mitigation: confirm modal already requires explicit click + the reason textarea hint adds friction.
