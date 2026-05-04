# Changelog

All notable changes to this project will be documented in this file.

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
