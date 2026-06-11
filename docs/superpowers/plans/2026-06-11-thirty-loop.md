# THIRTY-LOOP — Autonomous Execution Plan for the 2026-06-10 Audit Backlog

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan step-by-step (inline execution; do NOT use subagent-driven-development — this plan is optimized for a budget-constrained single session per tranche). Steps use checkbox (`- [ ]`) syntax tracked in the companion file `2026-06-11-thirty-loop-PROGRESS.md`.

**Goal:** Ship all 30 improvements from the 2026-06-10 full-codebase audit as a sequence of 35 independently-mergeable PRs, with zero human input except where this plan explicitly says STOP.

**Architecture:** A serial loop. Each iteration = one step = one branch = one PR = one squash-merge, in the dependency order of §6 (NOT the audit's size order). Measurement substrate ships first (T0), then transport hardening (T1), structure (T2), state safety (T3), cycle (T4), editorial supply (T5), publishing surface (T6), long tail (T7). Follower-visible *behavior* changes ship dark behind env flags (default off); follower-visible *draft content* changes ship live because every draft passes Andrew's manual approval queue.

**Tech stack:** Python 3.12 (src/, pytest, mypy, ruff), Next.js dashboard (node --test), GitHub Actions CI, gist-backed state, Codex CLI for cross-model review.

**Source of truth for "why":** the audit report (30 items + outage plan). The plan below restates everything the executor needs; the audit is background only.

---

## §0 Executor contract — read this first, every session

1. You are executing THIS plan. Do not re-audit, re-plan, re-rank, or expand scope. Every decision you might be tempted to make is either pre-made in §9 or marked STOP.
2. **Budget discipline (the reason this plan exists):** do NOT launch exploration/Explore subagents. Do NOT read files not named in the current step. The plan contains the map (§B facts file). Read only: the step spec, the files it names, and the tests you touch. One step at a time.
3. **Resume protocol:** every session starts with: read `docs/superpowers/plans/2026-06-11-thirty-loop-PROGRESS.md`, pick the first row with status `TODO` whose `deps` are all `DONE`, run the §2 preflight, execute that step. Fresh session per tranche is recommended; per step is fine.
4. Line numbers in this plan are anchors **as of main @ 0.9.23.0 (`a58a02c`)**. They WILL drift as steps land. Every anchor has a grep pattern — trust the grep, not the number.
5. When a step says **STOP**, write the requested note into PROGRESS.md, set status `BLOCKED(<reason>)` or `AWAITING-ANDREW`, and move to the next eligible step. Never improvise past a STOP.
6. Each step's PR includes the PROGRESS.md row update (status → `DONE`, PR number filled in) in the same commit. The loop's state lives in git, nowhere else.

## §1 Production rails — NEVER list (verbatim, no exceptions)

- NEVER push to `main`. Everything ships via PR. `gh pr checks <N> --watch` must show `test pass` before merge; merge is `gh pr merge <N> --squash --delete-branch`; then `git checkout main && git pull`.
- NEVER disable, rename, or edit the triggers of the 4 active workflows (`theheat-bot`, `refresh-thresholds`, `voice-regression`, `source-health-sentinel`) except where a step explicitly specifies the exact edit.
- NEVER set `THEHEAT_REGANOM_ENABLED`. Never flip posting mode. Never call `gh variable set` for any variable unless a step explicitly says so (none do).
- NEVER edit the production gist (`gh gist edit`) by hand. State changes happen only through code the bot runs.
- NEVER weaken the editorial bar: no threshold lowering, no banned-pattern removal, no fact-check loosening, no critic disabling. The critic kill-switch is for Andrew.
- NEVER regenerate `tests/fixtures/merge_state_golden.json` casually. Regeneration (`source .venv/bin/activate && python scripts/gen_merge_golden.py`) is allowed ONLY in steps S-15/S-16/S-17 which intentionally change merge semantics, and the fixture diff MUST be summarized key-by-key in the PR body.
- NEVER change the Python sentinel classifier (`scripts/source_health_sentinel.py`) without making the mirror change to the JS classifier (`dashboard/lib/source-health.js`) in the same PR, and vice versa. Both test suites lock the contract.
- The writer/critic/fact-check prompts: keep guidance DECLARATIVE (constraints, examples), never imperative multi-step process instructions — imperative process steps leak into strict-JSON output (established failure mode).
- All Bash for this repo: `cd /Users/andrewpuschel/Documents/Claude/theheat` explicitly in every command (background shells reset cwd). Python commands need `source .venv/bin/activate` first.
- Permission note: PR merges and `vercel --prod` after dashboard-touching PRs are pre-authorized by Andrew for this loop (see kickoff prompt, §A).

## §2 The loop protocol — every iteration, in order

```bash
# PREFLIGHT (run all; abort the iteration if any fails — fix main first or STOP)
cd /Users/andrewpuschel/Documents/Claude/theheat
git checkout main && git pull
source .venv/bin/activate
python -m mypy src/ 2>&1 | tail -1                                  # expect: Success: no issues found
python -m pytest tests/ -q -m "not voice_replay" --tb=line 2>&1 | tail -1   # expect: all passed
(cd dashboard && node --test 2>&1 | grep -E '^# (pass|fail)')        # expect: fail 0
# Production health (--json is REQUIRED; without it -q errors and 2>/dev/null fakes an all-clear):
gh issue list --state open --label source-health-sentinel --json number,title,labels \
  -q '.[] | "#\(.number) [\(.labels|map(.name)|join(","))] \(.title)"'
```
- If a sentinel issue is open with label `ours` or `unknown`: **fix that first** (it outranks the loop — diagnose, ship the fix as an unplanned PR using §3 mechanics, then resume). Label `external`: note it in PROGRESS.md, continue.
- If preflight tests fail on a clean main: STOP, status `BLOCKED(main-red)`, write diagnosis.

```text
ITERATE:
 1. Pick step (first TODO with deps DONE).
 2. Branch: git checkout -b loop/s<NN>-<slug>
 3. For steps marked [MINI-PLAN]: invoke superpowers:writing-plans and write the line-level
    task list for THIS step into the PR description draft (not a new file), using the step
    spec as the requirements. Then execute it with TDD.
    For all other steps: follow the inline spec directly (tests first where tests are specified).
 4. Implement. Run the step's GATES (every step lists them). All must pass.
 5. For steps marked [CODEX]: run the §5 review, address P0/P1 findings, note them in the PR body.
 6. Bump VERSION (next minor: 0.9.24.0, 0.9.25.0, ... one per PR), add CHANGELOG entry (§3 format).
 7. Update PROGRESS.md row (DONE, PR #, one-line note). Same commit or same PR.
 8. Commit (§3 format), push, open PR (§3 template), gh pr checks <N> --watch, squash-merge,
    git checkout main && git pull.
 9. If the PR touched dashboard/: (cd dashboard && vercel --prod), then
    curl -s -o /dev/null -w "%{http_code}" https://dashboard-phi-beryl-65.vercel.app  → expect 401.
10. Next iteration.
```

## §3 Shipping mechanics (exact)

- **Branch:** `loop/s<NN>-<slug>` e.g. `loop/s07-http-jitter-session`.
- **VERSION:** single line file at repo root. Read current, bump third segment by 1 (e.g. `0.9.23.0` → `0.9.24.0`). One bump per PR, no exceptions, including docs-only PRs.
- **CHANGELOG.md:** insert ABOVE the previous top entry, exactly this shape:

```markdown
## [0.9.NN.0] - <YYYY-MM-DD>

<One-paragraph prose summary: what changed and why it matters.>

### Changed

- **<Headline>.** <2-4 sentences of specifics with file names.>
```

- **Commit message:** `<type>(<area>): <summary> (0.9.NN.0)` + body explaining what/why/verification. Types: `feat`, `fix`, `refactor`, `test`, `docs`, `ci`. End with the Claude Code co-author trailer your harness specifies.
- **PR body template:**

```markdown
## What
<bullets>
## Why
THIRTY-LOOP step S-NN (audit item #X). <one line>
## Verification
<each gate command + its actual observed output line>
## Codex review (if [CODEX])
<findings + dispositions>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- **Merge:** `gh pr checks <N> --watch` (the repo requires the `test` check; `--auto` is disabled at repo level) then `gh pr merge <N> --squash --delete-branch && git checkout main && git pull`.
- **PR size rule:** if a step's diff exceeds ~600 changed lines excluding tests/fixtures/docs, split it at the spec's marked seam into `S-NNa`/`S-NNb` PRs (add a PROGRESS row for the split).

## §4 Universal verification gates (every PR, in addition to per-step gates)

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat && source .venv/bin/activate
python -m ruff check src/ tests/ scripts/
python -m mypy src/ 2>&1 | tail -1
python -m pytest tests/ -q -m "not voice_replay" --tb=short 2>&1 | tail -2
cd dashboard && node --test 2>&1 | grep -E '^# (tests|pass|fail)' && npm run build 2>&1 | tail -3
```
All green, no skipped-because-broken. New code: mypy-clean (no `# type: ignore` unless the step says so), tests added per step.

## §5 Codex outside-voice protocol (steps marked [CODEX])

```bash
cd /Users/andrewpuschel/Documents/Claude/theheat && PATH=/opt/homebrew/bin:$PATH codex exec -s read-only \
"Review the uncommitted diff (git diff main) for step <S-NN> of docs/superpowers/plans/2026-06-11-thirty-loop.md. \
Spec: <paste the step's Spec block>. Find REAL flaws only: value bugs, contract violations \
(MERGE_SPEC/state, sentinel JS-Python sync, voice gates), missed failure modes, test gaps. \
Verify against code. Numbered findings with severity P0/P1/P2 + file:line + one-line fix. Max 8." 2>&1 | tail -40
```
P0: must fix before merge. P1: fix or rebut in PR body. P2: optional. If codex CLI is unavailable (command not found / auth error): note `codex-unavailable` in the PR body and proceed — do not block the loop on it.

## §6 Execution queue

| Step | Audit item | Title | Size | Deps | Flags |
|---|---|---|---|---|---|
| S-01 | #30a | Dead `drafted` plumbing + per-source drafted credit | S | — | |
| S-02 | #30b | pytest config, README, PIPELINE.md glossary, critic passthrough, action versions | S | — | |
| S-03 | #27 | Dashboard truth fixes (todayCount, stateError, staleness, funnel label) | S | — | deploy |
| S-04 | #29 | Sentinel 403 classification (Python + JS, in sync) | S | — | deploy |
| S-05 | #13 | error_class telemetry + alerts-lane liveness + `if: failure()` alarm | M | S-04 | [CODEX] |
| S-06 | #14 | Sentinel stale-success / zero-yield detection | M | S-05 | |
| S-07 | #1a | `_http.py`: jitter + shared Session + pooling | S | — | [CODEX] |
| S-08 | #1b | Migrate all bare `requests.get` callers to `fetch_with_retry` | M | S-07 | |
| S-09 | #1c | WAF-aware 403/429 retry (host-scoped) + unify gpm per-city retry | M | S-07 | [CODEX] |
| S-10 | #20 | Conditional requests (ETag/Last-Modified) for static CSV sources | M | S-08 | |
| S-11 | #8 | Decompose `common.py` (mechanical move + shim) | L | S-08 | [MINI-PLAN] [CODEX] |
| S-12 | #4a | gpm chain `datapool→s3→opendap` + creds pre-mint | M | S-09 | [CODEX] |
| S-13 | #4b | GDACS GeoRSS fallback + mirror survey doc | M | S-09 | |
| S-14 | #3a | `assert_freshness` rollout to unguarded sources | M | S-06 | |
| S-16 | #10 | Record-store caps + state pruning (MERGE_SPEC care) | L | — | [MINI-PLAN] [CODEX] |
| S-15 | #3b | Last-good cache for slow movers (provenance + compactness) | L | S-14, S-16 | [MINI-PLAN] [CODEX] |
| S-17 | #12 | Double-post hardening: durable tweet_id + optimistic gist lock | M | — | [CODEX] |
| S-18 | #21 | SQLite backend CI smoke (wire, don't delete) | S | — | |
| S-19 | #28 | Dashboard payload trim + visibility-gated polling | M | S-03 | deploy |
| S-20 | #7 | DAG-concurrent source execution + per-source budgets + breaker | L | S-05, S-08, S-11 | [MINI-PLAN] [CODEX] |
| S-21 | #23 | Orchestrator test gaps (co_ops/nifc/marine) + voice fixtures | M | — | |
| S-22 | #2 | Multi-draft best-of + critic REVISE (both flag-gated, default off) | L | S-21 | [MINI-PLAN] [CODEX] |
| S-23 | #16 | Coral reef-system angle library | M | S-21 | |
| S-24 | #17 | Record margin-percentile bundle fact | M | S-21 | |
| S-25 | #15 | Air-quality ground-station corroboration (OpenAQ) | M | S-08 | |
| S-26 | #19 | air_quality fan-out redesign (chunk spreading) | M | S-09 | |
| S-27 | #6 | Synthesis expansion: global fire-drought-heat + SST×coral | L | S-21 | [MINI-PLAN] |
| S-28 | #24 | Reganom activation readiness runbook (NO flip) | S | — | |
| S-29 | #26 | Hot 10 audience-unit fix | S | — | |
| S-30 | #25 | Inter-tweet spacing guard | S | — | |
| S-31 | #22 | Cyclone advisory source links | S | S-21 | |
| S-32 | #18 | Engagement-window scheduling (flag, default off) | M | S-30 | |
| S-33 | #9 | Hot 10 image card + alt text (flag, default off) | L | S-29 | [MINI-PLAN] [CODEX] |
| S-34 | #5 | Engagement metrics ingestion (flag; API-tier decision rule) | M | S-17 | |
| S-35 | #11 | Dashboard component extraction (page.js remainder) | L | S-19 | [MINI-PLAN] |

Work the queue top to bottom, skipping any step whose deps aren't all DONE yet — §0's pick rule (first TODO whose deps are all DONE) is authoritative, and a skipped step is simply picked up on a later pass. The queue order above already places dependencies before dependents.

---

## §7 Step specifications

> Format per step: **Why** (one line) · **Files** · **Spec** · **Tests** · **Gates** · **Traps**. Code blocks are real code to use; "named tests" are tests you must write (TDD: write them failing first). Grep anchors are authoritative over line numbers.

### S-01 (#30a) Dead `drafted` plumbing + per-source drafted credit — S

**Why:** every source runner reports `drafted=0` forever, so the per-source funnel is unmeasurable and the dashboard's per-source contribution metric lies.

**Files:** all 22 `src/orchestrator/sources/*.py`; `src/orchestrator/run_alerts.py`; `src/orchestrator/common.py` (`_bump_source_drafted_in_run`, grep `def _bump_source_drafted_in_run`); tests `tests/test_run_alerts.py` (create if absent).

**Spec:** Post-triage-migration, drafting happens in `_drain_and_write_triage_queue` (grep in common.py), so the per-runner `drafted = 0` outer variable and `source_drafted = 0` inner variable are dead. (1) Delete the dead variables; runners return `0` literal → change signature semantics: runners return `None` and `run_alerts.py` stops accumulating from them (grep `drafted +=` in run_alerts.py — keep ONLY the `_drain_and_write_triage_queue` contribution). (2) Verify `_bump_source_drafted_in_run` is invoked on the drain path for each saved draft so `current_run["sources"][i]["drafted"]` and source_health get post-drain credit (grep its callsites; if it is only defined but never called on the drain path, add the call where `save_draft` succeeds inside the drain loop). (3) `run_alerts.py` final print `Saved {drafted} drafts` must reflect the drain return value only.

**Tests (named):** `test_run_alerts_drafted_count_comes_from_drain_only`, `test_source_run_gets_drafted_credit_after_drain` (simulate one enqueued candidate surviving triage with a stubbed `generate_draft`; assert the originating source's run record shows `drafted == 1`).

**Gates:** §4 + `grep -rn "source_drafted" src/ | wc -l` → 0; `grep -rn "^\s*drafted = 0" src/orchestrator/sources/ | wc -l` → 0.

**Traps:** `sources/open_meteo.py` and `sources/gpm_imerg.py` return inner variables directly (grep `return source_drafted\|return drafted` in both) — same treatment. Do not change `_record_source_run`'s signature; other fields are load-bearing.

### S-02 (#30b) pytest config + README + PIPELINE.md glossary + critic passthrough + action versions — S

**Why:** local pytest behavior diverges from CI; cold-start docs don't exist; the critic has no runtime kill-switch; one workflow runs stale action versions.

**Files:** `pyproject.toml`; `README.md` (create); `PIPELINE.md` (grep `Stage Glossary`); `.github/workflows/bot.yml` (env block of the `run` job, grep `THEHEAT_TRIAGE_ENABLED`); `.github/workflows/refresh-thresholds.yml` (grep `actions/checkout@`).

**Spec:** (1) Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not voice_replay'"
markers = [
    "voice_replay: live-API voice regression replays (run by voice-regression workflow only)",
    "allow_network: opt out of the socket hermeticity gate",
    "real_backoff: opt out of the no-op retry backoff",
]
```
Check `tests/conftest.py` and `tests/voice_regression/conftest.py` for the exact existing marker registrations (grep `addinivalue_line`) and keep wording consistent; CI's explicit `-m "not voice_replay"` stays (harmless duplication). Verify the voice-regression workflow still selects its tests: its command uses `-m voice_replay` which OVERRIDES addopts — confirm by `python -m pytest tests/voice_regression/ --collect-only -q -m voice_replay | tail -1` collecting >0 items. (2) `README.md`: ~60 lines — what the bot is (one paragraph), quickstart (venv, `pip install -r requirements.txt`, `pytest`, `mypy`, dashboard `npm install && npm test`), the 4 workflows and their crons, state-backend note (gist prod / sqlite dormant), pointer to `PIPELINE.md`, `BRIEFING.md`, `docs/handoffs/` for context, and the standing rails (no push to main, sentinel/dashboard sync contract, MERGE_SPEC rule). (3) `PIPELINE.md`: rewrite ONLY the stale Stage Glossary section (grep `Gemini 2.5 Flash (Generator)` — that whole pre-2026-05-04 generator/evaluator description) to describe the current two-bot chain: deterministic gates → writer (`claude-sonnet-4-6`, `src/two_bot/writer.py`) → safety pipeline (`src/voice/safety.py`) → fact-check (`gemini-2.5-flash`, `src/two_bot/fact_check.py`) → critic (`gemini-2.5-pro`, `src/two_bot/critic.py`, PASS/KILL, `THEHEAT_CRITIC_ENABLED`); update the "14 free public data sources" mermaid label to the live count (count `src/orchestrator/sources/*.py` minus `__init__`/synthesis). Do not touch the accurate top prose. (4) bot.yml `run` job env: add `THEHEAT_CRITIC_ENABLED: ${{ vars.THEHEAT_CRITIC_ENABLED || '1' }}` adjacent to the existing `THEHEAT_TRIAGE_ENABLED` line, same pattern. (5) refresh-thresholds.yml: `actions/checkout@v4`→`@v6`, `actions/setup-python@v5`→`@v6` (match bot.yml).

**Gates:** §4 + `python -m pytest -q 2>&1 | tail -1` (no `-m` flag) shows the same count as CI's filtered run (voice_replay auto-deselected) + the collect-only check above.

**Traps:** addopts changes EVERY local pytest invocation — the voice-regression workflow's explicit `-m voice_replay` must keep working (gate above proves it).

### S-03 (#27) Dashboard truth fixes — S [deploy]

**Why:** the operator approves drafts off these numbers; today the daily count can be an arbitrary day's, a failed state read renders as an empty (healthy-looking) pipeline, and a days-stale Hot 10 looks current.

**Files:** `dashboard/app/page.js`; tests `dashboard/tests/` (new file `page-helpers.test.js` if helpers are extracted) or inline-testable via existing node:test setup.

**Spec:** (1) **todayCount:** grep `daily_tweet_count` in page.js — the bug is `Object.values(state.daily_tweet_count)[0]`. Replace with a date-keyed lookup:

```js
const todayKey = new Date().toISOString().slice(0, 10)
const todayCount = state?.daily_tweet_count?.[todayKey] ?? 0
```
(2) **stateError banner:** grep `stateError` — it is stored (`data.stateError`) but never rendered. Render it with the same visual pattern as `refreshError` (grep `refresh failed`) at the top of the content area, prefixed `state read failed:`, with `role="alert"`. (3) **Hot 10 staleness:** grep `last_hot10` / `timeAgo(hot10.date` — compute age; when older than 24h render an amber `(stale Nd)` suffix chip next to the date. Reuse existing badge/chip classes from `dashboard.css` (grep `.badge` there) — no new color system. (4) **Data-age vs fetch-age:** the header's "updated Xm ago" is fetch time. Add alongside it `data: <timeAgo(newest run_history started_at)>` so a stopped bot is visible even when polling succeeds. (5) **Funnel label dup:** grep `bundles_after_dedup` — two funnel stages share the label `Bundles (post-dedup)`. Check which key the Python pipeline emits (grep `bundles_after_dedup\|"bundles"` in src/) and delete the dead entry, or relabel the raw one `Bundles (raw)` if both are emitted. (6) Add `role="alert"` to the draftFeedback div (grep `draftFeedback`).

**Tests (named, node:test):** extract `todayTweetCount(dailyMap, nowIso)` and `hot10IsStale(dateStr, nowIso)` into `dashboard/lib/format.js` (new) and test both: `today count uses UTC date key`, `hot10 stale after 24h, fresh before`.

**Gates:** §4 + after merge: deploy + 401 check (§2 step 9).

**Traps:** page.js is `"use client"` with hooks — keep extracted helpers pure (no Date.now() default args in module scope; pass `now`).

### S-04 (#29) Sentinel 403 classification — S [deploy]

**Why:** a bare `403` always classifies `external` ("leave it"), but a 403 from Earthdata is an expired credential — ours, fixable, currently invisible.

**Files:** `scripts/source_health_sentinel.py` (grep `_UPSTREAM_RE` and `_OUR_BUG_RE`); `dashboard/lib/source-health.js` (grep `UPSTREAM_RE`); `tests/test_source_health_sentinel.py`; `dashboard/tests/source-health.test.js`.

**Spec:** Add a host/credential-aware override that runs BEFORE the upstream regex: if the error string matches `/(earthdata|urs\.earthdata|EDL|podaac)/i` AND contains `403`, classify `our_bug` (credential class). Implement identically in both classifiers (Python: extend `_OUR_BUG_RE` with `403[^\n]*earthdata|earthdata[^\n]*403` or a two-condition check — pick the two-condition check for readability; JS: the same logic in `classifyError`). Keep everything else untouched.

**Tests (named, BOTH sides):** `classifies earthdata 403 as our_bug`, `classifies generic gov 403 as upstream` (e.g. `403 Client Error: Forbidden for url: https://www.metoc.navy.mil/...`). The two suites' fixture strings must be copy-identical.

**Gates:** §4 + both new tests green + after merge: deploy + 401 check.

**Traps:** This is the sync-contract pair — one PR, both files, both test suites. Do not reorder existing regex alternatives (other tests pin them).

### S-05 (#13) error_class telemetry + alerts-lane liveness + failure alarm — M [CODEX]

**Why:** later phase gates are unmeasurable without per-run error classes; a crashed alerts lane is currently invisible (hourly `auto_publish_due` runs keep `run_history` fresh, and the sentinel reads only per-source health from the last successful state write).

**Files:** create `src/data/error_class.py`; `src/state_schema.py` (grep `class SourceHealthRun`); `src/state.py` (grep `_rebuild_source_health` and `record_source_health`); `src/orchestrator/common.py` (grep `_record_source_run`); `scripts/source_health_sentinel.py`; `.github/workflows/source-health-sentinel.yml` (the cron edit in spec point 4); `dashboard/lib/source-health.js`; `.github/workflows/bot.yml`; tests on all sides.

**Spec:** (1) **Shared classifier:** `src/data/error_class.py` exporting `classify_error_class(error: str | None) -> str` returning one of `"timeout" | "http5xx" | "http403" | "http429" | "dns" | "connection" | "auth" | "parse" | "other" | "none"`. Order: none (empty) → auth (401/404/410/Unauthorized/EARTHDATA_TOKEN/expired) → http403 → http429 → http5xx (`\b50\d\b|Server Error|Bad Gateway|Service Unavailable`) → timeout (`Timeout|timed out`) → dns (`NameResolution|getaddrinfo|NXDOMAIN`) → connection (`ConnectionError|Connection refused|Max retries|RemoteDisconnected`) → parse (`JSONDecodeError|ParseError|ExpatError`) → other. (2) **Record it:** `_record_source_run` passes `error_class=classify_error_class(error)` through to `record_source_health`; add `error_class: str` to `SourceHealthRun` (the TypedDict is already `total=False`, so the field is optional without importing `NotRequired`); `_rebuild_source_health` must PRESERVE the field in the rolling runs (grep the whitelist of preserved per-run fields and add it). This changes per-run payload, NOT merge semantics — golden fixture untouched; if `test_merge_state_golden` fails you did it wrong, revert and re-read. (3) **Sentinel liveness:** in the sentinel, after loading state, compute `newest_alerts_ts = max(r["started_at"] for r in run_history if r.get("mode") in ("alerts","both"))`; if older than `LIVENESS_MAX_AGE_H = 6` hours (alerts cron is every 4h), include a synthetic failing source `_pipeline_liveness` in the issue-planning pass with a body explaining the lane is stale and pointing at the Actions page. It auto-closes through the same lifecycle when a fresh alerts run lands. (4) **Sentinel cadence:** edit `source-health-sentinel.yml` schedule from `30 */4 * * *` to `30 * * * *` (hourly) so liveness detection is ≤ ~3h worst case; the issue-reconciliation logic is idempotent so hourly is safe. (5) **Workflow alarm:** in bot.yml `run` job, append:

```yaml
      - name: Open issue on scheduled-run failure
        if: failure() && github.event_name == 'schedule'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          title="Bot cycle failed: ${{ github.run_id }}"
          gh issue create --title "$title" \
            --label "source-health-sentinel,ours" \
            --body "Scheduled run failed: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }} — mode schedule ${{ github.event.schedule }}. Investigate; close when resolved." \
            || true
```
and add to the `run` job: `permissions: { contents: read, issues: write }` (grep existing `permissions:` — bot.yml's run job currently inherits; set explicitly, keeping any existing scopes). (6) **Dashboard:** JS classifier gains the same `error_class` vocabulary ONLY if it consumes it — minimal scope: surface `error_class` in the /health source detail if trivially available; otherwise skip UI, keep the field server-side (note the decision in the PR).

**Tests (named):** `test_classify_error_class_taxonomy` (one assertion per class, real prod error strings from §B.5 as fixtures), `test_source_health_run_preserves_error_class`, `test_sentinel_liveness_flags_stale_alerts_lane` (run_history with fresh auto_publish_due + 7h-old alerts → `_pipeline_liveness` failing), `test_sentinel_liveness_quiet_when_fresh`.

**Gates:** §4 + `python scripts/source_health_sentinel.py --help 2>&1 || true` still exits clean (grep its arg parsing first) + golden fixture test untouched and green.

**Traps:** Do NOT add a DEFAULT_STATE key (error_class lives inside existing run dicts — no MERGE_SPEC entry needed). The sentinel's `classify_error` (ours/upstream/unknown for ISSUE LABELS) and the new `classify_error_class` (transport taxonomy for TELEMETRY) are different functions with different jobs — do not merge them; S-04's label logic stays as shipped.

### S-06 (#14) Sentinel stale-success / zero-yield detection — M

**Why:** a source "succeeding" with empty or stale data stays green forever while contributing nothing — the last invisible outage class.

**Files:** `scripts/source_health_sentinel.py`; `tests/test_source_health_sentinel.py`; `dashboard/lib/source-health.js` + its test (only if classification output shape changes — keep shape identical to avoid the sync ripple).

**Spec:** Add a `yield-watch` advisory: for each source with ≥10 runs in the window, all `success`, and `total_observed == 0` across the window, AND the source is not in the known-quiet allowlist `YIELD_QUIET_OK = frozenset({"synthesis_fire_drought_heat", "manual_publish", "auto_publish_due", "leaderboard", "load_cities", "ozone_hole", "nao", "ao", "pdo", "enso", "nao_ao_alignment"})` (seasonal/conditional/stage records — copy exact key names from §B.4), include it in the sentinel's daily issue as a SECTION of an existing `Source-health digest` issue rather than per-source issues (one rolling issue titled `Yield watch: sources succeeding with zero observations`, create/update/close via the existing issue-action machinery with a distinct marker in the body). This is advisory: label `unknown`, never `external`.

**Tests (named):** `test_yield_watch_flags_zero_observed_success_source`, `test_yield_watch_ignores_allowlisted`, `test_yield_watch_requires_full_window`.

**Gates:** §4.

**Traps:** `total_observed` semantics differ per source (bulk rows vs events — co2 observes 600k rows); zero is the only safe threshold, do not get clever with averages. JS classifier untouched (no shape change).

### S-07 (#1a) `_http.py`: jitter + shared Session + pooling — S [CODEX]

**Why:** synchronized exponential retries hammer sick hosts in lockstep; every request pays a fresh TCP+TLS handshake on exactly the hosts that time out.

**Files:** `src/data/_http.py`; `tests/test_http_retry.py`.

**Spec:** Replace the sleep + add a module-level session (current code verified at 0.9.23.0):

```python
import random
...
_session: requests.Session | None = None

def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _session = s
    return _session

def _sleep_before_retry(attempt_index: int, backoff_base: float) -> None:
    if backoff_base <= 0:
        return
    base = backoff_base * (2 ** attempt_index)
    time.sleep(base + random.uniform(0, backoff_base))
```
In `fetch_with_retry`, change `requests.get(` to `_get_session().get(` (grep — single callsite inside the loop). Keep the exported function signature byte-identical.

**Tests (named):** `test_sleep_before_retry_jitter_bounds` (monkeypatch `time.sleep` + `random.uniform`, assert bounds `[base, base + backoff_base]`), `test_fetch_uses_shared_session` (monkeypatch `_get_session` to a recording stub, assert reuse across two calls), keep all existing retry tests green.

**Gates:** §4 + `python -m pytest tests/test_http_retry.py -v` all green.

**Traps:** `tests/conftest.py` no-ops `_sleep_before_retry` globally (grep `_fast_retry_backoff`) — your jitter test needs `@pytest.mark.real_backoff`. The module calls `force_ipv4()` at import; Session must be created lazily AFTER import (it is, via `_get_session()`). Thread-safety: data-layer ThreadPoolExecutors share the Session — `requests.Session` is thread-safe for requests; pool sizes 8 match `GPM_IMERG_MAX_WORKERS=8`.

### S-08 (#1b) Migrate bare `requests.get` callers — M

**Why:** 12+ fetchers die on a single TCP reset; GDACS alone failed 9/40 cycles on one-attempt fetches.

**Files:** the verified bare-caller list (grep `requests.get(` in each to confirm): `src/data/gdacs.py`, `enso.py`, `co2.py`, `nsidc_snow.py`, `sea_ice.py`, `nws_alerts.py`, `water_levels.py` (2 sites), `ocean.py`, `fire_footprint.py`, `drought.py`, `open_meteo.py` (7 sites incl. :233/:304/:333/:502/:537/:934/:956), `ghcn.py` (:264), `ice_mass.py` (CMR probe). Plus `tests/` for each touched module. AUTHORITATIVE inventory is the grep itself — run `grep -rn "requests\.get(" src/data/ --include="*.py" | grep -v _http.py` first and migrate every hit not in the sanctioned-exemption list below.

**Spec:** Mechanical per callsite: `requests.get(url, timeout=T, **kw)` → `fetch_with_retry(url, timeout=T, attempts=3, backoff_base=1.0, **kw)` (import `from src.data._http import fetch_with_retry` matching each file's existing import style — grep how `firms.py` imports it). PRESERVE each site's existing timeout value exactly. Where the caller manually checked `response.raise_for_status()` afterward, remove the duplicate call (fetch_with_retry raises). Where the caller treats specific status codes specially BEFORE raising (grep each file for `status_code` first!) — e.g. air_quality's 429 dance — leave that file alone (air_quality is NOT in this step's list). Open-Meteo sites: same mechanical change; their host is the most reliable feed but blips still drop cycles.

**Tests:** existing per-source tests already stub the data layer — they must stay green unchanged. Add one test per migrated module ONLY where a module had none covering the fetch error path: `test_<src>_fetch_failure_raises_clean` (mock `fetch_with_retry` to raise `requests.ConnectionError`; assert the source's existing error contract — grep what the runner catches).

**Gates:** §4 + structural: `grep -rn "requests\.get(" src/data/ --include="*.py" | grep -v "_http.py"` → ONLY sanctioned exemptions, each carrying a `# bare-get: <reason>` comment you add: `gpm_imerg.py` sites (migrated in S-09), `_s3credentials.py` (credential mint — leave its request mechanics alone), and any site with pre-raise status-code special-casing (e.g. air_quality's 429 dance — not in this step's list).

**Traps:** `ice_mass.py` already uses fetch_with_retry for data fetch — only its CMR probe is bare. Do not change retry counts for paid/credentialed endpoints without checking rate limits (none in this list are credentialed except ice_mass CMR — public, fine).

### S-09 (#1c) WAF-aware 403/429 retry + unify gpm per-city retry — M [CODEX]

**Why:** a transient WAF 403 from gov hosts (jtwc/coralreefwatch/USGS/copernicus, 2–3 failed cycles each last week) is instantly fatal today; gpm hand-rolls its own retry, skipping UA injection and jitter.

**Files:** `src/data/_http.py`; `src/data/gpm_imerg.py` (grep `_fetch_city_precip` and its inline retry ~`GPM_IMERG_RETRY_BACKOFF_S`); `tests/test_http_retry.py`, `tests/test_gpm_imerg.py`.

**Spec:** (1) In `_http.py` add:

```python
_WAF_RETRY_HOSTS = frozenset({
    "www.metoc.navy.mil",
    "coralreefwatch.noaa.gov",
    "waterservices.usgs.gov",
    "rapidmapping.emergency.copernicus.eu",
})

def _waf_retry_eligible(url: str, status_code: int) -> bool:
    from urllib.parse import urlparse
    return status_code in (403, 429) and urlparse(url).hostname in _WAF_RETRY_HOSTS
```
In `fetch_with_retry`'s loop, before `raise_for_status()`: if `_waf_retry_eligible(url, response.status_code)` and attempts remain, sleep `random.uniform(15, 45)` seconds and retry ONCE (track a `waf_retried` local so it fires at most once per call regardless of `attempts`). 401/404/410 keep failing fast everywhere (credential class — sentinel labels `ours`). (2) gpm: replace the inline per-city 1-retry block in `_fetch_city_precip` with a `fetch_with_retry(..., attempts=2, backoff_base=_retry_backoff_s())` call preserving its timeout and headers (grep the exact request construction first; keep `EARTHDATA_TOKEN` header injection identical).

**Tests (named):** `test_waf_403_retried_once_then_raises` (mock session returning 403 twice for a WAF host; assert exactly 2 requests + final raise), `test_waf_403_not_retried_for_unlisted_host`, `test_429_retried_for_waf_host`, `test_gpm_city_fetch_uses_shared_retry` (assert UA header present — it wasn't before).

**Traps:** the 15–45s WAF sleep × many URLs could balloon a cycle — it fires at most once per CALL; coral_dhw fetches N station files, so a fully-403ing host could add ~N×30s. Mitigate: module-level `_waf_budget = {"remaining": 4}` decremented per WAF retry per process; when exhausted, skip the special retry (plain fail). Test: `test_waf_budget_caps_process_wide_retries`. The conftest backoff no-op does NOT cover `random.uniform` sleeps — gate them behind `_sleep_before_retry(0, seconds_as_base)`-style indirection or a module-level `_waf_sleep()` that tests monkeypatch; do the latter.

**Gates:** §4 + new tests green.

### S-10 (#20) Conditional requests for static CSVs — M

**Why:** re-downloading unchanged government CSVs every 4h is wasted latency and exactly the request pressure that triggers IP-reputation 403s; a 304 is near-free.

**Files:** `src/data/_http.py`; callers: `co2.py`, `enso.py`, `sea_ice.py`, `nsidc_snow.py` (the daily CSV endpoints — grep each for its URL constant); `src/state.py` ONLY if you choose state-backed cache storage — DO NOT: use an in-repo-runner local cache instead (see Traps); tests.

**Spec:** Add `fetch_with_cache_revalidation(url, *, cache: dict[str, tuple[str, str]], **kwargs)` to `_http.py`: `cache` maps url → `(etag_or_lastmod_value, body_text)` held in a module-level dict (process-lifetime only). Send `If-None-Match` (preferred) or `If-Modified-Since`; on 304 return the cached body wrapped in the same return type callers expect (refactor the 4 callers to accept `(text, from_cache: bool)` or keep returning a Response-like shim — pick the smaller diff per caller after reading them). On 200, update the cache.

**Reality check (do this FIRST, before writing code):** `curl -sI https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_daily_mlo.csv | grep -i 'etag\|last-modified'` and the analogous HEAD for the other three URLs (grep their URL constants). If a host sends neither header, EXCLUDE it and note in the PR. If NONE of the four send validators: ship only the helper + tests, mark the step `DONE(helper-only; no upstream validators)` in PROGRESS.md.

**Tests (named):** `test_revalidation_sends_if_none_match`, `test_304_serves_cached_body`, `test_200_replaces_cache`.

**Traps:** GH Actions runners are fresh per run — a process-lifetime cache only helps within one cycle (multiple sources hitting the same host) and that's FINE; do not persist HTTP caches into bot state (state bloat, the §1 gist cliff). Scope is politeness + intra-cycle dedup, not cross-cycle.

### S-11 (#8) Decompose `common.py` — L [MINI-PLAN] [CODEX]

**Why:** 1,687-line god module star-imported into 30 files; every later orchestrator step pays its comprehension tax.

**Files:** `src/orchestrator/common.py` → new modules `src/orchestrator/{caps.py, suppression.py, telemetry.py, cyclones.py, dedup.py, draft_save.py, two_bot_dispatch.py, triage_queue.py}`; ALL `src/orchestrator/sources/*.py` keep working unchanged via the shim; `src/main.py` (`_sync_compat_globals`, grep it); tests.

**Spec (constraints for your mini-plan):** MECHANICAL MOVE ONLY — zero behavior change. The cluster map (verified): A imports/re-exports stay in common.py; B constants (`MAX_DRAFTS`, `CITY_COOLDOWN_DAYS`, `ELITE_COPY_SCORE`, `*_ANNUAL_CAP`) → `caps.py`; C datetime/format utils stay; D suppression ledger (grep `_CURRENT_SUPPRESSION_CTX` through `_should_draft`) → `suppression.py`; E `_record_source_run`/`_bump_source_*` → `telemetry.py`; F `_*_annual_cap_reached`/`_increment_*` → `caps.py`, AND collapse the five copy-pasted pairs into `def annual_cap_reached(bot_state, count_key, cap)` / `def increment_annual_count(bot_state, count_key)` with thin named wrappers preserving every existing callsite signature; G cyclone helpers (grep `_process_cyclone_source`) → `cyclones.py`; H same-day/city dedup → `dedup.py`; I `save_draft` + helpers → `draft_save.py`; J `_try_two_bot_draft` etc → `two_bot_dispatch.py`; K `_enqueue_story_candidate`/`_drain_and_write_triage_queue` → `triage_queue.py`; L stays. common.py becomes the compatibility shim: `from src.orchestrator.caps import *  # noqa: F403` etc., and `__all__` is REBUILT as the union of the new modules' `__all__`s with a test asserting the shim exports everything the old `__all__` did (snapshot the old list into the test BEFORE moving anything). `_sync_compat_globals` in main.py must keep functioning — it patches module globals by name; verify it iterates the new modules too or (better) that tests relying on it still pass unmodified; if any fail, patch `_sync_compat_globals` to walk `src.orchestrator.<new modules>` as well.

**Order of operations (one commit per move):** snapshot-test first → move F (with the dedup refactor) → move D → E → G → H → I → J → K → B → rebuild shim `__all__` → full suite between every commit.

**Gates:** §4 after EVERY move-commit + `python - <<'EOF'` snippet in the PR proving `set(old_all) <= set(common.__all__)` + `git log --oneline` on the branch shows ≥10 stepwise commits.

**Traps:** star-import shadowing — if two new modules export the same name, the LAST `import *` in the shim wins; the snapshot test must compare objects (`common.save_draft is draft_save.save_draft`), not just names. Do not rename ANY public symbol. Do not "improve" anything while moving — F's dedup is the single sanctioned exception.

### S-12 (#4a) gpm chain `datapool→s3→opendap` + creds pre-mint — M [CODEX]

**Why:** gpm still failed 5/12 runs after the datapool switch; the s3 path is built but unchained, and its credential mint shares datapool's host so naive chaining is false redundancy.

**Files:** `src/data/gpm_imerg.py` (grep `_gpm_grid_source_chain`); `src/data/_s3credentials.py` (grep the cache + mint function); `src/orchestrator/sources/gpm_imerg.py` (entry — for the pre-mint hook); tests `tests/test_gpm_imerg.py`.

**Spec:** (1) Chain change: `"datapool"` maps to `("datapool", "s3")` instead of `("datapool",)`. The existing post-chain unconditional OPeNDAP per-city fall-through (grep `alternate feeds can never regress gpm`) stays — that's the third leg. (2) Pre-mint: at the START of the gpm source run (before the datapool fetch), call the s3 credential mint inside a `try/except Exception: pass` and rely on the existing ≤55-min in-process cache (grep `_cache` in `_s3credentials.py`) so that if datapool's host degrades mid-cycle, s3 creds are already held. Pre-mint only when `EARTHDATA_TOKEN` is set (grep how `SourceSkipped` is raised). (3) Telemetry: when a fallback leg serves the data, ensure the existing log line names the leg (grep the chain-walk log) — extend to `[gpm] grid source <leg> served (chain position N)` if absent.

**Tests (named):** `test_datapool_chain_includes_s3`, `test_premint_failure_is_nonfatal`, `test_chain_falls_through_to_opendap` (existing — keep green).

**Gates:** §4 + `python -m pytest tests/test_gpm_imerg.py -q` green.

**Traps:** honesty in the PR body: s3 covers partial outages (data-path degradation while the auth host is up), NOT a full host black-hole — OPeNDAP (different host, `gpm1.gesdisc`) remains the independent leg. Do not reorder to s3-first: datapool is one request; s3 needs boto3 + creds (heavier).

### S-13 (#4b) GDACS GeoRSS fallback + mirror survey — M

**Why:** GDACS failed 9/40 cycles on its `gdacsapi` JSON tier; the same events publish on the GeoRSS feed at a different path.

**Files:** `src/data/gdacs.py`; `tests/test_gdacs.py`; create `docs/superpowers/specs/2026-06-XX-mirror-survey.md`.

**Spec:** (1) **Verify the feed FIRST:** `curl -s "https://www.gdacs.org/xml/rss.xml" | head -50` — confirm it serves RSS with event entries carrying GDACS event IDs, episode/alert levels. If the URL 404s or lacks the fields needed to build the same event tuples the JSON path produces (grep what `fetch_disasters` extracts: event id, type, alert level, country, coords, dates), STOP: mark `BLOCKED(georss-shape)` with the curl evidence and skip to the survey half. (2) Fallback: in `fetch_disasters`, on any exception from the JSON endpoint, fetch + parse the GeoRSS (stdlib `xml.etree.ElementTree`; the repo has no lxml dep — keep it that way) into the SAME normalized event dicts; tag a module-level log `[gdacs] served by georss fallback`. Set a parsed-field floor: if GeoRSS yields fields insufficient for scoring (`score_global_disaster` inputs — grep them), raise instead of half-filling. (3) **Survey doc:** for each 403-cluster + NASA source (`jtwc`, `coral_dhw`, `river_gauges` (already dual-host — document which is primary), `copernicus_ems`, `firms`, `ice_mass`, `nsidc_snow`, `sea_ice`), record: current endpoint(s), candidate official mirror/alternate (check: NOAA CoralReefWatch data mirrors, NASA FIRMS NRT vs SP endpoints, NSIDC `noaadata.apps.nsidc.org` alternates, GWIS as VIIRS redistributor, `api.water.noaa.gov` NWPS vs `waterservices.usgs.gov`), verification curl + observed result, and a CHAIN/WITNESS/NONE verdict. WebFetch/WebSearch allowed for THIS step only, capped at ~10 fetches. The survey is the input for future chain work — no code beyond gdacs in this step.

**Tests (named):** `test_gdacs_falls_back_to_georss_on_json_failure` (mock JSON path raising + GeoRSS returning a fixture XML — commit a small real-shape fixture under `tests/fixtures/gdacs_georss_sample.xml`), `test_gdacs_georss_insufficient_fields_raises`.

**Gates:** §4 + fixture-driven tests green + survey doc exists with ≥8 sources verdicted.

### S-14 (#3a) `assert_freshness` rollout — M

**Why:** 15 of 23 sources record `success` even when upstream silently serves week-old data — stale-success is invisible to every alarm and can produce tweets implying today.

**Files:** `src/data/_freshness.py` (read it first — grep `def assert_freshness`); the unguarded sources: `firms.py`, `sea_ice.py`, `drought.py`, `co2.py`, `gdacs.py`, `ice_mass.py`, `nws_alerts.py`, `river_gauges.py`, `water_levels.py`, `enso.py`, `jtwc.py`, `nhc.py`, `fire_footprint.py`, `gpm_imerg.py` (lookback NOTE below), `air_quality.py`; per-source tests.

**Spec:** For each source, add `assert_freshness(<newest data date in payload>, "<source_key>", max_age_days=N)` immediately after parse, with N from this table (tempo-derived; do not guess your own):

| source | N (days) | newest-date field (grep the parser) |
|---|---|---|
| firms | 2 | acquisition date of newest hotspot |
| nws_alerts | 1 | newest alert sent/effective ts |
| gdacs | 3 | newest event `fromdate`/update |
| jtwc / nhc | 2 | newest advisory timestamp |
| river_gauges / water_levels | 2 | newest gauge reading ts |
| drought | 10 | USDM release date (weekly product) |
| sea_ice | 5 | newest daily extent row |
| co2 | 7 | newest daily MLO row |
| enso | 45 | newest ONI month (monthly, lagged) |
| ice_mass | 75 | newest GRACE-FO month (monthly, lagged ~2mo) |
| fire_footprint | 4 | newest perimeter update |
| air_quality | 2 | newest model timestep |

For cyclone feeds (jtwc/nhc): an EMPTY feed in the off-season is normal — assert freshness ONLY when ≥1 advisory parsed. Same principle anywhere "no items" is a valid state: freshness guards the newest item's date, never requires items to exist. `gpm_imerg`: its date-walkback already bounds age to `GPM_IMERG_MAX_LOOKBACK_DAYS` (default 5) — add an explicit `assert_freshness` on the resolved date with N=6 so a regression in the walkback can't silently serve ancient grids.

**Tests (named, per touched source):** `test_<src>_stale_data_raises_freshness` (fixture with old dates) and keep the happy-path tests green by pinning their fixture dates relative to a frozen `today` (grep how `_freshness` gets "today" — if it calls `date.today()` directly, FIRST refactor it to accept `today: date | None = None` threaded for tests, default real).

**Gates:** §4 + grep-gate: every file in the table contains `assert_freshness(`.

**Traps:** This makes sources FAIL where they silently succeeded — that is the point, and the sentinel will (correctly) see new failures if an upstream is actually stale. Roll out in ONE PR so the change is auditable, but the PR body must list per-source N so Andrew can later tune. `SourceFetchError` is the right raise (grep how `_freshness` raises — reuse).

### S-15 (#3b) Last-good cache for slow movers — L [MINI-PLAN] [CODEX]

**Why:** a failed fetch is a silent zero even for monthly-tempo data where yesterday's reading is still true; outages currently break detection continuity (baselines/streaks) for free.

**Files:** `src/state.py` (DEFAULT_STATE + MERGE_SPEC + golden regen); `src/state_schema.py`; new `src/data/last_good.py`; slow-mover sources: `co2.py`, `enso.py`, `sea_ice.py`, `ice_mass.py`, `nsidc_snow.py`, `climate_indices.py`, `ozone_hole.py` + their orchestrator runners; tests.

**Spec (constraints for your mini-plan):** (1) New DEFAULT_STATE key `last_good_readings: dict[str, dict]` mapping source_key → `{"data_date": "YYYY-MM-DD", "captured_at": iso, "payload": <COMPACT dict>}`. **MERGE_SPEC entry REQUIRED** (the structural test fails without it): strategy = max-by-`captured_at` per source key (grep existing `max_by_key` strategies for the pattern; write a named helper `_merge_last_good` if the generic doesn't fit). Regenerate golden fixture; summarize its diff key-by-key in the PR body. (2) **Compactness rule (hard):** `payload` is the DERIVED reading the detector needs (e.g. co2: `{ppm, date}`; sea_ice: `{extent_mkm2, date, hemisphere}`), NEVER raw CSV/rows. Each cached payload ≤ 1 KB serialized; add `test_last_good_payload_size_cap` asserting the writer helper rejects >2 KB. (3) **Provenance rule (hard):** the orchestrator runner, on fetch failure, MAY call `last_good.read(bot_state, source_key, max_age_days=N)` (N = 3× the S-14 freshness budget) and use it ONLY to update continuity state (streak/baseline/tier maintenance); it MUST NOT enqueue story candidates from a cached reading. Enforce structurally: `read()` returns a `LastGoodReading` dataclass with `from_cache=True`, and `_enqueue_story_candidate`'s bundle audit gains a check rejecting any bundle whose facts carry `from_cache=True` (thread a marker through; mini-plan decides the exact seam — the audit hook in `evidence_contract.audit_story_bundle` is the natural place, grep it). Test: `test_cached_reading_cannot_reach_triage`. (4) On every SUCCESSFUL fetch, the runner writes the compact reading via `last_good.write(...)` — write path is unconditional and cheap. (5) Record `status="degraded"` (not `success`) for a cycle served from cache, with error text `served last-good (<data_date>)` — the sentinel's existing degraded handling then reports honestly. (6) GHCN/open_meteo record-streaks are explicitly OUT of scope; instead, in the open_meteo runner, find the streak-prune call (grep `prune_stale_record_streaks`) and skip pruning when THAT source's fetch failed this cycle (one `if not fetch_failed:` guard + `test_streaks_not_pruned_on_fetch_failure`).

**Gates:** §4 + golden fixture regenerated with diff summarized + `test_merge_spec_covers_exactly_default_state` green + the provenance + size-cap tests green.

**Traps:** the gist is 80 KB from its cliff — the size cap is load-bearing, not style. Do not cache air_quality/gpm (fast, big); the slow-mover list above is closed.

### S-16 (#10) Record-store caps + state pruning — L [MINI-PLAN] [CODEX]

**Why:** unbounded stores (`snow_daily_swe_gain_records` ~252 KB, `precip_daily_records`, uncapped `memory.shipped_tweets`, immortal tier dicts, old-year annual counts) march the state toward the ~900 KB gist truncation cliff it already fell off once (2026-05-13).

**Files:** `src/state.py` (merge helpers + a new prune pass), `src/data/nsidc_snow.py` + `gpm_imerg.py` (tracking updates), `src/orchestrator/finalize.py` (prune hook), `scripts/gen_merge_golden.py` fixture regen; tests `tests/test_state.py`.

**Spec (constraints for your mini-plan):** one `prune_state(bot_state, now)` function called from `finalize_run` (grep it) applying ALL of:
- `snow_daily_swe_gain_records` / `precip_daily_records`: drop entries whose record `year < now.year - 10` AND drop any station/city whose `*_recent_by_*` sibling has no row newer than 90 days (dormant key eviction — a station not scanned can't fire).
- `snow_recent_by_station` / `precip_recent_by_city`: evict keys whose newest row is >90 days old (row depth already capped at 10).
- `memory.shipped_tweets`: cap 200 newest by `shipped_at`; ALSO add the same cap inside `_merge_memory` (grep it — currently union-no-trim).
- Tier dicts with TTL: entries gain/refresh an `updated_at` iso field at their existing write sites (grep each writer): `fire_complex_tiers` 90d, `cyclone_tiers` 30d, `flood_activation_tiers` 60d; prune drops entries past TTL. MIGRATION: entries WITHOUT `updated_at` (all current prod data) are stamped `now` on first prune, never dropped same-cycle. Schema is additive — verify the tier readers (grep each `.get(` consumer) tolerate the extra key; the existing `max_by_key` raw-compare merge for tiers must keep comparing the TIER VALUE — if entries become dicts where they were ints, that is a MERGE SEMANTICS CHANGE: check the actual current shapes first (`jq` the prod snapshot in §B.6); if tiers are bare ints, store timestamps in a SIDECAR key `tier_touch_ts: dict[str, str]` (new DEFAULT_STATE key + MERGE_SPEC max-by-key) instead of mutating tier shapes. Decide by evidence, document in PR.
- `*_annual_count` dicts + `ozone_hole_last_peak`: drop year-keys `< now.year - 1`.
- `posted_events` cap stays 500 (dedup window — do NOT shrink; raising is Andrew's call).
**Size guard:** in `_write_gist_state` (grep it), after serialization: `if len(payload) > 800_000: print(f"[state] WARNING size {len(payload)}B approaching gist inline cliff")` and record a structured error via `log_error` so it surfaces on the dashboard.

**Tests (named):** one per bullet (`test_prune_drops_old_snow_records`, `test_prune_evicts_dormant_stations`, `test_shipped_tweets_capped_in_merge`, `test_tier_ttl_prune_with_migration_stamp`, `test_annual_counts_old_years_dropped`, `test_size_guard_warns_over_800k`) + golden regen with key-by-key diff summary.

**Gates:** §4 + structural MERGE_SPEC test green + a before/after size simulation in the PR body: run `prune_state` against the prod snapshot (download per §B.6 to /tmp, run via a scratch script, report KB before/after — do NOT write back).

**Traps:** every new DEFAULT_STATE key needs MERGE_SPEC (structural test enforces); prune must be deterministic (sorted iteration) to keep merged output hash-stable; never prune inside `_merge_state` itself (merge stays pure — prune is a finalize-stage concern).

### S-17 (#12) Double-post hardening — M [CODEX]

**Why:** if both state writes fail after a successful post, the draft stays `pending` durably and the next hourly pass re-posts it — a follower-visible duplicate.

**Files:** `src/orchestrator/posting.py` (grep `post_approved` and `process_due_drafts`); `src/posting/twitter.py` (tweet_id is already returned — grep `response.data["id"]`); `src/state.py` (write path, grep `_write_gist_state` / `write_state`); `src/orchestrator/cli.py` (retry block, grep `write_state`); tests.

**Spec:** (0) **Signature reality (do this first):** `post_approved` currently takes `(tweet_text, bot_state)` and its two callers pass only text (grep `post_approved(` in posting.py) — refactor it to take the draft dict (+ bot_state) so event_id/intent are available at post time; update both callers and `run_manual_tweet`'s pathway accordingly. S-33 reuses this signature. (1) **Durable intent ledger, posted-BEFORE-posting:** before calling `post_tweet`, write a minimal marker into the gist via a dedicated small write: add state key `publish_ledger: dict[event_id, {"intent_id": str, "tweet_id": str | None, "at": iso}]` (DEFAULT_STATE + MERGE_SPEC dict-overlay; golden regen + diff summary). Flow in `post_approved`: (a) ledger[event_id] = {intent, tweet_id: None} → `write_state` (if THIS write fails: abort the post entirely — no tweet without a durable intent); (b) `post_tweet`; (c) ledger[event_id].tweet_id = id; draft.status="posted"; draft.tweet_id=id → normal end-of-run write (retry as today). (2) **Recovery check:** at the top of the posting loop, skip+repair any draft whose event_id exists in `publish_ledger` with `tweet_id` set but `status != "posted"` (stamp it posted, log `[posting] repaired half-recorded post`); treat ledger entries with `tweet_id: None` older than 2h as failed attempts (clear them). (3) **Optimistic re-merge (honesty: this NARROWS the concurrent-write window, it cannot close it — the gist PATCH API has no conditional-write primitive):** add `_state_rev: int` (DEFAULT_STATE, MERGE_SPEC take-max). `write_state` flow: re-read the gist immediately before PATCH; if its `_state_rev` differs from the value read at run start, re-merge against the fresh read and PATCH with `rev+1` (one such retry, then fail as today), and log a `[state] write conflict re-merged` line as conflict telemetry. (4) Surface `tweet_id` in the dashboard drafts payload (one-line projection addition; permalink rendering is S-35's concern — skip UI now).

**Tests (named):** `test_no_tweet_without_durable_intent` (mock write_state→False; assert post_tweet never called), `test_half_recorded_post_repaired_not_reposted`, `test_stale_intent_cleared_after_2h`, `test_state_rev_conflict_triggers_remerge`.

**Gates:** §4 + golden regen with diff summary + structural test green.

**Traps:** the pre-post write adds one gist round-trip per ACTUAL post (rare — fine); do NOT add it to draft-only cycles. `_state_rev` take-max merge means concurrent writers both bump — acceptable monotonic semantics; document. tweepy must not be imported at module scope in tests (grep how existing posting tests stub it — follow that pattern).

### S-18 (#21) SQLite backend CI smoke — S

**Why:** ~600 lines of dormant escape-hatch must either provably work or rot; pre-made decision (§9): wire, don't delete.

**Files:** `.github/workflows/bot.yml` (test job); possibly `tests/test_state.py` (grep `TestSqliteBackend` — suite exists).

**Spec:** In bot.yml's `test` job, after the main pytest step add:

```yaml
      - name: SQLite backend smoke
        run: |
          source .venv/bin/activate 2>/dev/null || true
          THEHEAT_DB_PATH=/tmp/theheat-smoke.sqlite python -m pytest tests/test_state.py -q -k "Sqlite" --tb=short
```
(match the workflow's existing python invocation style — grep how the main pytest step activates the env; replicate exactly). If the Sqlite tests already run in the default suite (they do, with tempdirs), this step's value is exercising the ENV-VAR-driven backend selection path: add one test `test_backend_selection_via_env` asserting `_configured_backend()` returns `"sqlite"` when `THEHEAT_DB_PATH` is set (monkeypatch env) and `"gist"` otherwise.

**Gates:** §4 + the new CI step green on the PR run.

### S-19 (#28) Dashboard payload trim + visibility polling — M [deploy]

**Why:** every 30s poll ships the whole ~1 MB state to the client, which reads five keys; hidden tabs keep polling and burning the same GitHub API budget state writes depend on.

**Files:** `dashboard/app/api/dashboard/route.js` (grep `results.state = state`); `dashboard/app/page.js` (grep `setInterval(fetchData`); `dashboard/tests/` new `dashboard-projection.test.js`.

**Spec:** (1) Replace `results.state = state` with a projection — grep page.js for EVERY `state.` / `data.state` access first and build the exact list (verified-as-of-audit list: `last_hot10`, `streaks`, `errors`, `daily_tweet_count`, `run_history` — re-verify by grep, the truth is the current code): `results.state = projectStateForDashboard(state)` implemented in `dashboard/lib/projection.js` returning only those keys. Other route consumers (`pendingDrafts(state)`, `suppressionsPayload(...)`, `buildSourceHealthPayload(state)`) already receive the full server-side object — unchanged. (2) Visibility gate: wrap the interval callback: `if (document.visibilityState === "hidden") return` and add a `visibilitychange` listener triggering an immediate refresh on return-to-visible. (3) Keep `/api/state` route untouched (it has its own consumers; auditing it is S-35).

**Tests (named):** `projection returns only whitelisted keys`, `projection tolerates missing keys` (empty state → empty-but-shaped object).

**Gates:** §4 + after merge: deploy + 401 check + `curl -s -u "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" .../api/dashboard | wc -c` comparison in PR body IF creds are available in the local env (`env | grep -q DASHBOARD_USERNAME`); otherwise note `size-check: local build inspection only`.

**Traps:** grep for `state.` accesses in ALL dashboard components, not just page.js (`grep -rn "\.state\." dashboard/app dashboard/lib | grep -v api/`) — the projection must be a superset of every client read or you ship a blank panel.

### S-20 (#7) DAG-concurrent execution + budgets + breaker — L [MINI-PLAN] [CODEX]

**Why:** 27 sequential fetchers make cycle time the SUM of slow hosts; one hung host steals time from everything behind it; a known-down source burns its full timeout every cycle.

**Files:** `src/orchestrator/run_alerts.py`; new `src/orchestrator/scheduler.py`; `src/orchestrator/triage_queue.py` (post S-11; the enqueue lock); `src/state.py` (breaker bookkeeping read); tests.

**Spec (constraints for your mini-plan):** (1) **DAG:** two stages only — Stage 1: all independent source runners; Stage 2: `run_synthesis` (consumes fire/drought/heat components written by FIRMS/drought/open_meteo runners — verified dependency). `run_leaderboard` stays OUTSIDE this scheduler (it's a different mode). (2) **Concurrency:** `ThreadPoolExecutor(max_workers=6)` over Stage-1 runners. SHARED-STATE AUDIT IS THE STEP'S CORE RISK: every runner mutates `bot_state` (dict) — Python dict ops are GIL-atomic but compound read-modify-write is not. Mitigation: a single `threading.Lock` in the new `triage_queue` enqueue path; runners' OTHER bot_state writes are per-source-keyed (each runner touches its own keys — verify by grep per runner in the mini-plan and LIST the verified key-ownership table in the PR; any runner sharing a key with another runner (synthesis components: firms/drought/open_meteo all write `synthesis_components`) gets its own lock or those three runners are serialized within Stage 1 — simplest correct choice: run those three in a serial sub-batch first, then the rest concurrently). (3) **Per-source budget:** `future.result(timeout=120)` per runner; on `TimeoutError`, record `status="failed", error="budget exceeded (120s)", error_class="timeout"` and DO NOT cancel the thread (it self-completes; document the zombie-thread tradeoff — acceptable in a 20-min-capped job). (4) **Breaker:** before dispatching a runner, read its source_health: if the last `BREAKER_N = 3` runs in the window all have `error_class == "timeout"` (S-05's field), skip with `status="skipped"` + a run-record field `breaker: true` + error text `circuit breaker (cooldown 1 cycle)`. NEVER a new status string — `_rebuild_source_health` normalizes unknown statuses to `failed` (verified) and the JS classifier counts statuses; `skipped` is already first-class on both sides. Breaker applies only to `error_class="timeout"` sources (connection-class flapping recovers via retry; 403s are not breaker business). (5) **Flag:** entire scheduler behind `THEHEAT_CONCURRENT_SOURCES` env, default `"0"` (sequential legacy path preserved verbatim). bot.yml passthrough `${{ vars.THEHEAT_CONCURRENT_SOURCES || '0' }}`. Flipping is Andrew's (§9). (6) Deterministic print interleaving is lost under concurrency — prefix every runner print with `[<source_key>]` if not already (grep; most have it).

**Tests (named):** `test_stage1_concurrent_stage2_after` (recording stub runners; assert synthesis ran last), `test_runner_budget_timeout_records_failed`, `test_breaker_skips_after_3_timeouts`, `test_breaker_records_skipped_not_failed`, `test_synthesis_component_writers_serialized`, `test_flag_off_runs_sequential_legacy`.

**Gates:** §4 + run BOTH paths in tests (flag on/off) + codex review.

**Traps:** `_CURRENT_SUPPRESSION_CTX` global (suppression module) is set per-source around runner bodies — grep its activation; under threads it MUST become a `contextvars.ContextVar` or suppression records cross-attribute between sources. This is the hidden P0 of the step; the mini-plan must address it explicitly.

### S-21 (#23) Orchestrator test gaps + voice fixtures — M

**Why:** the three untested runners are where a silent skip-condition bug ships; the newest bundle types have zero voice-regression coverage so prompt drift on them is invisible.

**Files:** create `tests/test_co_ops.py`, `tests/test_nifc.py`, `tests/test_marine.py` (orchestrator-level, mirroring `tests/test_gdacs.py`'s structure — read it as the template); `tests/voice_regression/test_writer_replay.py` (grep `BUNDLE_FIXTURES`).

**Spec:** (1) Each new test file covers: success path enqueues expected candidate (stub data layer), failure path records `status="failed"` + cycle continues, skip path (nifc weekly gate / credentials) records `skipped`, and dedup short-circuit. (2) Voice fixtures: add replay bundles for `precipitation_extreme`, `air_quality_hazard`, `dust_event`, `synthesis_fire_drought_heat`, `marine_heatwave`, `wet_bulb_extreme` — build each fixture by grepping the corresponding `src/two_bot/intern/` builder for its bundle shape and instantiating a REALISTIC example (real city/reef names, plausible magnitudes); these run only in the voice-regression workflow (marker already applied module-wide). Keep the suite's per-run cost reasonable: 6 new bundles ≈ +$0.10/day — acceptable, note in PR.

**Gates:** §4 + `python -m pytest tests/test_co_ops.py tests/test_nifc.py tests/test_marine.py -v` green + `python -m pytest tests/voice_regression/ --collect-only -q -m voice_replay | tail -1` shows the increased count (collection only — do NOT run live replays locally).

### S-22 (#2) Multi-draft best-of + critic REVISE — L [MINI-PLAN] [CODEX]

**Why:** one writer attempt per candidate and PASS/KILL-only criticism waste scarce signals; supply is the product bottleneck.

**Files:** `src/two_bot/pipeline.py`, `src/two_bot/writer.py`, `src/two_bot/critic.py`, `src/two_bot/prompts/critic_prompt.py`, `src/config.py` (the model/env config module — there is NO `src/two_bot/config.py`; writer/fact_check/critic import from `src.config`, grep their imports), `src/orchestrator/finalize.py` (cap env), bot.yml env passthroughs; tests in `tests/two_bot/`.

**Spec (constraints for your mini-plan):** (1) **Multi-draft:** `THEHEAT_WRITER_SAMPLES` (read in `src/config.py`, default `1` — DARK SHIP; >1 is Andrew's flip since writer calls are his metered API spend). When >1: N parallel `write_tweet` calls (ThreadPoolExecutor, the prompt is cache-hit after call 1); non-null drafts go to the critic as a SLATE — extend the critic user prompt with a `candidate_drafts` block and ask it to select the strongest or kill all; selected draft proceeds to safety/fact-check as today. Writer self-kills (tweet=null) reduce the slate; all-null = killed as today. (2) **REVISE:** `THEHEAT_CRITIC_REVISE_ENABLED` (default `0`, dark). When on: the critic verdict schema gains `verdict: "PASS"|"KILL"|"REVISE"` + `revise_instruction: str|null` (≤200 chars). On REVISE: exactly ONE writer re-call appending a DECLARATIVE constraint block (`Previous draft: ... / The critic requires: ...` — statement form, never imperative step lists), then the revised draft re-enters at the SAFETY stage (not the critic — no loops; revised draft gets normal critic pass? NO: revised draft goes safety→fact-check→critic-with-revise-DISABLED for that pass; one revise max per candidate). (3) Prompt changes are DECLARATIVE additions; do not restructure existing prompt sections (voice-regression replays pin behavior). (4) `MAX_DRAFTS_PER_CYCLE` becomes `int(os.environ.get("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3"))` in finalize.py + bot.yml passthrough — default UNCHANGED (=3); raising is Andrew's (§9). (5) Fail-closed inheritance: JSON-parse exhaustion on the slate-critic = KILL all (match existing critic fail-closed pattern — grep it).

**Tests (named):** `test_samples_1_is_byte_identical_to_legacy_path` (the load-bearing dark-ship proof: with default env, pipeline call sequence is unchanged — assert via recording stubs), `test_slate_critic_selects_one`, `test_all_writer_kills_short_circuits`, `test_revise_single_iteration_then_terminal`, `test_revise_disabled_by_default`, `test_revised_draft_passes_safety_again`.

**Gates:** §4 + voice-replay COLLECTION still green (no live runs) + codex review.

### S-23 (#16) Coral reef-system angle library — M

**Why:** coral DHW is the volume source and 7-of-8 drafts die to template convergence; the bundle gives the writer nothing reef-specific to vary on.

**Files:** new `src/data/reef_context.py` (static data module); `src/two_bot/intern/marine.py` (grep the coral bundle builder); tests.

**Spec:** A dict keyed by the reef/region identifiers the CRW feed actually uses (grep `coral_dhw.py` for region/station id shape and enumerate the live keys from the prod snapshot: `jq -r '.coral_dhw_last_tier | keys[]' /tmp/st.json` per §B.6): for each of the ~15-30 active regions, 3-5 FACTUAL context entries `{current_system, notable_history, ecosystem_note}` — content must be textbook-stable facts (e.g., GBR: EAC influence, 2016/2017/2020/2022 mass bleaching years; Florida: 2023 marine heatwave) — cite-checkable, no speculation, no superlatives. Builder injects the region's entries as bundle facts under `reef_context`; writer prompt gains ONE declarative line in the coral section: reef_context facts are available for the system clause. Cap: ≤3 context facts per bundle.

**Tests (named):** `test_reef_context_keys_match_live_region_ids` (fixture of known region ids), `test_coral_bundle_includes_context_when_available`, `test_unknown_region_omits_context_cleanly`.

**Gates:** §4 + fact-spot-check note in PR (list 5 entries + their public source URLs).

**Traps:** WORLD_KNOWLEDGE fact-check generosity covers established reef facts — keep entries within that envelope (named currents, documented bleaching years, ecosystem roles; no numbers that look like bundle data).

### S-24 (#17) Record margin-percentile bundle fact — M

**Why:** "broke by 0.2°C" and "largest margin ever recorded there" are different stories; the thresholds DB already knows the distribution but the bundle never says.

**Files:** `src/data/ghcn.py` or wherever the station-thresholds SQLite is queried (grep `station_thresholds`); `src/two_bot/intern/temperature.py` (record bundle builders); tests with a small fixture SQLite.

**Spec:** At record detection time, query the station's historical record-break margins for that month (the SQLite schema — inspect first: `sqlite3 <db> .schema` via a downloaded copy per the refresh-thresholds release asset, or grep the existing query layer for what's available). If margin history is derivable: add fact `margin_rank: {"rank": k, "of": n, "label": "largest margin in this station's N-year archive"}` ONLY when rank ≤3 (otherwise omit — non-elite margins are noise). If the schema does NOT support margin history (only current thresholds): STOP this step, mark `BLOCKED(schema-no-history)` with the observed schema, move on — do NOT bolt on a new data pipeline.

**Tests (named):** `test_margin_rank_top3_included`, `test_margin_rank_below_top3_omitted`, `test_missing_history_omits_cleanly`.

**Gates:** §4.

### S-25 (#15) Air-quality ground-station corroboration — M

**Why:** model-estimated evidence grade forces hedged framing and kills most AQ candidates; a co-located ground station turning the same number converts hedge into confidence.

**Files:** new `src/data/openaq.py`; `src/data/air_quality.py` or the AQ orchestrator (grep where PM2.5 candidates form); `src/two_bot/intern/air_quality.py` (grep `evidence_grade`); tests.

**Spec:** (1) **API reality check FIRST:** OpenAQ v3 requires a free API key. Check `env | grep -i openaq` — if absent: implement the module + wiring behind `OPENAQ_API_KEY` presence (raise `SourceSkipped` without it), mark the step `DONE(dark; needs OPENAQ_API_KEY secret)` and write the 3-line runbook (get key at openaq.org, `gh secret set OPENAQ_API_KEY`, add bot.yml env passthrough — include the passthrough in THIS PR so the flip is secret-only). (2) Corroboration: for each PM2.5 candidate city, query OpenAQ latest PM2.5 within 25 km; if a station value within ±35% of the CAMS estimate and <6h old exists: `evidence_grade = "model_corroborated_by_station"` + facts gain `{station_name, station_pm25, distance_km}`. (3) Writer prompt: one declarative line permitting "consistent with ground-station readings" phrasing at that grade; fact-check prompt: add the grade to its known vocabulary (grep where `model_estimated` is special-cased). (4) Budget: ≤1 OpenAQ call per candidate (not per city scanned), timeout 10s, failures degrade silently to the existing grade.

**Tests (named):** `test_corroboration_upgrades_grade`, `test_distant_or_stale_station_no_upgrade`, `test_openaq_failure_keeps_model_grade`, `test_skipped_without_api_key`.

**Gates:** §4.

### S-26 (#19) air_quality fan-out redesign — M

**Why:** 13 bursty chunks of 50 cities reliably trip the per-minute budget (2 ok / 5 degraded last week); the shape, not the volume, is the problem.

**Files:** `src/data/air_quality.py` (grep `CHUNK_SIZE` and `_rate_limit_wait_seconds`); tests `tests/test_air_quality.py`.

**Spec:** Spread instead of burst: between chunk requests insert `_chunk_pacing_sleep()` (default `int(os.environ.get("THEHEAT_AQ_CHUNK_PACING_S", "8"))` seconds — 13 chunks × 8s ≈ +100s cycle time, amortized inside the existing per-source budget). Keep the existing 429 recovery-pass machinery untouched as the backstop. Honor `Retry-After` if the 429 response carries it (grep the 429 handler; currently derives wait from the Date header — prefer Retry-After when present).

**Tests (named):** `test_chunks_are_paced` (recording sleep stub; assert called between chunks, not after last), `test_retry_after_header_honored`, existing 429 tests stay green.

**Gates:** §4. **Traps:** conftest's backoff no-op doesn't cover this sleep — route it through a module-level `_pacing_sleep()` seam tests monkeypatch.

### S-27 (#6) Synthesis expansion: global fire-drought-heat + SST×coral — L [MINI-PLAN]

**Why:** the highest-bar story class (threshold 82) has exactly one rule and it's US-only; the Amazon/Mediterranean/Sahel compound goes undetected every year.

**Files:** `src/editorial/synthesis.py` (grep `RULE_FIRE_DROUGHT_HEAT`); `src/orchestrator/sources/synthesis.py`; drought components: grep how `synthesis_components.drought_snapshot` is fed (USDM, US-only); `src/data/copernicus_ems.py` or a new global-drought feed; `src/two_bot/intern/` for the new bundle; `src/editorial/thresholds.py`; `src/editorial/scoring/`; tests.

**Spec (constraints for your mini-plan):** (1) **SST×coral first (cheaper, all data in-state):** new rule `RULE_MARINE_COMPOUND`: a coral region at DHW Alert Level 2 (grep tier semantics in `coral_dhw.py`) AND a basin SST anomaly ≥ +2.0 °C in the matching region (grep `sst_anom_last_tier` / ocean_sst_anomaly region keys — the mini-plan must build the coral-region→SST-region mapping table explicitly and commit it as data) within the same 14-day window → one synthesis candidate, threshold 82, cooldown per region 60d via the existing `synthesis_cooldown` mechanics. Bundle: both components' numbers + the mechanism slot. (2) **Global fire-drought-heat second:** only if a usable global drought signal exists without a new heavy dependency — candidates: Copernicus EMS drought activations (already fetched — grep what copernicus_ems yields) or GDACS drought events. If neither carries drought-severity data sufficient for the rule's gate, ship SST×coral alone and mark the global half `BLOCKED(no-global-drought-signal)` with evidence. Do NOT integrate a new raster/NetCDF pipeline for this. (3) New signal type end-to-end checklist (verified plumbing): data accumulation → `synthesis_components` (14d TTL pattern), detector in `synthesis.py`, runner wiring, bundle builder in `intern/`, scoring fn, `THRESHOLDS` entry (82), triage `legacy_type` mapping, approval policy `manual_only` (grep the policy table), voice fixture (add to replay set).

**Tests (named):** `test_marine_compound_fires_on_overlap`, `test_marine_compound_respects_window_and_cooldown`, `test_region_mapping_total` (every coral region maps or is explicitly unmapped), plus the standard new-source contract tests mirroring `test_synthesis.py`'s existing structure.

**Gates:** §4 + voice-replay collection green.

### S-28 (#24) Reganom activation readiness runbook — S

**Why:** the field-scan detector is the biggest supply unlock and it's one variable away; Andrew flips it, the loop makes the flip risk-free.

**Files:** create `docs/runbooks/reganom-activation.md`; NO production changes.

**Spec:** (1) Verify readiness, evidence into the runbook: `python -m pytest tests/test_reanalysis_anomaly.py -q` (or grep the actual test filename) green; climatology cache present (`ls -la data/climatology_daily_cache.json` + row sanity via a 3-line python read); bot.yml passthrough exists (grep `THEHEAT_REGANOM_ENABLED` in bot.yml); voice fixture for `regional_anomaly` exists in the replay set (grep) — if missing, ADD it in this PR (that's content work, allowed). (2) Runbook contents: preconditions checklist (all verified-green with this PR's evidence), the flip (`gh variable set THEHEAT_REGANOM_ENABLED --body 1 --repo andrewzp/theheat`), what to watch for 48h (sentinel for the source key, suppression ledger for its kill stages, the drafts queue), the revert (`gh variable delete ...`), and the honesty-defense summary (the 5 layers, grep `docs/plans/2026-06-08-reanalysis-anomaly.md` for their names). (3) **STOP:** do not flip. Status `DONE(awaiting-andrew-flip)`.

**Gates:** §4 (docs PR still bumps VERSION + runs suite).

### S-29 (#26) Hot 10 audience-unit fix — S

**Why:** the only temperature bundle without `_audience_unit_facts` — a US-led leaderboard can ship Celsius-first to a °F audience.

**Files:** `src/two_bot/intern/temperature.py` (grep `def build_hot10_bundle`); `tests/two_bot/` (grep the existing hot10 bundle test file).

**Spec:** In `build_hot10_bundle`, add `*_audience_unit_facts(leader_country)` into the bundle's facts list, where `leader_country` is the top city's country (grep how the leader row is selected; other builders show the exact call pattern — copy it, e.g. `*_audience_unit_facts(ev.country)` adapted to the leader variable).

**Tests (named):** `test_hot10_bundle_us_leader_gets_fahrenheit_first`, `test_hot10_bundle_non_us_leader_gets_celsius_first` (assert on the same fact shape other builders' tests use — grep one for the fixture pattern).

**Gates:** §4.

### S-30 (#25) Inter-tweet spacing guard — S

**Why:** simultaneous due drafts post back-to-back in one pass; three tweets in one minute reads as a malfunctioning firehose.

**Files:** `src/orchestrator/posting.py` (grep `process_due_drafts` loop); `src/state.py` (a `last_posted_at` read — check if any timestamp of last post already exists in state: grep `posted_at`; drafts carry it — use the max over drafts instead of a new state key if present); tests.

**Spec:** At the top of each iteration of the due-drafts loop: compute `last_post = max(posted_at of drafts with status=="posted")` (helper in posting.py); if `now - last_post < MIN_TWEET_SPACING_MIN (= int(env THEHEAT_MIN_TWEET_SPACING_MIN, default 15))` minutes: leave the remaining due drafts pending (they re-qualify next hourly pass), log `[posting] spacing guard: deferring N due drafts`. Post at most ONE draft per `auto_publish_due` run when the guard is active; the first post of a run is always allowed if spacing from the previous run's last post permits. No new DEFAULT_STATE key.

**Tests (named):** `test_spacing_defers_second_due_draft`, `test_spacing_allows_after_window`, `test_spacing_env_override`.

**Gates:** §4. **Traps:** manual posts (`run_manual_tweet`) are NOT subject to the guard (Andrew's explicit action wins) — assert that in a test.

### S-31 (#22) Cyclone advisory source links — S

**Why:** life-safety claims deserve one-click verification; the advisory URL is already in the bundle and never ships.

**Files:** `src/orchestrator/common.py` — or `draft_save.py`/`cyclones.py` post-S-11 — this is where the append lives: cyclone candidates are built around `_bundle_for_cyclone_event`/`_process_cyclone_source` and drafts persist through `save_draft` (grep all three); `src/two_bot/intern/disasters.py` (grep `public_advisory_url` for where the URL rides the bundle); `src/voice/safety.py` ONLY to confirm URLs pass the regex gates (grep the banned patterns for anything URL-hostile — exclamation/hashtag rules don't hit URLs; verify no length interplay); tests.

**Spec:** Post-pipeline append, not writer-discretion: immediately BEFORE draft persistence in `save_draft` (or its cyclone-specific caller), for cyclone `legacy_type`s only, if the bundle carries `public_advisory_url` and `len(tweet) + 1 + 23 <= 280` (t.co canonical length), append `\n<public_advisory_url>` to the draft text. Deterministic code, not prompt change (the writer keeps writing clean copy; the link is plumbing). The bundle's URL must be threaded to the save site — grep whether `save_draft`'s inputs already include the bundle or its facts; if not, pass it via the existing review-context/metadata path rather than widening `save_draft`'s signature. Safety pipeline runs on the FINAL text including the URL.

**Tests (named):** `test_cyclone_draft_gets_advisory_url_when_fits`, `test_url_omitted_when_over_budget`, `test_non_cyclone_unaffected`, `test_safety_passes_with_url`.

**Gates:** §4. **Traps:** the 280 check in safety/posting counts raw characters; t.co normalizes any URL to 23 — use the RAW length for the safety gate (conservative) and note that a long advisory URL may therefore be omitted more often than strictly necessary.

### S-32 (#18) Engagement-window scheduling — M (flag, default off)

**Why:** `auto_approve_at` is a pure review-hold timer; nothing stops a 3 AM ET auto-publish once lanes go auto.

**Files:** `src/orchestrator/common.py`/`draft_save.py` post-S-11 (grep `_utc_after_minutes_iso(policy.recommended_delay_minutes)`); new pure function in `src/editorial/scheduling.py`; tests.

**Spec:** `defer_to_engagement_window(ts: datetime) -> datetime` (pure): if `ts` falls in 05:00–11:00 UTC (overnight US/EU dead zone — fixed window, no per-audience logic in v1), push to 12:30 UTC same day; else unchanged. Applied to `auto_approve_at` at draft save ONLY when `THEHEAT_ENGAGEMENT_WINDOW_ENABLED=1` (default 0; bot.yml passthrough `|| '0'`). Manual posts unaffected.

**Tests (named):** `test_dead_zone_deferred_to_1230utc`, `test_outside_window_unchanged`, `test_flag_off_no_change`, `test_boundary_0459_and_1100`.

**Gates:** §4. **Traps:** pure function takes the timestamp as an argument — no `datetime.utcnow()` inside (testability + the repo style; grep `_utc_now` for the canonical clock seam).

### S-33 (#9) Hot 10 image card + alt text — L [MINI-PLAN] (flag, default off)

**Why:** a visual anomaly ranking is instantly graspable mid-scroll; text-only leaderboards get skimmed past — and alt text finally serves screen-reader followers.

**Files:** new `src/media/hot10_card.py` (Pillow-only — add `Pillow` to `requirements.txt`); `src/posting/twitter.py` (media upload needs tweepy v1.1 `API` — `tweepy.Client` cannot upload; grep existing auth construction and build the `tweepy.API` sibling from the same OAuth1 creds); `src/orchestrator/hot10.py`; tests.

**Spec (constraints for your mini-plan):** (1) Renderer: pure function `render_hot10_card(cities: list[dict]) -> bytes` (PNG, 1200×675): dark background `#0a0a0a`, mono font (bundle DejaVu Sans Mono via Pillow's default truetype lookup on the runner — pin a font FILE into `src/media/fonts/` to avoid runner drift; check license = DejaVu is free), 10 rows: rank, city+country, anomaly bar (length ∝ anomaly, color by sign: warm `#f87171`, cool `#60a5fa`), `+X.X °C` mono numerals. No logos, no decoration. (2) Alt text: `build_hot10_alt_text(cities) -> str` ≤ 420 chars: lead city + anomaly, then "Top 10 cities by temperature anomaly: " + compact list of top 5 + "and 5 more". (3) Posting: `post_tweet(text, media_png: bytes | None = None, alt_text: str | None = None)` — upload via v1.1 `media_upload` + `create_media_metadata` (alt text), pass `media_ids` to `create_tweet`. (4) Flag: `THEHEAT_HOT10_CARD_ENABLED` default `0` (the dashboard approval queue cannot preview media yet — dark until S-35 or Andrew accepts text-only review; runbook in PR body). (5) Never put image bytes into state-persisted draft JSON. VERIFIED REALITY: saved drafts carry text/metadata only, and the posting path passes only `draft["text"]` into `post_approved` — so this step has two mandatory plumbing changes: (a) at hot10 draft-save time, persist the compact city rows (rank, city, country, anomaly_c, temp_high_c; ≤1 KB total) onto the draft record (e.g. `draft["hot10_rows"]`), and (b) refactor the posting call path so `post_approved` receives the draft dict (S-17 makes the same signature change — if S-17 landed first, reuse its signature; coordinate via grep, do not create two competing signatures). Render the card + alt text at POST time from `draft["hot10_rows"]` when the flag is on.

**Tests (named):** `test_card_renders_10_rows_deterministic` (golden-bytes is brittle across Pillow versions — assert size/format/px-probe of bar colors instead), `test_alt_text_under_420_and_names_leader`, `test_post_tweet_uploads_media_when_provided` (stub tweepy API), `test_flag_off_posts_text_only`.

**Gates:** §4 + Pillow added to requirements.txt with version pin + CI green (Pillow installs on ubuntu runner — no system deps for PNG).

### S-34 (#5) Engagement metrics ingestion — M (flag + API-tier decision rule)

**Why:** the bot learns nothing from readers; even a coarse per-category engagement table makes the editorial loop steerable.

**Files:** new `src/data/twitter_metrics.py`; `src/orchestrator/hot10.py` (piggyback hook at the END of leaderboard mode, guarded by flag — do NOT create a new workflow or a new CLI mode, and do NOT nest metrics under `memory`); `src/state.py` (new top-level key `tweet_metrics: dict[tweet_id, {"at": iso, "likes": int, "retweets": int, "replies": int}]`, DEFAULT_STATE + MERGE_SPEC max-by-`at` per id, golden regen + diff summary); tests.

**Spec:** (1) `fetch_metrics(tweet_ids: list[str]) -> dict` via tweepy `get_tweets(ids, tweet_fields=["public_metrics"])`, batched ≤100. Source ids from `publish_ledger` (S-17) + drafts with `tweet_id`, last 30 days, max 50. (2) Flag `THEHEAT_METRICS_ENABLED` default `0`. (3) **API-tier decision rule:** on first real run attempt (in the PR, via a one-off local invocation with prod creds NOT available — so instead: implement, test with stubs, and mark `DONE(dark; tier-unverified)` with a runbook: flip flag → watch one cycle → if 429/403 with tier-cap error text, flip back and the runbook's verdict is "needs paid tier, park it"). Never poll more than once/day. (4) Surface: none yet (dashboard rendering is future); state table is the deliverable.

**Tests (named):** `test_metrics_batches_and_stores`, `test_metrics_respects_30d_window`, `test_flag_off_noop`, MERGE_SPEC structural green.

**Gates:** §4 + golden regen with diff summary.

### S-35 (#11) Dashboard component extraction — L [MINI-PLAN] [deploy]

**Why:** the remaining 1,800-line page.js mixes ~12 components in one file; the CSS step (0.9.23.0) was step 1, this is step 2 — maintainability for every future dashboard fix.

**Files:** `dashboard/app/page.js` → `dashboard/app/components/{Badge,AutomationStrip,DraftWorkbench,SourcesView,SuppressedView,PipelineView,RunsTable,Hot10Card}.js` (exact set per the mini-plan's read of the file); `dashboard/app/page.js` keeps state + data fetching + tab switching; dead-code removals; tests.

**Spec (constraints for your mini-plan):** mechanical extraction, zero behavior change: each `function XxxView(...)` moves to its own file with explicit prop imports; shared helpers (`timeAgo`, `formatDuration`, badge components — grep duplicates) move to `dashboard/lib/format.js` (S-03 started it) and `dashboard/app/components/shared.js`. Dead code removals sanctioned: the unused `/api/state` route IF grep proves zero consumers (`grep -rn "api/state" dashboard/ --include="*.js"` finding only the route itself), the duplicate funnel key remnant (post S-03), `stateBackend` pill rendering ADDED (it's fetched, never shown — one small visible improvement, sanctioned). One component per commit; `npm test && npm run build` between every commit.

**Gates:** §4 + after merge: deploy + 401 check + click-test note: load `/`, switch all 6 tabs, confirm no console errors via the build (no browser automation needed — Next build + node tests + the deploy 401 are the bar; note the manual-check limitation in the PR).

---

## §8 Failure & escalation protocol

- **Per-step fix budget:** 3 attempts at a red gate. Then: `git checkout main && git branch -D <branch>` (abandon), set PROGRESS row `BLOCKED(<one-line diagnosis>)`, continue to the next eligible step.
- **Hard stops (set status, write `docs/handoffs/THIRTY-LOOP-haltnote-<date>.md`, end the session):**
  - 2 consecutive BLOCKED steps.
  - Any sentinel issue labeled `ours` opening within 24h after one of YOUR merges → first REVERT: `gh pr create` a revert of the suspect merge (`git revert <sha>` on a branch, normal PR flow, merge it), THEN halt-note.
  - Preflight red on main that your last merge caused and one revert doesn't fix.
  - The `test` check failing on a PR for reasons unrelated to your diff (infra) twice in a row.
- **Never** force-push, never `--admin` merge, never edit someone else's open PR (#207 `daily-plan-current` is the grading routine's — do not touch).
- Each halt-note: what was attempted, exact failing output, hypothesis, what NOT to retry blindly.

## §9 Pre-made decisions register (so the executor never has to choose)

| Decision | Ruling | Rationale |
|---|---|---|
| SQLite backend fate | CI smoke, keep (S-18). Deletion = Andrew's future call. | Escape hatch from gist cliff; additive + reversible. |
| Reganom | Runbook only (S-28). **Flip = Andrew.** | Standing directive outranks "no interference". |
| Multi-draft samples / REVISE / per-cycle cap / concurrency / engagement window / hot10 card / metrics | Ship dark, defaults preserve current behavior exactly. **Flips = Andrew** (each step's PR body carries the flip+revert runbook). | They change spend, timing, or follower-visible behavior. |
| Draft CONTENT changes (S-23/24/25/29/31) | Ship live, no flags. | Every draft passes Andrew's manual approval queue — the human gate reviews content. |
| posted_events cap (500) | Unchanged. | Dedup window resize = taste call. |
| New deps | Pillow only (S-33). Everything else stdlib/already-present. | $0-stack discipline. |
| Dashboard deploys | Auto after dashboard-touching merges (pre-authorized). | Pure-refactor parity, verified by 401 check. |
| Anything not covered | Smallest reversible interpretation; note it in the PR body under `## Judgment calls`. | |

## §A Kickoff prompt (paste verbatim into a fresh Claude Code session, model: Sonnet)

> Execute the THIRTY-LOOP plan at `/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/plans/2026-06-11-thirty-loop.md`. Read §0–§6 fully, then the spec of the step you pick; track state ONLY in `docs/superpowers/plans/2026-06-11-thirty-loop-PROGRESS.md`. Use the superpowers:executing-plans skill inline (no subagent-driven development, no Explore agents, no re-auditing — the plan contains the map). Authorizations for this loop, standing: merge your own PRs once the `test` check passes (`gh pr checks <N> --watch` then `gh pr merge <N> --squash --delete-branch`), and run `vercel --prod` from `dashboard/` after dashboard-touching merges. Prohibitions (absolute): no push to main; never set `THEHEAT_REGANOM_ENABLED`; never disable workflows; never edit the gist by hand; obey every STOP in the plan. Work steps in §6 order, one PR per step, until you hit a hard stop (§8) or run out of eligible steps, then write the session handoff the plan describes. Budget discipline: read only what each step names; fresh session per tranche.

## §B Facts file — verified map (as of main `a58a02c` / 0.9.23.0)

**B.1 Layout:** `src/orchestrator/` (cli, run_alerts, common 1687L, triage, finalize, posting, hot10, sources/×22) · `src/data/` (per-source fetchers + `_http.py`, `_freshness.py`, `_s3credentials.py`) · `src/two_bot/` (pipeline, writer, critic, fact_check, prompts/, intern/) · `src/editorial/` (scoring/, thresholds, synthesis, approval, evaluator) · `src/voice/` (safety, generator) · `src/state.py` (1796L; MERGE_SPEC ~:1385) · `src/storage/sqlite_store.py` (dormant) · `dashboard/` (Next.js; `lib/source-health.js` syncs with `scripts/source_health_sentinel.py`) · `tests/` 1631 quick tests · `.github/workflows/` ×4 active.

**B.2 Pipeline flow:** cli → run_alerts → 22 sequential runners → each: fetch (`_fetch_strict`) → `is_duplicate` → score → `_should_draft` → `_enqueue_story_candidate` → drain: TTL sweep → `select_survivors` (cat-cap 2 / pending-type 3 / cycle 3) → `generate_draft` (writer claude-sonnet-4-6 → safety regex+LLM → fact-check gemini-2.5-flash → critic gemini-2.5-pro PASS/KILL) → `save_draft` (5 dedup gates) → state write ×2 (gist read-merge-PATCH).

**B.3 Env/flags (live):** `THEHEAT_GPM_SOURCE=datapool` (repo var) · `THEHEAT_TRIAGE_ENABLED=1` · `THEHEAT_REGANOM_ENABLED` UNSET (forbidden) · `GPM_IMERG_MAX_CITIES=75`, `GPM_IMERG_MAX_WORKERS=8` (bot.yml hardcoded) · secrets: TWITTER_×4, GEMINI_API_KEY, ANTHROPIC_API_KEY, GIST_ID, GH_GIST_TOKEN, BLUESKY_×2, NASA_FIRMS_API_KEY, EARTHDATA_TOKEN.

**B.4 source_health keys (34):** air_quality, ao, auto_publish_due, ch4_milestone, co2, copernicus_ems, coral_dhw, drought, enso, fire_footprint, firms, gdacs, gpm_imerg, ice_mass_antarctica, ice_mass_greenland, jtwc, leaderboard, load_cities, manual_publish, nao, nao_ao_alignment, nhc, nsidc_snow, nws_alerts, ocean, ocean_sst, ocean_sst_anomaly, open_meteo_extreme_signals, ozone_hole, pdo, river_gauges, sea_ice_antarctic, sea_ice_arctic, synthesis_fire_drought_heat, water_levels.

**B.5 Real prod error strings (test fixtures):** `GPM IMERG fetch hit 3 repeated ConnectTimeout failures for 2026-06-08; first error: Connec…` · `GDACS fetch failed: HTTPSConnectionPool(host='www.gdacs.org', port=443): Max retries excee…` · `FIRMS fetch failed: HTTPSConnectionPool(host='firms.modaps.eosdis.nasa.gov', port=443): Ma…` · `JTWC fetch failed: 403 Client Error: Forbidden for url: https://www.metoc.navy.mil/jtwc/rs…` · `River gauge flood-stage fetch failed for 07010000: 403 Client Error: Forbidden for url: ht…` · `Copernicus EMS flood fetch failed: 403 Client Error: Forbidden for url: https://rapidmappi…` · `coral_dhw fetch failed: 403 Client Error: Forbidden for url: https://coralreefwatch.noaa.g…` · `50 air-quality city fetches failed`.

**B.6 Prod state snapshot (read-only, for simulations):** `gh gist view 06c02c97ffc0d11458687f1ed998d9e5 -f state.json > /tmp/st.json` (~980 KB; the ~900 KB inline-API cliff is real — incident 2026-05-13). NEVER write back.

**B.7 Funnel evidence (why T5 exists):** 7-day: observed 924,425 → promoted 26,161 → drafted 6. Suppression kills: triage_cap 135 · critic 30 · score_gate 20 · writer 13 · fact_check 2.

**B.8 Outage evidence (why T1/T2 exist):** 40-run window fails — gpm 18 (post-datapool residue 5/12), gdacs 9, firms 5 (already retried!), jtwc/river/copernicus 3 each + coral 2 (all 403). Shapes: gpm `XXXXXXXXXX......X....X.X....X.X..XXX....` · gdacs `...........XX.....X.XX...XXX.......X....` · firms `....X...........X....X.X...........X....`.

**B.9 Merge mechanics:** `gh pr checks <N> --watch` (test check required; `--auto` disabled) → squash → `git checkout main && git pull`. Grading PR #207 (`daily-plan-current`) is the routine's — never touch.
