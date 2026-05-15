# Resume @theheat — Next Session Prompt (written 2026-05-12, revised end-of-day after PRs #78 + #80)

You are picking up work on the @theheat climate Twitter bot. This brief is dated **2026-05-12**; the next scheduled validation events are the **2026-05-13 09:00 UTC voice-regression cron** (first nightly run against the new voice prompt + length retry) and the **next bot.yml alerts cron** (first run with the FRP rounding fix from #80 — fire drafts should now survive fact-check on decimal-precision mismatch). Before doing anything else, run the **First 5 minutes** block below to ground yourself in current state.

---

## First 5 minutes — orient

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat

# 1. Confirm main and where the last session landed
git fetch && git log --oneline -10 main

# 2. Was the 09:00 UTC voice-regression cron green?
#    Last manual run before merge was 12/12 in 1:32 on 2026-05-12 04:43 UTC (PR #76).
#    The 2026-05-13 nightly is the first cron against main with the new prompt + retry guardrail.
gh run list --workflow=voice-regression.yml --limit 3 --json databaseId,conclusion,createdAt

# 3. Last 5 scheduled bot.yml runs (every-4-hours alerts + hourly auto-publish)
gh run list --workflow=bot.yml --limit 5 --json conclusion,event,createdAt

# 4. Open PRs (review #72 mypy + watch for daily-plan PR from 15:03 UTC routine)
gh pr list --state open --limit 5

# 5. Current pipeline state (pending drafts, recent kills)
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/state.json && \
  jq '{
    pending: (.drafts // [] | map(select(.status == "pending")) | length),
    pending_ids: (.drafts // [] | map(select(.status == "pending")) | map(.id)),
    recent_kills: ((.suppressions // []) | sort_by(.ts) | .[-5:] | map({ts, stage, summary})),
    last_run: (.run_history // [] | sort_by(.started_at) | last | {id, mode, failures: (.failures // [] | length)})
  }' /tmp/state.json

# 6. Local sanity: tests + lint + types
source .venv/bin/activate
python -m pytest tests/ -q -m "not voice_replay" 2>&1 | tail -3
ruff check src/ tests/ 2>&1 | tail -1
mypy src/ 2>&1 | tail -1
```

Expected (if nothing regressed since 2026-05-12):
- `main` HEAD is `4677869` (PR #80) or newer
- Voice-regression 2026-05-13 09:00 UTC: **12 passed**. If it failed, the most likely fixture is `sissonville_monthly_low_bundle` or `verkhoyansk_monthly_high_bundle` — the retry guardrail should have absorbed transient overlong drafts (p³ ≈ 0.01%), but watch for `kill_reason` mentioning "writer produced over-280-char tweets across 3 attempts" which would mean the writer is consistently producing oversized tweets on that fixture and needs a fresh exemplar.
- bot.yml runs: all SUCCESS. **Watch the first alerts run with PR #80 merged** — fire drafts should now survive the fact-checker on FRP precision (BUNDLE_FACT kills on `480.34 → 480` should be gone). If fire drafts still kill, classify: other BUNDLE_FACT class (likely station-name normalization per PR #79's P1), or WORLD_KNOWLEDGE class (named-facility fabrication should already be banned by #74's HARD RULE).
- 884 tests passing, lint + mypy clean
- 7 pending drafts (was 8 before #156 Mankato was killed)

---

## State as of end-of-session 2026-05-12

Read these in order. They build on each other.

1. **`BRIEFING.md`** — project front matter. Top section reflects today's voice overhaul + dashboard refresh fix + FRP rounding. Latest commits, test count (884), open PRs (#72 mypy, #73 daily-plan-05-11, #77 this docs sweep, #79 daily-plan-05-12).
2. **`docs/SESSION_BRIEF.md`** — top section is **2026-05-11/12 — Voice overhaul: Attenborough/Economist + code-side length guardrail + dashboard refresh + FRP rounding**. Read at least that section.
3. **`CHANGELOG.md`** — most recent entry is `[0.5.0.0] - 2026-05-12`.

Key facts:

- **Voice rewritten.** The writer prompt at `src/two_bot/prompts/writer_prompt.py` is now anchored to **David Attenborough or The Economist**: report the precise data, name the system that produces it, stop. No wink-kickers ("It's May.", "Calendar says spring.", "A record is a record." — banned by *shape* not just literal phrase). No self-supplied facility MW comparisons (after observed Hoover Dam + Akosombo Dam fabrications). 6 approved exemplars are in the prompt.
- **Code-side 280-char guarantee.** `write_tweet()` retries up to 2x if the model returns >280 chars (declarative feedback in user prompt). After 3 failed attempts, returns KILL with explicit `kill_reason`. **Twitter never sees a >280-char string from this pipeline** regardless of model stochasticity. Cost: ~$0.30/voice-regression run extra.
- **Fire FRP rounded at the bundle (NEW 2026-05-12 afternoon).** `src/two_bot/intern.py:build_fire_bundle` now does `round(fire.frp, 1)` for both `headline_metric.value` and `raw_signal_dump.frp`. Closes the BUNDLE_FACT kill class where writer rounding `480.34 → 480` mismatched the raw bundle value. The fact-check prompt still enforces exact match — the fix puts the normalized value upstream so exact match holds naturally. Codex on PR #79 caught the original "writer-side rule + claimed tolerance" plan as internally inconsistent (no tolerance in the live fact-checker); revised plan + implementation is in #80.
- **Dashboard refresh button now gives feedback (NEW 2026-05-12 afternoon).** Was silently doing the right thing (5 API calls firing in ~60ms) but the button stayed labeled "refresh" the whole time and errors went to `console.error`. PR #78 added three states: `refreshing` (drives "refreshing…" label + disabled + orange tint), `lastUpdated` (renders "updated 5s ago"), `refreshError` (orange "refresh failed" pill with hover-tooltip error). Live on Vercel after deploy.
- **Pending drafts may still have old-voice wink-kickers.** Drafts #154 (Imperial: "weeks before summer solstice") and #158 (Point Lay: "The calendar says spring.") were generated under the *old* prompt. They're still in the pending queue as of session end. Decision deferred: kill them so the next bot.yml run regenerates under the new voice, or let them ship and let Andrew compare.
- **Dashboard URL.** `https://dashboard-andrew-puschels-projects.vercel.app` (HTTP Basic Auth — credentials in Vercel env vars `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`, not in repo). For local dev: `cd dashboard && npx next dev -p 3030` (3030 without auth — dev-mode bypass when env vars are empty).
- **Dashboard QA partial.** Refresh button is now fixed (#78). Dashboard verified to render cleanly (dark monospace, 5 tabs: Dashboard / Pipeline / Workbench / Suppressed / Sources). Per-tab exploration (Pipeline / Workbench / Suppressed / Sources) was not completed. Resume with `/qa the dashboard` when ready.
- **Memory hook added 2026-05-12:** [feedback_prompt_json_contract](../memory/feedback_prompt_json_contract.md) — when a prompt requires strict-JSON output, **imperative process language** ("count chars, identify clause, remove, recount, repeat") leaks into the response as reasoning text *before* the JSON, breaking the parser. Keep all guidance **declarative**. The iter-4 PR-#74 trap and the original P2 IMPROVEMENT_PLAN text both fell into this trap; both were caught by external review (voice-regression + Codex respectively).

---

## Outstanding follow-ups (carry forward if no new priority lands)

### 1. Review + merge PR #72 (mypy ignore-list removal via BotState TypedDict)

**Status:** OPEN, CI green, never reviewed. Authored on a previous session; ready to merge.

Removes `ignore_errors = true` overrides for `src.main`, `src.state`, `src.editorial.scoring` in `pyproject.toml`. Adds `src/state_schema.py` with a `BotState` TypedDict + nested types (`Hot10Snapshot`, `MemoryState`, `SynthesisComponents`, `CityRecord`, `IceMassLoss`, `DroughtSnapshot`, `RecordStreakEntry`, `StreakEntry`, `OceanSSTStreak`). Propagates annotations through `state.py`, `main.py`, `scoring.py`, `editorial/synthesis.py`, `two_bot/{memory,fact_check,pipeline}.py`. 147 previously-hidden errors → 0. Includes a `TestBotStateSchemaRoundTrip` to guard against future drift between `DEFAULT_STATE` and `BotState`.

To review:

```bash
gh pr view 72 --json title,body,statusCheckRollup,files
gh pr diff 72 --color | head -200
```

To merge:

```bash
gh pr merge 72 --squash --delete-branch
```

### 2. Decide on pending drafts #154 (Imperial) and #158 (Point Lay)

Both were generated under the old prompt and have wink-kicker text the new voice would now reject:
- #154: ends with "weeks before summer solstice"
- #158: ends with "The calendar says spring."

Options:
- **Kill both** (so the next bot.yml alerts run regenerates them under the new voice). Same machinery as the #156 Mankato kill on 2026-05-11:
  ```bash
  GITHUB_TOKEN=$(gh auth token) GIST_ID=06c02c97ffc0d11458687f1ed998d9e5 \
    python -c "
  import os
  os.environ['THEHEAT_STATE_BACKEND'] = 'gist'
  from src.state import read_state, write_state
  from datetime import datetime, timezone
  s = read_state()
  for d in s['drafts']:
      if d.get('id') in ('draft_20260509_165940_154', 'draft_20260511_034142_158'):
          d['status'] = 'rejected'
          d['kill_stage'] = 'manual_editorial'
          d['kill_reason'] = 'Old-voice wink-kicker; voice overhaul 2026-05-12 raises bar'
          d['updated_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
  write_state(s)
  "
  ```
- **Ship them as-is** and use them to A/B against the next batch under the new voice.

Andrew's preference last session leaned toward letting them ride and comparing voices side-by-side. Defer until he weighs in.

### 3. Watch the first bot.yml alerts run after #80 merged

PR #80 rounded fire FRP at the bundle so the writer naturally echoes the bundle's 1-decimal value and the fact-checker confirms exact match. The class of BUNDLE_FACT kills on `480.34 → 480` should be gone. Check the next alerts run:

```bash
gh run list --workflow=bot.yml --limit 3 --json conclusion,createdAt
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json | jq '.suppressions | map(select(.stage == "fact_check")) | sort_by(.ts) | .[-5:] | map({ts, summary, score_total})'
```

If fire drafts still kill at fact_check, classify the failure:
- **BUNDLE_FACT on station-name** — PR #79's P1 (apply `normalize_station_name()` to bundle fields in `src/two_bot/intern.py` GHCN builders). Different fix from #80.
- **WORLD_KNOWLEDGE on named-facility comparison** — writer is fabricating again despite #74's ban. Tighten the prompt's HARD RULE.
- **Other category** — investigate.

### 4. Finish the dashboard QA

The refresh button is now fixed (#78). Per-tab exploration is still incomplete (Pipeline / Workbench / Suppressed / Sources). To resume:

```bash
cd dashboard && (npx next dev -p 3030 > /tmp/dashboard.log 2>&1 &) && sleep 6
# Then drive with the browse tool, snapshot each tab, document issues
```

Per `/qa` Standard tier: fix critical + high + medium issues with atomic commits; mark low as deferred. WTF-likelihood self-regulation applies.

### 5. Implement remaining IMPROVEMENT_PLAN items from PR #79

The 2026-05-12 grading agent revised the plan in commit `dcc6848`. P2 (FRP rounding) is merged via #80. Other priorities still open:
- **P1: station-name normalization in GHCN bundles.** `_build_monthly_high_bundle`, `_build_record_bundle`, `_build_all_time_record_bundle`, `_build_anomaly_bundle` in `src/two_bot/intern.py` — apply `normalize_station_name()` to `where` and `station_name` fields before bundle hits the writer. Suffixes like "Paddock Lake 4 Ne" survive into fact-check today and BUNDLE_FACT-kill.
- **P3: seasonal/calendar context as a verifiable framing for fires.** Writer kills fire drafts citing "no historical_context; no peer comparison; no verifiable seasonal or rarity framing." But "The burning season in [region] peaks in [month]" is world-knowledge-level. One paragraph addition to the writer prompt's fire framing section.
- **P4: Wodehouse rule for the new prompt.** Already partially landed in the Attenborough/Economist voice (no winks, no flourishes). Worth a pass to verify the explicit rule lives at the top of the new prompt.

### 6. Coverage gap for Southern Africa (carry-forward from 2026-05-11 review)

When Andrew was reviewing the morning's tweet drafts on 2026-05-11, he flagged a Mozambique 38°C event (Chitima, Caia, Inhambane) that our bot didn't capture. We monitor 4 Mozambique cities (Beira, Maputo, Matola, Nampula) but not the three the @extremetemps account flagged. Inhambane is a ~80k-pop coastal city — real gap.

Scope: add Inhambane MZ + 4-6 other Southern Africa cities in the GFS-red anomaly band (Polokwane SA, Bulawayo ZW, etc.) to `data/cities.csv`. Cost ~$0 (Open-Meteo is free, marginal API calls negligible). Worth a small PR.

### 7. Investigate low signal-detection rate

Latest alerts run (2026-05-11 21:20 UTC) saw only **2 open_meteo extreme signals** across 613 cities. That's low for a continental-scale anomaly day (the North America dipole was active and several other regions were running hot). Either threshold tuning is too strict, the data fetch is partial, or this is an off-day. Worth a half-hour investigation.

---

## Operating constraints (carried from prior sessions)

- **It's a utility, not a business.** Don't propose growth hacks, character voice, or engagement optimization. The data IS the product.
- **$0 stack is hard.** Current recurring: ~$13/mo Sonnet writer + **~$9/mo nightly voice-regression replay** (up from $6 after #76's length retry adds ~$0.30/run worst case) + ~$60-90/mo Sonnet evaluator. Anything new gets explicit confirmation.
- **Drafts are not auto-posted.** Bot is in draft-only mode pending the corpus-A-rate resumption bar (set 2026-04-26 in `docs/QUALITY_TREND.md`).
- **Don't push to main.** Branch + PR. Branch protection enforces this regardless.
- **Voice gates are belt-and-suspenders.** Writer prompt is primary; safety regex is failsafe; the new length retry is a code-side hard cap. Don't reduce coverage at any layer without surfacing the trade-off explicitly.

---

## If the user opens with…

| User input | Default response |
|---|---|
| "how are we looking?" | Run First-5-minutes block, summarize crisply (CI status + pending drafts + recent kills + voice-regression state). |
| "what should we work on?" | Suggest Outstanding follow-ups in priority order: PR #72 review/merge → decide on #154/#158 wink-kicker drafts → resume dashboard QA → Southern Africa coverage. |
| "fix X" | Branch off main, TDD-shape it (failing test → impl → green), PR with green CI. |
| "voice-regression is failing again" | Read the failed run's log via `gh run view <id> --log-failed`. Classify: (a) `kill_reason` "writer produced over-280-char tweets across 3 attempts" → consistent oversize on a fixture, add a tighter exemplar for that signal_kind; (b) `ValueError: invalid JSON in model response` → check for any imperative process language that crept into the writer prompt (see memory hook feedback_prompt_json_contract); (c) wink-kicker leaked → tighten the shape ban with the specific new phrasing; (d) banned phrase from safety regex → was the prompt edit too permissive, or is the regex too tight? |
| "merge X" | Confirm CI green via `gh pr view N --json statusCheckRollup`, squash-merge with `--delete-branch`, sync local main. |
| "/qa the dashboard" | Resume from where 2026-05-12 left off. Local dev on `:3030`. URL `https://dashboard-andrew-puschels-projects.vercel.app` (Basic Auth in Vercel env). |

---

## Files to never touch without explicit ask

Per project memory:
- `brand/VOICE.md`, `brand/MESSAGING_ARCHITECTURE.md`, `brand/HUMOR_RESEARCH.md`, `brand/EXEMPLARS.md`, `brand/VIRALITY_RESEARCH.md`, `brand/VOICE_PATTERNS.md` — spec docs, owned by Andrew.
- `data/era_anchors.json` content — only `_meta.audit_history` may be appended.
- `src/voice/generator.py` prompt strings and `_STOCK_FORMULA_PATTERNS` regex — only with explicit ask. (Note: this is the LEGACY voice generator. `main.py` flags it as "voice gen no longer reachable" — the active writer is `src/two_bot/writer.py` calling `src/two_bot/prompts/writer_prompt.py:WRITER_SYSTEM_PROMPT`.)
- `src/two_bot/prompts/writer_prompt.py:WRITER_SYSTEM_PROMPT` — heavily curated by today's session. Edits should be **declarative only** (no imperative process steps; see memory hook). Use `voice-check` label on PRs to trigger voice-regression.

---

## Memory hooks the user expects you to honor

- **Subagent model floor** — Sonnet 4.6 default for Agent dispatches. Opus only for high-risk reasoning.
- **Plan before code** — for non-trivial code, brainstorm → write-plan → eng-review first.
- **Verify the wire** — for boundary-layer changes (JSON serialization, SDK request bodies), verify the actual bytes that cross.
- **Editorial bar** — only tweet astounding events. Apply the "Wait, what?" test.
- **Attenborough/Economist voice** (added 2026-05-11) — place each data point inside the system the reader doesn't fully see; teach, don't wink.
- **Bigger picture kicker** (same) — every tweet's last beat must explain stakes / pattern / climate arc, not wink at facts.
- **JSON-output prompt contracts** (added 2026-05-12) — imperative process steps leak into strict-JSON output; keep prompt guidance declarative.
- **Versioned doc filenames** — never overwrite a regenerated doc; date-suffix it (this file is the canonical example).
- **Verify subagent file claims** — spot-check file/dir/symbol names from agents with grep/ls before relaying to user.
- **URL-first walkthroughs** — for any external UI task, lead with a deep-link.
