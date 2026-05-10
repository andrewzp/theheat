# Resume @theheat — Next Session Prompt (written 2026-05-10)

You are picking up work on the @theheat climate Twitter bot. This brief is dated **2026-05-10**; the next scheduled validation event is **2026-05-11 09:00 UTC** (nightly voice-regression cron). Before doing anything else, run the **First 5 minutes** block below to ground yourself in current state.

---

## First 5 minutes — orient

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat

# 1. Confirm main and where the last session landed
git fetch && git log --oneline -8 main

# 2. Was the 09:00 UTC voice-regression cron green?
gh run list --workflow=voice-regression.yml --limit 3 --json databaseId,conclusion,createdAt

# 3. Last 5 scheduled bot.yml runs (every-4-hours alerts + hourly auto-publish)
gh run list --workflow=bot.yml --limit 5 --json conclusion,event,createdAt

# 4. Open PRs (especially auto-opened daily-plan PR from 15:03 UTC routine)
gh pr list --state open --limit 5

# 5. Current pipeline state (pending drafts, recent kills)
gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/state.json && \
  jq '{
    pending: (.drafts // [] | map(select(.status == "pending")) | length),
    recent_kills: ((.suppressions // []) | sort_by(.ts) | .[-5:] | map({ts, stage, summary})),
    last_run: (.run_history // [] | sort_by(.started_at) | last | {id, mode, failures: (.failures // [] | length)})
  }' /tmp/state.json

# 6. Local sanity: tests + lint + types
source .venv/bin/activate
python -m pytest tests/ -q -m "not voice_replay" 2>&1 | tail -3
ruff check src/ tests/ 2>&1 | tail -1
mypy src/ 2>&1 | tail -1
```

Expected (if nothing regressed since 2026-05-10):
- `main` HEAD is `1ed7e2c` (PR #68) or newer
- Voice-regression cron 2026-05-11 09:00 UTC: **12 passed** (no false positives — that's the verification of PR #67/#68)
- bot.yml runs: all SUCCESS
- 876+ tests passing, lint + mypy clean

---

## State as of end-of-session 2026-05-10

Read these in order. They build on each other.

1. **`BRIEFING.md`** — project front matter. Shows latest commits, test count, branch-protection state, cost.
2. **`docs/SESSION_BRIEF.md`** — top section is 2026-05-10 (cron-feedback-loop). Read at least that section.
3. **`CHANGELOG.md`** — most recent entry is `[0.4.1.0] - 2026-05-10`.

Key facts:

- **Pipeline working end-to-end.** All 5 streams from 2026-05-09's ship-quality session are live (PRs #55-#65). 2026-05-10's session was a feedback loop: voice-regression caught 3 real false-positives on first run; both regexes tightened in #67/#68.
- **Branch protection on `main`** requires the `test` status check. Direct push blocked. Andrew (admin) can bypass for emergencies.
- **Voice-regression harness** runs nightly at 09:00 UTC against real Anthropic Sonnet. ~$6/mo. **The feedback loop is real** — the harness paid for itself on day one.
- **Daily-plan grading-agent** (routine `trig_016PGeHZgEYWmeQhx1xGmYg6`) was failing on a public-API rate limit. Repaired out-of-tree on 2026-05-10. Validates at 15:03 UTC each day. [Routine UI](https://claude.ai/code/routines/trig_016PGeHZgEYWmeQhx1xGmYg6).

---

## Outstanding follow-ups (carry forward if no new priority lands)

### 1. Parallel-session WIP in working tree (don't sweep up by accident)

When you arrive, `git status` may show modifications to files **you did not edit**. These belong to another session/lane and are NOT in scope unless the user explicitly asks. Specifically:

- `.github/workflows/bot.yml` (Node setup + dashboard test/build steps)
- `dashboard/app/api/source-health/route.js`
- `dashboard/lib/state-store.js`
- `dashboard/tests/source-health.test.js`
- `dashboard/tests/state-store.test.js`
- `docs/codex-review-findings-2026-05-08.md`
- `src/data/source_status.py`
- `tests/voice_regression/test_writer_replay.py`
- Untracked Finder duplicates like `"route 2.js"` / `"test 2.js"` in dashboard/

Leave them be. If a commit is needed, stage only YOUR specific files. Check with the user before merging any of these into your PRs.

### 2. Mypy ignore-list reduction (~3 modules)

`pyproject.toml` has `ignore_errors = true` for three modules pending a `bot_state` TypedDict refactor:
- `src.main` (47 errors)
- `src.state` (68 errors)
- `src.editorial.scoring` (47 errors)

Largest single-PR effort available. Would unlock real type coverage across the orchestrator. Tradeoff: ~2-3 hours, touches a lot of files, but each fix is mechanical.

### 3. Bundle payload in suppression records

Right now, suppression records carry `event_id` + score but not the full `StoryBundle` that produced them. Persisting the bundle would let the voice-regression corpus pull from **real-killed bundles** instead of hand-curated fixtures — much higher-fidelity drift detection. Schema change to `bot_state.suppressions`.

### 4. Validate the grading-agent routine fix

The routine's next run is **2026-05-11 15:03 UTC**. After that fires:

```bash
gh pr list --state open --search "daily-plan" --limit 1
```

If a `daily-plan-2026-05-11` PR opens with real drafts graded (not "0 drafts, access failure"), the fix worked. If it opens with another infra-failure note, look at the PR body — Step 2's new `git clone` path should give a specific FATAL message that points to what's still broken (network blocked from Anthropic cloud? gist URL changed? auth scope?).

---

## Operating constraints (carried from prior sessions)

- **It's a utility, not a business.** Don't propose growth hacks, character voice, or engagement optimization. The data IS the product.
- **$0 stack is hard.** Current recurring: ~$13/mo Sonnet writer + ~$6/mo nightly voice-regression + ~$60-90/mo Sonnet evaluator. Anything new gets explicit confirmation.
- **Drafts are not auto-posted.** Bot is in draft-only mode pending the corpus-A-rate resumption bar (set 2026-04-26 in `docs/QUALITY_TREND.md`).
- **Don't push to main.** Branch + PR. Branch protection enforces this regardless.
- **Voice gates are belt-and-suspenders.** Writer prompt is primary; safety regex is failsafe. Don't reduce coverage at either layer without surfacing trade-off explicitly.

---

## If the user opens with…

| User input | Default response |
|---|---|
| "how are we looking?" | Run First-5-minutes block, summarize crisply (CI status + pending drafts + recent kills + voice-regression state). |
| "what should we work on?" | Suggest Outstanding follow-ups in priority order (validate yesterday's fix → mypy reduction → bundle in suppressions). |
| "fix X" | Branch off main, TDD-shape it (failing test → impl → green), PR with green CI. |
| "voice-regression is failing again" | Read the failed run's log via `gh run view <id> --log-failed`, find the assertion + tweet text, classify (true positive → fix prompt/writer; false positive → tighten safety regex like #67/#68). Use `tests/test_safety.py::TestMonthRepetition` as the pattern template. |
| "merge X" | Confirm CI green via `gh pr view N --json statusCheckRollup`, squash-merge with `--delete-branch`, sync local main. |

---

## Files to never touch without explicit ask

Per project memory:
- `brand/VOICE.md`, `brand/MESSAGING_ARCHITECTURE.md`, `brand/HUMOR_RESEARCH.md`, `brand/EXEMPLARS.md`, `brand/VIRALITY_RESEARCH.md`, `brand/VOICE_PATTERNS.md` — spec docs, owned by Andrew.
- `data/era_anchors.json` content — only `_meta.audit_history` may be appended.
- `src/voice/generator.py` prompt strings and `_STOCK_FORMULA_PATTERNS` regex — only with explicit ask.

---

## Memory hooks the user expects you to honor

- "Subagent model floor" — Sonnet 4.6 default for Agent dispatches. Opus only for high-risk reasoning.
- "Plan before code" — for non-trivial code, brainstorm → write-plan → eng-review first.
- "Verify the wire" — for boundary-layer changes (JSON serialization, SDK request bodies), verify the actual bytes that cross.
- "Editorial bar" — only tweet astounding events. Apply the "Wait, what?" test.
- "Versioned doc filenames" — never overwrite a regenerated doc; date-suffix it (this file is the canonical example).
- "Verify subagent file claims" — spot-check file/dir/symbol names from agents with grep/ls before relaying to user.
- "URL-first walkthroughs" — for any external-UI task, lead with a deep-link.
