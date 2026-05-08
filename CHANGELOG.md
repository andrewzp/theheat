# Changelog

All notable changes to this project will be documented in this file.

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
