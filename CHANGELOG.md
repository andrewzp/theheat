# Changelog

All notable changes to this project will be documented in this file.

## [0.7.2.0] - 2026-05-17

The post-hardening release. Four PRs landed in one session: a 7-theme
post-wave hardening patchset that had been sitting uncommitted on main,
plus two new bugfixes surfaced by a 2026-05-15 → 2026-05-17 Anthropic
credit-exhaustion outage that revealed two missing diagnostic surfaces
(billing failures looked identical to model bugs; GPM-IMERG per-city
failures returned an opaque "638 failed" count). Plus a fully-reviewed
architecture spec for deterministic pre-writer triage — the next
session's implementation work.

Production verdict at session close: pipeline healthy, fresh Costa Rica
coral_bleaching draft created at 01:30 UTC, suppression mix back to
normal (critic 22 / writer 4 / fact_check 3 / pipeline_error 1).

### Added — post-wave hardening (#126)

Six orthogonal fixes that closed gaps the 0.7.0.0 + 0.7.1.0 waves
opened. The patchset was in the working tree from a prior session and
had never been branched. All themes have tests.

- **State schema completeness** (`src/storage/sqlite_store.py` +
  `dashboard/lib/state-store.js`) — register Plan E (precip, snow,
  flood) and Plan F (cyclone, NAO/AO/PDO, ozone) state keys in BOTH
  the alt-SQLite metadata-JSON-keys tuple AND the dashboard JS
  allow-list. Without this, those state shapes would silently
  round-trip-lose on every dashboard write.
- **GPM-IMERG city cap** (`src/data/gpm_imerg.py` +
  `src/orchestrator/sources/gpm_imerg.py` + `.github/workflows/bot.yml`)
  — default 638-city scan overwhelms per-cycle runtime. Cap to 75 with
  `GPM_IMERG_MAX_CITIES` env override (>= 1 required).
- **Prune mapping covers new draft types**
  (`src/orchestrator/finalize.py`) — `_PRUNE_SOURCE_KEY_BY_TYPE` was
  missing `precipitation_extreme`, `snow_extreme`,
  `seasonal_snow_record`, `oscillation_alignment`, `ozone_hole_peak`.
  Pruned drafts couldn't get attributed back to source telemetry.
  Added `review_context.source_key` fallback path.
- **Claim-extractor JSON-parse retry parity**
  (`src/two_bot/claim_extractor.py`) — mirrors the #121 generalization
  (writer / fact_check / critic got retry, claim_extractor was missed).
  Single retry with contract-reminder suffix before raising.
- **Pipeline records claim_extractor failures as
  `kill_stage="claim_extractor"`** (`src/two_bot/pipeline.py`) instead
  of generic `pipeline_error`. New suppression stage row visible in the
  dashboard `Suppressed` tab.
- **Open-Meteo telemetry counter fix**
  (`src/orchestrator/sources/open_meteo.py`) — two missing
  `source_drafted += 1` increments in record_streak and country-
  similarity draft paths.

### Added — BudgetExhaustedError short-circuit + distinct kill_stage (#127)

Production observed 2026-05-15 → 2026-05-17: bot Anthropic key ran
dry; 182 of last 200 suppressions were `pipeline_error` rows with
identical "credit balance is too low" text, each chewing through 3
retries + exponential backoff before bubbling (~5s wasted per draft).
Dashboard surfaced nothing operationally useful — operators had to
read retry stack traces to realize the fix was "top up the key."

- **`src/two_bot/retry.py`** — new `BudgetExhaustedError(RuntimeError)`.
  Substring-match on `"credit balance is too low"` (the Anthropic 400
  pattern). On match, the retry helper short-circuits on attempt 1 and
  raises `BudgetExhaustedError` — no sleeps, no duplicate ledger rows.
  Pattern list intentionally narrow — only patterns observed in prod
  (adding patterns that DO resolve on retry would swallow real
  transients).
- **`src/two_bot/pipeline.py`** — catch `BudgetExhaustedError` before
  generic `Exception` and record `kill_stage="budget_exhausted"`.
- **`src/orchestrator/common.py`** — extend the kill_stage docstring
  with the new `budget_exhausted` stage plus the `claim_extractor`
  stage added in #126.
- **Tests** — `tests/two_bot/test_retry.py` adds 3 cases (short-circuit
  on budget pattern, normal-error pass-through unchanged, pre-classified
  error reraise without wrapping). `tests/two_bot/test_pipeline.py`
  adds 1 case (pipeline records distinct `budget_exhausted` stage).

### Added — GPM-IMERG per-city failure diagnostic logging (#128)

PR #116 shipped GPM-IMERG 2026-05-13. Over the next 4 days the lane
ran 17 cron failures with `success=0`; production
`source_health.last_error` gave only `"(N failed)"` — no HTTP status,
no URL, no exception type. Diagnosing auth-vs-endpoint-vs-outage
required curling NASA by hand.

- **`src/data/gpm_imerg.py`** — captures the first per-city failure
  and threads it into both the strict-mode `SourceFetchError` and a
  one-line stdout log. For `requests.HTTPError`: `"HTTP {status} from
  {url}"`. For everything else: `"{ExceptionType}: {message}"`.
  Production behavior after this lands: a fresh
  `source_health.last_error` reads `"GPM IMERG fetch returned no city
  readings for 2026-05-17 (75 failed); first error: HTTP 401 from
  <opendap-url>"`. 401 → token expired or GES DISC application not
  authorized in Earthdata profile; 403 → token lacks scope; 404 →
  endpoint changed; TimeoutError → NASA outage. The fix does not
  address the underlying auth root cause — that's an operator action
  (rotate token, authorize GES DISC application). What it does is
  convert blind failure into one-line diagnosis the next time this
  happens.
- **Tests** — `tests/test_gpm_imerg.py` adds 2 cases (multi-city 401
  bundle surfaces "HTTP 401" + "GPM_3IMERGDL.07" in error message;
  single-city 404 short-circuit surfaces "HTTP 404").

### Added — Code-first triage spec (#129, doc-only)

[docs/superpowers/specs/2026-05-17-code-first-triage-design.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-05-17-code-first-triage-design.md)
— architecture spec for moving the per-cycle writer-call cap from
post-writer (current `_prune_weakest_cycle_drafts` in `finalize.py`)
to pre-writer (new deterministic triage stage between bundle build and
LLM stages). Target: **source-growth-proof flat-line cost** —
doubling sources should not double credit burn.

Spec walked through `/plan-eng-review` interactively. Six findings
folded in (3 architecture + 3 test gaps): queue persistence bug fixed
with explicit two-guard pattern (pop-on-entry + skip-in-persist);
coalescing rule redefined as same-event-across-sources, not
same-geographic-bucket; partial-migration / queue-cleanup-on-exception
/ telemetry-attribution tests added. Verdict: **ENG CLEARED**, ready
to implement. Three open questions in spec § 12 are knobs for the
implementation plan, not blockers (default cap values, tiebreaker,
kill-switch default).

No code changes in this PR — implementation follows in subsequent PRs
once the next session begins.

### Deferred (still in working tree, not landed)

- **Fact-check disposition reversal** — modification to
  `src/two_bot/prompts/fact_check_prompt.py` + `tests/two_bot/test_prompts.py`
  that walks back the #119 "When in doubt, ACCEPT" disposition toward
  "primary-source confidence required, otherwise UNVERIFIABLE." Held
  for explicit sign-off because it contradicts the
  `TheHeat fact-checker is generous` memory hook the #119 work
  established. The change has merit (post-#119 production data may
  show over-acceptance) but it's a deliberate voice/editorial-policy
  reversal, not a bugfix — Andrew's call. Files remain in the working
  tree on `main` for review.

## [0.7.1.0] - 2026-05-15

The editorial-architecture release. Three PRs landed in one session to lift
the A-rate ceiling that the 0.7.0.0 wave couldn't address from the data
layer. The fact-checker is now generous on the writer's external knowledge
(canonical scales, named geography, IPCC framings); a second-pass critic
(Gemini 2.5 Pro) catches the writer's blind spots, especially template
convergence across same-cron drafts; and both Gemini callers gained
JSON-parse retry parity with the writer so stochastic refusals stop
crashing the pipeline.

Production verdict at session close: the post-architecture cron killed 27
weak/template-convergent drafts in one alerts run (with specific
kill_reasons in the suppression ledger) while letting through the Galapagos
24.5°C-week DHW Alert Level 5 banger as the lead pending draft.

### Changed — fact-check WORLD_KNOWLEDGE widened (#119)

- **`src/two_bot/prompts/fact_check_prompt.py`** — rewrite of the
  WORLD_KNOWLEDGE bucket with concrete allow-list categories:
  - **Canonical published scales:** NOAA Coral Reef Watch DHW alert
    levels (4 / 8 / 12 / 16 / 20 °C-weeks → Bleaching Alert Levels 1–5),
    Saffir-Simpson, Beaufort, Fujita/EF, VEI, Drought Monitor D0–D4,
    GDACS tiers.
  - **Named marine and physical geography:** seas, channels, straits,
    basins, reef systems, archipelagos, currents, plates — atlases are
    settled science; don't require the bundle to spell out every named
    feature.
  - **IPCC AR6-grade climate framings:** Indian Ocean warming faster
    than most tropical basins, Arctic amplification, ENSO mechanics,
    monsoon timing, warm-pool / convergence-zone behavior.
  - **Basic ocean / atmospheric mechanism:** semi-enclosed basin heat
    retention, warm-current poleward transport, rain shadows, cold-air
    drainage.
  Disposition revised in same session: **primary-source confidence is
  required** — clearly established by NOAA / IPCC / NASA / NSIDC / USGS
  / WMO / canonical encyclopedia → ACCEPT; plausible / vibes-based /
  unpredictable-search → UNVERIFIABLE. The automated gate owns accuracy;
  no "let the human catch shaky claims" escape clause.
- **`src/two_bot/prompts/writer_prompt.py`** — NO FABRICATED CONTEXT
  bullet aligned to the new fact-check framing (drops "95%+ verifiable"
  language; names NOAA / IPCC / NASA / NSIDC / USGS / WMO as the
  authoritative sources; calls out canonical scales as fair game; frames
  external knowledge as the editorial product).
- **`src/two_bot/prompts/writer_prompt.py`** — two narrow new bullets:
  - **NO SNAPSHOT-TREND CLAIMS** — trend language ("still climbing,"
    "approaching," "closing on") requires a bundle trend / streak /
    rate-of-change field; a single DHW value, single °C reading, or
    single SST anomaly is a snapshot, not a direction.
  - **NO RELATIVE-POSITION CLAIMS THAT DON'T COMPUTE** — "halfway,"
    "midway," "closer to A than B" must be arithmetically true given
    the bundle numbers (a DHW of 5.2 between 4 and 8 is 30% above the
    floor, not "halfway").
- **`tests/two_bot/test_prompts.py`** — 36 structural assertions guarding
  the new posture (canonical-scale allow-list survives, the 95%+
  quantitative bar stays dropped, primary-source requirement stays
  required, narrow UNVERIFIABLE guards stay tight, JSON output contract
  unchanged, writer-prompt nudges present).

### Added — F3 second-pass editorial critic (#120)

The deferred lever from the 0.7.0.0 handoff. Runs after fact_check
passes and acts as the final editorial gate before a draft enters the
human-approval queue. PASS/KILL only in v1 — no rewrite loop.

- **`src/two_bot/prompts/critic_prompt.py`** — editorial-bar prompt.
  Two gates (stop-mid-scroll, send-it-to-a-friend). Kill conditions
  split into editorial / template-repetition / voice-craft / scale
  buckets. **Bias toward KILL on borderline** — asymmetric cost: missed
  kill = boring feed erodes signal-to-noise; missed pass = good draft
  will return tomorrow when the event re-fires.
- **`src/two_bot/critic.py`** — Gemini 2.5 Pro call with
  `HttpOptions(timeout=90000)` (90s in MILLISECONDS, regression-guarded).
  `_collect_pending_today` filters drafts by UTC-date prefix and
  excludes the in-flight `event_id` — gives the critic cross-draft
  awareness the writer lacks (writer only sees shipped / 24h-cooldown
  history). Compact `_format_pending_block` / `_format_shipped_block`
  helpers keep prompt tokens bounded (~3K input + 200 output ⇒ ~$0.006
  per call; daily ~$0.30–$0.60).
- **`src/two_bot/types.py`** — `CriticResult` dataclass with
  passed/kill_reason invariants enforced in `__post_init__`.
- **`src/config.py`** — `CRITIC_MODEL = "gemini-2.5-pro"`, env-overridable
  via `THEHEAT_CRITIC_MODEL`. Comment explicitly bans Flash per
  `feedback_theheat_flash_no_taste.md` — never Flash for taste-bearing
  roles.
- **`src/two_bot/pipeline.py`** — critic wired between fact_check pass
  and draft return. `THEHEAT_CRITIC_ENABLED=0` operations kill-switch
  for emergency disable without a deploy. Metadata records critic
  verdict + model name; dashboard can show "critic-approved" badge.
- **`src/orchestrator/common.py`** — `kill_stage` comment updated to
  include `"critic"` alongside writer/safety/fact_check/pipeline_error.

### Added — JSON-parse retry parity for Gemini callers (#121)

