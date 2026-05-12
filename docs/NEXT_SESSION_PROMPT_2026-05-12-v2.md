# Resume @theheat — Next Session Prompt (v2, written 2026-05-12 late evening)

This brief **supersedes** `NEXT_SESSION_PROMPT_2026-05-12.md`. That doc was written earlier in the day; this one captures the full-day cleanup wave that followed (4 more merged PRs, 4 stale PRs closed, production fixes for the entire day's kill cascade).

You are picking up work on the @theheat climate Twitter bot. The next scheduled validation events are:

- **Next bot.yml alerts run at 18:39 UTC** — first run with all four production fixes from #82 (Paddock Lake station-name regex, Nettles Is JSON-parse retry, ocean_sst UA header, river_gauges graceful degradation). The previous three runs (06:40, 10:34, 14:40 UTC) all logged kills for these exact issues; the 18:39 run is the verification.
- **2026-05-13 09:00 UTC voice-regression cron** — first nightly run on a clean main with the full Attenborough/Economist voice + length retry + JSON-parse retry. Will email `andrew.puschel@gmail.com` on red.

Before doing anything else, run the **First 5 minutes** block below to ground yourself.

---

## First 5 minutes — orient

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat

# 1. Confirm main and recent commits
git fetch && git log --oneline -12 main
# Expected HEAD: 48ee110 fix: four production issues killing every alerts run today (#82)

# 2. Did the 18:39 UTC alerts run survive the fixes from #82?
gh run list --workflow=bot.yml --limit 6 --json conclusion,event,createdAt,databaseId
# Want: most recent alerts run conclusion="success", no kills from Paddock Lake / Nettles Is / ocean_sst / river_gauges

# 3. Voice-regression nightly status (cron is 09:00 UTC daily; latest manual run before close-of-day was 12/12)
gh run list --workflow=voice-regression.yml --limit 3 --json databaseId,conclusion,createdAt

# 4. Open PRs (should be 0 after end-of-day cleanup)
gh pr list --state open --limit 10

# 5. Pipeline state
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/state.json && jq '{
  pending: (.drafts // [] | map(select(.status == "pending")) | length),
  pending_ids: (.drafts // [] | map(select(.status == "pending")) | map(.id)),
  recent_kills: (.suppressions // [] | sort_by(.suppressed_at) | reverse | .[0:5] | map({id: .draft_id, reason: .reason, at: .suppressed_at}))
}' /tmp/state.json

# 6. Tests + types (sanity check that main is clean)
source .venv/bin/activate
python -m mypy src/ 2>&1 | tail -5  # expect: Success: no issues
python -m pytest tests/ -q -m "not voice_replay" 2>&1 | tail -5  # expect: 894 passed
```

If any of the above is unexpected (HEAD ≠ 48ee110, pending drafts > 1, failing tests, kills in the new run), stop and investigate before doing further work.

---

## What landed today (2026-05-12) — eleven PRs merged, four stale PRs closed

| # | PR | What | Why |
|---|---|---|---|
| 1 | #72 | `BotState` TypedDict; remove `src.main` / `src.state` / `src.editorial.scoring` mypy overrides | Re-enable 147 errors worth of type safety for the highest-trafficked modules |
| 2 | #73 | Daily plan refinement 2026-05-11 | Routine cron PR |
| 3 | #74 | Voice prompt v1 → Attenborough/Economist anchor; THE SIGNATURE MOVE; wink-kicker ban | Editorial direction shift after Andrew rejected "The calendar says spring." kicker |
| 4 | #75 | Voice prompt v2 — compress exemplars to ≤280, add declarative trimming tactics, remove imperative "self-check" that broke strict-JSON | Iter 4 of voice work broke 5/12 fixtures with leaked reasoning text. v2 is purely declarative. |
| 5 | #76 | Writer-side length-cap retry — up to 3 attempts, clean KILL on exhaust | "Failure is not an option" — Twitter never sees a >280-char string from this pipeline regardless of model variance |
| 6 | #77 | Docs sweep — voice overhaul + dashboard refresh + FRP rounding | Documentation parity with merged behavior |
| 7 | #78 | Dashboard refresh button — visible feedback states | Silent refresh felt broken |
| 8 | #79 | Daily plan refinement 2026-05-12 (P2 rewritten per Codex review) | Codex caught a tolerance contradiction; bundle-side rounding is the correct fix |
| 9 | #80 | Bundle-side FRP rounding (`round(fire.frp, 1)` in `intern.py`) | Fixes fire-bundle BUNDLE_FACT kills on `frp 8.7 vs 8.7000000000001` decimal precision |
| 10 | #81 | +25 stations (Cyprus / Okinawa / QLD / N China / Verkhoyansk / Furnace Creek) | Coverage-gap closure; 613 → 638 cities |
| 11 | #82 | Four production fixes: GHCN regex (Paddock Lake), JSON-parse retry+KILL (Nettles Is), ocean_sst UA header, river_gauges graceful degradation | Eliminate the kill cascade that ran on every 06:40/10:34/14:40 UTC alerts run |

**Four stale daily-plan PRs closed without merging** (#52, #56, #65, #68) — superseded by the cleanup wave and not worth rebasing.

---

## Why the pending-PR queue is empty (and what that means)

The day started with 5 open PRs (3 daily-plan reconciliation PRs + 2 in-flight feature PRs) accumulating over a week. By close of day all merge-worthy PRs were merged, stale ones were closed. The four production issues in #82 had been quietly killing **every** alerts run all day; the dashboard had a silently-broken refresh button; the voice prompt had a wink-kicker tic. All resolved.

The next bot.yml alerts run is the verification. If it lands clean (no kills from the four #82 issues), the bot is fully healthy heading into 05-13.

---

## Outstanding follow-ups (in priority order)

1. **Verify #82 fixes hold in production.** Watch the next 18:39 UTC alerts run (or the run that fires after this session opens). All four issues should be silent. If any recurs, the relevant `src/data/*.py` or `src/two_bot/writer.py` retry path needs a second look.

2. **Operator action pending: paste the daily-plan PR closure config into Claude routines UI.** The auto-close-after-7-days rule was spec'd but not pasted by Andrew. Without it, daily-plan PRs will accumulate again.

3. **Replacement endpoint for USGS WaterWatch flood-stage.** The retired endpoint is now silently returning `{}`. River-gauge data is still reported (current heights), just without the `above_flood` flag. Find or build a substitute — likely NWS AHPS gauge JSON.

4. **Investigate low signal-detection rate.** On 2026-05-12 (a continental-anomaly day) only 2/638 cities fired. Either thresholds are too high or the detection layer has a bug. Start with the `monthly_high` / `anomaly_high` detection paths in `src/data/open_meteo.py` and the `STATION_*_THRESHOLD` constants.

5. **Southern Africa coverage gap.** PR #81 added northern Asia / Cyprus / QLD; Botswana/Namibia/Zambia/Zimbabwe are still uncovered. Pull a starter set (Maun, Windhoek, Lusaka, Bulawayo, Beitbridge) from GHCN.

6. **Finish dashboard QA.** Started in earlier session, only the Refresh button was completed (#78). Per-tab QA still owed for Pipeline / Workbench / Suppressed / Sources.

7. **First voice-regression nightly run.** 2026-05-13 09:00 UTC. If red, the email lands at `andrew.puschel@gmail.com`. Recent manual runs were 12/12 in ~1:32; nightly is the first cron against merged voice.

---

## Memory hooks to honor (don't repeat past mistakes)

- **JSON-output prompt contracts** (`feedback_prompt_json_contract`) — Imperative process steps ("count chars, identify clause, remove, recount") in a strict-JSON system prompt leak as visible reasoning into the model output. Iter 4 of voice work broke 5/12 fixtures this way. Keep guidance **declarative**: state the constraint, not the procedure.
- **Attenborough/Economist voice** (`feedback_voice_bigger_picture`) — Each data point goes inside a system the reader doesn't fully see. Teach, don't wink. The three approved exemplars in the memory file are the calibration set.
- **Voice failures** (`feedback_voice_failures`) — Banned shapes: press-release openers, `label:value` formatting, date repetition, tier explainers, wink-kickers (`"The calendar says spring."` family).
- **Editorial bar** (`feedback_editorial_bar`) — Only tweet astounding events. Apply the "Wait, what?" test.
- **Verify the wire** (`feedback_verify_the_wire`) — For boundary changes (JSON serialization, SDK bodies, DB writes), verify the actual bytes crossing the boundary, not the in-process value. TypedDict is erased at runtime — when in doubt, dump and diff the JSON.
- **Generalize fixes** (`feedback_generalize_fixes`) — When a bug surfaces through one example (Paddock Lake, Nettles Is, FRP `8.7000001`), fix the class. Don't hardcode the example.
- **Eng-review after plans** (`feedback_eng_review_after_plan`) — After /write-plan, run /plan-eng-review on the plan doc **before** dispatching subagent-driven-development.
- **Subagent model floor** (`feedback_subagent_models`) — Never Haiku for Agent dispatches. Sonnet for routine, Opus for high-risk. Pass `model` explicitly.
- **AI PR hygiene** — PRs you/Codex author count as **your** PRs, not Andrew's. Don't leave them open over a weekend. Don't frame stale PRs as operator inattention.
- **Versioned doc filenames** (`feedback_versioned_doc_filenames`) — When regenerating a doc, use `-v2` / `-v3` / date suffix. Don't overwrite. (This brief is `-v2` for that reason.)

---

## Don't touch without re-reading

- **`src/two_bot/prompts/writer_prompt.py`** — voice prompt is freshly stable after iter-3 merge + iter-5 patches. Every word in HARD RULE and THE SIGNATURE MOVE sections was paid for in voice-regression iterations. Before editing, re-read `feedback_voice_bigger_picture`, `feedback_voice_failures`, `feedback_prompt_json_contract` and run the voice-regression manually first to establish a baseline.
- **`src/two_bot/writer.py`** retry loops — nested length-retry + JSON-parse-retry are tuned for `p^3 ≈ 0.8%` worst-case fail rate at ~$0.07/retry. Budget constants (`LENGTH_RETRY_BUDGET=2`, `JSON_PARSE_RETRY_BUDGET=1`) reflect that math. Don't widen without thinking through cost.
- **`pyproject.toml` mypy section** — the three deleted overrides (main / state / scoring) cost ~6 hours of TypedDict work. Don't re-add them. The `src.voice.generator` override is still present and **out of scope**.
- **`src/state_schema.py`** — `BotState` mirrors `DEFAULT_STATE` in `src/state.py:19`. If you add a key to DEFAULT_STATE, mirror it here in the same PR.

---

## Operator constraints (Andrew's standing rules)

- **$0 stack.** No paid services without explicit approval. (Anthropic API + Gemini API + GitHub Actions are pre-approved.)
- **Draft-only mode.** Bot writes drafts to dashboard; Andrew approves manually. No auto-posting to Twitter without explicit go.
- **No push to main.** All changes via PR. Squash-merge with `--delete-branch`.
- **Voice gate is belt-and-suspenders.** Blocking on briefing path, logging-only on synthesis path. Banned phrase → partial-record fallback, not silent ship.
- **Andrew does not code.** When a PR is authored by `andrewzp`, it was generated by Claude or Codex — frame it as AI hygiene, not operator action.
- **Subscription is Max 20x** — Sonnet 4.6 for routine, Opus only for hard problems, parallel concurrency is the throughput lever.
- **Plan before code.** Run /brainstorm → /write-plan → /plan-eng-review → /autoplan before non-trivial code. Rework is the Opus tax.

---

## Useful one-liners

```bash
# Tail the live state for kills + pending drafts
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | jq '.suppressions[-5:], .drafts[-3:]'

# Re-run voice-regression manually (~$0.20)
gh workflow run voice-regression.yml && gh run watch

# Trigger alerts run on demand
gh workflow run bot.yml -f mode=alerts && gh run watch

# Local one-shot: ingest signals + score editorially without writer call (fast)
THEHEAT_DB_PATH=/tmp/local.db python -m src.main --mode=ingest_only

# Check this brief is fresh
git log --oneline -1 -- docs/NEXT_SESSION_PROMPT_2026-05-12-v2.md
```

---

## Branch state at handoff

- `main` HEAD: `48ee110` (PR #82 merged)
- Open branches you may see: `docs-sweep-2026-05-12-end-of-day` (pending BRIEFING.md edit — abandon or finish)
- Tests: 894 passing (excluding voice_replay), mypy clean across `src/`
- Cities monitored: 638
- Pending drafts: should be 0 or 1 (depending on alerts cycle position)
- Open PRs: 0
- Voice-regression baseline: 12/12, 1:32 wall time, ~$0.20/run

If the branch `docs-sweep-2026-05-12-end-of-day` still exists with uncommitted BRIEFING.md changes, the previous session was interrupted mid-docs-sweep to write this brief. Either finish it (commit + PR + merge BRIEFING.md updates) or abandon (`git checkout main && git branch -D docs-sweep-2026-05-12-end-of-day`).

---

## First substantive task suggestion

After the orient block:

1. Verify the 18:39 UTC alerts run cleared all four #82 issues.
2. If clean, paste the daily-plan PR auto-close routine config (operator follow-up #2 above).
3. Then start on follow-up #4 (low signal-detection rate investigation) — that's the highest-leverage open question and the entire reason fire / ocean / city anomaly drafts were sparse all week.

Don't open a new feature line until the production verification is in hand.
