# @theheat — Project Briefing

**Last updated:** 2026-05-12 (end-of-day — voice overhaul + dashboard refresh fix + FRP rounding).
**Status:** **PIPELINE WORKING END-TO-END WITH NEW VOICE + STRICTER FACT-CHECK PASS-THROUGH.** Five PRs merged today. Writer prompt now teaches Attenborough/Economist voice with explicit system-explainer mandate (#74), nightly voice-regression stays green on cold records via a topographic exemplar (#75), a code-side length-cap retry guarantees no >280-char tweet can ship (#76), the dashboard refresh button gives visible feedback for the first time (#78), and fire FRP is rounded at the bundle so fact-check no longer kills on decimal-precision mismatch (#80). Voice-regression: **12/12 green**.
**Latest merged commits (2026-05-12):** `4cd1b20`...`38e0c17` (#74 Attenborough/Economist voice) → `c8c30c5` (#75 cold-record exemplar #6 + compact Verkhoyansk exemplar) → `7542728` (#76 writer-side length retry + hard kill) → `77ad753` (#78 dashboard refresh-button feedback — refreshing/lastUpdated/error states) → `4677869` (#80 fire FRP rounded to 1 decimal at the bundle builder; closes the BUNDLE_FACT decimal-precision kill class).
**Open PRs:** #72 (mypy ignore-list removal via BotState TypedDict — CI green, ready). #73 (auto-PR daily-plan 2026-05-11: 8 drafts, 12.5% A-rate). #77 (this docs sweep). #79 (auto-PR daily-plan 2026-05-12: 0 drafts; revised in `dcc6848` after Codex caught a tolerance contradiction — addressed by #80).
**Earlier this stack (2026-05-10):** `8ab835c` (#67 month-repetition false-positives + Andrew's single-digit Celsius cold-record relaxation) → `1ed7e2c` (#68 Codex follow-up: tighten both regexes) → `8490ed4` (#69 docs sweep) → `d6665a2` (#70 parallel-session WIP reconciliation) → `84f496d` (#71 dashboard last_error surfacing).
**Earlier (2026-05-09):** `4cb1eba` (#55 flaky tests) → `3f92b9d` (#56 CI on PRs + Node 24) → `15469b9` (#57 hermeticity gate) → `84c7d9f` (#58 anti-fabrication safety) → `7015e01` (#60 safety gate inline in pipeline) → `03ba309` (#61 voice-replay regression suite) → `1d3e490` (#62 ruff) → `13480a2` (#63 mypy) → `69f2fcf` (#64 dashboard source-health) → `0fdec6c` (#65 doc sweep).
**Branch protection:** required `test` status check on `main` (admin bypass for emergencies). Every change is a PR with green CI.
**Tests:** **884 passing** locally (was 876 at end of 2026-05-10; +7 `TestLengthRetry` tests in #76, +1 `test_build_fire_bundle_rounds_frp_to_one_decimal` in #80). +12 voice-replay fixtures run nightly via `voice-regression.yml`; final run after #76 was 12/12 green.
**Cost:** GHCN-Daily free. Sonnet writer ~$13/mo + voice-regression nightly went from ~$6/mo to ~$9/mo (the length retry adds up to 2 extra Sonnet calls per fixture worst case). Total ~$22/mo Anthropic on top of the existing Sonnet evaluator (~$60-90/mo per memory). Gemini Flash usage unchanged.

## What changed structurally on 2026-05-11/12 (voice overhaul + dashboard refresh + FRP rounding)

Five PRs landed, all merged. Cumulative effect: (1) the writer prompt teaches a coherent voice (Attenborough/Economist with explicit system-explainer mandate, wink-kicker bans, fabrication bans), (2) a code-side length retry makes the 280-char cap a hard guarantee not a hope, (3) the dashboard refresh button finally gives visible feedback (was silently doing the right thing), (4) fire FRP is rounded at the bundle so the fact-checker stops killing fire drafts on decimal-precision mismatch.

- **PR #74 — Attenborough/Economist voice + system-explainer mandate** (4cd1b20...38e0c17). Rewrote the writer prompt's voice anchor from "Economist correspondent" to "David Attenborough and The Economist" with explicit signature-move description: report the precise data, name the system that produces it, stop. Triggered by Andrew rejecting a wink-kicker on the Point Lay May blizzard draft ("The calendar says spring."). The OLD prompt's "Context" example was literally `"Blizzard warning in Point Lay. It is May 1."` — it was actively teaching the failure mode. New sections: THE SIGNATURE MOVE (3-beat structure + "delete the last sentence" test), declarative climate-arc-vs-stakes guidance, HARD RULE banning wink-shape (not just literal phrases) plus the no-self-supplied-facility-MW rule (after observed Hoover Dam + Akosombo Dam fabrications). 4 approved exemplars (Point Lay, Imperial, Mauna Loa, Mali fire). Iterated 3x across the merged commits before landing.

- **PR #75 — cold-record exemplar to stop voice-regression flap** (be0a02f + 2aa8e04 → c8c30c5). The merged #74 prompt had no `monthly_low` exemplar; nightly voice-regression kept failing on Sissonville and Verkhoyansk with the writer reaching for verbose "Cold records in an era of warming..." preambles. Added APPROVED EXEMPLAR #6 at 262 chars (Sissonville-style topographic mechanism only, no warming preamble) + Andrew compacted the Verkhoyansk exemplar #5 (drops "the cold poles are warming faster..." second-half clause). Plus a declarative rule: for `monthly_low` / `country_low`, pick topographic / geographic / local-flow mechanism, skip warming framing.

- **PR #76 — writer-side length-cap retry + hard kill** (7542728). Prompt-only length discipline is fragile under Sonnet's sampling stochasticity. Added a code-side guardrail in `src/two_bot/writer.py:write_tweet`: if the model returns a tweet > 280 chars, retry up to `LENGTH_RETRY_BUDGET=2` times with declarative length feedback appended to the user prompt. After 3 failed attempts, return KILL with explicit `kill_reason` ("writer produced over-280-char tweets across 3 attempts (last attempt: N chars)"). Probability math: at worst-observed p=0.2 per-call over-length rate, all 3 attempts fail at p³=0.8%. Cost: ~$0.30/voice-regression run extra. 7 new `TestLengthRetry` tests cover retry, kill, no-retry-on-fit, no-retry-on-kill, feedback content, boundary at 280, boundary at 281. **Twitter no longer sees a >280-char string from this pipeline, regardless of how the model samples on any given call.**

- **PR #78 — dashboard refresh-button feedback** (77ad753). Andrew reported "when I click refresh on the dashboard it doesn't look like anything happens." Diagnosed: all 5 API calls (state, drafts, suppressions, config, source-health) were firing correctly in ~60ms locally — the bug was purely UX. Button stayed labeled "refresh" the whole time, no disabled lock, no loading indicator, and errors went to `console.error` silently. Even on a successful refresh, if the underlying data hadn't changed, the page looked identical to before the click. Fix: three new states in `fetchData` — `refreshing` (drives "refreshing…" label + disabled + orange tint), `lastUpdated` (renders "updated 5s ago" via the existing `timeAgo()` helper), and `refreshError` (surfaces a "refresh failed" pill with the error as a hover-tooltip). Plus `min-width: 96px` to prevent layout shift between the two labels. Existing 16 dashboard tests still pass; no API-contract changes.

- **PR #80 — fire FRP rounded to 1 decimal at the bundle builder** (4677869). NASA FIRMS returns FRP at two-decimal precision (e.g. `480.34 MW`); the fact-check prompt requires exact numerical match — *"Verify exact match (number, unit, date). Mismatches = failure."* — with no tolerance. Writer rounding `480.34 → "480 MW"` produced BUNDLE_FACT kills on three fires in two cycles (480.34 → 480, 547.92 → 548, 301.55 → 301). Codex review on the daily-plan PR #79 caught that the proposed P2 fix would have added a writer-prompt rule claiming a ±0.5 MW tolerance the live fact-checker doesn't have — the doc was internally inconsistent. Plan revised (commit `dcc6848` on PR #79) and implemented as a one-line bundle-side change in `src/two_bot/intern.py:build_fire_bundle` — both `headline_metric.value` and `raw_signal_dump.frp` get `round(fire.frp, 1)`. The bundle becomes the 1-decimal source of truth; writer naturally echoes the clean value; fact-checker confirms exact match. Regression test covers five representative cases including the three production failures plus a banker's-rounding edge.

### What today's session proved

The voice work made the prompt smaller but smarter — declarative rules + 6 exemplars + 1 code-side guardrail = the system that consistently passes voice-regression. The iter-4 trap of trying imperative process language ("count, identify, remove, recount, repeat") was caught mid-PR by the harness itself: that prompt broke strict-JSON output on 5/12 fixtures. Saved to memory ([feedback_prompt_json_contract](memory/feedback_prompt_json_contract.md)) — imperative process steps leak into strict-JSON output.

The FRP rounding fix demonstrates the same lesson at a different layer: rather than asking the model to behave better with a soft rule the runtime contract doesn't honor, fix the data at the source so the contract holds naturally. Codex caught the version that would have leaked.

Also killed pending draft #156 Mankato (manual editorial — 0.1°C tied record in 16yr archive didn't clear the editorial bar set by the new voice).

| Layer | Status |
|---|---|
| Writer prompt voice | **Rewritten 2026-05-12 (#74-#75) — Attenborough/Economist** |
| Code-side length guarantee | **NEW 2026-05-12 (#76) — retry + kill, hard cap** |
| Safety regex at draft-time | #60 inline + #67/#68 precision-tuned |
| Fact-checker | Existing — exact match contract preserved |
| Bundle-side FRP normalization | **NEW 2026-05-12 (#80) — round to 1 decimal at intern.py** |
| Safety regex at post-time | Existing |
| Nightly Sonnet replay | #61 firing daily; 12/12 green after #76 |
| Source health visibility | #64 + #71 last_error surfacing |
| Dashboard refresh UX | **Fixed 2026-05-12 (#78) — refreshing/lastUpdated/error states** |
| Daily quality grading | Repaired #66 → validated by #73 + #79 auto-PRs firing daily |

## What changed structurally on 2026-05-10 (cron-feedback-loop session)

Two PRs and one out-of-tree routine fix, all driven by the new voice-regression harness's first run catching real signal:

- **PR #67 — `check_month_repetition` rewrite + single-digit Celsius cold-record relaxation.** Voice-regression cron at 10:06 UTC rejected three otherwise-good monthly_low/high tweets (Sissonville, Dayton, Verkhoyansk) with `Month '<x>' mentioned N times — redundant date`. The old `count >= 2` rule was tuned for the bureaucratic restatement `"NWS issued… April 10, 2026. It's April."` but false-positived on the now-standard `"hit X on May 4 — new May cold record"` shape where the month is load-bearing twice (date + record class). Replaced with two targeted patterns: literal `"It's <Month>"` standalone, and same-month year-anchored restatement. Safety net at 4+ mentions for egregious padding. Also picked up Andrew's parallel-session WIP for `check_truncated_temperature` — single-digit Celsius is valid for cold-record signals (Dayton's 4°C is a real reading), so the Celsius branch was dropped and Celsius is now fact-checker territory.

- **PR #68 — Codex review follow-up.** Codex flagged two precision bugs in #67's regexes: (1) the `it'?s` pattern made apostrophe optional, false-positiving on possessive `"its May record"`; (2) the year-anchored pattern used a non-capturing group `(?:Month)` for the second occurrence instead of a backreference, false-positiving on cross-month comparisons like `"April 2026. May records..."`. Fixed: apostrophe now required (straight + curly), second occurrence now `\1`. Three regression tests covering the exact Codex examples.

- **Grading-agent routine repaired (out-of-tree, via [routine UI](https://claude.ai/code/routines/trig_016PGeHZgEYWmeQhx1xGmYg6)).** PR #66 (auto-opened by the agent at 15:06 UTC) reported zero drafts graded due to `403 API rate limit exceeded` on the unauthenticated `curl https://api.github.com/gists/<id>`. Updated the routine prompt: Step 2 now does `git clone https://gist.github.com/<id>.git` first (public gists are git repos, no auth needed for reads, no REST rate limit) with `gh api` as fallback. Step 7 (gist write for staleness rejection) now degrades gracefully — logs a skip note in the PR body if `gist:write` scope is missing, instead of aborting the whole run. Added a global "DO NOT abort on infra failures" hard constraint. Validates on next cron at 2026-05-11 15:03 UTC.

### What today's session proved

The voice-regression harness is **earning its $6/mo**. PR #67 + #68 closed a feedback loop that would otherwise have only been visible after live posting resumed and a fact-check kill cascade made it into production. Net effect on the regression surface from yesterday's stack:

| Layer | Status |
|---|---|
| Writer prompt (HARD RULES) | Tested via #58's prompt-content tests |
| Safety regex at draft-time | #60 inline + #67/#68 now precision-tuned |
| Fact-checker | Existing |
| Safety regex at post-time | Existing |
| Nightly Sonnet replay | **#61 firing daily; caught 3 false positives on first run** |
| Source health visibility | #64 Sources tab |
| Daily quality grading | Repaired today (post-rate-limit fix) |

## What changed structurally on 2026-05-09 (ship-quality session)

Five distinct streams, each its own PR, each verified by the new pre-merge CI gate:

- **CI on PRs (#56).** `bot.yml` now triggers on `pull_request: { branches: [main] }` so the `test` job runs on every PR. The `run` job stays scheduled-only (`github.event_name != 'pull_request'`) — no tweet posting / gist writes / API quota burn on PRs. `actions/checkout@v4` → `@v6` and `actions/setup-python@v5` → `@v6` (Node 24-native, clears the deprecation warning).
- **Hermeticity gate (#57).** Autouse fixture in `tests/conftest.py` monkey-patches `socket.socket.connect` to refuse non-localhost connections during test execution. Pure stdlib (`unittest.mock`), no new pip dep. Any test that forgets to mock the network layer fails immediately with an actionable error pointing at the missing mock. This closes the class of bug that caused PR #55's flake.
- **Anti-fabrication safety + HARD RULES tests (#58).** Five new `BANNED_PATTERNS` in `src/voice/safety.py` mirror the writer prompt's verbatim banned-phrase examples (`"three weeks into meteorological spring"`, `"January reading"`, `"flowers are already up"`, `"the ground froze"`, `"fruit trees blooming early"`). New `TestFabricatedContext` class in `tests/test_safety.py` (8 tests, including 3 negative tests protecting `"Fruit trees were not consulted"` flourish + `"three springs later"` echo). New `TestWriterPromptHardRules` class in `tests/two_bot/test_writer.py` (11 tests, one per HARD RULE bullet asserting canonical anchor is present so a future prompt edit that drops a bullet fails at PR time).
- **Safety inline in `pipeline.generate_draft` (#60).** `run_safety_pipeline` was previously only invoked at post-time; the inline integration kills bad drafts at write-time. Combined with #58, the safety regex catches anti-fabrication phrases at the earliest possible point.
- **Nightly voice-replay regression suite (#61).** New `tests/voice_regression/` directory with `StoryBundle` fixtures and a writer-replay harness. New workflow `.github/workflows/voice-regression.yml` runs daily at 09:00 UTC against the real Anthropic writer + Gemini fact-checker, asserting every output passes the safety pipeline. Triggers: `schedule` daily, `workflow_dispatch` manual, `pull_request: labeled` with `voice-check` label for opt-in PR gating. Cost: ~$0.20/run × daily ≈ $6/mo.
- **Ruff lint in CI (#62).** New `pyproject.toml` config selects E/F/W with project-wide `E402` ignore (codebase puts `from __future__` before docstring across 18 files). New CI step runs `ruff check src/ tests/`. Caught and fixed 5 pre-existing issues (dead `age` / `years_ago` variables, lambda-assignment in test, dead `a`/`b` in `test_era_anchors.py`). Auto-fix removed 4 imports that LOOKED unused but were accessed via test patching — restored each with `# noqa: F401` and a comment.
- **Mypy permissive baseline (#63).** Permissive (`check_untyped_defs`, `no_implicit_optional`, `ignore_missing_imports`). Wired into CI test job. Three modules use `ignore_errors = true` pending a `bot_state` TypedDict refactor: `src.main` (47 errors after rename), `src.state` (68), `src.editorial.scoring` (47). **Real bug found:** variable `record` was reassigned across two type domains in `src/main.py` (`SeaIceRecord | None` from `sea_ice.detect_record_low` at line 1971; `IceMassRecord | None` from `ice_mass.detect_monthly_record` at line 2400). Functionally safe but a real maintenance hazard — renamed the IceMass variable to `ice_record` in lines 2400-2480. Plus 6 small Optional unwrap fixes across LLM-response handlers (`response.text or ""` and an isinstance narrowing for Anthropic content blocks).
- **Dashboard per-source health view (#64).** New `Sources` tab in the dashboard aggregates per-source success rate, last error, and observation/draft totals across the last 20 runs (`bot_state.run_history`). Sorted worst-first so problem sources surface immediately. New `GET /api/source-health` endpoint with a 4-tier health classifier (`idle` / `healthy` / `degraded` / `unhealthy`) over **active** runs only — skipped sources (e.g. drought on a Tuesday) classify as `idle`, not `unhealthy`. 4 new tests in `dashboard/tests/source-health.test.js`.

The day also shipped **branch protection** (Settings → Branches → require `test` to pass on `main`; admin bypass on for emergencies; no force-push, no deletions). With CI now triggering on PRs (#56), this closes the loop where a red PR could merge silently.

### Net effect on regression surface

```
Pre-2026-05-09                       2026-05-09 stack
─────────────────────────            ──────────────────────────────────────────
Test gap → flaky 4 days              fix #55 + hermeticity gate #57
PR merges with no checks             #56 PR trigger + #62 ruff + #63 mypy in CI
Anyone can push red to main          branch protection #F
Voice prompt drift = silent          #58 prompt-content tests (one per HARD RULE)
Fabrication = fact-check kill        #58 + #60 safety regex at draft-time
No replay coverage                   #61 nightly voice-regression suite
Suppression view shows kills         #64 source-health surfaces failing sources
```

## What changed structurally on 2026-05-08

- **Suppression ledger** (`bot_state.suppressions`) — every editorial-gate near-miss AND every downstream kill (writer / fact-check / pipeline-error) now records `id` + `ts` + `run_id` + `source` + `stage` + `event_id` + `category` + `score_total` + `threshold` + `reasons` + `summary`. Surfaced via `GET /api/suppressions` (auth-protected) and the dashboard's `Suppressed` tab.
- **Shared boundary helpers** (`src/two_bot/json_utils.py`, `src/two_bot/retry.py`, `src/data/source_status.py`) — one `json_default` covers date/datetime/Decimal/set/dataclass/bytes; one `loads_model_json` handles fences + preamble + comments + trailing commas; one `call_with_retries` wraps every LLM call with bounded exponential backoff; typed `SourceFetchError` / `SourceSkipped` distinguish transport failure from "legitimately quiet."
- **Bundle enrichment** for GHCN-touching builders (`build_monthly_high_bundle`, `build_record_bundle`, `build_all_time_record_bundle`, `build_anomaly_bundle`):
  - Station name normalized: `SISSONVILLE 1SW` → `Sissonville`, `MIAMI INTL AP` → `Miami`, `WFO SAN JUAN` → `San Juan`.
  - US state name expanded: `WV` → `West Virginia`, included in bundle's `where` and `current_facts`.
  - `observation_kind` fact: `"overnight low"` for TMIN-based, `"afternoon high"` for TMAX-based — lets writer say "May night" without fact-check rejecting "night" as not-in-bundle.
  - Integer Fahrenheit pre-computed alongside Celsius. `audience_unit` fact tells writer `"fahrenheit_first"` for US locations, `"celsius_first"` elsewhere.
- **Writer prompt** (`src/two_bot/prompts/writer_prompt.py`) gains a `TEMPERATURE FORMATTING` section: lead with `°F` for `audience_unit=fahrenheit_first`, `°C` elsewhere. Forbids ad-hoc conversions; must use bundle's pre-rounded values.
- **Anthropic writer client** timeout 90s → 180s (PR #41); the SDK auto-retries on 529s but our `call_with_retries` wraps externally too.
- **Gemini timeout values** corrected: `fact_check.py` 90 → 90000ms (90s), `writer.py` Gemini fallback 90 → 180000ms, `claim_extractor.py` (was unbounded) → 90000ms (PR #43 + #47). Regression test introspects source for `HttpOptions(timeout=NNN)` and asserts ≥5000.
- **Dashboard `mergeState()`** in `dashboard/lib/state-store.js` now spreads `{...base, ...next}` before explicit per-key merges so Python-owned keys (`memory`, `record_streaks`, `data_source_failures`, `ocean_sst_streak`, `ice_mass_*`, `fire_complex_tiers`, `synthesis_*`) survive every dashboard write. Was silently erasing them on every approve/reject click.
- **SQLite `_METADATA_JSON_KEYS`** now includes `memory` and `data_source_failures` — were lost on every sqlite-backed round-trip.

## Posting resumption bar (set 2026-04-26)

**Posting is paused until the majority of corpus-graded drafts in a cycle earn A grades.** Track in `docs/QUALITY_TREND.md`. The voice→two-bot port (May 3–4) was triggered after a draft shipped *"75.9F in Riga today, the record for this date is 72.7F"* — no country, trivial signal. The May 7 GHCN migration adds the *signal-side* fix: instead of polling 638 cities (which missed station-level records like Verkhoyansk, Phalodi, Death Valley), the bot now sees the full 11,907-station population. The two-bot writer + station-level coverage are the bet that closes the quality gap. Editorial gate + fact-check still backstop.

---

## What is this?

@theheat is an automated climate data bot for X (Twitter). It monitors free public data sources for extreme climate signals — all-time heat records, monthly records, temperature anomalies, record-breaking streaks, simultaneous events across cities, wildfires, floods, storm surge, CO2 milestones, sea ice loss, drought, ocean waves, ENSO shifts, severe weather — then generates tweets and queues them for review.

**Core principle (session-hardened):** It's a utility that surfaces astounding climate facts. Not a growth startup. Astounding data → clean presentation. The DATA is the product. If the facts are lame, no voice trick, visual, or meme template saves it.

**What the account is NOT:**
- Not a "cynical weatherman" voice account (this framing was killed in April 2026 — it was too mannered)
- Not a breakout-viral content machine (research confirms breakout climate viral requires human timing/register-break)
- Not a competitor to @extremetemps (it's a utility, not a business)

**Target audience:** Data people. Weather nerds. Climate-aware people who want the signal without the preaching.

---

## Architecture

```
CRON (GitHub Actions free tier, 6x/day alerts + hourly auto-approval)
│
├── Fetch from data sources (14 sources — 9 always-on, 5 day-gated)
│   ├── Open-Meteo ──────── city temps + archive (613 cities, 179 countries, all records)
│   ├── NASA FIRMS ────────── satellite wildfire detections (VIIRS_SNPP_NRT)
│   ├── NIFC WFIGS ────────── US fire-complex cumulative burn area (daily, tier-crossing only)
│   ├── NOAA GML ──────────── Mauna Loa CO2 (daily PPM, capped at 12 tweets/year)
│   ├── NWS Alerts ────────── US severe weather — Tornado Emergency, Flash Flood
│   │                          Emergency, Hurricane, Storm Surge, Extreme Wind,
│   │                          Blizzard, Ice Storm, Extreme Cold, Extreme Heat.
│   ├── GDACS ──────────────── Red-tier global disasters only
│   ├── NSIDC ──────────────── Arctic/Antarctic sea ice (Mondays only)
│   ├── GRACE-FO (PODAAC) ─── Greenland + Antarctica monthly ice mass (Mondays only,
│   │                          Earthdata Login required, capped at 8 tweets/year)
│   ├── US Drought Monitor ── state drought intensity (Fridays only)
│   ├── NOAA CPC ──────────── ENSO transitions (1st of month)
│   ├── Open-Meteo Marine ── ocean wave heights (16 points, location-aware thresholds)
│   ├── NOAA CO-OPS ────────── coastal tide gauge storm surge (12 stations)
│   ├── USGS Water ────────── river flood stages (12 gauges)
│   └── NOAA OISST v2.1 ──── global-mean sea surface temperature via ClimateReanalyzer.
│                              Fires on archive-record streaks of 5+ days (day-5 first-fire,
│                              then milestones at 10, 25, 50, 100, 150, 200, 250, 300, 365,
│                              400, +50 thereafter). Threshold: 78. Approval: suggested_auto,
│                              90-min delay.
│
├── Detect extreme signals per city (unified bundle)
│   ├── All-time records (hottest/coldest in ~30yr archive) — elite
│   ├── Country records (country-wide archive peak across all sampled
│   │   cities in that country — the biggest single story)
│   ├── Monthly records (hottest April ever, etc.) — strong
│   ├── Anomaly records (15°C+ above/below monthly mean) — strong
│   ├── Calendar-date records (legacy) — strong if big margin/old record
│   ├── Record streaks (3+ consecutive daily records per city)
│   └── Simultaneous events (5+ cities same day → one summary signal)
│   Picks strongest signal per city; one tweet per bundle max.
│
├── Cross-source synthesis (meta-layer, fires after per-source sections)
│   └── Fire × Drought × Heat (US state, 14-day window, per-state cooldown)
│
├── Score events (editorial scoring — 22+ scoring functions, thresholds 56-82)
│
├── Deduplicate against state (last 500 event IDs)
│
├── Generate tweet candidates (Gemini 2.5 Flash, 4 per event)
│
├── Safety pipeline (40+ regex + LLM check)
│   ├── Press-release opener ban (NWS/NOAA/GDACS...)
│   ├── Weather-service boilerplate ban (HURRICANE-FORCE, catastrophic,
│   │   life-threatening, EXTREME force, dangerous conditions)
│   ├── Tell-don't-show ban (THIS IS SERIOUS, pay attention, you should
│   │   be worried, this is rare)
│   ├── Label:value ban (Severity: Severe, Alert level: Red)
│   ├── Explainer ban (highest severity level GDACS issues)
│   ├── Tier explainer ban (the highest alert tier)
│   ├── Month-repetition check (catches "April 10. It's April.")
│   ├── Truncated temp check (rejects "1F forecast" bugs)
│   ├── Bureaucratic suffix ban (-26, -2026)
│   └── LLM harm check (Gemini)
│
├── Heuristic ranking (clarity/context/voice/punch)
│
├── Virality evaluator — Claude Sonnet 4.6
│   ├── Scores 5 dimensions: awe, comparison, social currency, opener, show-not-tell
│   ├── Passes if 7+ on 4 of 5
│   ├── Fails → provides rewrite
│   ├── Rewrite runs through safety + score-regression check
│   └── Evaluator FAIL with no usable rewrite = kills the draft entirely
│
├── Per-cycle cap (max 3 drafts, top by signal score)
│
├── Save drafts to GitHub Gist (state.json)
│
├── AUTO-APPROVAL QUEUE (hourly cron)
│   ├── Low-sensitivity + high-scoring drafts auto-post after timed delay
│   └── Safety pipeline re-runs before every auto-post (double-gate)
│
└── DASHBOARD (Next.js 15 on Vercel, auth-protected)
    ├── Human reviews pending drafts
    ├── Posts to X via Tweepy + cross-posts to Bluesky
    └── Bulk-reject below threshold API (for cleaning backlogs)
```

---

## Codebase

```
theheat/
├── src/                              ~7,800 lines Python
│   ├── main.py                       Orchestrator (~1,900 lines; +suppression hooks +SourceSkipped catch)
│   ├── state.py                      Gist state + json_default + suppression merge (560 lines)
│   ├── config.py                     Central model config (CHEAP_MODEL / WRITER_MODEL)
│   ├── data/                         Data source modules
│   │   ├── open_meteo.py             Unified extreme signal detection + country aggregation
│   │   │                               (event dataclasses now carry signal_date + state)
│   │   ├── ghcn.py                   NOAA GHCN-Daily detection — 11,907 stations.
│   │   │                               normalize_station_name() + expand_us_state() upstream
│   │   │                               of bundle creation so writer + fact-check see clean names
│   │   ├── ghcn_db.py                SQLite threshold cache schema + upsert helpers
│   │   ├── ghcn_format.py            Pure-stdlib parser for NOAA .dly + superghcnd_diff
│   │   ├── source_status.py          NEW (#42). Typed errors:
│   │   │                               - SourceFetchError (transport/schema)
│   │   │                               - SourceSkipped (intentional, e.g. missing optional config)
│   │   ├── firms.py                  NASA FIRMS wildfires (raises SourceSkipped/FetchError)
│   │   ├── fire_footprint.py         NIFC WFIGS (raises SourceFetchError on partial fetch)
│   │   ├── co2.py                    Mauna Loa CO2 milestones (12/yr cap)
│   │   ├── nws_alerts.py             NWS — 9 extreme-tier event types
│   │   ├── gdacs.py                  GDACS — Red-tier only, intensity-tier dedup
│   │   ├── sea_ice.py                Arctic/Antarctic sea ice (Mondays only)
│   │   ├── ice_mass.py               GRACE-FO Greenland + Antarctica (Mondays, Earthdata)
│   │   ├── ocean_sst.py              NOAA OISST v2.1 global-mean streaks
│   │   ├── drought.py                US Drought Monitor (Fridays only)
│   │   ├── enso.py                   ENSO transitions (1st of month)
│   │   ├── ocean.py                  Extreme waves (location-aware thresholds)
│   │   ├── water_levels.py           NOAA CO-OPS storm surge
│   │   └── river_gauges.py           USGS river flood stages
│   ├── editorial/
│   │   ├── scoring.py                22+ signal-scoring functions
│   │   ├── candidates.py             Heuristic ranking (clarity/context/voice/punch)
│   │   ├── approval.py               3-tier approval policy
│   │   ├── evaluator.py              Claude Sonnet 4.6 virality evaluator
│   │   ├── synthesis.py              Cross-source synthesis rules (fire×drought×heat)
│   │   ├── regions.py                Lat/lon → US state + city → state helpers
│   │   └── _util.py                  Shared clamp utility
│   ├── two_bot/                      Live writer pipeline (since 2026-05-04 port)
│   │   ├── pipeline.py               generate_draft(bundle, state, result_out=...) → draft|None
│   │   │                               populates kill_stage + kill_reason in result_out
│   │   ├── intern.py                 23 build_*_bundle functions (one per signal source)
│   │   │                               +helpers: _format_where, _ghcn_observation_facts,
│   │   │                                          _c_to_f, _is_us_country, _audience_unit_facts
│   │   ├── writer.py                 Sonnet 4.6 writer.
│   │   │                               180s Anthropic timeout. Imports from json_utils + retry.
│   │   ├── fact_check.py             Gemini Flash fact-checker (90000ms = 90s timeout)
│   │   ├── claim_extractor.py        Gemini Flash claim extractor (90000ms timeout — fixed #47)
│   │   ├── memory.py                 Two-bot reuse memory (banned moves, era anchors, etc.)
│   │   ├── types.py                  StoryBundle / WriterResult / FactCheckResult dataclasses
│   │   ├── json_utils.py             NEW (#42). Shared boundary helpers:
│   │   │                               - json_default: date/datetime/Decimal/set/dataclass/bytes
│   │   │                               - extract_json_payload: balanced span finder, string-aware
│   │   │                               - loads_model_json: fence + preamble + comments + commas
│   │   ├── retry.py                  NEW (#42). call_with_retries — bounded exp-backoff
│   │   │                               around every LLM call (writer, fact-check, claim-extract)
│   │   └── prompts/
│   │       ├── writer_prompt.py      System prompt + TEMPERATURE FORMATTING section (#46)
│   │       ├── fact_check_prompt.py  Strict entity-match contract
│   │       └── claim_extractor_prompt.py
│   ├── voice/
│   │   ├── generator.py              Dead since 2026-05-04 (slated for deletion).
│   │   │                               No live call sites in main.py. 1,730 lines.
│   │   ├── templates.py              Fallback templates (no AI needed)
│   │   └── safety.py                 Two-layer safety pipeline (179 lines)
│   ├── posting/
│   │   ├── twitter.py                Tweepy (rate-limit aware)
│   │   └── bluesky.py                AT Protocol cross-posting
│   └── storage/
│       └── sqlite_store.py           SQLite backend (PRESERVES memory + data_source_failures
│                                       since #47; was previously lossy on those keys)
│
├── tests/                            500+ tests across signal, scoring,
│                                     generator, safety, state, synthesis,
│                                     and integration suites
│
├── dashboard/                        Next.js 15 + React 19 on Vercel
│   └── app/
│       ├── page.js                   Control panel UI (dark terminal theme)
│       ├── layout.js                 
│       └── api/
│           ├── state/route.js        Read Gist state
│           ├── drafts/route.js       Draft management + bulk-reject-below
│           ├── generate/route.js     Trigger GitHub Actions
│           ├── post/route.js         Post approved tweet
│           └── trigger/route.js      Trigger specific run modes
│
├── brand/
│   ├── VOICE.md                      Voice spec (moved from root in April 2026)
│   ├── MESSAGING_ARCHITECTURE.md     Positioning
│   ├── VIRALITY_RESEARCH.md          Research reference (Part 1 content-first, Part 2 platform mechanics)
│   ├── EXEMPLARS.md                  Verified viral climate tweets with real engagement data
│   └── VOICE_PATTERNS.md             Voice pattern reference (labeled honestly: not proven-viral)
│
├── data/
│   ├── cities.csv                    613 cities across 179 countries (city, country, lat, lon, elevation_m)
│   └── normals.csv                   Climatological normals
│
├── BRIEFING.md                       This file — session entry point
├── PIPELINE.md                       Manufacturing-style flow diagram
├── docs/
│   ├── DESIGN.md                     Architecture decisions
│   ├── BUILD_BRIEF.md                Product scope
│   ├── FUTURE_STATE.md               Aspirational future
│   ├── SESSION_BRIEF.md              Latest session context (see for current thinking)
│   └── mockups/                      Dashboard mockups (HTML)
└── requirements.txt                  tweepy, atproto, google-genai, anthropic, requests, pytest, pytest-mock, responses
```

---

## Data Flow: Alert Cycle (updated)

Every 4 hours, GitHub Actions runs `python -m src.main alerts`:

1. **Read state** from GitHub Gist
2. **Fetch data** from all sources (each wrapped in try/catch)
3. **Detect extreme signals per city** (NEW unified handler):
   - One archive fetch per city (257 priority-ordered) yields ALL signal types
   - Bundle includes: all_time_high/low, monthly_high/low, anomaly_hot/cold, calendar_date_high/low
   - Handler picks strongest signal per city (all-time > monthly > anomaly > calendar-date)
   - Monthly records whose prior record was set in the current calendar year are suppressed (confusing framing — "hottest April, old record set in 2026" reads as nonsense)
   - Country-level aggregation runs after the per-city loop: for each country with ≥2 sampled cities, compare today's peak vs the archive-wide peak across the same cities. Emits a `country_high` / `country_low` signal when today exceeds the archive. Threshold 82, elite by default.
4. **Score events** — editorial scoring with per-category thresholds (62-80). Elite events pass.
5. **Deduplicate** against posted_events (last 500)
6. **Generate 4 candidates** via Gemini 2.5 Flash, ranked by copy score
7. **Safety check** — regex gate (40+ patterns), then LLM ("mocks suffering?")
8. **Virality evaluator** — Sonnet scores 5 dimensions, rewrites on fail. Rewrite must pass safety AND score higher than original on heuristic. Otherwise draft dies.
9. **Streak tracking** — if a city broke a daily record, update `record_streaks`. If 3+ consecutive days, emit a streak signal as a bonus draft.
10. **Simultaneous detection** — if 5+ cities broke records today, emit ONE summary signal
11. **Per-cycle cap** — max 3 drafts, keep top by signal score, reject the rest
12. **Same-city-same-day dedup** — highest signal score wins per `(city, YYYY-MM-DD)`. A stronger signal that arrives later supersedes a still-pending weaker draft; a weaker one is dropped. If a tweet for that `(city, date)` is already posted, the new one is skipped.
13. **City cooldown (3 days)** — after we post about a city, drafts for that city are skipped for 3 days unless the signal is *elite* (all-time record, anomaly ≥18°C, record streak) OR the copy itself is exceptional (`candidate_score.total ≥ 95`). Scoped to Open-Meteo extreme-temperature signals; fires/disasters/CO2/etc. bypass.
14. **Assign approval policy** (armed_auto / suggested_auto / manual_only)
15. **Save drafts** to Gist with full metadata

## Data Flow: Auto-Approval (hourly)

Every hour, `python -m src.main auto_publish_due`:
1. Scan for drafts with elapsed `auto_approve_at`
2. Verify `armed_auto` mode — block if policy not armed
3. **Re-run safety pipeline** (double-gate)
4. Post to X (Tweepy) + cross-post to Bluesky
5. On rate-limit (429): keep draft pending for retry

## Data Flow: Manual Posting
Dashboard → approve → workflow_dispatch with DRAFT_ID → Actions posts via Tweepy → marked "posted" → Bluesky cross-post.

## Data Flow: Leaderboard
Daily at 12:00 UTC, `python -m src.main both`:
1. Fetch temps for 257 cities
2. Compute anomalies vs climatological normals
3. Rank top 10 by anomaly
4. Generate Hot 10 tweet

---

## Schedule

| UTC   | Cron             | Mode              | What runs                                  |
|-------|------------------|-------------------|--------------------------------------------|
| :30   | `30 * * * *`     | auto_publish_due  | Hourly auto-approval queue                 |
| 00:00 | `0 0 * * *`      | alerts            | All sources                                |
| 04:00 | `0 4 * * *`      | alerts            | All sources                                |
| 08:00 | `0 8 * * *`      | alerts            | All sources                                |
| 12:00 | `0 12 * * *`     | both              | Leaderboard + all sources                  |
| 16:00 | `0 16 * * *`     | alerts            | All sources                                |
| 20:00 | `0 20 * * *`     | alerts            | All sources                                |

Source-specific gates: sea ice (Mondays), drought (Fridays), ENSO (1st of month), CO2 milestones (max 1/day), CO2 weekly (Sundays).

---

## Editorial System

### Signal Scoring (`src/editorial/scoring.py`)

Signal types and thresholds:
- **synthesis_fire_drought_heat** — threshold 82 (compound story, elite by design)
- **country_record** (archive peak across all sampled cities in a country) — 82 (elite)
- **all_time_record** — 80 (elite by default)
- **simultaneous_records** — 78
- **marine_heatwave** (global-mean SST streak ≥5 days above archive) — 78
- **monthly_record** — 76
- **anomaly** — 76
- **record_streak** — 74 (fires at 3+ days)
- **fire_footprint** — 72 (named US fire complex crossing acreage tier; manual_only)
- **ice_mass_record** (GRACE-FO monthly loss record / cumulative milestone) — varies, elite-tier
- **record** (calendar-date) — 72
- **record_low** — 72
- **fire** — 64 (NASA FIRMS point detections)
- **co2_milestone** — 58 (capped at 12 tweets/year via `co2_annual_count`)
- **severe_weather** — 58
- **global_disaster** — 62
- **sea_ice_record** — 60
- **drought** — 62
- **enso** — 56
- **extreme_wave** — 62
- **storm_surge** — 60
- **river_flood** — 62
- **hot10** — 56

### Copy Ranking (`candidates.py`)
Gemini produces 4 candidates. Each scored on clarity/context/voice/punch. Best selected.

### Virality Evaluator (`evaluator.py`) — Claude Sonnet 4.6
5 dimensions: awe, concrete comparison, social currency, scroll-stopping opener, show-not-tell.
Passes if 7+ on 4 of 5. Fails → rewrite provided. Rewrite must pass safety AND beat original heuristic score. If no viable rewrite → draft dies.

### Approval Policies (`approval.py`)
- **armed_auto** — Auto-posts after timed delay (Hot 10, CO2 milestones)
- **suggested_auto** — Dashboard suggests auto, requires human (records, ice, ENSO)
- **manual_only** — Human required (fires, fire footprints, severe weather, disasters, storm surge, floods, drought)

### Cross-source synthesis

A meta-detection layer fires a single high-confidence tweet when three
independent signals converge on the same US state within 14 days:
exceptional (D4) drought from USDM, a qualifying wildfire from NASA
FIRMS, and a qualifying heat record from Open-Meteo. The first rule is
`fire_drought_heat`; additional rules (marine heatwave × coastal heat
dome; hurricane × storm surge × river flood) plug into the same
scaffolding.

Synthesis tweets use `suggested_auto` approval with a 120-minute review
window because compound claims are factually more brittle. The
synthesis layer never replaces the per-source tweets — it adds a
compound story on top.

---

## Voice Rules (current)

**Prompt orientation:** astounding data + clean presentation. NOT "cynical weatherman" (killed in session). NOT "personified heat character" (rejected after Karl the Fog research). The bot reports, doesn't narrate.

**Hard bans (safety pipeline):**
- Emojis, hashtags, exclamation marks
- Press-release openers (NWS, NOAA, GDACS, etc. at start of tweet)
- Weather-service boilerplate (HURRICANE-FORCE, catastrophic, life-threatening, EXTREME force, dangerous conditions)
- Tell-don't-show meta-commentary (THIS IS SERIOUS, this is rare, pay attention, you should be worried)
- Label:value format (Severity: Severe, Alert level: Red)
- Tier explainers (the highest alert tier)
- Month repetition (same month twice in adjacent sentences)
- Truncated temperatures (bugs like "1F forecast")
- Bureaucratic suffixes (-26, -2026 in storm names)

**Positive principles (from evaluator + virality research):**
- First 5-7 words must surprise or pattern-break
- Historical-human anchors beat physical metaphors ("last time Buenos Aires was this hot, the Great Depression hadn't started")
- Leave gaps for the reader to complete
- Specific numbers beat round numbers
- One idea per tweet

**Framing honesty (key rule from session):**
- Archive goes back ~30 years, not "all time"
- All-time record tweets must say "hottest in 30 years of archive data" or "hottest since 1995" — NEVER "hottest ever"

**Temperature formatting (added 2026-05-08, PR #46):**
- Bundles now carry both Celsius (`*_c`) and integer-rounded Fahrenheit (`*_f`).
- `current_facts.audience_unit` field tells the writer:
  - `"fahrenheit_first"` for US locations — write `28°F (-2.2°C)`, F primary, C in parens.
  - `"celsius_first"` for everywhere else — write `-15°C` primary; F is optional.
- Writer prompt forbids ad-hoc conversions mid-tweet — must use the bundle's pre-rounded values (otherwise fact-checker rejects rounding mismatches).

---

## Safety Pipeline (40+ regex + LLM)

**Layer 1 — Regex (deterministic):** 40+ patterns covering all the bans above, plus length check (280 chars), month-repetition structural check, and truncated-temperature check.

**Layer 2 — LLM (Gemini Flash):**
Asks: "Does this tweet mock human suffering, trivialize death, or cross from dark humor into cruelty?" Fails logged; tweet passes on LLM unavailability (regex already caught the mechanical stuff).

**Fallback chain:** Gemini generation (4 candidates) → 3 retries on safety rejection → template-based fallback → None (skip event).

**Double-gate on auto-publish:** Safety pipeline runs at generation time AND again before every auto-post.

---

## State Management

Single JSON file in GitHub Gist, read/written via GitHub API each run.

```json
{
  "last_hot10":           { "date": "...", "cities": [...] },
  "streaks":              { "Miami": { "consecutive_days": 14, "last_seen": "..." } },
  "posted_events":        [ "record_PHX_20260407", ... ],
  "daily_tweet_count":    { "2026-04-18": 3 },
  "co2_annual_count":     { "2026": 2 },
  "drafts":               [ ... draft records with score, candidates, approval_policy, review_context ... ],
  "run_history":          [ { "id": "...", "mode": "alerts", "sources": [...], "source_runs": [...] } ],
  "errors":               [ ... ],
  "data_source_failures": { "ghcn": 0, "firms": 0, ... },
  "memory": {
    "ongoing_events":         [ ... ],
    "used_era_anchors":       [ ... ],
    "used_peer_comparisons":  [ ... ],
    "used_framings":          [ ... ],
    "shipped_tweet_texts":    [ ... ]
  },
  "suppressions": [
    {
      "id":          "supp_2026-05-08T01:32:09.290851Z_a1b2c3d4",
      "ts":          "2026-05-08T01:32:09.290851Z",
      "run_id":      "run_alerts_20260508T013240Z",
      "source":      "alerts",
      "stage":       "score_gate" | "writer" | "fact_check" | "pipeline_error",
      "event_id":    "monthly_low_USC00468191_05_2026-05-04",
      "category":    "monthly_record",
      "score_total": 80,
      "threshold":   76,
      "reasons":     [ "Frost in May is not unusual here;: UNVERIFIABLE: ..." ],
      "summary":     "Sissonville, West Virginia"
    }
  ],
  "city_all_time_max": { "Phoenix": {"temp_c": 48.2, "year": 2018} },
  "city_all_time_min": { ... },
  "city_monthly_max":  { "Phoenix": { "4": {"temp_c": 44.0, "year": 2024} } },
  "city_monthly_min":  { ... },
  "record_streaks":    { "Phoenix": { "days": 11, "start_date": "...", "last_date": "...", "peak_temp_c": 45.0 } },
  "ocean_sst_streak":  { ... },
  "ice_mass_max_loss": { ... },
  "fire_complex_tiers": { ... },
  "synthesis_components": { ... },
  "synthesis_cooldown":   { ... }
}
```

**Caps:** 500 event IDs, 200 drafts (pruned oldest non-pending), 50 errors, 200 suppression records, 10 tweets/day, 3 drafts/cycle.

### Suppression stage discriminator

- **`score_gate`** — editorial scoring failed (`score.total < score.threshold`). Captured only when the gap is within `SUPPRESSION_NEAR_MISS_GAP` (default 15) so the ledger doesn't flood with obvious noise.
- **`writer`** — Sonnet 4.6 returned `tweet=null` with a `kill_reason` (e.g. "no historical_context available; nothing else earned extraordinary").
- **`fact_check`** — Gemini fact-checker found one or more UNVERIFIABLE / BUNDLE_FACT mismatches.
- **`pipeline_error`** — exception caught by `generate_draft`'s try/except. Today's saga had this fire repeatedly with `ReadTimeout` (root: Gemini ms-vs-s timeout bug, fixed in #43).

---

## Dashboard

Next.js 15 + React 19 on Vercel. Auth-protected. Dark terminal aesthetic.

Sections:
- **Drafts to Review** — pending tweets with approve/edit/delete, editorial scores, approval policy, review context
- **Generate Drafts** — trigger alerts, leaderboard, or both via workflow_dispatch
- **Compose Tweet** — manual composition with Gemini generation
- **Stats, Hot 10, Streaks, Recent Runs, Recent Errors**

API routes: bulk_reject_below (for threshold cleanups), approve, reject, edit, auto_approve, select_candidate.

**URL:** https://dashboard-andrew-puschels-projects.vercel.app

---

## Dependencies

```
tweepy>=4.14,<5       # X API posting
atproto>=0.0.61       # Bluesky cross-posting
google-genai>=1.0     # Gemini 2.5 Flash (generation + safety LLM)
anthropic>=0.42       # Claude Sonnet 4.6 (virality evaluator)
requests>=2.31        # HTTP for data sources
pytest>=8.0
pytest-mock>=3.12
responses>=0.25
```

---

## Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET` | X API |
| `GEMINI_API_KEY` | Google AI Studio API key for Gemini |
| `GEMINI_MODEL` | (Optional) Model ID for the candidate generator. Default `gemini-flash-latest` — the alias Google rolls to whatever the current best Flash is (currently `gemini-3-flash-preview`, $0.30/$2.50 per MTok). Override with `gemini-3-pro-preview`, a pinned snapshot like `gemini-3-flash-preview`, or fallback `gemini-2.5-flash` without redeploying. |
| `GEMINI_SAFETY_MODEL` | (Optional) Separate model ID for the LLM safety layer. Defaults to whatever `GEMINI_MODEL` is. |
| `EVALUATOR_ENABLED` | (Optional) Set to `false` to skip the Sonnet 4.6 virality-evaluator pass and save ~$25-45/mo. Defaults to `true`. Drafts then flow Gemini → safety → ranking → dashboard with no second-pass rewrites or kills. |
| `ANTHROPIC_API_KEY` | Claude Sonnet 4.6 evaluator |
| `GIST_ID` | State storage (`06c02c97ffc0d11458687f1ed998d9e5`) |
| `GH_GIST_TOKEN` | PAT with `gist` scope for state writes |
| `NASA_FIRMS_API_KEY` | NASA fire satellite detection |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | Bluesky cross-post |
| `EARTHDATA_TOKEN` | NASA Earthdata Login bearer token, used by the GRACE-FO ice-mass lane. Generate at https://urs.earthdata.nasa.gov/ (profile → "Generate Token"). Optional: if unset the ice_mass lane short-circuits to skipped and the rest of the pipeline runs normally. |

### Fire footprint source (no secret required)

- **Source:** NIFC WFIGS (Wildland Fire Interagency Geospatial Services) — `services3.arcgis.com/T4QMspbfLg3qTGWY/.../WFIGS_Incident_Locations_Current`
- **Auth:** None (public ArcGIS FeatureServer).
- **Coverage:** US only.
- **Rationale for NIFC over GWIS:** GWIS (EU Joint Research Centre) was the original target — it provides global coverage — but as of 2026-04-20 GWIS publishes only WMS map layers, no JSON/GeoJSON API. Pivoted to NIFC per the plan's explicit fallback. Revisit GWIS if they publish a JSON endpoint.
- **Fallback if NIFC degrades:** no secondary source implemented; the orchestrator catches fetch failures and logs them without blocking other sources.

---

## Known Issues & Growth Levers

### Issues (current — 2026-05-08)

**Open from Codex review (medium / low — see `docs/codex-review-findings-2026-05-08.md`):**
1. **Suppression `stage` not surfaced in dashboard UI** (medium / certain). Schema is wired, API returns it, but `dashboard/app/page.js::SuppressedView` groups by `source` only and the card copy still says "editorial gate kills" (no longer accurate — stage covers writer / fact_check / pipeline_error / score_gate). Render `stage` as primary pill + add stage filter.
2. **`observation_kind` says "overnight low" / "afternoon high"** but TMIN/TMAX are 24-hour extrema, not timestamped. A cold front past sunrise can set the daily min; a warm overnight event can set the max. Acceptable imprecision today; worth `daily_minimum` / `24h_low` framing if hourly data ever lands.
3. **GHCN observed records still labeled `forecast_*_c`** in the bundle's headline_metric (medium / likely). Same event dataclasses serve both Open-Meteo forecasts AND GHCN observed station readings — but the metric label says "forecast." Should split into `observed_*_c` for GHCN, keep `forecast_*_c` for Open-Meteo.
4. **`loads_model_json` trailing-comma fallback isn't string-aware** (low / edge). A payload like `{"tweet":"a,}","kill_reason":null,}` silently becomes `{"tweet": "a}"}`. Replace the regex with a string-aware character walker.
5. **Station normalization mangles `JFK INTL AP`** → `Jfk` via `text.title()`. Cosmetic; the live station inventory has acronym-style names.

**Open from earlier:**
6. **Sequential API calls** — 613 cities checked sequentially on the Open-Meteo path (Hot 10). Alert cycle ~30 min worst-case.
7. **Dashboard auto-deploy not firing** — Vercel GitHub integration appears inactive; deploys go through manual `vercel --prod` from `dashboard/`. Worth investigating.
8. **Stray worktree artifact** — `theheat/theheat/` duplicate subdir from a Conductor worktree; untracked, safe to `rm -rf` when convenient. Causes `ImportPathMismatchError` on repo-root pytest.
9. **13 cities missing elevations** — bulk fetch on 2026-04-24 hit Open-Meteo elevation API rate limit on the last batch. Easy retry.

### Resolved 2026-05-08 (just for the record — DO NOT reopen these)

- ✅ **Drafts not flowing** — root cause was `HttpOptions(timeout=90)` meaning 90ms not 90s in google-genai (#43).
- ✅ **Pipeline kills invisible** — suppression ledger surfaces every kill stage (#38, #39, #42).
- ✅ **Dashboard merge erasing Python state** — preserved via `{...base, ...next}` spread (#47).
- ✅ **Sonnet emitting `\`\`\`json` fences and "Let me think..." preambles** — `_extract_json_payload` handles both (#40, #41).
- ✅ **Date in `raw_signal_dump` choking `json.dumps`** — `json_default` ISO-coerces (#39).
- ✅ **`_METADATA_JSON_KEYS` dropping `memory` + `data_source_failures`** — added (#47).
- ✅ **Claim extractor unbounded Gemini timeout** — `HttpOptions(timeout=90000)` (#47).
- ✅ **Station-name suffixes like "1SW" rejected by fact-check** — `normalize_station_name` strips them (#44).
- ✅ **Fact-check rejecting "West Virginia" / "night"** — bundle now carries `state` + `observation_kind` (#45).
- ✅ **All-Celsius drafts unfriendly to US readers** — `audience_unit=fahrenheit_first` for US, F-first formatting (#46).

### Growth levers (deferred by session owner)
1. **Visual cards** — research says images 28× engagement. User rejected: "not if the facts are lame." Revisit once fact quality is proven.
2. **Voice engine upgrade** — see `docs/IDEAS.md`. Data-ticker tweets are "ok, not breakout-viral." Generator prompt, evaluator calibration, or a dedicated lead-with-the-stake rewrite pass are the three candidate interventions.
3. **Fire geocoder regional precision** — `firms.py::reverse_geocode_simple` returns continent-only labels ("somewhere in Asia"), which produces weak fire drafts. Candidates: bounding boxes per country/region, or a bundled country polygon dataset.
4. **RSS enrichment** — Carbon Brief, Climate Central feeds.
5. **GWIS global fire footprint** — currently NIFC (US only). Revisit GWIS if they publish a JSON/GeoJSON API.
6. **Additional synthesis rules** — marine heatwave × coastal heat dome (blocked until OISST has fired enough); hurricane × surge × flood (waits for hurricane season so the rule can be observed firing before we trust it).

---

## Repo

- **GitHub:** `github.com/andrewzp/theheat`
- **Branch:** `main` (latest: `d9c84ff` — PR #47 codex high-severity batch)
- **Gist ID:** `06c02c97ffc0d11458687f1ed998d9e5`
- **Dashboard:** https://dashboard-andrew-puschels-projects.vercel.app
- **X:** @theheat (Premium tier — 4x/2x algo boost already active)
- **CHANGELOG:** through 0.3.10.0 (2026-05-08); ten releases shipped on 2026-05-08 alone (#38 through #47).