Production audit during the #120 verification cron found a Somalia
coral_bleaching pipeline_error with
`ValueError: invalid JSON: Expecting "," delimiter: line 7 column 384`.
Two prior 2026-05-12 errors on Nettles Is, Florida record_low were the
same class. ~1 in 50 drafts hits a stochastic Gemini refusal (empty
body, mid-truncation, prose preamble) that the existing
`call_with_retries` layer doesn't catch — JSON parse runs AFTER the API
call returns. The writer already had the right pattern; the two
Gemini-side callers didn't.

- **`src/two_bot/fact_check.py`** — added `JSON_PARSE_RETRY_BUDGET = 1`
  (matching writer). `_call_gemini` gains optional `retry_suffix: str = ""`
  kwarg, appended to the user prompt before sending. `fact_check()` wraps
  `_call_gemini` + `_parse_fact_check_json` in a retry loop. On
  exhaustion: `FactCheckResult(passed=False, failures=["fact-checker
  returned invalid JSON across 2 attempts: ..."])`. Fail-closed — the
  gate blocks the draft when it can't read the verdict.
- **`src/two_bot/critic.py`** — identical shape. On exhaustion:
  `CriticResult(passed=False, kill_reason="critic returned invalid JSON
  across 2 attempts: ...")`. Fail-closed.

### Production observed at session close

- **27 critic kills** in the first post-deploy alerts run (last 50
  suppressions). Kill reasons: `template_convergence: one of nine
  similar coral drafts today, but its 4.9°C-week signal is much weaker
  than others (e.g., Galapagos at 24.5)`; `recycled_phrasing: system
  clause explaining the 4/8°C-week thresholds echoes shipped East
  Java/Bali tweet`; `interesting_but_not_memorable: 4.1°C-weeks is the
  entry threshold for bleaching, not an extraordinary signal that
  passes the 'Wait, what?' test`; `underwhelming_scale: 4.3°C-weeks is
  a low-impact signal`.
- **Fact-check kills dropped 22 → 13** in the last 50 (~40% reduction).
- **Pending coral_bleaching: 6 → 8.** Lead draft is Galapagos at
  24.5°C-weeks (DHW Alert Level 5, score 88) — *"double the 12°C-week
  tier where coral mortality is expected. The Galapagos sits where cold
  upwelling normally buffers heat; when that buffer..."*
