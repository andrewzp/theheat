# Lane 06 — Plan A Lane B: State Hygiene (Trim Rejected Drafts)

**Branch:** `plan-a/state-trim`
**Plan-of-record:** `docs/PLAN_A.md` (in-repo)
**Scope:** Plan A Phase 4 only — independent of Lane A
**Estimated time:** 1 hour CC, single PR
**Runs in parallel with Lane 05 (different files; no merge conflicts)**

## Why this lane exists

`state.json` on the GitHub Gist is currently **958 KB on a 900 KB API truncation cap**. PR #87 made reads survive truncation via raw_url fallback. Writes are still at risk — a single cron writing 1 MB+ corrupts the file and the bot loses draft queue, dedup history, and memory in one cycle.

Audit findings:

```
state.json (958 KB total):
  drafts          472,724 bytes  49%   ← THE FIX TARGET
  suppressions    100,470 bytes  10%
  run_history      35,352 bytes   4%
  errors            7,961 bytes  <1%
  posted_events     6,778 bytes  <1%
  memory            3,827 bytes  <1%
  other             ~330,000     35%

drafts breakdown (165 entries, 200-cap):
  6 pending  •  1 posted  •  158 REJECTED ← dead weight
  median draft: 2,769 bytes, driven by `review_context` (~1.2 KB)
  oldest: 2026-04-09
```

Each rejected draft retains its `review_context` blob after the human decision is final. The blob is only useful while the human is reviewing; once status flips to rejected it's dead weight. 158 × 1.2 KB = ~190 KB recoverable from review_context alone; trimming whole rejected drafts >30 days recovers ~400 KB and restores headroom.

## Read first

1. `docs/PLAN_A.md` — Plan A doc, Phase 4 section
2. `src/state.py` — existing trim logic for drafts (find the function that enforces the 200-cap; this lane extends it)
3. `tests/test_state.py` — existing draft-trim tests

## The change

Single function update in `src/state.py`:

```python
def trim_drafts(state: BotState) -> None:
    """Existing 200-cap trim, PLUS new time-based trim of rejected drafts.

    Policy:
      - All 'pending' drafts kept indefinitely (queue for human review)
      - All 'posted' drafts kept indefinitely (audit trail)
      - 'rejected' drafts older than 30 days dropped
      - After time-trim, enforce the 200-cap as a backstop
    """
```

The 30-day window is a constant at module level: `REJECTED_DRAFT_RETENTION_DAYS = 30`. Easy to tune later.

## Files

- `src/state.py` — extend `trim_drafts` (find current function name; adjust if differently named)
- `tests/test_state.py` — add tests:
  - `test_rejected_drafts_older_than_30_days_are_trimmed`
  - `test_pending_drafts_never_trimmed_regardless_of_age`
  - `test_posted_drafts_never_trimmed_regardless_of_age`
  - `test_200_cap_still_enforced_after_time_trim`
  - `test_rejected_drafts_newer_than_30_days_kept`

## Acceptance

- mypy clean.
- Full pytest suite passes with 4-5 new tests added (currently 910).
- After deploy, next state write should drop ~150 rejected drafts older than 30 days. Confirm via:

  ```bash
  gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | wc -c
  ```

  Expect ~500-550 KB.

## Constraints

- **Don't touch draft schema.** Just trim by status + age.
- **Don't change pending or posted retention.** The handoff document and dashboard depend on those being present.
- **Don't bundle other Plan A work.** This lane ships alone. Lane 05 is the foundation + restore lane.
- **Verify the wire.** After PR merges and first cron runs, confirm Gist payload size dropped. The in-process state object size dropping doesn't prove the Gist write succeeded.
- **Subagent model floor (memory):** never Haiku for any spawned subagent work. Sonnet 4.6 default.

## Rollback safety

If the time-based trim drops drafts that shouldn't have been dropped, two recovery paths:

1. Drafts in state are advisory only — the pipeline's dedup uses `posted_events`, not `drafts`. Trimmed rejected drafts have already been decided; trimming them doesn't affect any pending behavior.
2. The 200-cap backstop and 30-day window are constants. Adjust either with a one-line revert PR.

This change is structurally low-risk.

## Test conventions

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat
source .venv/bin/activate && python -m pytest tests/test_state.py -v
python -m mypy src/
```

## Branch / PR sequence

1. Branch `plan-a/state-trim` from `main`.
2. Implement + tests + mypy clean.
3. PR → CI green → Andrew merges.
4. After merge, run one alerts cron (or wait for hourly cron) and verify Gist size dropped.

Done. ~1 hour CC end-to-end.