- **Voice-regression green** against the new prompts (no fixture
  changes needed; replay path doesn't go through the critic).

### Tests

1235 passing (was 1151 at 0.7.0.0 close; +84 across this release):
- `tests/two_bot/test_prompts.py` — 36 structural assertions
  guarding both the loosened-WORLD_KNOWLEDGE bar and the critic-prompt
  shape (kill conditions, output contract, user-prompt template keys).
- `tests/two_bot/test_critic.py` — 38 tests covering JSON parse,
  CriticResult invariants, pending-today filtering, prompt-block
  formatting, mocked-Gemini PASS/KILL paths, JSON-parse retry, timeout
  regression guard.
- `tests/two_bot/test_fact_check.py` — 12 new tests for the JSON-parse
  retry shape (mirrors writer's `TestJsonParseRetry`).
- `tests/two_bot/test_pipeline.py` — +4 critic-integration tests +1
  module-scoped autouse fixture so pre-existing pipeline tests stay
  green without per-test edits.

### Architecture

```
writer (Sonnet 4.6) → safety → claim_extractor (Gemini Flash) → fact_check (Gemini Flash) → critic (Gemini 2.5 Pro) → pending
```

The critic adds two structural lifts the writer can't self-deliver:
**different model family** (Gemini 2.5 Pro vs Sonnet writer = different
blind spots) and **cross-draft awareness** (the writer can't see its
siblings produced in the same cron run; the critic can).

### Cost

- Critic: ~$0.30–$0.60/day at current volume (Gemini 2.5 Pro: $1.25/M
  input, $10/M output; no free tier for 2.5 Pro).
- Fact-check: unchanged (Gemini 2.5 Flash, existing paid Gemini key).
- Writer: unchanged (Sonnet 4.6, existing Anthropic key, ~$22/month).

## [0.7.0.0] - 2026-05-15

The largest single landing in @theheat's history. 23 PRs merged in ~6 hours
overnight via parallel Conductor + Claude Code workspaces. Plan A through
Plan F shipped end-to-end. F2 bundle enrichment live. Threshold registry
centralized. main.py decomposed from 3,070 lines to 96. Median Conductor
lane time: ~23 min from prompt-paste to PR merge.

This release is **infrastructure + coverage + architecture** all at once.
Editorial-quality verification is now the only remaining blocker on the
posting flip.

### Added — new sources (+9, total 14 → 23)

- **`src/data/coral_dhw.py`** (#109) — NOAA Coral Reef Watch Degree Heating
  Weeks per region. Bleaching levels: warning (DHW ≥ 4), alert (≥ 8),
  critical (≥ 12). Tier-dedup pattern. Live smoke at merge: 137 active
  stress stations, 42 tier crossings ready to fire.
- **`src/data/methane.py`** (#109) — NOAA GML CH4 monthly mean milestones.
  Mirrors `co2.py` shape. Annual cap 12/year. Live at merge: CH4 had just
  crossed 1940 ppb (1940.43 actual).
- **`src/data/cyclones.py`, `nhc.py`, `jtwc.py`** (#108) — Tropical cyclone
  coverage. NHC (Atlantic + East Pacific) and JTWC (West Pacific, Indian
  Ocean, Southern Hemisphere). Detection: rapid intensification (≥30 kt
  in 24h), Saffir-Simpson tier crossings, major hurricane landfalls (Cat
  3+), basin records. Ready for June 1 Atlantic season opener.
- **`src/data/copernicus_ems.py`** (#112) — Copernicus Emergency Management
  Service global flood activations. Severity tiers + population-impact
  threshold. Non-US coverage that closes the Pakistan/Sudan/BC gap.
- **`src/data/gpm_imerg.py`** (#116) — NASA GPM-IMERG daily precipitation
  extremes. Per-city daily total records, multi-day rolling accumulations,
  country-wide simultaneous events. Requires existing `EARTHDATA_TOKEN`
  env var (same as GRACE-FO ice mass).
- **`src/data/nsidc_snow.py`** (#116) — NSIDC Snow Today single-event snow
  extremes + multi-day blizzards + seasonal snowfall records. Annual cap
  8/year via the sea-ice pattern.
- **`src/data/climate_indices.py`** (#115) — NAO + AO + PDO monthly
  oscillation indices. Detection: phase transitions, 2-sigma extreme
  excursions, multi-index winter-blocking alignment. Mirrors ENSO pattern.
- **`src/data/ozone_hole.py`** (#115) — NASA Ozone Watch Antarctic ozone
  hole. Seasonal peak detection (Aug-Nov). Annual cap 2/year.

### Added — bundle enrichment (F2)

- **`src/data/_climate_context.py`** (#107) — 38 curated climate regions
  with bounding boxes + climate-system phrase + topography note +
  Wikipedia source URL per entry. Writer-produced system clauses ("the
  western Pacific warm pool", "the Androscoggin Valley funnels cold air")
  now pass fact-check because the bundle carries the verifiable phrase.
  Wired into `build_fire_bundle`, `build_record_bundle`, `build_monthly_*`,
  `build_anomaly_bundle`, `build_all_time_record_bundle`,
  `build_coral_bleaching_bundle`, `build_cyclone_*`,
  `build_global_flood_bundle`, and Plan E/F bundle builders.

### Added — observability platform (Plan A Phase 1)

- **`src/data/source_status.py`** extended (#99) with `assert_response_schema`
  helper — top-of-fetch shape check that raises `SourceFetchError` on
  upstream schema drift. Catches the ocean_sst silent-death class of bugs
  on day one.
- **`src/data/_freshness.py`** (#99) — `assert_freshness(data_date, source,
  max_age_days)` for cadence-gated sources. Stale data fails loud.
- **`state.source_health`** (#99) — rolling 7-day per-source record:
  success/degraded/failed/skipped counts + `last_success_ts`, `last_error`,
  `last_error_ts`. Persists across the 20-entry run_history buffer.
- **`dashboard/app/api/source-health/route.js`** (#101) — aggregates
  run_history into per-source health classifier (healthy / degraded /
  unhealthy / idle). Sorted worst-first.
- **`dashboard/app/health/`** (#101) — `/health` route with stats card +
  per-source grid. Andrew sees source health at a glance, no jq required.

### Added — threshold registry

- **`src/editorial/thresholds.py`** (#114, #117) — Centralized
  `THRESHOLDS: dict[str, ThresholdEntry]` with 32 entries covering every
  `score_*` function. Each entry has category + threshold + rationale
  string. Calibration is now a one-config-table edit instead of a
  grep-and-patch.
- **`tests/test_thresholds.py`** — registry coverage assertions: every
  public score function is in the registry, no inline threshold literals
  remain, every entry has a non-empty rationale.

### Added — shared helpers

- **`src/data/_http.py`** (#102) — `fetch_with_retry` helper. Exponential
  backoff (1s, 2s, 4s) on `ConnectionError` / `Timeout` / 5xx. Does NOT
  retry on 4xx or schema-drift errors. Wired into FIRMS, ocean_sst, and
  available to all sources.

### Changed — restored broken sources

- **`src/data/ocean_sst.py`** (#102) — Switched from dead
  `oisst2.1_world_sst_day.json` endpoint to ClimateReanalyzer's
  `json_2clim/world2` payload. Schema-drift + freshness assertions added.
  Marine heatwave streak detection back online (was 0/8 success for weeks).
- **`src/data/river_gauges.py`** (#102) — USGS WaterWatch flood-stage
  parsing replaced with NOAA NWPS gauge metadata. Flood-stage flag back
  online.
- **`src/data/firms.py`** (#102) — Wrapped in `fetch_with_retry`. Closes
  the ~12%-per-cron HTTPSConnectionPool transient failure class.

### Changed — open_meteo "degraded" calibration

- **`src/main.py` → now `src/orchestrator/run_alerts.py`** (#105) — GHCN
  `diff_dates_missing == 1` (newest expected date lagging upstream) now
  classifies as `success` instead of `degraded`. Investigation note at
  `docs/conductor-lanes/05-phase3-open-meteo-investigation.md` shows
  every degraded row had identical `diff_dates_missing=[2026-05-13]`
  pattern; NCEI was just publishing yesterday's diff late.

### Changed — anomaly score threshold

- **`src/editorial/scoring/temperature.py`** (#96) — `score_anomaly`
  threshold lowered 76 → 74. Florida -11.1°C cold anomaly was firing every
  cron and dying at the gate. -11.1°C below normal in May Florida is real
  news. Formula self-protects at smaller anomalies (8°C scores 70).

### Refactored — monolith decomposition

- **`src/main.py`** (#113) — 3,070 lines → 96-line entrypoint facade.
- **`src/orchestrator/`** (NEW package, #113) — `run_alerts.py`,
  `common.py`, `finalize.py`, `pipeline_routing.py`, `hot10.py`,
  `posting.py`, plus `sources/<source>.py` per-source runner files
  (22 files at landing).
- **`src/editorial/scoring/`** (NEW package, #113) — per-category files:
  `atmospheric.py`, `disasters.py`, `drought.py`, `fire.py`, `hot10.py`,
  `marine.py`, `precipitation.py`, `synthesis.py`, `temperature.py`, plus
  `_shared.py` (EditorialScore dataclass + `_build_score` + `_clamp`).
- **`src/two_bot/intern/`** (NEW package, #113) — per-category files
  mirroring the scoring split. `__init__.py` re-exports preserve all
  existing imports.
- Why this matters: every future source-add lane touches a NEW file in
  each package. Two concurrent lanes never edit the same file. Parallel
  source-adds are now structurally safe.

### Changed — state hygiene

- **`src/state.py`** (#98) — `trim_drafts` extended with time-based trim
  of rejected drafts older than 30 days. Pending and posted kept
  indefinitely. 200-cap backstop preserved. Recovered ~400 KB of
  state.json size; future writes self-prune.

### Documentation

- **`docs/PLAN_A.md`** — full 5-phase plan-of-record for the wave (added
  in #97, kept in repo for handoff continuity)
- **`docs/conductor-lanes/`** — 12 lane briefs authored (05-16) covering
  the full wave. README updated with queue order + parallelism map.
- **`docs/handoffs/`** — 6 prior NEXT_SESSION_PROMPT files consolidated
  here in #106 via `git mv` (history preserved). New handoff at
  `2026-05-15.md` captures this release.
- **`docs/cyclone-feed-investigation.md`**, **`copernicus-ems-flood-investigation.md`**,
  **`main-py-refactor-map.md`** — Conductor workspaces committed
  investigation artifacts as the first commit of their respective lanes.
  Reference for future source-add work.

### Tests

- **1151 passing** (was 909). +242 tests across all the new lanes.
- mypy clean across 88 source files.
- Voice-regression green; cyclone scenarios added.

### Production state at release

- **`state.json`:** 906 KB (down from 958 peak, will continue trimming as
  rejected drafts age past 30 days).
- **Pending drafts:** 12 (up from 6 — new sources firing).
- **`source_health` tracked:** 24 sources/runners with rolling per-source
  health.
- **Suppression mix (24h):** writer 23, fact_check 22, cycle_cap 4, safety
  1. **Zero score_gate kills** — anomaly threshold tuning + new sources
  flowing cleanly through the gate.

### What's still NOT done (queued)

- F3 second-pass editorial agent (deferred: "Flash has no taste, no new
  models tonight")
- theheat.ai landing page (domain bought, parked)
- Posting mode flip from `manual_only` to `armed_auto` / `suggested_auto`
- X profile Location field (recommend `Earth`) + Website field (set after
  landing page deploys)

## [0.6.0.1] - 2026-05-14

Anomaly score_gate calibration. 24h of post-v3 alerts crons showed the same
Florida -11.1°C cold anomaly firing every cycle, scoring 74, dying at the
score_gate's 76-threshold every time. -11.1°C below normal in May Florida is
genuinely extraordinary by Wait,what? standards. The scoring formula's 15°C
"baseline elite" anchor was too high — 11–14°C anomalies are real news.

### Fixed

- **`src/editorial/scoring.py`** — `score_anomaly` threshold lowered 76→74.
  Opens the 11–14°C anomaly band that was being rejected. The formula's own
  downside penalty keeps 8°C and below self-filtering — no widening to noise.
- **`tests/test_editorial_scoring.py`** — added two cases. The Florida -11.1°C
  event now passes (`test_anomaly_11c_florida_cold_passes`); -8°C still does
  not (`test_anomaly_8c_remains_below_bar`). 912 tests pass; mypy clean.

### Verification

Empirical: next alerts cron after merge should promote the still-pending
-11.1°C anomaly from `score_gate` suppression to `pending` draft.

## [0.6.0.0] - 2026-05-14

Brand-kit correction session. The brand book and asset kit had been built
around an invented "climate data wire / logbook of a planet running a fever"
tagline that didn't match canonical messaging architecture. This release
corrects the kit end-to-end while preserving the visual system (wordmark,
mark, lockup geometry, palette, typography all unchanged). No code changes.

**Tagline locked:** *Diary of a warming planet.*

### Brand

- **`brand/MESSAGING_ARCHITECTURE.md` updated** (#94). Tagline line corrected
  to *"Diary of a warming planet."* (was *"The planet's scorecard."*).
  Personality opener rewritten — *"The Heat is a diary of a warming planet —
  the planet keeps its own record; we transcribe the entries with calm
  authority and one sentence on the system behind each number."* — replacing
  the "climate data wire service that developed a personality" framing.
  Voice references updated to Attenborough + The Economist + Reuters/AP wire
  (replacing older @spectatorindex / @unusual_whales / @darth which predated
  the May voice work). Voice section updated to lead with "system clause
  second — name the mechanism, consequence, or rate behind the data when one
  exists" instead of "Dry observation third, only when earned."

- **NEW `FUTURE DIRECTION` section** in MA (#94) captures three v2 brand-
  evolution questions: (1) Karl-the-Fog-style first-person personified-heat
  arc — held until model capability supports consistent personified narration
  without collapsing into anthropomorphic cuteness; (2) the thermometer mark
  may eventually over-index on temperature when the brand covers all
  planetary vital signs; (3) the orange accent applied to "values that
  matter" semantically reads as *heat* and miscues on cold-record values.

- **`brand/handoff/` asset overhaul** (#94, deliveries from Claude Design v2
  zip). Banner light + reverse simplified to lockup + tagline only — the
  previous newspaper-pastiche overlay (volume number, source list, station
  count, embedded live data) removed. OG card light + dark replaced — the
  previous frozen-in-time Kayes Mali data card retired in favor of brand-
  frame only (lockup + tagline). Brand Book HTML: cover tagline corrected,
  "climate data wire / logbook / wire desk / running a fever / amber / the
  brand is the reading" framing removed throughout (every page running
  header, every section deck, every embedded mockup). Usage Guide HTML:
  intro deck rewritten. Operator Dashboard HTML: renamed from "Wire Desk" to
  "Operator Dashboard"; item IDs renamed from `WIRE-XXXX` to `DRAFT-XXXX`;
  hero deck rewritten as internal editorial console framing.

- **`brand/CLAUDE_DESIGN_BRIEF_BRAND_KIT_CORRECTION_2026-05-14.md`** (#94)
  preserved in repo for traceability. The master spec used to drive Claude
  Design's deliveries, including: §1 product description, §2 diagnosis of
  the wrong positioning, §3 Phase 1 visual replacement deliverables, §4
  Phase 2 copy correction deliverables (8 sub-areas), §5 brand DNA to
  preserve, §6 hard constraints, §7 visual self-review protocol with three
  checklists + 16-string grep banlist, §8 reference files, §9 open questions
  for future v2 pass (mark, accent), §10 out of scope.

- **`brand/CLAUDE_DESIGN_BRIEF_MA_UPDATE_2026-05-14.md`** (#94) — companion
  brief instructing Claude Design to update its cached MA reference.
  Preserved alongside the master spec for the same traceability reason.

### Operations

- **Twitter / X profile updated** (off-repo, performed in-session). @theheat
  banner, avatar, bio, and pinned tweet now reflect the corrected
  positioning. Bio reads: *"Records, anomalies, and readings from across
  the climate system. Every post sourced. UTC times."* Display name and
  handle unchanged.

- **`theheat.ai` purchased on GoDaddy** (off-repo, in-session). Not yet
  pointed at a landing page; coming-soon page is a future task. X profile
  Website field left blank rather than linking to a GoDaddy parking page.

- **PR #93 closed without merge** (`voice-prompt-trust-more-prescribe-less`).
  Reason: v3 (PR #91, merged 2026-05-13) is philosophically opposite — v3
  explicitly preserves all 6 approved exemplars + 4 fire-variety alternatives
  + the 25-city orient-the-reader list (expanded to add Dubai + Singapore)
  + adds a new dedicated KILL DISCIPLINE section, while PR #93 cut exactly
  those elements. Selective porting produced near-empty diff because every
  cut in #93 intersected a v3 preserve. The 50-line simplification diff is
  stashed locally — to be re-examined if v3 produces another round of
  template-converged fires on subsequent alerts cycles.

### Memory hooks honored / added

- **Honored — `feedback_versioned_doc_filenames`**: the two Claude Design
  briefs use date-suffixed filenames. The MA update wasn't versioned because
  MA is the single canonical source (overwrite-in-place is the correct
  pattern for the canonical doc; old content lives in git history).
- **Honored — `feedback_absolute_file_paths`**: file references in the
  briefs use absolute paths.
- **Added — "Bring decisions to the user, not finished work."** Tagline
  iterations during this session showed the cost of slipping unapproved
  copy into briefs — I drafted "The planet's scorecard" → "An automated
  climate desk that surfaces events..." as cover sub-deck → Claude Design
  rendered them → user rejected. Pattern fix: any brand-facing copy in a
  brief must be either (a) lifted verbatim from MA / canonical docs, or
  (b) surfaced to the user as a decision before the brief ships.

### Tests

- **909 passing** (unchanged from 2026-05-13). No code changes this release.
- Mypy clean across `src/`.
- v3 writer prompt's 2026-05-14 09:00 UTC voice-regression nightly was the
  first nightly against v3 — confirmed green.

## [unreleased] - 2026-05-13

Three quality PRs and one infra hotfix opened today, none merged yet. Headline:
first graded two-bot cycle (PR #86) returned **4 drafts at 0% A-rate**. Voice
work landed (no Wodehouse violations observed, no P3 self-kills, FRP rounding
confirmed working) but new failure modes emerged — fire template convergence
across multiple drafts in a cycle, and expository-rather-than-punchy system
clauses limiting Chuuk monthly_high to a B-grade ceiling. Three afternoon PRs
address both classes. Plus a state-truncation hotfix after three scheduled
runs failed on a Gist API limit. **Open PRs: 4** (#84, #85, #86, #87).

### Added

- **State-truncation handling in `_read_gist_state` (#87, off main).** The
  GitHub Gists REST API truncates the inline `content` field at ~900 KB. When
  `state.json` grows past that the API sets `truncated: True` + exposes the
  full payload at `raw_url`. The previous code path read `content`
  unconditionally and fed it to `json.loads`, which crashed every scheduled
  run with `state.json is not valid JSON` until state shrank back. Observed
  in production 2026-05-13: three runs failed at 11:03 (auto_publish_due),
  13:34 (auto_publish_due), 14:47 (alerts). State at the time was 928 KB.
  Fix follows `raw_url` when the truncated flag is set, using the same auth
  headers and a 30s timeout (larger than the inline path's 15s).
  Regression test in `tests/test_state.py::test_read_state_handles_truncated_gist_via_raw_url`
  reproduces the exact production failure.

- **Defensive `normalize_station_name()` in 4 GHCN bundle builders (#84).**
  PR #82 root-caused the Paddock Lake / Sioux City BUNDLE_FACT kills at the
  regex source. This PR adds belt-and-suspenders normalization at the bundle
  boundary in `build_monthly_high_bundle`, `build_record_bundle`,
  `build_all_time_record_bundle`, `build_anomaly_bundle`. Idempotent on
  already-clean inputs; pure defense against any future signal-detection
  path that bypasses `ghcn.py:381`. Codex review surfaced an inconsistency
  where the normalization touched `where` and `current_facts.city` but left
  `raw_signal_dump.city` as the raw form — fixed via dict-spread
  (`{**asdict(ev), "city": city}`) in a follow-up commit so the bundle's
  internal city representations stay consistent. 5 new tests.

- **P3 — seasonal context as world knowledge for fires (#84).** Two
  changes to `writer_prompt.py`: removed the over-broad
  `"[country]'s fire/storm/wet season peaks in [month]"` bullet from the
  historical_context=empty "do NOT write" list, and added a new
  "Seasonal context for fires is world knowledge" paragraph. Closes the
  May 11–12 self-kill class where the writer killed Sahel/Siberia fire
  drafts citing "no verifiable seasonal framing without archive data."
  Empirically confirmed today (PR #86): no P3 self-kill failures across
  the 4 graded drafts.

- **P4 — Wodehouse rule section (#85).** New `# THE WODEHOUSE RULE`
  section in writer_prompt.py before `# HARD RULES`. Names four
  effort-signal failure modes: approximation when exact is available,
  restate-padding, poetry-attempt closers, defensive justification.
  Single most predictive failure mode across 5 corpus cycles per the
  grading agent. Today's grader (PR #86) found zero Wodehouse violations
  in the corpus — voice work already addresses this — but the explicit
  rule hardens the prompt against future regression. Empirical test:
  voice-regression cron tomorrow.

- **FRP intensity tier in `build_fire_bundle` (#85).** New `_frp_tier()`
  helper classifies FRP into low (<30 MW) / moderate (30–100) / high
  (100–500) / very_high (≥500). Adds two `current_facts` entries:
  `frp_tier` (label) and `frp_tier_floor_mw` (inclusive lower bound).
  Writer prompt instructs use of the tier word ("high-intensity at 309 MW",
  "in the very-high-intensity tier") instead of raw MW values that mean
  nothing to non-specialist readers. Explicit anti-attribution — no NASA,
  no FIRMS claim. Closes Andrew's editorial concern from 2026-05-12:
  "how is a normal reader supposed to understand what 364 MW is?"
  6 TDD tests at boundaries.

- **Per-day category cooldown via `MemorySlice.recent_categories` (#85).**
  New field on `MemorySlice` exposes signal categories already posted in
  the last 24 hours. `_signal_kind_to_category()` maps the 25+
  fine-grained signal_kinds to ~13 coarse categories (fire +
  fire_footprint → "fire"; all temperature record variants →
  "temperature_record"; etc.). Writer prompt's new `# PER-DAY CATEGORY
  COOLDOWN` section sets the softer rule: if your draft's category is in
  `recent_categories`, must clear meaningfully different mechanic /
  geography / scale, else kill with `kill_reason="category cooldown"`.
  Stops the "two fires in a row" pacing failure Andrew flagged from the
  2026-05-12 pending queue. 4 TDD tests.

- **P6 — fire sentence-1 variety (#85, second commit).** Grader found all
  3 fire drafts in 2026-05-13's first graded cycle used the identical
  opener: *"A fire in [location] is radiating X MW of heat, detected by
  satellite at N% confidence."* The 24h category cooldown above catches
  this across cron runs, not within a single cycle. New paragraph in
  writer_prompt.py names 4 alternative sentence-1 forms
  (lead-with-location, lead-with-seasonal-frame, lead-with-tier-word,
  lead-with-stakes-or-scale-anchor) with full example tweets. Bans the
  default opener when `recent_categories` already contains "fire" within
  24h.

- **Chuuk expository → punch nudge (#85, second commit).** Grader called
  the Chuuk monthly_high draft (B-grade ceiling) for an expository
  second sentence ("Chuuk sits in the Pacific warm pool") that described
  the system rather than doing work. Augmented `# THE SIGNATURE MOVE`
  section's bullet-2 with the expository-vs-punch distinction. Concrete
  B-vs-A example pair using the Chuuk case. New "delete the system
  clause" test: if removing your second sentence leaves the reader
  thinking "so what?", load-bearing; "oh, fair enough", expository.

- **`docs/writer-prompt-brief-v3.md`** — design brief for the writer
  prompt as a handoff doc to a fresh AI session that could rewrite the
  prompt from scratch. Captures brand context (utility not growth,
  rejected directions), reader profile, the shareability test
  framework (stop-mid-scroll + send-to-friend two-gate), the lodestar
  voice (Attenborough/Economist), pipeline context, operational
  constraints, output structure, observed failure modes (each rule
  traced to a real grading cycle), and a "what the prompt should NOT
  do" anti-pattern list. Iterated through 3 versions in chat. v3
  reconciles the "no virality" framing with the pipeline's actual
  virality evaluator by reframing both as quality measures, not growth
  tools.

### Findings

- **First graded two-bot cycle: 0% A-rate.** PR #86. 4 drafts, scores 64
  (Mali fire C+) / 65 (Campeche fire C) / 80 (Chuuk monthly_high B) /
  64 (Mongolia fire C). Gap from resumption bar: 50pp. Voice work is
  not the bottleneck this cycle — template convergence and
  expository-vs-punch are.

- **State.json approaching the GitHub Gist truncation limit.** State
  was 928 KB this morning (~900 KB API limit). Out-of-band trimming
  brought it back, but the underlying drift requires either #87 (graceful
  handling) or proactive state pruning. The `posted_events` and
  `suppressions` lists are the main contributors; both have cap logic
  but the cap may be too generous.

### Editorial framework changes

- **Shareability test now explicit as the two-gate editorial bar.**
  Stop-mid-scroll AND send-to-friend, both required. Codified in
  `docs/writer-prompt-brief-v3.md`. The existing virality-research
  evaluator (awe, social currency, opener, show-not-tell, comparison)
  is the operational form of this test — quality measures, not growth
  tools. Memory hook updated implicitly through brief; explicit memory
  update deferred to next operator session.

### Open items for tomorrow

- Merge order recommendation: #87 first (urgent CI hotfix), then #84,
  then #85 (auto-rebases onto main after #84). PR #86 (docs-only,
  grading agent) can merge any time after #84/#85 to avoid
  IMPROVEMENT_PLAN.md conflicts.
- Voice-regression cron 2026-05-14 09:00 UTC is the first empirical
  test of #85's Wodehouse + Chuuk punch + fire variety changes against
  fixtures.
- Codex review on PR #85 not yet run (was run on #84 only). Worth
  doing once #84 + #85 settle; the prompt is now ~225 lines and may
  have accreted conflicts.

## [0.5.1.0] - 2026-05-12

End-of-day cleanup wave. Six PRs merged after the morning's voice + length
retry + dashboard work (0.5.0.0): mypy ignore-list removed, +25 coverage-gap
stations, four production issues fixed in one PR, two daily-plan
reconciliations, and the docs sweep. Plus four stale daily-plan auto-PRs
closed without merge. **Open PR count: 5 → 0.**

### Added

- **`BotState` TypedDict + nested types (#72).** New `src/state_schema.py`
  defines `BotState` as a `TypedDict, total=False` mirroring
  `DEFAULT_STATE` exactly, with nested TypedDicts for the 9 keys that
  have known internal shapes (`Hot10Snapshot`, `MemoryState`,
  `OceanSSTStreak`, `SynthesisComponents`, `CityRecord`, `IceMassLoss`,
  `DroughtSnapshot`, `RecordStreakEntry`, `StreakEntry`). `total=False`
  lets older gist payloads (predating newer lane additions) still
  typecheck. The schema is derived from `src/state.py:19` `DEFAULT_STATE`
  as the single source of truth — drift is structurally prevented.

- **JSON-parse retry + clean KILL in writer (#82).** Mirror of #76's
  length retry but for the case where the model returns empty / non-JSON
  output. Observed 2026-05-12 on the Nettles Is Florida calendar_date_low
  bundle: same bundle, same writer call, same `Writer returned invalid
  JSON` error three runs in a row, surfacing as `pipeline_error` in the
  suppression ledger. Root cause is stochastic refusal — a second
  sampling almost always produces JSON. New constant
  `JSON_PARSE_RETRY_BUDGET = 1` plus declarative-only retry feedback (per
  the `feedback_prompt_json_contract` memory hook: never use imperative
  process language in strict-JSON prompts):

  > [JSON-output retry: the previous attempt did not return valid JSON.
  >  Return ONLY the JSON object specified by the system prompt's OUTPUT
  >  FORMAT section — no prose before or after, no markdown fences, no
  >  chain-of-thought.]

  After budget exhausted, returns a `WriterResult` with `tweet=None` and
  `kill_reason="writer returned invalid JSON across 2 attempts: …"`
  instead of raising — the pipeline no longer crashes on writer-output
  garbage, the dashboard shows a clean kill_reason. Five new tests in
  `tests/two_bot/test_writer.py::TestJsonParseRetry` cover retry path,
  exhaust → kill, no-retry-on-success, no-retry-on-good-kill, feedback
  content shape.

- **GHCN station-name normalization for space-separated COOP suffix +
  ANG military suffix (#82).** `_COOP_SUFFIX_RE` was tight enough to
  catch `1SW` / `2N` but missed space-separated `4 NE`. Stations like
  `PADDOCK LAKE 4 NE` (Wisconsin) carried unnormalized names through to
  the bundle; writer dropped the suffix when composing the tweet; fact-
  checker killed BUNDLE_FACT on every run. New regex:
  `\s+\d+(?:\.\d+)?\s*[NSEW]{1,3}$` (added `\s*` between digit and
  direction). Plus a new `_MILITARY_SUFFIX_RE` for the Air National
  Guard suffix (e.g. `SIOUX CITY ANG`). Two regression tests cover the
  exact production failures.

- **+25 stations closing coverage gaps (#81).** Cherry-picked from a
  6-day-old branch onto current main as a clean rebase. 613 → 638
  cities. Closes immediate gaps revealed by competitive coverage on
  2026-05-05: **Japan southern islands** (Naha, Ishigaki, Miyakojima);
  **Japan northern** (Sendai, Niigata); **Queensland coast** (Cairns,
  Townsville, Rockhampton, Mackay, Bundaberg); **Australia cool-side**
  (Hobart, Canberra); **northern China heatwave belt** (Harbin,
  Shenyang, Hohhot, Lanzhou, Taiyuan, Changchun); **Cyprus** (Limassol,
  Larnaca, Paphos); **cold-pole reporters** (Verkhoyansk, Oymyakon,
  Phalodi, Furnace Creek).

- **Wire-round-trip regression test for `BotState` (#72).** New
  `tests/test_state.py::TestBotStateSchemaRoundTrip` (3 tests) — load
  `DEFAULT_STATE`, `json.dumps(...)` with `json_default`, `json.loads`,
  run through `_normalize_state` and `_merge_state(empty, parsed)`,
  assert key-set equivalence and shape stability. Wire-format guarantee
  for the gist + SQLite round-trip per the `feedback_verify_the_wire`
  memory hook (TypedDict is erased at runtime but we still verified the
  bytes).

### Changed

- **Removed `ignore_errors = true` mypy overrides for `src.main`,
  `src.state`, `src.editorial.scoring` (#72).** Pyproject's
  `[[tool.mypy.overrides]]` had been hiding 147 errors across the three
  highest-trafficked modules pending a TypedDict refactor that this PR
  finally lands. Flip on those modules; mypy now type-checks the
  orchestrator end-to-end. The `src.voice.generator` override is out of
  scope and remains.

  - **`src/state.py`**: ~37 function signatures flipped `dict → BotState`,
    `DEFAULT_STATE` annotated, `_merge_memory` bootstrap refactored to
    use `cast(MemoryState, ...)` rather than dict iteration with
    literal-key restrictions.
  - **`src/main.py`**: ~20 function signatures flipped. The `:1000-1200`
    if-cascade that reassigned `ev` across mutually-exclusive branches
    (mypy couldn't narrow once locked) was rewritten with distinct
    variable names per branch — `ev_mh`, `ev_ml`, `ev_ah`, `ev_ac`,
    `ev_cdh`, `ev_cdl`. Minimal behavioral surface; pure type-narrowing
    fix.
  - **`src/editorial/scoring.py`**: widened `_build_score` and
    `_compute_total` metric params from `int` to `float`. `_clamp`
    already returns `int` so the wire format (SQLite + gist scores) is
    unchanged. One signature change cascaded to ~30 call sites.

- **`src/data/ocean_sst.py` — User-Agent header on
  climatereanalyzer.org requests (#82).** Server loops requests without
  a UA into infinite redirects (the `requests` default max of 30 is
  hit, raising `TooManyRedirects`). Adopted the `theheat-bot` UA
  convention already used by `src/data/nws_alerts.py`. Source goes
  green; SST anomaly tracking restored.

- **`src/data/river_gauges.py` — graceful degradation on retired
  flood-stage endpoint (#82).** USGS WaterWatch
  (`waterwatch.usgs.gov/webservices/floodstage`) was retired sometime
  before 2026-05-12 and now 301-redirects without a Location header
  returning HTML "Old Page" text. `_fetch_flood_stages` previously
  raised `SourceFetchError` in strict mode, killing the entire
  `river_gauges` source on every alerts run. Now always returns `{}`
  on failure with a docstring explaining the graceful-degradation
  contract. Current gauge heights still flow; only the
  `above_flood_stage` flag is lost. Finding a replacement endpoint
  (likely NWS AHPS gauge JSON) is tracked as a follow-up.

### Operations

- **Four stale daily-plan auto-PRs closed without merge** (#37, #49,
  #59, #66 — accumulated 2026-05-05 through 2026-05-10). Each was
  superseded by later daily-plan PRs and would have been a backward-
  revert of today's docs sweep had they been merged.

- **PR #29 (the +25 stations branch) closed via #81 supersession.**
  The original had stale doc commits on top of the station additions
  that would have reverted the morning's `BRIEFING.md` / `CHANGELOG.md`
  / `PIPELINE.md` updates. Cherry-picked just the data commits onto
  current main as the clean #81 instead.

- **Operator follow-up spec'd: switch daily-plan routine to a single
  long-lived `daily-plan-current` branch + persistent PR.** The
  accumulated PRs above were an AI-PR-hygiene problem (the routine
  opens fresh PRs but never closes the previous one), not an operator-
  inattention problem. Routine prompt change drafted; Andrew to paste
  into the Claude routines UI.

### Memory hooks honored / added

- **Honored — `feedback_prompt_json_contract`.** The new
  JSON-parse-retry feedback in `write_tweet` uses declarative language
  only ("Return ONLY the JSON object…") — no imperative process steps
  like "count, identify, remove, recount, repeat" that the iter-4 voice
  work proved will leak as visible reasoning into strict-JSON output.
- **Honored — `feedback_verify_the_wire`.** The `BotState` work added
  an explicit JSON round-trip test rather than relying on the TypedDict
  to enforce wire format (it doesn't — it's erased at runtime).
- **Honored — `feedback_generalize_fixes`.** The GHCN regex fix
  generalized to `\s*` between digit and direction rather than
  hardcoding the Paddock Lake station ID. The JSON-parse retry handles
  the class of stochastic refusals rather than the specific Nettles Is
  bundle.
- **Honored — `feedback_versioned_doc_filenames`.** The afternoon's
  end-of-day brief lives at `docs/handoffs/2026-05-12-v2.md`,
  not overwriting the morning's v1.
- **Added — AI PR hygiene framing.** Auto-PRs authored by Claude or
  Codex via the routines UI are AI hygiene, not Andrew's responsibility.
  Stale auto-PRs must not be framed as operator inattention.

### Tests

- **894 passing** (was 884 at the close of 0.5.0.0). Net deltas:
  +3 `TestBotStateSchemaRoundTrip` in #72, +2 station-name normalization
  in #82, +5 `TestJsonParseRetry` in #82, -1 net from 2 pre-existing
  writer tests updated for new retry+kill behavior.
- Mypy now clean across `src/` (147 previously-hidden errors → 0).
  `src.voice.generator` override remains (out of scope; different
  problem, retained for future cleanup).

### Production verification

- The three alerts runs preceding #82 (06:40, 10:34, 14:40 UTC) each
  produced 0 drafts, with the suppression ledger showing the four
  distinct failure modes targeted by #82 (Paddock Lake BUNDLE_FACT,
  Nettles Is pipeline_error, ocean_sst TooManyRedirects, river_gauges
  JSONDecodeError). The 18:39 UTC run is the first one against the
  fixes — if it reaches the writer without any of those four classes
  firing, the cleanup is complete in production.

## [0.5.0.0] - 2026-05-12

Voice-overhaul session. Three PRs landed cumulatively rewriting the writer's
editorial direction (Attenborough/Economist voice with explicit
system-explainer mandate) AND adding a code-side guardrail that makes
the 280-char Twitter cap a hard guarantee rather than a hoped-for property
of the prompt. Voice-regression went 12/12 green on the final state.

### Added

- **Attenborough/Economist voice + system-explainer mandate (#74).**
  Rewrote `src/two_bot/prompts/writer_prompt.py`'s voice anchor from
  "Economist correspondent" to "David Attenborough and The Economist"
  with explicit signature-move description: report the precise data
  point, name the system that produces it, stop. New sections:
  - **THE SIGNATURE MOVE** — three-beat structure (data / system / stop)
    with the "delete the last sentence" test for catching wink-kickers.
  - **Climate-arc vs stakes/pattern guidance** — explicit list of
    strong climate-connect candidates (heat records, marine heatwaves,
    sea ice loss, drought, hot-season expansion, etc.) and weak ones
    (cold records, isolated storms) where stakes / pattern framing is
    more honest than warming attribution.
  - **HARD RULE: no wink-kickers** — bans the *shape* not just the
    literal phrases. Forbidden: any closer whose main job is to
    reference "the calendar", "the season", "the date", or "what
    [month] would suggest". Explicit examples include "The calendar
    says spring.", "It's only May.", "Weeks before summer solstice.",
    "A record is a record.", "well past what the calendar suggests".
  - **HARD RULE: no self-supplied facility MW** — after the iter-2
    voice-regression run caught the writer fabricating "Hoover Dam at
    full capacity" (361 MW vs Hoover's actual ~2,080 MW) and then
    "Akosombo Dam at full capacity" (vs Akosombo's ~1,020 MW), the
    soft "95%+ confident" qualifier was replaced with a hard ban.
    Writer must use bundle-supplied comparison numbers or skip the
    comparison.
  - **5 APPROVED EXEMPLARS (after #75)** — Point Lay Arctic system
    (233 chars), Imperial County hot-season expansion (267), Mauna Loa
    CO2 accumulation (177), Mali fire without facility comparison
    (183), Verkhoyansk warm-record one-mechanism (187).

  Triggered by Andrew rejecting a wink-kicker on the pending Point Lay
  May blizzard draft ("The calendar says spring."). The old prompt's
  "Context" example was literally `"Blizzard warning in Point Lay. It
  is May 1."` — actively teaching the failure mode.

- **Cold-record exemplar #6 + compact Verkhoyansk (#75).** Voice-regression
  on the #74-merged state kept failing on Sissonville (monthly_low)
  and Verkhoyansk (monthly_high) — both at >280 chars because the
  writer reached for verbose "Cold records in an era of warming are
  increasingly local and topographic:" preambles. Added APPROVED
  EXEMPLAR #6 at 244 chars: Sissonville-style cold record with
  topographic mechanism only (Kanawha Valley cold-air drainage), no
  warming preamble. Andrew compacted exemplar #5 (Verkhoyansk) by
  dropping the second-half "cold poles are warming faster..."
  climate clause that overshot the budget. Plus a declarative rule:
  for `monthly_low` / `country_low`, pick topographic / geographic /
  local-flow mechanism, skip warming framing.

- **Writer-side length-cap retry + hard kill (#76).** Code-side
  guardrail in `src/two_bot/writer.py:write_tweet`. New constants
  `TWEET_MAX_LENGTH = 280` and `LENGTH_RETRY_BUDGET = 2`. If the model
  returns a tweet > 280 chars, retry up to 2 more times with
  *declarative* length feedback appended to the user prompt:
  > [Length retry: a previous attempt produced N characters. The
  >  280-character cap is hard. Return a shorter tweet that fits, or
  >  set tweet=null with kill_reason if no fitting version is possible.]

  After 3 failed attempts, return a KILL result with explicit
  `kill_reason`: `"writer produced over-280-char tweets across 3
  attempts (last attempt: N chars)"`. The dashboard surfaces this as
  a draft kill rather than shipping a truncated tweet to Twitter.

  Probability math: at the worst observed per-call over-length rate
  p=0.2 (run 4 against the unfinished prompt), all-3-attempts-fail =
  p³ = 0.8%. At the post-#75 baseline p≈0.05, all-fail = 0.01%.
  Cost: each retry ~$0.07 Sonnet call; worst case adds ~$0.30/voice-
  regression run, taking nightly cost from ~$6/mo to ~$9/mo.

  7 new tests in `TestLengthRetry` (tests/two_bot/test_writer.py)
  cover: retry on overlong, kill after retry budget exhausted, no
  retry when first attempt fits, no retry on kill, declarative
  feedback content in retry prompt, boundary at exactly 280, boundary
  at 281.

- **New memory hook: feedback_prompt_json_contract.md.** Imperative
  process steps ("count chars, identify clause, remove, recount,
  repeat") in a strict-JSON prompt leak into the response as
  reasoning text before the JSON, breaking the parser. Caught
  mid-PR-iteration when an iter-4 commit on the (since-deleted)
  voice-attenborough-economist branch broke 5/12 voice-regression
  fixtures with `ValueError: invalid JSON in model response`. Andrew
  merged at iter-3 before iter-4 landed, so main was never affected.
  Saved for future prompt edits: keep guidance declarative for any
  prompt with a strict-output contract.

### Changed

- **Killed pending draft #156 Mankato (manual editorial).** 0.1°C
  tied record in 16yr archive with a defensive "A record is a
  record." closer — didn't clear the editorial bar set by the new
  voice. Marked status=rejected with kill_stage=manual_editorial via
  `state.write_state()` (race-safe through `_merge_state`).

### Added (afternoon — dashboard UX + FRP rounding)

- **Dashboard refresh-button feedback (#78).** Andrew reported "when I
  click refresh on the dashboard it doesn't look like anything
  happens." The button was functionally fine — all 5 API calls were
  firing in ~60ms — but gave zero UI signal. Three new states wired
  into `fetchData` in `dashboard/app/page.js`:
  - `refreshing` (boolean) — true while any of the 5 parallel fetches
    is in-flight. Drives button label "refresh" → "refreshing…",
    disables the button, tints it the brand orange so the click is
    visibly acknowledged. Also prevents double-fire on rapid clicks.
  - `lastUpdated` (ISO string) — set on every successful run.
    Renders as "updated 5s ago" next to the button using the existing
    `timeAgo()` helper. Makes unchanged-data refreshes visibly
    successful (the relative timestamp ticks) and surfaces the
    auto-refresh interval to the operator.
  - `refreshError` (string | null) — surfaces network/parse failures
    as an orange "refresh failed" pill with the error in the title
    attribute (hover tooltip). Replaces the silent `console.error`
    path that was the original bug's root cause.

  CSS: new `.refresh-group` flex container, `min-width: 96px` on the
  button to prevent layout shift between the two labels,
  `.refresh-btn.is-refreshing` overrides the disabled-opacity so the
  brand orange remains saturated. 16 existing dashboard tests still
  pass; no API-contract changes.

- **Fire FRP rounded to 1 decimal at the bundle builder (#80).** NASA
  FIRMS returns FRP at two-decimal precision (e.g. `480.34 MW`). The
  fact-check prompt (`src/two_bot/prompts/fact_check_prompt.py` line
  9) requires exact numerical match — *"Verify exact match (number,
  unit, date). Mismatches = failure."* — with no tolerance rule.
  Writer rounding `480.34 → "480 MW"` produced BUNDLE_FACT kills on
  three fires in two cycles (480.34 → 480, 547.92 → 548,
  301.55 → 301; all BUNDLE_FACT). Fix: round at the bundle builder,
  not at the writer. `src/two_bot/intern.py:build_fire_bundle` now
  computes `frp_rounded = round(fire.frp, 1)` and uses it for both
  `headline_metric.value` and `raw_signal_dump.frp` so every
  consumer of the bundle sees the same 1-decimal value. The bundle
  becomes source-of-truth; writer naturally echoes the clean value;
  fact-checker confirms exact match.

  **Codex saved us from the wrong fix.** The original P2 proposal in
  `docs/IMPROVEMENT_PLAN.md` would have added a writer-prompt rule
  claiming a "±0.5 MW tolerance" the live fact-checker does not have.
  Codex caught the contradiction in review on PR #79. The plan was
  rewritten (commit `dcc6848` on the daily-plan-2026-05-12 branch)
  and implemented per the corrected design. See memory hook
  [feedback_prompt_json_contract](memory/feedback_prompt_json_contract.md)
  for the related "don't paper over runtime contracts with prose"
  pattern.

  Regression test in `tests/two_bot/test_intern.py` exercises five
  representative cases:
  - 480.34 → 480.3 (production failure)
  - 547.92 → 547.9 (production failure)
  - 361.0 → 361.0 (already-clean values pass through)
  - 250.05 → 250.1 (Python banker's rounding)
  - 1000.999 → 1001.0 (full carry)

  Asserts both `headline_metric.value` and `raw_signal_dump.frp` so
  consumers can't drift apart.

### Verification

- `python -m pytest tests/ -m "not voice_replay"` — **884 passed**
  (876 baseline + 7 new TestLengthRetry tests in #76, + 1 new
  test_build_fire_bundle_rounds_frp_to_one_decimal in #80).
- `python -m mypy src/` — clean (with the voice.generator override
  still in place per #63; mypy overrides for src.main, src.state,
  src.editorial.scoring remain pending merge of #72).
- `ruff check src/ tests/` — clean.
- Voice-regression on each PR via `voice-check` label: #74 ran 4
  times before final commit (each iteration caught a different
  failure mode that informed the next iter); #75 ran 1x green; #76
  ran 1x green. Final state on main: **12/12 fixtures pass**.
- Dashboard: 16 existing tests pass through #78 (no API-contract
  changes); manual browser verification of idle / refreshing / error
  states with `gstack-browse` tool.

### Open follow-ups

- **PR #72 (mypy ignore-list removal via BotState TypedDict)** is
  open with green CI. Not auto-merged — was authored on a previous
  session and never reviewed. Removes `ignore_errors = true` for
  `src.main`, `src.state`, `src.editorial.scoring` by adding a
  `BotState` TypedDict module (`src/state_schema.py`) + propagating
  annotations through `src/editorial/synthesis.py` and
  `src/two_bot/{memory,fact_check,pipeline}.py`. 147 previously-
  hidden errors → 0. Adds a `TestBotStateSchemaRoundTrip` to guard
  against future drift between `DEFAULT_STATE` and `BotState`.

- **PR #73 (auto-opened daily-plan refinement 2026-05-11: 8 drafts,
  12.5% A-rate)** — proves yesterday's grading-agent routine repair
  is working. Review when ready.

## [0.4.1.0] - 2026-05-10

Cron-feedback-loop session. The voice-regression harness shipped yesterday
(#61) fired on its first scheduled run 2026-05-10 10:06 UTC and caught
three real safety false-positives — exactly the silent-drift gap it was
built for. Two PRs (#67, #68) tightened the regexes; the daily-plan
grading-agent routine was repaired out-of-tree.

### Fixed

- **`check_month_repetition` false-positives on monthly_low/high (#67).**
  The 10:06 UTC voice-regression cron rejected three otherwise-good
  tweets (Sissonville WV, Dayton WY, Verkhoyansk RU) with `Month '<x>'
  mentioned N times — redundant date`. The old `count >= 2` rule
  targeted the bureaucratic `"April 10, 2026. It's April."` shape but
  false-positived on the now-standard `"hit X on May 4 — new May cold
  record"` pattern where the month is load-bearing twice (date + record
  class). Replaced with two targeted patterns:
  - Literal `"It's <Month>"` standalone (apostrophe REQUIRED — see #68)
  - Same-month year-anchored restatement (backreference — see #68)
  Plus a safety net at count ≥ 4 for egregious padding.

- **`check_truncated_temperature` single-digit Celsius relaxation (#67).**
  Picked up from Andrew's parallel-session WIP. Single-digit C (1°C, 4°C,
  5°C) is valid for cold-record signals — Dayton's 4°C reading was a
  real cold-record. Celsius branch dropped; left to the bundle fact-checker.
  Single-digit F still rejected (those reliably mean the writer dropped a
  leading digit, e.g. 91F → 1F).

- **Codex review of #67: regex precision (#68).**
  - `\bit'?s ({month})\b` made apostrophe optional, false-positiving on
    possessive `"Phoenix broke its May record"`. Apostrophe now required
    (straight `'` and curly `’` both accepted).
  - `({month})\s+\d{4}\.\s+(?:{month})` matched any month after a
    `Month YYYY.` sentence, false-positiving on cross-month comparisons
    like `"April 2026. May records have already fallen."` Second
    occurrence is now `\1` — only same-month repeats trigger.
  - 3 regression tests covering Codex's exact examples.

### Changed (out-of-tree)

- **Grading-agent routine prompt repaired** (routine `trig_016PGeHZgEYWmeQhx1xGmYg6`,
  "TheHeat daily plan refinement (15:00 UTC)"). PR #66 (auto-opened
  2026-05-10 by the failing agent) reported zero drafts graded due to
  `403 API rate limit exceeded` on the unauthenticated REST API path.
  - Step 2 (gist read) now uses `git clone https://gist.github.com/<id>.git`
    first — public gists are git repos, no auth needed for reads, no REST
    rate limit. Falls back to `gh api gists/<id>` if clone fails.
  - Step 7 (gist write for staleness rejection) now degrades gracefully
    — logs a skip note in the PR body if `gist:write` scope is missing,
    instead of aborting the entire run.
  - Added global "DO NOT abort on infra failures" hard constraint so the
    routine always produces useful output even with one degraded layer.
  - Validates on next cron at 2026-05-11 15:03 UTC.

### Verification

- 876 tests passing locally (was 866 at end of 2026-05-09; +10 across
  PR #67 and PR #68).
- `ruff check src/ tests/` clean; `mypy src/` clean (37 files, 0 errors).
- End-to-end `run_safety_pipeline` smoke on the 3 cron-rejected tweets:
  all 3 now PASS. Must-fail cases (canonical "It's April." + 4× padding)
  still REJECT.

## [0.4.0.0] - 2026-05-09

Ship-quality session — locked in defenses against silent test/CI gaps,
voice/prompt drift, and the kind of regression that took 4 days to
notice yesterday. Ten PRs (#55-#64) plus branch protection on `main`.

### Added

- **CI on PRs (#56)** — `bot.yml` `pull_request: { branches: [main] }`
  trigger so the `test` job runs on every PR. The `run` job stays
  scheduled-only; no tweet posting / gist writes / API quota burn on
  PRs. `actions/checkout@v4` → `@v6` and `actions/setup-python@v5` →
  `@v6` (Node 24-native, clears the deprecation warning).
- **Branch protection on `main`** — required `test` status check, no
  force-push, no deletions. Admin (Andrew) can bypass for emergencies.
  Direct pushes blocked; every change is a green-CI PR.
- **Hermeticity gate (#57)** — autouse fixture in `tests/conftest.py`
  blocks non-localhost `socket.connect` during tests. Pure stdlib.
  Any test that forgets to mock the network layer fails immediately
  with an actionable error pointing at the missing mock.
- **Anti-fabrication safety regex (#58)** — five new `BANNED_PATTERNS`
  in `src/voice/safety.py` mirror the writer prompt's verbatim banned
  examples. `TestFabricatedContext` (8 tests) and
  `TestWriterPromptHardRules` (11 tests, one per HARD RULE bullet)
  catch prompt drift at PR time.
- **Safety inline in `pipeline.generate_draft` (#60)** — was post-time
  only; now kills bad drafts at write-time.
- **Nightly voice-replay regression suite (#61)** —
  `tests/voice_regression/` with `StoryBundle` fixtures and a writer-
  replay harness. New `.github/workflows/voice-regression.yml` runs
  daily at 09:00 UTC + `workflow_dispatch` + `pull_request: labeled`
  with `voice-check`. Cost: ~$0.20/run × daily ≈ $6/mo.
- **Ruff lint in CI (#62)** — `pyproject.toml` E/F/W with `E402`
  ignore. Fail-fast lint step before pytest.
- **Mypy permissive baseline (#63)** — `check_untyped_defs`,
  `no_implicit_optional`, `ignore_missing_imports`. Three modules use
  `ignore_errors = true` pending a `bot_state` TypedDict refactor:
  `src.main` (47 errors), `src.state` (68), `src.editorial.scoring`
  (47).
- **Dashboard per-source health view (#64)** — new `Sources` tab
  aggregates per-source success rate, last error, and observation
  totals across the last 20 runs. New `GET /api/source-health`
  endpoint. Worst-first sort. Health tiers: `idle` / `healthy` /
  `degraded` / `unhealthy`, computed over **active** runs (skipped
  sources don't count as failures).

### Fixed

- **Flaky `test_main.py` tests (#55)** — three tests asserted
  `_try_two_bot_draft` called once but saw 3 calls under-mocked
  pipelines. Real CI network occasionally returned qualifying data on
  unmocked branches (`nws_alerts`, `gdacs`, `sea_ice`, `drought`,
  `enso`, `ocean`, `ocean_sst`, `water_levels`, `river_gauges`,
  `ice_mass`, `synthesis`, `ghcn`, `fire_footprint`). Added
  `mock_alerts_pipeline_sources` fixture and applied to 11 tests.
- **`record` variable type-confusion in `src/main.py` (#63)** — same
  name reused for `SeaIceRecord | None` (line 1971) and
  `IceMassRecord | None` (line 2400). Mypy locked the static type to
  the first assignment, hiding ~30 latent attribute-error
  possibilities. Renamed the IceMass-block variable to `ice_record`
  in lines 2400-2480.
- **Six small Optional unwraps (#63)** in LLM-response handlers —
  `response.text` is Optional in google-genai but was treated as
  plain `str` in `claim_extractor.py`, `fact_check.py`, `writer.py`
  (Gemini path), `voice/safety.py`, `voice/generator.py`. Anthropic's
  `response.content[0]` narrowed via `isinstance(block, TextBlock)`
  with explicit `RuntimeError` on unexpected block types. Empty-text
  fallbacks route through existing JSON-parse error path.
- **Five pre-existing lint issues (#62)** — dead `age` /
  `years_ago` variables, lambda-assignment in test, dead `a`/`b` in
  `test_era_anchors.py`. Plus 8 auto-fixed (unused imports, multi-
  imports, missing f-string placeholder). 4 imports that LOOKED
  unused were actually accessed via test patching (`@patch
  ("src.main.generator")`, etc.) — restored each with `# noqa: F401`.

### Pending follow-ups

- **Bot-state TypedDict refactor** — would unlock removing the three
  mypy ignores (`src.main`, `src.state`, `src.editorial.scoring`) and
  catch dict-key typos at static time. Largest single-PR effort
  available.
- **Bundle payload in suppression records** — would let real-killed
  bundles drive the voice-regression corpus beyond the hand-curated
  fixtures.

## [0.3.10.0] - 2026-05-08

Three high-severity fixes flagged by Codex review of PRs #38-#46.
Findings report at `docs/codex-review-findings-2026-05-08.md`.

### Fixed

- **Dashboard mergeState data-loss** in
  [dashboard/lib/state-store.js](dashboard/lib/state-store.js).
  Every dashboard approve/reject/edit click was rewriting `state.json`
  through a fixed dashboard-era key whitelist, erasing Python-owned
  keys: `memory` (two-bot repetition guard), `record_streaks`,
  `data_source_failures`, `ocean_sst_streak`, `ice_mass_*`,
  `fire_complex_tiers`, `synthesis_*`. Fix: spread base + incoming
  before applying explicit merge logic, so unknown top-level keys
  pass through.

- **SQLite round-trip dropped `memory` and `data_source_failures`**
  in [src/storage/sqlite_store.py](src/storage/sqlite_store.py).
  Both were live keys in `src/state.py` but absent from
  `_METADATA_JSON_KEYS`. On a sqlite-backed run, the two-bot
  repetition guard and the consecutive-source-failure counters
  reset every cycle. Added both keys + sqlite round-trip tests
  for each.

- **Claim extractor had no Gemini timeout** in
  [src/two_bot/claim_extractor.py](src/two_bot/claim_extractor.py).
  Missed in PR #43's timeout-unit fix. SDK default is `None` (=
  unbounded), so a stuck Gemini call could hang the cron run
  indefinitely. Now passes `HttpOptions(timeout=90000)` (90s) for
  parity with fact-check. Extended
  `TestGeminiTimeoutUnit::test_claim_extractor_gemini_timeout_is_in_milliseconds_range`
  to cover this path so the next regression fails loudly.

### Out of scope (still — punted to follow-ups)

- Suppression `stage` field rendering in dashboard (medium / certain) —
  schema is wired but the UI groups by `source` only, hiding the
  score_gate / writer / fact_check / pipeline_error distinction.
- `observation_kind` accuracy (medium / possible) — TMIN/TMAX are
  24-hour extrema, not strictly "overnight" / "afternoon." Acceptable
  imprecision for now; consider `daily_minimum` / `24h_low` framing
  if hourly data ever lands.
- GHCN observed records still labeled `forecast_*_c` (medium / likely)
  — semantically wrong for NOAA observed data. Should split into
  `observed_*_c` for GHCN, keep `forecast_*_c` for Open-Meteo. Lint-
  level concern; doesn't break the pipeline.
- JSON cleanup fallback isn't string-aware (low / edge) — trailing-
  comma regex could corrupt strings containing `,}` patterns. Edge
  case, but worth a string-aware walker upgrade.
- `JFK INTL AP` → `Jfk` (low / possible) — `text.title()` mangles
  IATA codes. Cosmetic; live station inventory has the case.

## [0.3.9.0] - 2026-05-08

Bilingual temperature units (Fahrenheit-first for US, Celsius-first
elsewhere). The bot's primary audience is American; until now every
draft was Celsius-only, which means a Sissonville reading of `-2.2°C`
forced US readers to do mental math. The pre-PR drafts were correct
but unfriendly.

The fix is a US-audience-first convention: lead with `°F` (integer-rounded)
and put `°C` in parens when `country = "United States"`. Everywhere else
stays Celsius-primary. Both values are pre-computed in the bundle so the
fact-checker accepts whichever the writer leads with — no rounding-mismatch
rejections.

### Added

- **`_c_to_f()`** in `src/two_bot/intern.py` — Celsius → Fahrenheit, rounded
  to integer. Matches how a US reader speaks the number ("28°F", not
  "28.04°F"). Passes `None` through.
- **`_is_us_country()`** — recognizes "United States" / "USA" / "US" /
  "U.S." (and case variants). Conservative: "Puerto Rico [United States]"
  and "Guam" are NOT US for unit-priority purposes — territory name
  comes first in tweets, and PR uses metric anyway.
- **`_audience_unit_facts()`** — adds `{"label": "audience_unit", "value":
  "fahrenheit_first" | "celsius_first"}` to the bundle's `current_facts`.

### Changed

- **4 GHCN-touching builders** (`build_monthly_high_bundle`,
  `build_record_bundle`, `build_all_time_record_bundle`,
  `build_anomaly_bundle`) now surface:
  - `headline_metric.value_f` — integer Fahrenheit alongside the Celsius `value`
  - `current_facts.today_temp_f` (or `today_f` for anomalies)
  - `current_facts.audience_unit`
  - `historical_context.prior_record_f` and `historical_context.margin_f`
- The anomaly delta is converted with **9/5 scaling only** (no +32 offset)
  because a temperature *delta* converts differently from an absolute
  temperature. `-9.5°C` anomaly = `-17°F` anomaly, not `-49°F`.
- **Writer prompt** in `src/two_bot/prompts/writer_prompt.py` gains a
  TEMPERATURE FORMATTING section explaining when to lead with F vs C
  and forbidding the writer from computing its own conversions
  mid-tweet (must use the bundle's pre-rounded values).

### Tests

- 7 new tests in `tests/two_bot/test_intern.py::TestFahrenheitConversion`
  cover known-value conversions (freezing / Phoenix / Verkhoyansk),
  US-country recognition, the territory-bracket exclusion, US vs non-US
  bundle differences, and the anomaly-delta scaling-only rule.
- Adjusted 4 existing tests that asserted `headline_metric == {exact dict}`
  to use field-by-field assertions, accommodating the new `value_f` field
  without forcing every test to know about it.
- Suite passes 308 across `test_ghcn / test_main / test_state /
  two_bot / test_open_meteo`.

### What this means in production

The Sissonville draft from yesterday's verification cycle would now
read:

> Sissonville, West Virginia hit **28°F (-2.2°C)** overnight on May 4th —
> breaking the previous May low of **29°F (-1.7°C)** set in 2020...

Dayton WY:

> Dayton, Wyoming dropped to **15°F (-9.4°C)** overnight on May 5th —
> breaking the previous May low of **17°F (-8.3°C)** set in 2010...

A Verkhoyansk reading would still read `-15°C` primary. The writer
gets to choose; the bundle contract makes both acceptable to the
fact-checker.

## [0.3.8.0] - 2026-05-08

Bundle enrichment to ground writer prose in bundle facts. After 0.3.7.0
landed station-name normalization, the fact-checker started catching a
new class of writer hallucinations:

- `"Dayton, Washington"` — writer guessed the state from world knowledge
- `"coldest May night"` — writer assumed TMIN observation was at night
- `"May in the inland Pacific Northwest"` — writer added regional context

These are correct rejections (the bundle didn't say those things) but
the *facts themselves* are right — Dayton IS in Washington, TMIN IS the
overnight low. The fix is to put those facts in the bundle so the writer
can ground in them and the fact-checker accepts the resulting prose.

### Added

- **`state` field** on RecordEvent / MonthlyRecord / AllTimeRecord /
  AnomalyEvent. Default None for backward compatibility.
- **`expand_us_state()`** in `src/data/ghcn.py` — maps 2-letter US state
  codes to full names (`"WV"` → `"West Virginia"`). Only expands for
  US country code; foreign 2-letter codes pass through as None so a
  Canadian "BC" doesn't get mis-expanded.
- **`_format_where()`** helper in `src/two_bot/intern.py` — composes
  `"{city}, {state}, {country}"` when state is set, falls back to
  `"{city}, {country}"` otherwise.
- **`_ghcn_observation_facts()`** helper in `src/two_bot/intern.py` —
  returns extra `current_facts` entries for `state` and
  `observation_kind` (`"overnight low"` for TMIN-based bundles,
  `"afternoon high"` for TMAX-based). Both no-op when inputs are None,
  so non-GHCN paths get an empty list.

### Changed

- `_detect_signals_for_station()` in ghcn.py extracts `state` once at
  the top and passes it to all 8 event constructors (4 high, 4 low).
- 4 bundle builders (`build_monthly_high_bundle`, `build_record_bundle`,
  `build_all_time_record_bundle`, `build_anomaly_bundle`) now use the
  helpers to surface state + observation_kind in `current_facts` and
  include the state in the bundle's `where` field.

### Tests

- 14 new tests in `tests/two_bot/test_intern.py::TestStateAndObservationKindEnrichment` and
  `TestExpandUsState` cover all four builders, US/non-US paths,
  case-insensitive state codes, US territories (PR/DC), and the
  observation_kind mapping.
- Suite passes 299 across `tests/test_ghcn.py tests/test_main.py
  tests/test_state.py tests/two_bot/ tests/test_open_meteo.py`.

### Out of scope (still)

- Regional descriptors ("Pacific Northwest", "Sahel", "Eastern Siberia").
  Requires a lat/lon → region geographic mapping table. Separate effort.
- Pure speculative hallucinations ("Flowers are already up", "the ground
  froze"). These aren't fixable via bundle enrichment — they need writer
  prompt tightening to forbid claims not grounded in bundle data.

## [0.3.7.0] - 2026-05-08

GHCN station-name normalization. After 0.3.6.0 unblocked the
fact-check timeout, the SISSONVILLE 1SW bundle made it through writer
+ fact-check successfully but the fact-checker rejected the draft on
editorial grounds:

> "Sissonville: UNVERIFIABLE: The specific named entity 'Sissonville'
> (without '1SW') does not appear exactly in the bundle. The bundle
> refers to 'SISSONVILLE 1SW'."

The writer correctly shortened the GHCN station name to "Sissonville"
(`1SW` is a CoCoRaHS direction-distance suffix meaning "1 mile
southwest"). The fact-checker treated the missing suffix as an
unverifiable named-entity claim.

Fix: normalize at the data-source boundary so writer + fact-check
both see the same clean place name. Raw GHCN name preserved on
``bundle.station_name`` for ops traceability.

### Added

- ``normalize_station_name()`` in [src/data/ghcn.py](src/data/ghcn.py).
  Strips three GHCN naming patterns:
  - CoCoRaHS suffix: `"SISSONVILLE 1SW"` → `"Sissonville"`
  - Airport suffix: `"MIAMI INTL AP"` → `"Miami"` (also "INTERNATIONAL", "MUNI", "REGIONAL", "NATIONAL")
  - WFO prefix: `"WFO SAN JUAN"` → `"San Juan"`
- Title-cases the result. 7 new tests in `tests/test_ghcn.py`.

### Changed

- `_detect_signals_for_station()` now uses the normalized name for
  ``bundle.city`` (and downstream events). ``bundle.station_name``
  keeps the raw GHCN form because it's only used for logging and
  doesn't reach the LLM.

## [0.3.6.0] - 2026-05-08

**The actual root cause of the 4-day outage.** After the codex sweep
(0.3.5.0) added retry logic to LLM calls, the new
`[two_bot.retry]` diagnostic lines finally surfaced what was
killing drafts: every Gemini fact-check call was timing out in
<300ms across 3 retry attempts.

The bug: `google-genai` SDK's ``HttpOptions.timeout`` is in
**milliseconds**, not seconds. (Confirmed against
googleapis/python-genai/google/genai/types.py — field docstring
"Timeout for the request in milliseconds.") Three sites in the
codebase were passing bare integers (``timeout=90``,
``timeout=180``) believing they were seconds; they were 90ms and
180ms — barely enough for a TLS handshake.

Likely introduced when the codebase migrated from the older
``google-generativeai`` SDK (timeout in seconds) to the newer
``google-genai`` SDK (timeout in milliseconds). The unit changed,
the values didn't.

### Fixed

- `src/two_bot/fact_check.py:63` — ``timeout=90`` → ``timeout=90000``
  (90 seconds, the original intent).
- `src/two_bot/writer.py:112` — ``timeout=90`` → ``timeout=180000``
  (Gemini fallback writer, parity with the Anthropic writer's 180s).
- `src/voice/generator.py:743` — ``timeout=180`` → ``timeout=180000``
  (voice-gen is dead code but fix the unit-of-measure bug for
  parity in case it's ever re-imported).

### Added

- 2 regression tests in `tests/two_bot/test_fact_check.py` that
  introspect the source of `_call_gemini` and `_call_google` to
  assert any HttpOptions timeout is >= 5000 (5 seconds in ms).
  Anything smaller fails loudly with a message explaining the
  millisecond-vs-second trap.

## [0.3.5.0] - 2026-05-07

Codex bug-hunt sweep. After today's reactive PR ladder (#38-#41) failed
to converge, ran a systematic sweep against the six-pattern rubric in
`docs/codex-bug-hunt-2026-05-07.md`. Codex found 13 findings (0
blocker, 7 high, 6 medium) and applied fixes in one pass. Findings
report at `docs/codex-bug-hunt-findings-2026-05-07.md`.

### Added

- **`src/two_bot/json_utils.py`** — shared boundary helpers used by
  every LLM parser and state writer. ``json_default`` covers
  date/datetime, Decimal, set/frozenset, dataclass, and bytes (raises
  loudly on truly unknown types). ``extract_json_payload`` finds the
  first balanced top-level object or array span, ignoring braces
  inside quoted strings (more robust than the first-`{` / last-`}`
  approach). ``loads_model_json`` falls back to comment- and
  trailing-comma-tolerant parsing on a `JSONDecodeError`.
- **`src/two_bot/retry.py`** — bounded retry helper with exponential
  backoff. Wraps every LLM call (writer, fact-check, claim extraction)
  so a single 529 / ReadTimeout / transient blip doesn't kill the
  draft. Default 3 attempts, 1s base sleep, doubles each attempt.
- **`src/data/source_status.py`** — typed exceptions for
  source-fetch failures: `SourceFetchError` (transport/schema) and
  `SourceSkipped` (intentional skip, e.g. missing optional config).
  Replaces "return empty list and pretend success" pattern in FIRMS
  + fire_footprint.

### Changed

- **Writer / fact-check / claim-extractor** all now use the shared
  ``loads_model_json`` and ``call_with_retries``. Removes ~100 lines
  of duplicated parsing / serialization / retry code from the writer.
- **State persistence** (`src/state.py`, `src/storage/sqlite_store.py`)
  now uses ``json_default`` so any future date/dataclass/Decimal slip
  into state can't crash the Gist write.
- **FIRMS** raises `SourceSkipped` when API key is missing,
  `SourceFetchError` on transport/schema failures. `main.py` catches
  these and records `status="skipped"` or `status="failed"` instead
  of "success with 0 fires."
- **Fire footprint** raises `SourceFetchError` on fetch failure and
  no longer advances `fire_footprint_last_run` until a confirmed
  successful fetch — failed runs can retry rather than waiting until
  tomorrow.

### Visibility

The downstream-suppression hooks shipped in 0.3.2.0 now cover more
ground because failures that previously vanished into "success with 0
items" now surface as proper source-level `failed`/`skipped` status,
or as suppression records when individual items die. The dashboard
funnel keeps its existing schema; the `Suppressed` tab gets richer
content automatically.

### Tests

- 31 new tests across `tests/test_source_failures.py`,
  `tests/test_threshold_update_script.py`, `tests/two_bot/test_retry.py`,
  and additions to `test_open_meteo.py`, `test_state.py`,
  `test_claim_extractor.py`, `test_fact_check.py`, `test_pipeline.py`.
- Suite total: **774 passed** (was 743 after #41).

### Out of scope (deferred)

- Cycle-cap / city-cooldown / same-day-dedup suppression stages.
  Documented in findings as medium / likely; left for a follow-up
  PR because they require a bigger main.py refactor and the
  visibility today goes through editorial-gate + writer/fact-check
  /pipeline-error stages first.
- LLM tool-use / response_format mode. Defensive parsing is
  sufficient for now; tool-use is a larger architectural decision.

## [0.3.4.0] - 2026-05-07

Tolerant writer-response parsing + larger Anthropic timeout. After the
fence-stripping fix in 0.3.3.0, the next alerts cycle revealed two
more failure modes: ``ReadTimeout`` at the 90s client cap, and
chain-of-thought preamble (`"Let me think about this carefully."`)
emitted *before* the JSON object — neither matched by the fence
stripper.

### Fixed

- **Anthropic client timeout 90s → 180s** in
  [src/two_bot/writer.py](src/two_bot/writer.py). Sonnet 4.6's
  variance under load exceeds 90s for some bundles. 180s is well
  within GitHub Actions cron headroom.
- **Robust JSON extraction** via new ``_extract_json_payload``: locates
  the first ``{`` and last ``}`` in the (de-fenced) response and
  parses the substring between them. Handles preamble, postamble, and
  nested ``raw_signal_dump`` objects without false positives. 7 new
  tests cover preamble stripping, postamble stripping, combined
  preamble + fences, nested-object handling, clean-response
  passthrough, no-braces fail-loud, and the full
  ``_parse_writer_json`` path on a realistic Sonnet preamble response.

## [0.3.3.0] - 2026-05-07

Strip markdown code fences from writer output. Sonnet 4.6 wraps its
JSON in ```json fences despite the prompt explicitly forbidding them
("No markdown. No code fences. No prose outside the JSON."). After the
date-serialization fix landed in 0.3.2.0, the very next alerts cycle
revealed this is the next layer: 2 monthly_low + 2 fire bundles still
died with ``ValueError: Writer returned invalid JSON``. The
suppression ledger captured all 4 with ``stage: pipeline_error`` so we
could see the kill — that's the loop closing.

### Fixed

- **Tolerant writer-response parsing** in
  [src/two_bot/writer.py](src/two_bot/writer.py). New
  ``_strip_markdown_fences`` pre-processor handles ``\`\`\`json``,
  ``\`\`\`JSON``, plain ``\`\`\``, and any of the above with leading or
  trailing whitespace. Strict prompting wasn't enough; defensive
  parsing is the durable fix. 7 new tests cover the variants plus the
  full ``_parse_writer_json`` happy path on a fenced response and the
  loud-fail contract for genuinely malformed JSON.

## [0.3.2.0] - 2026-05-07

Unblock GHCN drafts. Today's first 3 post-cutover monthly_low bundles
(SISSONVILLE 1SW, ATKA ISLAND, WFO SAN JUAN) all passed the editorial
score gate (score 80, monthly threshold 76) and died downstream with
``TypeError: Object of type date is not JSON serializable``. The
two-bot pipeline's catch-all swallowed the stack trace, so the
dashboard showed "0 drafts" with no surfaced cause for ~13 hours.
Cause: the ``signal_date: date | None`` field added in PR #32 leaks
through ``asdict(ev)`` into ``raw_signal_dump`` and chokes
``json.dumps()`` in the writer + fact-check stages.

### Fixed

- **Date serialization** at the LLM API boundary in
  [src/two_bot/writer.py](src/two_bot/writer.py) and
  [src/two_bot/fact_check.py](src/two_bot/fact_check.py). New shared
  ``_json_default`` hook coerces ``date``/``datetime`` to ISO 8601
  strings (which is the format the writer prompt expects anyway) and
  raises ``TypeError`` loudly on any other unknown type — no silent
  ``str()`` coercion of future surprises. 4 new tests cover bundle +
  memory + fact-check JSON paths and the loud-failure contract.

### Added

- **Downstream suppression capture**. The ``suppressions`` ledger now
  records kills that happen *after* the editorial score gate — writer
  kills, fact-check rejections, and pipeline exceptions. Each record
  carries a ``stage`` discriminator (``score_gate`` |  ``writer`` |
  ``fact_check`` | ``pipeline_error``) and the actual ``kill_reason``
  string surfaced through a new ``result_out`` parameter on
  ``generate_draft()``. Today's bug would have been visible in the
  dashboard within minutes if this had existed; future variants will
  be. 5 new tests cover all four kill paths plus the success and
  no-active-context cases.

### Out of scope (still)

- Cycle-cap and per-city-cooldown kills. These happen in main.py
  before ``_try_two_bot_draft`` runs and would need their own capture
  hooks. Lower priority — they're already visible in cycle_dropped
  events and the source_run notes.

## [0.3.1.0] - 2026-05-07

Suppression ledger + dashboard health-calc fix. Captures the
"near-miss" editorial-gate kills the bot has been making invisibly,
surfaces them in the dashboard, and fixes the headline health tile
that was counting intentionally-idle lanes as unhealthy.

### Added

- **`suppressions: []` in state** + `_merge_suppressions` in
  `src/state.py` (id-dedupe, ts-sort, 200 cap). Mirrored in
  `dashboard/lib/state-store.js` for the JS read path.
- **`SUPPRESSION_NEAR_MISS_GAP` env var** (default 15) — only kills
  where `threshold - total <= gap` are recorded, so the ledger
  doesn't flood with obvious noise.
- **`_should_draft()` capture in `src/main.py`** via a process-level
  context (`_activate_suppression_ctx`), wired into `run_alerts`
  and `run_leaderboard`. Records `id`, `ts`, `run_id`, `source`,
  `event_id`, `category`, `score_total`, `threshold`, `reasons`,
  `summary`.
- **SQLite `suppressions` table** + read/write round-trip in
  `dashboard/lib/state-store.js`. Python side reuses the
  `_METADATA_JSON_KEYS` path in `src/storage/sqlite_store.py`.
- **`GET /api/suppressions`** route (auth-protected, default limit
  50, max 200) with `source` and `since` filters and aggregate
  stats (24h, 7d, top source, source counts).
- **Suppressed view** in the dashboard — stats tiles + per-source
  breakdown + filtered list.
- **24 new tests** in `tests/test_state.py` (default state, merge
  dedupe + cap + sort, SQLite round-trip, capture-on-near-miss,
  capture-not-on-far-miss, capture-not-without-context, capture
  cap).

### Fixed

- **Dashboard health calc** in `dashboard/app/page.js`. The
  "Current Run" tile counted only `status === "success"` as
  healthy, which marked legitimate scheduled-skip lanes
  (Mondays-only sea-ice / ice-mass, Fridays-only drought,
  1st-of-month ENSO, "already ran today" caps) as unhealthy.
  On a typical Thursday cycle, 7 lanes are intentionally idle
  and the headline read 11/18 = 61% healthy. Now treats
  `skipped` as healthy and surfaces the count in the sub-label
  ("· 7 scheduled idle"), so the same cycle reads 100% / 18 of
  18 healthy · 7 scheduled idle.

### Out of scope

- Suppression capture for downstream kills (writer fact-check,
  virality-evaluator, cycle-cap, dedup, cooldown). Today only
  the editorial score gate is captured; the 3 GHCN bundles in
  the first post-cutover cycle that died with `score: 80`
  (which passes the 76 monthly threshold) wouldn't show up
  here. Follow-up.

## [0.3.0.0] - 2026-05-07

NOAA GHCN-Daily migration. The extreme-signals lane now reads 11,907
active stations instead of 638 curated cities — a 19× expansion of
coverage, at $0/month operating cost. Hot 10 leaderboard stays on
Open-Meteo. Identity layer (brand) locked.

### Added (PRs #30, #31, #32)

- **`src/data/ghcn_format.py`** — pure stdlib parser for NOAA `.dly`
  fixed-width files and `superghcnd_diff` tar archives (insert/update/
  delete CSV members). Compute_thresholds builds all-time/monthly/
  calendar-date max+min plus climatological_mean for TMAX and TMIN.
- **`src/data/ghcn_db.py`** — SQLite schema (`stations`, `thresholds`,
  `meta`) with upsert/load helpers. Bootstrap database is ~913 MB,
  9.28M threshold rows, distributed as a GitHub Release asset
  (`thresholds-latest`).
- **`src/data/ghcn.py`** — `check_extreme_signals_for_stations()`
  mirrors the Open-Meteo entry-point contract. Fetches recent
  `superghcnd_diff` tarballs in parallel via `ThreadPoolExecutor`,
  filters out stale backfill (older than `MAX_OBS_AGE_DAYS`),
  detects all-time / monthly / calendar-date / anomaly signals,
  dedups to top-2 per country.
- **`scripts/refresh_station_inventory.py`** — pulls
  `ghcnd-stations.txt`, `ghcnd-inventory.txt`, `ghcnd-countries.txt`
  and seeds the `stations` table.
- **`scripts/build_station_thresholds.py`** — one-time local bootstrap
  (downloads 3.44 GB `ghcnd_all.tar.gz`, computes thresholds, writes
  the SQLite, ~6 min on M-series). Re-runnable without re-download.
- **`scripts/update_thresholds_incremental.py`** — weekly CI script
  fetches `superghcnd_diff` since `last_synced` watermark, updates
  affected stations.
- **`.github/workflows/refresh-thresholds.yml`** — weekly cron that
  runs the incremental update and re-uploads the asset.
- **Feature flag `THEHEAT_SIGNALS_PROVIDER`** — `open_meteo` (default
  fallback) or `ghcn` (default in production). Single env var flip
  for rollback.
- **`signal_date: date | None` field** on every extreme-signal
  dataclass (`RecordEvent`, `AllTimeRecord`, `MonthlyRecord`,
  `AnomalyEvent`, `RecordStreakEvent`, `CountryRecord`,
  `ExtremeSignalBundle`). Plus `station_id: str` and `station_name: str`
  on `ExtremeSignalBundle`. None defaults preserve backward compat.
- **`_resolve_when` helper** in `src/two_bot/intern.py` — applied to
  all 6 extreme-temperature `build_*_bundle` functions so the writer's
  `when` field reflects the actual obs date on the GHCN path (24-48 hr
  lag) and falls back to `date.today()` on Open-Meteo.
- **`data_source_failures: dict` in `DEFAULT_STATE`** + helpers in
  `src/state.py` (`increment_data_source_failure`,
  `reset_data_source_failure`, `get_data_source_failure_count`).
  Three consecutive failures emits `[alerts] STRUCTURAL ALERT`.
- **CI threshold-DB sanity check** in `bot.yml` — refuses to run the
  bot if the SQLite has fewer than 1,000 active stations or 1,000
  thresholds. Fails loud on a corrupt asset rather than silently
  zero-coverage.

### Added (PR #36 — dashboard drill-down)

- **`details: dict` field on `source_run`** records (`src/state.py`).
  Schema is loose; conventional keys: `pipeline_metrics`, `events`,
  `fetch_meta`. Each source can populate what's useful.
- **`metrics_out: dict` parameter** on
  `check_extreme_signals_for_stations()` — caller can inspect the
  funnel without changing the public return contract.
- **Per-bundle event log** captured by the GHCN dispatch in
  `src/main.py`. Each row records station, decision (`drafted` /
  `rejected` / `no_qualifying_signal`), score, signal_date, observed
  temps. Top 200 events shipped to source_run details.
- **Dashboard `SourceRow` component** with click-to-expand. Renders
  `PipelineFunnel` (bar chart of stage drop-off) + `EventsTable`
  (per-bundle decisions with badges). Visible on the `Source Health`
  panel of the latest bot run.

### Fixed (PR #35 — post-cutover diagnostic findings)

- **Stale-obs filter** in `src/data/ghcn.py`. `superghcnd_diff` files
  routinely contain late-arriving observations from 1–2 weeks earlier
  (a station finally uploads its old readings). Treating those as
  fresh signals would surface week-old weather as "today's news."
  New constant `MAX_OBS_AGE_DAYS` (env-tunable, default 4) sets a
  freshness floor; older records are dropped with a logged count.
- **TMIN climatology persistence regression test**
  (`test_upsert_thresholds_persists_climatological_mean_min`). The
  shipped 2026-05-05 SQLite asset had no `climatological_mean_min`
  rows, blocking all cold-anomaly detection. Fixed in the bootstrap
  code (Codex review pass) and now backed by a test that asserts
  TMIN climatology round-trips through SQLite.

### Codex review pass (in PR #33)

- Corrected `superghcnd_diff` handling to the live tar/CSV format
  (insert.csv / update.csv / delete.csv inside the tarball, not the
  flat `.dly`-shaped text the original implementation assumed).
- Same-day TMAX and TMIN preserved instead of one element masking
  the other.
- Delete records and QC-failed updates correctly remove any earlier
  value seen in the lookback window.
- TMIN-only stations now eligible for cold-anomaly detection.
- Missing/no-observation GHCN cycles fail closed (raise +
  data_source_failures increment) rather than silently emitting nothing.
- Threshold DB replacement hardened against partial-write races.

### Coverage scope (deferred to a future hybrid-feeds PR)

GHCN-Daily covers most but not all @extremetemps records. Verified
present: Phoenix Sky Harbor, MSP, Verkhoyansk, Oymyakon, Phalodi,
Death Valley. **Verified missing:** Tokashiki/Okinawa, Troodos/Cyprus
(Japan + Cyprus have sparse station coverage in GHCN). Closing those
gaps requires hybrid feeds (JMA AMeDAS, Cyprus DoMS) — separate PR
when/if a station-level Japan or Cyprus event surfaces and we miss it.

### Brand identity (separate work, parallel)

Brand system locked at R3 v4. Production handoff at
`brand/handoff/` (single canonical location after consolidation):

- Wordmark: Inter SemiBold mixed case, -0.020em letterspacing
- Mark: thermometer + accent bulb (`#C2410C`)
- Color system: paper/ink palette + single accent on headline numbers
- Number typography: integer + decimal in accent, unit in ink-2,
  superscript °C, tabular figures
- Avatar (rebuilt locally, mark fills 65% of the circle), banners
  (rebuilt locally, no fake live data, no newspaper-masthead LARP),
  favicons, Apple touch icon, OG card, Brand Book, Operator Dashboard
  treatment, Usage Guide

### Out of scope this release

- Hot 10 leaderboard migration (locked: stays on Open-Meteo).
- Hybrid feeds for Japan / Cyprus / small-island gaps.
- Theheat.ai website design.
- Open-Meteo dead-code removal — kept dormant behind the feature flag
  for at least one quarter as rollback path.

## [0.2.0.0] - 2026-05-04

The two-bot architecture is now THE pipeline. Gemini Flash retired from
the writing path; Sonnet 4.6 drafts every audience-facing tweet.

### Added (PR #21)

- **Shadow A/B infrastructure** for `monthly_high`, `country_record`,
  and `severe_weather` signals — generates a parallel two-bot draft
  alongside the live voice-gen tweet for side-by-side comparison.
  Gated by `THEHEAT_SHADOW_AB_ENABLED=1`.
- **90-second timeouts on all LLM clients** (`anthropic.Anthropic`,
  `genai.Client`) to prevent indefinite GitHub Actions hangs. The
  trigger: a stuck production run held the concurrency lock for 2+
  hours on a slow Gemini 3 Flash Preview call.
- Bundle builders for `monthly_high`, `country_record`, and
  `severe_weather` (`build_*_bundle` in `src/two_bot/intern.py`).

### Added (PR #22)

- **Centralized model config** in `src/config.py` (`CHEAP_MODEL`,
  `WRITER_MODEL`). All four LLM callers (voice/generator,
  two_bot/{fact_check, claim_extractor, writer}) now import defaults
  from one place; per-caller env overrides preserved for surgical A/B.
- **Dashboard hardening**: `GET /api/config` endpoint, MODEL CONFIG
  panel showing live model selection, `robots.txt` + `X-Robots-Tag`
  HTTP header + meta robots tag, `Referrer-Policy: no-referrer`.
  Belt+suspenders against indexing on top of existing Basic Auth.

### Changed (PR #22)

- **Rolled voice generator off `gemini-flash-latest`** (currently
  aliases to Gemini 3 Flash Preview, chronically slow under our
  workload) back to stable `gemini-2.5-flash`. Bumped HTTP timeout
  90s → 180s for voice-gen specifically (12K-char prompt asking for
  4 candidates is heavier than fact-check). Dropped `MAX_RETRIES`
  3 → 1: timeouts don't recover on retry.

### Changed (PR #25)

- **Full voice→two-bot port.** Every audience-facing signal type now
  runs through the two-bot writer (Sonnet 4.6). Voice generator is no
  longer reached on any live path. 22 bundle builders in
  `src/two_bot/intern.py`, one per signal source.
- **Dashboard `/api/generate`** swapped from Gemini Flash to Anthropic
  Sonnet (`THEHEAT_WRITER_MODEL`). Manual compose now uses the same
  writer as the bot.
- **Removed `already_drafted` repetition guard** for `severe_weather`
  and `global_disaster`. Replaced with `recent_tweets_same_event`
  window in `src/two_bot/memory.py` so the writer sees prior drafts
  in the same NWS/GDACS event series.
- **Extreme-signals dispatch** now drops unsupported signal types
  rather than falling through to voice gen. A missed tweet is better
  than a Gemini-Flash-written tweet.

### Codex review fixes (in PR #25)

Bundle builders now preserve facts the writer needs:
- `build_all_time_record_bundle`: `archive_window_only=True` and
  `signal_kind="open_meteo_archive_high/low"` to keep the writer
  honest about archive scope (not "hottest day ever in history").
- `build_monthly_high_bundle`: `monthly_low` label distinguished
  from `monthly_high` based on `kind`.
- `build_enso_bundle`: aligned key names with the dispatch dict
  (`status_to`, `previous_duration_months`).
- `build_fire_footprint_bundle`: now carries the tier threshold the
  voice generator referenced.
- `build_ice_mass_bundle`: archive span preserved.
- `build_drought_bundle`: severity metrics surfaced beyond raw counts.

### Removed (effectively)

- `src/voice/generator.py` is no longer called on any live signal
  path. The 1,730 lines remain in the repo as defensive code +
  template fallbacks. Slated for deletion in a follow-up cleanup PR.

### Deferred / open follow-ups

- Disable Sonnet evaluator pass via `EVALUATOR_ENABLED=false`
  (saves $25–45/mo; redundant with `fact_check.py`).
- Delete `src/voice/generator.py` and downstream dead code.
- Category-tune `writer_prompt.py` for the ~16 newly-ported signal
  types as production data surfaces failure modes.

## [0.1.0.0] - 2026-04-21

### Added

- **Fire footprint pipeline (Lane 3)** — the bot now tracks cumulative wildfire burn
  area and drafts a tweet each time a named or unnamed fire complex crosses one of
  six hectare thresholds: 20k, 50k, 100k, 250k, 500k, and 1M ha. Tier crossings are
  deduped by complex ID so a fire that grows through multiple tiers over days emits
  one tweet per threshold, not one per cron run.
- `src/data/fire_footprint.py` — fetches active fire perimeters from the NIFC WFIGS
  ArcGIS Feature Service (open API, no auth). Converts acres to hectares, filters
  child incident rows (`IsCpxChild`), orders by largest fires first, and warns when
  the 2,000-row result cap is hit.
- `detect_tier_crossings` — compares current burn area against stored tier state and
  returns only complexes that have crossed a new (higher) tier since the last run.
- `score_fire_footprint` — editorial scoring with named-complex and shoulder-season
  novelty multipliers; threshold 72, `manual_only` approval policy.
- `fire_footprint_template` / `generate_fire_footprint_tweet` — acreage-first tweet
  framing with named and unnamed fire complex variants and NIFC attribution.
- `fire_complex_tiers` and `fire_footprint_last_run` state keys with max-merge
  semantics to guard against concurrent cron writes.
- 59 new tests across `test_fire_footprint.py`, `test_state.py`, `test_editorial_scoring.py`,
  `test_editorial_approval.py`, `test_editorial_candidates.py`, `test_generator.py`,
  and `test_main.py` (370 total, all passing).

### Changed

- `src/main.py` — `run_alerts` inserts fire footprint as section 2b (between FIRMS
  and CO2). Each tier-crossing iteration runs in its own `try/except` so a transient
  Gemini error on one complex does not abort the remaining crossings for the day.
- `src/state.py` — `DEFAULT_STATE` extended with `fire_complex_tiers` and
  `fire_footprint_last_run`; `_merge_state` handles both with max semantics.
- `src/editorial/scoring.py` — off-by-one `reasons[:3]` slice removed from
  `_build_score`; `score_fire_footprint` added.
- `BRIEFING.md` / `PIPELINE.md` — pipeline diagram, scoring table, and NIFC source
  documentation updated to reflect the new lane.
- Data source pivoted from GWIS (no JSON API) to NIFC WFIGS ArcGIS Feature Service.
