# Changelog

All notable changes to this project will be documented in this file.

## [0.9.53.0] - 2026-06-12

THIRTY-LOOP S-26 spreads Open-Meteo air-quality chunk requests across the
minute budget so the source avoids self-induced 429 bursts while keeping the
existing recovery pass as a backstop.

### Changed

- **Pace Air Quality API chunks.** `src/data/air_quality.py` now reads
  `THEHEAT_AQ_CHUNK_PACING_S` with an 8-second default and sleeps through a
  testable `_pacing_sleep` seam between chunk requests, never after the last
  chunk. The 429 recovery path now prefers `Retry-After` when Open-Meteo sends
  it and falls back to the existing Date-header minute-boundary wait otherwise;
  `tests/test_air_quality.py` covers pacing, Retry-After, and the existing
  recovery behavior without real sleeps.

## [0.9.52.0] - 2026-06-12

THIRTY-LOOP S-25 dark-ships OpenAQ PM2.5 ground-station corroboration so
model-estimated air-quality hazards can carry stronger evidence when Andrew
adds the OpenAQ API key.

### Changed

- **Add OpenAQ corroboration behind a secret.** New `src/data/openaq.py` fetches
  the nearest fresh OpenAQ PM2.5 reading within 25 km, upgrades an air-quality
  event only when the station value is within 35% of the CAMS 24-hour mean, and
  degrades silently on OpenAQ failures. PM2.5 bundles now carry station facts
  when corroborated, the writer/fact-check prompts recognize
  `model_corroborated_by_station`, and `.github/workflows/bot.yml` passes
  `OPENAQ_API_KEY` from secrets while production remains unchanged until the
  secret is configured.

## [0.9.51.0] - 2026-06-12

THIRTY-LOOP S-23 adds reef-system context to coral bleaching bundles so the
writer can vary coral drafts with factual regional mechanics instead of
reusing generic DHW threshold language.

### Changed

- **Add Coral Reef Watch region context.** New `src/data/reef_context.py`
  maps the live `coral_dhw_last_tier` region keys to capped factual context
  facts covering the current ocean system, notable history, and ecosystem
  setting. `src/two_bot/intern/marine.py` now injects up to three
  `reef_context` facts into coral bleaching bundles, and the writer prompt
  gets one declarative line naming those facts as bundle-supplied context
  without authorizing unsupported trend claims.

## [0.9.50.0] - 2026-06-12

THIRTY-LOOP S-22 dark-ships multi-draft writer sampling and one-pass critic
revision so supply can be expanded later without changing default production
behavior.

### Changed

- **Add flagged best-of and revision paths.** `src/two_bot/pipeline.py` keeps the
  single-sample path byte-for-byte compatible by default, while
  `THEHEAT_WRITER_SAMPLES>1` runs parallel writer samples, sends viable drafts
  to the critic as a slate, and fail-closes on slate parse exhaustion.
  `THEHEAT_CRITIC_REVISE_ENABLED=1` allows one declarative critic revision
  note, after which the revised draft reruns safety, fact-check, and a terminal
  no-revise critic pass; `.github/workflows/bot.yml` also passes through the
  dark flags and `THEHEAT_MAX_DRAFTS_PER_CYCLE` keeps the default cap at 3.

## [0.9.49.0] - 2026-06-12

THIRTY-LOOP S-21 closes orchestrator test gaps around coastal water levels,
NIFC fire footprints, and marine waves, and broadens voice-replay collection
to cover the newest bundle families.

### Changed

- **Add missing runner and voice coverage.** New orchestrator tests exercise
  CO-OPS storm surge, NIFC fire footprint, and Open-Meteo marine-wave success,
  failure, skip where applicable, and dedup paths without live network calls.
  The voice regression replay set now includes precipitation extreme,
  air-quality hazard, dust event, synthesis fire-drought-heat, marine heatwave,
  and wet-bulb extreme fixtures built from realistic production bundle shapes.

## [0.9.48.0] - 2026-06-12

THIRTY-LOOP S-20 adds a dark-shipped concurrent source scheduler so alerts-mode
source fetching can be budgeted, breaker-protected, and eventually run as a DAG
without changing production behavior until Andrew flips the flag.

### Changed

- **Add flagged DAG source scheduling.** `src/orchestrator/scheduler.py` now runs
  synthesis-component writers serially, dispatches the remaining Stage-1 source
  runners through a six-worker pool, records 120-second budget timeouts with
  `error_class="timeout"`, and skips sources whose last three source-health rows
  timed out with a breaker-marked `skipped` row. `src/orchestrator/run_alerts.py`
  preserves the legacy sequential path by default and only enters the scheduler
  when `THEHEAT_CONCURRENT_SOURCES=1`; suppression context is now thread-local
  and triage enqueue is locked for concurrent runner safety.

## [0.9.47.0] - 2026-06-12

THIRTY-LOOP S-19 trims the dashboard state payload and stops hidden browser
tabs from polling continuously.

### Changed

- **Project dashboard state and gate polling.** `/api/dashboard` now returns
  only the state keys the page reads (`last_hot10`, `streaks`, `errors`,
  `daily_tweet_count`, and `run_history`) while preserving full server-side
  state for drafts, suppressions, and source-health derivation. The dashboard
  refresh interval now skips hidden tabs and refreshes immediately when the tab
  becomes visible again.

## [0.9.46.0] - 2026-06-12

THIRTY-LOOP S-18 wires a CI smoke test for the SQLite state backend escape
hatch.

### Changed

- **Exercise SQLite backend selection in CI.** The main bot workflow now runs a
  dedicated `THEHEAT_DB_PATH=/tmp/theheat-smoke.sqlite` smoke test over the
  existing SQLite state suite, and `src/state.py` now resolves
  `THEHEAT_STATE_BACKEND` / `THEHEAT_DB_PATH` at backend-selection time so
  env-driven selection is covered directly.

## [0.9.45.0] - 2026-06-12

THIRTY-LOOP S-17 hardens publish idempotency so an approved draft cannot be
sent to X unless its publish intent is already durable.

### Changed

- **Record publish intent before posting.** Approved draft publishing now writes
  a compact `publish_ledger` row before calling X, aborts when that durable
  pre-post write fails, repairs half-recorded posted drafts from ledger rows
  with `tweet_id`, clears stale two-hour intents, and exposes `tweet_id` in
  dashboard draft payloads. State writes now carry monotonic `_state_rev`
  values and re-merge once against the fresh gist snapshot when a concurrent
  revision is observed before PATCH.

## [0.9.44.0] - 2026-06-12

THIRTY-LOOP S-15 adds compact last-good cache continuity for slow-moving
sources without allowing cached readings to generate story candidates.

### Changed

- **Cache compact slow-mover readings.** `src/data/last_good.py` now stores
  small per-source derived readings under the new `last_good_readings` state
  key, merged by newest `captured_at` and persisted through SQLite metadata.
  CO2, ENSO, sea ice, ice mass, NSIDC Snow Today, climate indices, and ozone
  hole runners write compact successful readings and record cache-served fetch
  failures as `degraded` with `served last-good (<data_date>)` telemetry, while
  `src/two_bot/evidence_contract.py` rejects any bundle facts marked
  `from_cache=True`.

## [0.9.43.0] - 2026-06-12

This sentinel fix treats Copernicus EMS as a known-quiet conditional source so
green no-activation windows do not block the loop as silent zero-yield outages.

### Changed

- **Allow quiet Copernicus EMS windows.** `scripts/source_health_sentinel.py`
  now excludes `copernicus_ems` from yield-watch advisories, matching its
  active-flood activation semantics: a successful poll with no current floods
  legitimately observes zero reportable activations. `tests/test_source_health_sentinel.py`
  covers the quiet-window case alongside the existing yield-watch allowlist
  tests.

## [0.9.42.0] - 2026-06-12

THIRTY-LOOP S-16 adds deterministic state pruning and size warnings so record
stores, tier suppressions, and shipped-tweet memory stop drifting toward the
gist inline-content cliff.

### Changed

- **Prune durable state growth.** `src/state.py` now caps merged
  `memory.shipped_tweets`, prunes dormant snow/precip record stores from
  `finalize_run`, expires old annual-count and ozone peak years, and records a
  dashboard-visible warning when serialized gist state exceeds 800 KB. Bare
  fire/cyclone/flood tier values keep their existing merge semantics while
  `tier_touch_ts` sidecar timestamps provide TTL pruning with first-prune
  migration coverage.

## [0.9.41.0] - 2026-06-12

THIRTY-LOOP S-14 rolls freshness guardrails across the remaining unguarded
source parsers so stale upstream payloads fail loudly instead of recording
silent successes.

### Changed

- **Guard source payload freshness.** `src/data/_freshness.py` now provides
  shared parsing for ISO, RFC, and epoch-based upstream timestamps, and the
  unguarded source parsers now call `assert_freshness` with their planned
  source-specific max ages. Fixture-driven tests cover stale payload failures
  for all 15 rollout sources while keeping valid empty-feed behavior intact.

## [0.9.40.0] - 2026-06-12

THIRTY-LOOP S-13 gives GDACS a verified GeoRSS fallback and records the mirror
survey verdicts for the current official-source cluster.

### Changed

- **Add GDACS GeoRSS fallback and mirror survey.** `src/data/gdacs.py` now falls
  back from the JSON event API to the official GeoRSS feed, preserves normalized
  disaster event fields, and logs when the fallback serves data. The new mirror
  survey documents eight official sources with `CHAIN`, `WITNESS`, or `NONE`
  verdicts for future fallback work.

## [0.9.39.0] - 2026-06-12

THIRTY-LOOP S-12 strengthens the GPM IMERG fetch chain so the datapool path can
fall through to already-built S3 retrieval before the independent OPeNDAP
fallback.

### Changed

- **Chain GPM datapool through S3 and pre-mint credentials.** `src/data/gpm_imerg.py`
  now maps `THEHEAT_GPM_SOURCE=datapool` to `datapool → s3 → opendap`, preserving
  the existing S3-first `s3 → datapool → opendap` path and logging the grid leg
  that served data. `src/orchestrator/sources/gpm_imerg.py` now pre-mints the
  GES DISC S3 credentials when `EARTHDATA_TOKEN` is present, swallowing mint
  failures so the datapool and OPeNDAP paths remain available.

## [0.9.38.0] - 2026-06-12

This incident fix restores clean-main preflight by making the regional SST
anomaly freshness fixture date-stable and keeps healthy quiet SST-anomaly runs
out of the zero-yield sentinel.

### Changed

- **Fix SST anomaly freshness and yield telemetry.** `src/data/ocean_sst_anomaly.py`
  now accepts a test-only `today` seam when asserting gridded-data freshness, so
  fixture-backed tests do not decay as the calendar advances.
  `src/orchestrator/sources/ocean_sst_anomaly.py` now records sampled region
  boxes as the source-health observed count, rather than counting only
  tier-crossing events, so successful below-threshold runs no longer look like
  a silently empty source.

## [0.9.37.0] - 2026-06-11

THIRTY-LOOP S-11 decomposes the orchestration common module into focused helper
modules while preserving the legacy star-import compatibility surface.

### Changed

- **Split common helpers behind a compatibility shim.** `src/orchestrator/common.py`
  now re-exports focused modules for caps, suppression, telemetry, cyclone
  handling, draft deduplication, draft saving, two-bot dispatch, and triage
  queue draining. `src/main.py` now syncs compatibility monkeypatches into the
  split modules, and shim tests lock the legacy `__all__` export set plus moved
  symbol identities.

## [0.9.36.0] - 2026-06-11

THIRTY-LOOP S-10 adds process-lifetime conditional request support for static
feeds that advertise ETag or Last-Modified validators.

### Changed

- **Revalidate static data fetches.** `src/data/_http.py` now exposes
  `fetch_with_cache_revalidation`, serving cached response bodies on upstream
  `304 Not Modified` responses and refreshing cache entries on validator-backed
  `200` responses. `co2`, `enso`, `sea_ice`, and `nsidc_snow` now use the helper
  with per-module process caches, avoiding persistent state or gist payload
  growth while preserving their existing parsing contracts.

## [0.9.35.0] - 2026-06-11

THIRTY-LOOP S-09 hardens transient government-host blocks and brings GPM city
precipitation fetches onto the shared retry path.

### Changed

- **Retry known WAF 403/429 responses and unify GPM retrying.** `src/data/_http.py`
  now retries one 403/429 response for the known WAF-prone hosts with a capped
  process-wide retry budget, while ordinary 4xx failures still fail fast.
  `src/data/gpm_imerg.py` now uses `fetch_with_retry` for per-city OPeNDAP
  requests, preserving auth headers and timeout/backoff settings while gaining
  the shared user-agent and jitter behavior.

## [0.9.34.0] - 2026-06-11

THIRTY-LOOP S-08 routes the remaining safe public data fetchers through the
shared retry helper so transient transport failures get the same pooled,
jittered retry behavior.

### Changed

- **Migrate bare `requests.get` callers.** `co2`, `gdacs`, `nws_alerts`, `enso`,
  `sea_ice`, `water_levels`, `ocean`, `fire_footprint`, `nsidc_snow`, `drought`,
  `open_meteo`, and the `ice_mass` CMR probe now call `fetch_with_retry` with
  their existing timeouts. The only remaining bare gets are explicitly marked
  GHCN 404-probe and GPM retry/status-handling exemptions reserved for later
  THIRTY-LOOP steps.

## [0.9.33.0] - 2026-06-11

THIRTY-LOOP S-07 makes the shared HTTP retry helper less bursty and cheaper to
reuse across the data fetchers that depend on it.

### Changed

- **Add retry jitter and pooled sessions.** `src/data/_http.py` now lazily creates
  one shared `requests.Session` with an 8-connection pool for both HTTP and HTTPS,
  and `fetch_with_retry` uses that session while preserving its public signature.
  Retry backoff now adds bounded jitter on top of the exponential base, with
  `tests/test_http_retry.py` pinning both the jitter range and session reuse.

## [0.9.32.0] - 2026-06-11

THIRTY-LOOP S-06 adds an advisory yield watch so sources that stay green while
returning zero observations no longer disappear into a healthy-looking dashboard.

### Changed

- **Add zero-yield sentinel digest.** `scripts/source_health_sentinel.py` now
  detects non-allowlisted sources with at least 10 retained success runs and zero
  observed records, then maintains a single marked `Yield watch: sources succeeding
  with zero observations` issue labeled `unknown`. The advisory creates, updates,
  removes stale cause labels, and closes through the same sentinel lifecycle without
  changing dashboard classifier output.

## [0.9.31.0] - 2026-06-11

THIRTY-LOOP S-05 adds durable failure-shape telemetry and liveness alarms so
transport failures and a stalled alerts lane are visible instead of being hidden
by unrelated successful hourly runs.

### Changed

- **Record error classes and alert on stale lanes.** `src/data/error_class.py`
  introduces the source-health taxonomy, `_record_source_run` now records it into
  rolling source-health run rows, and `_rebuild_source_health` preserves the field
  without adding state keys or changing merge semantics. `scripts/source_health_sentinel.py`
  now adds a synthetic `_pipeline_liveness` failure when no alerts/both run is fresh
  within six hours, the sentinel workflow runs hourly, and the bot workflow opens a
  sentinel issue if a scheduled run itself fails.

## [0.9.30.0] - 2026-06-11

THIRTY-LOOP S-04 keeps the source-health sentinel and dashboard in sync when
Earthdata returns credential-shaped 403 failures.

### Changed

- **Classify Earthdata 403s as ours.** `scripts/source_health_sentinel.py` and
  `dashboard/lib/source-health.js` now apply the same pre-upstream override for
  403 errors mentioning Earthdata, URS, EDL, or PO.DAAC, so expired credential
  failures open/red-render as our bug while generic government 403s remain external.
  Both Python and dashboard tests pin the mirrored fixture strings.

## [0.9.29.0] - 2026-06-11

THIRTY-LOOP S-03 makes the dashboard’s operational truth match the underlying bot state
so stale or failed state reads no longer look healthy.

### Changed

- **Show truthful dashboard state age and counts.** `dashboard/app/page.js` now reads
  today’s tweet count by UTC date key, surfaces `stateError` as an alert banner, shows
  bot data age alongside fetch age, flags Hot 10 snapshots older than 24 hours, removes
  the dead raw `bundles` funnel row, and marks draft action feedback as an alert.
  `dashboard/lib/format.js` adds tested helpers for UTC daily counts and Hot 10 staleness.

## [0.9.28.0] - 2026-06-11

THIRTY-LOOP S-02 aligns local test defaults, cold-start docs, pipeline glossary,
critic workflow configuration, and refresh-thresholds action versions with the
current two-bot production path.

### Changed

- **Sync local pytest, docs, and workflow plumbing.** `pyproject.toml` now excludes
  `voice_replay` tests by default while keeping the voice-regression collection path
  available. `README.md` documents quickstart, workflows, state backend, and standing
  rails; `PIPELINE.md` now describes the Sonnet writer, safety, Gemini fact-check, and
  Gemini Pro critic chain with the live 24-source count. `.github/workflows/bot.yml`
  passes `THEHEAT_CRITIC_ENABLED`, and `.github/workflows/refresh-thresholds.yml`
  uses checkout/setup-python v6.

## [0.9.27.0] - 2026-06-11

THIRTY-LOOP S-01 moves draft accounting to the triage drain so saved-count telemetry
matches drafts that actually reached the review queue.

### Changed

- **Use drain-only drafted accounting.** `src/orchestrator/run_alerts.py` now treats
  source runners as side-effect-only and sets the final saved count from
  `_drain_and_write_triage_queue`. The source runners in `src/orchestrator/sources/`
  and the cyclone helper in `src/orchestrator/common.py` return `None` and write
  `drafted=0` pre-drain telemetry, while the drain increments the originating source
  after a saved draft.

## [0.9.26.0] - 2026-06-11

### Fixed

- **.gitignore quoted patterns never matched** (landed in #220; this entry reconciles
  VERSION/CHANGELOG, which #220's broken command chain skipped). gitignore treats quotes
  as literal characters, so the iCloud-duplicate patterns (`*" 2.js"` etc.) and the
  brand-zip entry silently matched nothing. All rewritten unquoted; verified with
  `git check-ignore` for both pattern classes.

## [0.9.25.0] - 2026-06-11

Session sweep: the 2026-06-10 audit is committed, THIRTY-LOOP execution is delegated to
Codex CLI (Anthropic-token-free), and the canonical handoff moves to 2026-06-11.

### Added

- **docs/audits/2026-06-10-thirty-improvements-and-outage-plan.md.** The full audit: 30
  ranked improvements, the 5-phase source-outage resilience plan (Codex-hardened, 11
  findings incorporated), the item-to-phase crosswalk, and the production evidence
  (outage shapes, editorial funnel).
- **docs/superpowers/plans/2026-06-11-thirty-loop-CODEX-KICKOFF.md.** Launch
  instructions plus the verbatim executor prompt adapting THIRTY-LOOP for OpenAI Codex:
  skill-reference translations, self-review substitution for the [CODEX] gates,
  environment facts, absolute prohibitions, per-iteration discipline.
- **docs/handoffs/2026-06-11.md.** Canonical handoff superseding 2026-06-09-v4; next
  Claude sessions triage the loop's BLOCKED/AWAITING-ANDREW rows instead of re-planning.
- **handoff/ (brand handoff package).** Brand Book, Operator Dashboard, Usage Guide
  HTML + png/svg assets, now versioned; the redundant .zip archive and iCloud
  '" 2.css"' duplicates are gitignored.

## [0.9.24.0] - 2026-06-11

THIRTY-LOOP: an autonomous execution plan covering all 30 improvements from the
2026-06-10 full-codebase audit, written for a budget-constrained executor model to run
as a serial PR loop with no human input except explicitly marked STOPs.

### Added

- **docs/superpowers/plans/2026-06-11-thirty-loop.md.** 35 dependency-ordered steps
  (S-01..S-35) with per-step specs, named tests, verification gates, traps, and verified
  code anchors as of 0.9.23.0; production rails, shipping mechanics, Codex outside-voice
  protocol, failure/escalation rules, a pre-made-decisions register (follower-visible
  behavior ships dark behind default-off flags; reganom flip and all flag flips remain
  Andrew's), and a facts file transferring this session's verified codebase map.
  Hardened by a Codex cross-model review (8 findings, 6 P0s — queue-order deadlock,
  forbidden-file trap, false fetch inventory, nonexistent module path, two missing-file
  specs — all fixed).
- **docs/superpowers/plans/2026-06-11-thirty-loop-PROGRESS.md.** The loop's only state:
  per-step status table each PR updates in-place, plus a session log.

## [0.9.23.0] - 2026-06-10

Dashboard CSS extraction (backlog bet #6, step 1): the ~640-line `<style jsx global>`
block and the SourcesView scoped `<style jsx>` block move out of
`dashboard/app/page.js` into a dedicated stylesheet. No logic or markup changes —
`page.js` drops from 2,499 to 1,803 lines and the CSS now ships as a cacheable static
asset instead of riding inside the JS bundle.

### Changed

- **Extract inline styled-jsx into `dashboard/app/dashboard.css`.** The former scoped
  SourcesView rules are re-scoped as `.source-health-table` descendant selectors
  (replacing the styled-jsx hash class) and kept above the global section so the
  original cascade — including the global `.source-row:last-child` / `:first-child`
  overrides — is preserved. `dashboard.css` is imported by `app/page.js` only, so no
  styles leak into `/health` (routes link via full-reload `<a>` navigation).

## [0.9.22.0] - 2026-06-09

State-merge architecture: replace the 314-line imperative `_merge_state` with a
declarative `MERGE_SPEC` table plus a 6-line driver. Retires the "added a state key but
forgot the merge handler" bug class that silently reset `air_quality_*_tiers`
([#194](https://github.com/andrewzp/theheat/pull/194)) and `data_source_failures` to
`{}` on every write. Behavior-preserving — byte-identical to the old merge across the
live 1.06 MB production state and the full edge-case suite.

### Changed

- **Declarative `MERGE_SPEC` replaces hand-rolled `_merge_state` ([#215](https://github.com/andrewzp/theheat/pull/215)).**
  Each of the 54 `DEFAULT_STATE` keys maps to one of 6 reusable strategies
  (`take_incoming`, `max_by_key`, `reduce_by_key`, `dict_overlay`, `ordered_unique`,
  `custom`) or a named helper; a 6-line driver merges by iterating the table. Net −116
  lines in `state.py`; the 15 existing custom mergers are reused unchanged.
- **The merge contract is now structural.** The probe-based "is every key handled?" test
  is replaced by `assert set(MERGE_SPEC) == set(DEFAULT_STATE)` — total coverage by
  construction, so a newly added `DEFAULT_STATE` key with no strategy fails at test
  collection instead of silently resetting in production.

### Verified

- **Cross-model adversarial review (Codex) before implementation** caught a valid-data
  bug in the first design (a legitimate tier `0` collapsing to the `-1` floor) and
  tightened the equivalence contract; both resolved before any code landed. Five
  regression tests now lock the findings.
- **Codex review of the implementation diff** then drove two hardenings: the
  `max_by_key`/`reduce_by_key` outputs now iterate `sorted()` keys (deterministic merged
  state, no longer hash-seed-dependent), and the dev-time equivalence harness is now a
  committed golden fixture (`tests/fixtures/merge_state_golden.json`, regenerated by
  `scripts/gen_merge_golden.py`) so wrong-strategy/floor wiring is caught in CI.
- **Golden-master equivalence:** new vs. pre-refactor `_merge_state` produce
  value-identical output across the real production state ⊗ itself/default/empty and 21
  synthetic edge pairs.
- mypy clean (97 files); **1631 tests pass** (incl. the new structural contract + golden).

## [0.9.21.0] - 2026-06-09

Source-health correctness: a real false-alarm fix. The daily sentinel filed
`air_quality` as a failing source ([#201](https://github.com/andrewzp/theheat/issues/201),
"last success: never", 0% rate) while it was actually working — observing 588/638
cities and promoting candidates every run. Two layers fixed it; the second
generalizes to every source.

### Fixed

- **air_quality recovers rate-limited cities + stops the false alarm ([#212](https://github.com/andrewzp/theheat/pull/212)).**
  Open-Meteo's free tier weights multi-city calls heavily and 429s the tail of the
  638-city / 13-chunk sweep (~12 chunks/min budget, no `Retry-After`).
  `fetch_with_retry` doesn't retry 429, so ~50 cities (incl. Furnace Creek / Death
  Valley) dropped every run. Now failed chunks are retried up to `RECOVERY_PASSES`
  (2) times, waiting out the per-minute window (derived from the server `Date`
  header). Wire-verified in prod: 638/638 coverage in ~53s. The runner also reports
  `success` at ≥`AQ_MIN_COVERAGE` (90%) coverage rather than `degraded` on any
  single city loss — 92%+ coverage with promoted candidates IS a successful run.
- **Sentinel: a consistently-degraded source is degraded, not failing ([#213](https://github.com/andrewzp/theheat/pull/213)).**
  `classify_source` computed `failing` (the issue-filing trigger) from clean-success
  rate alone, so a source that runs `degraded` every cycle — no hard failures, just
  partial data — read as 0% success and tripped a false `failing` issue. The
  dashboard's `classifyHealth` already gated `unhealthy` on hard failures, so the two
  had DIVERGED. Now `failing` requires a hard failure (`failed > 0`) AND a low recent
  success rate, mirroring the JS. Strictly a false-alarm reducer: it can only move a
  source `failing → degraded`, never the reverse. Retires the bug class for every
  source, not just air_quality.

### Notes

- Both source-health issues closed: #201 (air_quality — our fix) and #202
  (gpm_imerg — NASA genuinely recovered, 3 consecutive successes). Zero open
  source-health issues; sentinel reads 0 failing / 4 degraded / 31 healthy-idle.
- air_quality "promoted but not drafted" is working as designed — its model-estimate
  PM2.5/dust candidates compete in triage and lose to hard extreme-temp/disaster
  events under `MAX_DRAFTS_PER_CYCLE = 3` + the critic. Not a bug.
- mypy clean (97 source files); pytest 1626 passed / 25 voice-replay deselected;
  dashboard 49 JS tests pass; ruff clean.

## [0.9.20.0] - 2026-06-09

Post-Part-B hardening, performance, and a tech-stack review. The @extremetemps
lane is complete (Part B landed in 0.9.19.0); this rolls up the state-correctness
fixes, the gist/CI wins from the review, and a dead-code deletion.

### Fixed

- **State-merge correctness — three silent state-loss bugs.** `_merge_state`
  rebuilds from `_fresh_state()` defaults and sets each key explicitly, so any
  `DEFAULT_STATE` key without an explicit handler was silently reset to default on
  every gist+sqlite write. Fixed: **air-quality tier dedup** keys
  (`air_quality_pm25_tiers`/`_dust_tiers`) — the bigger bug was the missing
  `_merge_state` handler, not just the sqlite allowlist ([#204](https://github.com/andrewzp/theheat/pull/204)) — and **`data_source_failures`**, the consecutive-failure
  counter, merged with reset-aware semantics (a success-reset wins; max otherwise)
  rather than a plain max() that would erase resets and pin the structural-alert
  streak high ([#206](https://github.com/andrewzp/theheat/pull/206)). Earlier:
  **SST anomaly dedup keys** added to the sqlite allowlist ([#200](https://github.com/andrewzp/theheat/pull/200)).
- **Cycle-cap callback ordering ([#204](https://github.com/andrewzp/theheat/pull/204)).**
  A draft pruned by `MAX_DRAFTS_PER_CYCLE` could still consume dedup/cap state
  (annual counts, tiers) for a tweet that never queued. `on_draft_success` now
  defers past the prune and fires only for survivors.

### Added

- **`_merge_state` contract test ([#206](https://github.com/andrewzp/theheat/pull/206)).**
  Probes every `DEFAULT_STATE` key and fails if any silently resets to default, so
  the "added a key but forgot the merge handler" bug class can't recur.
  Self-validating (the custom-helper allowlist is coupled to a preservation
  fixture).
- **Part-B activation passthrough ([#205](https://github.com/andrewzp/theheat/pull/205)).**
  `THEHEAT_REGANOM_ENABLED` in `bot.yml` (default `'0'`, dormant). reganom is
  landed + `manual_only` but stays OFF until the repo variable is set to `1`.

### Performance / CI

- **Gist state written minified, not `indent=2` ([#208](https://github.com/andrewzp/theheat/pull/208)).**
  −621 KB / −39% on the live state (1606 → 985 KB). On 2026-05-13 the state hit
  928 KB and crossed the Gist ~900 KB inline-content truncation cliff, failing 3
  runs; this buys back the entire whitespace margin. Reads handle either format.
- **Test suite 26s → 4s ([#209](https://github.com/andrewzp/theheat/pull/209)).**
  An autouse fixture no-ops `fetch_with_retry`'s backoff (retry behavior is still
  asserted via call counts). Also: `timeout-minutes` on all 5 workflow jobs so a
  hung LLM/socket fails fast instead of burning the 6h runner budget.

### Removed

- **Dead `claim_extractor` LLM stage ([#210](https://github.com/andrewzp/theheat/pull/210)).**
  −240 lines. The module + prompt were fully wired but unreachable (fact-check does
  extraction inline); the only `src/` reference was a stale kill-stage comment.

### Notes

- A super-detailed tech-stack review ran this session (≈9.8/10 hygiene). The
  architectural backlog (declarative `MERGE_SPEC`, `common.py` decomposition,
  record-store caps, SQLite-backend fate, `requests.Session`, the source-runner
  abstraction) is in the canonical handoff.
- mypy clean (97 source files); pytest 1617 passed / 25 voice-replay deselected;
  ruff clean; suite ~4s.

## [0.9.19.0] - 2026-06-09

@extremetemps lane — Part B (reanalysis regional anomaly). Adds the final lane
signal, `manual_only` and env-gated OFF. **The @extremetemps build lane is now
complete.**

### Added

- **Reanalysis regional anomaly** (`regional_anomaly`) — detects when a
  climatically-coherent region's sampled cities run far above their 1991–2020
  daily ERA5 normal for ≥3 consecutive *complete* days. A POINT INDEX over N
  sampled cities (never an area-weighted national mean), computed from the
  Open-Meteo ERA5 archive against a checked-in daily climatology cache
  (`data/climatology_daily_cache.json`). Curated `REGION_WATCHLIST` of 16
  cross-hemisphere regions / 100 sample points (Sahel, Pacific Northwest, East
  Siberia, Indo-Gangetic Plain, Iberia, Central Mediterranean, Southeast
  Australia, Southern South America…), each anchored to a documented,
  attribution-studied heat event. Standalone runner (gpm_imerg pattern),
  env-gated OFF via `THEHEAT_REGANOM_ENABLED`, `manual_only` at launch.
- **Trigger (§B):** fires only when the point-mean anomaly ≥ +6 °C **and** the
  mean z-score ≥ 2σ (per-MM-DD sigma from the cache) **and** ≥50 % of the
  region's points individually exceed +6 °C — so a flat +6 °C means the same
  thing in the low-variance Sahel and high-variance midlatitudes, and one
  scorching city can't drag the regional mean over the line.
- **Honesty defense (5 layers):** bundle framing (`where` = "N sampled cities in
  X" + `forbidden_claims`), writer-prompt rules, fact-check guards, a
  deterministic bundle-aware §F gate (load-bearing, runs before fact-check), and
  a bundle-blind safety-regex backstop. The signal is never framed as a
  whole-region or national mean.
- **`scripts/build_climatology_cache.py`** — one-time ERA5 daily-climatology
  backfill (1991–2020 mean + σ per sample point), 429-aware patient backoff,
  atomic per-point checkpoint, idempotent resume.

### Notes

- Built directly on Claude-main (Conductor unavailable). Honored the plan's
  Rev-3 deltas §A–§G; a 6-dimension multi-agent adversarial review substituted
  for the unavailable cross-model Codex pass.
- The climatology backfill requests `temperature_2m_max` only — this halves
  Open-Meteo's weighted per-request cost (the free archive's rate limit is the
  binding constraint on a 100-point backfill). `mean_min_c` (reserved for the
  *deferred* cold-anomaly feature, unused in v1) is therefore null for points
  backfilled this way; re-backfill with `_min` if/when cold-anomaly lands.
- Landing is zero-change-on-land: the runner returns 0 until an operator sets
  `THEHEAT_REGANOM_ENABLED=1` (after verifying the committed cache). mypy clean,
  full pytest suite green, CI green.

## [0.9.18.0] - 2026-06-08

@extremetemps lane — Wave 2 (SST). Adds the regional SST anomaly signal,
`manual_only`. This completes the build lane (Part B reanalysis is build-LAST,
not yet built).

### Added

- **Regional SST anomaly** (`regional_sst_anomaly`) — per-basin sea-surface-
  temperature anomaly across 13 global marquee basins (N Atlantic, NE Pacific
  "Blob", Mediterranean, Tasman, GBR, Coral Triangle, Niño-3.4…) via NOAA Coral
  Reef Watch's gridded 5 km published anomaly through NOAA CoastWatch ERDDAP (no
  auth). cos-latitude area-weighted basin mean; tiered absolute anomaly
  +2.5/+3.5/+4.5°C (NOT Hobday). Distinct from the existing global-mean
  marine-heatwave streak signal.

### Notes

- Built in a Conductor worktree (PR #198), branched from post-Wave-1 main → no
  registry conflict. Pre-merge reviewed (0 blockers): `_merge_state` persistence
  of both new state keys, lag-aware year keying, per-region degradation,
  fill/valid-range filtering, dateline fail-fast, and min-valid-cell coverage all
  verified. mypy clean (98 source files), pytest 1531 passed / 22 voice-replay
  deselected, CI green.
- Calibration: 0/13 basins fire in June (highest Med +1.97°C) — correct seasonal
  behavior (SST is a NH-late-summer signal). Box-tightening (basin-wide boxes
  dilute localized events) is a documented post-summer fast-follow.

## [0.9.17.0] - 2026-06-08

@extremetemps coverage lane — Wave 1. Three new editorial signal areas ship, all
`manual_only` (queued for human review; nothing auto-posts).

### Added

- **Absolute-extreme** (`absolute_extreme`) — latitude-banded absolute temperature
  extremes (e.g. ~50°C in the tropics, ~30°C above the Arctic Circle), riding the
  existing extreme-signal fetch (no new data). Works on both the Open-Meteo
  forecast and the GHCN observed paths.
- **Wet-bulb extreme** (`wet_bulb_extreme`) — heat-stress lethality via Open-Meteo
  daily `wet_bulb_temperature_2m_max`, wired into the existing forecast + archive
  requests (no new HTTP calls). Tiers ≥33°C / ≥35°C; framed as forecast-model
  values, never as an observed "survivability limit."
- **Air quality** (`air_quality_hazard` + `dust_event`) — NEW CAMS-backed source
  (Open-Meteo Air Quality API, no key). Hazardous PM2.5 (24h-mean tiers
  150/250/350 µg/m³, framed against the WHO 15 µg/m³ guideline) + major dust
  events (daily-max tiers 500/2000/5000 µg/m³). Batched (~13 calls for 638 cities).

### Notes

- Built in parallel Conductor worktrees (PRs #195, #194), each pre-merge reviewed
  (0 blockers) against its plan's gates; #194's registry conflict resolved by
  keeping both lanes' entries (fact-check labels sequenced g→h→i).
- Part B (`reanalysis_anomaly`) plan hardened to **Revision 3** (#196): a 4-agent
  hardening pass + a Codex cross-model outside-voice review folded 4 verified P0s;
  decisions made (curated REGION_WATCHLIST + σ floor). Build-LAST, not yet built.
- SST regional anomaly (gridded NOAA Coral Reef Watch) is Wave 2, in flight.
- Verification: mypy clean (97 source files), pytest 1495 passed / 22 voice-replay
  deselected, dashboard 48/48, CI green on all merges.

## [0.9.16.1] - 2026-06-08

Review follow-up release. No editorial behavior change; this tightens the
source-health reconciliation loop and the new GPM grid fallback path, and brings
the current-state docs up to the 0.9.16.x reality.

### Fixed

- **Source-health sentinel issues now stay current.** Creates and updates carry
  the sentinel label plus the current cause label (`ours`, `external`, or
  `unknown`), and existing open issues are edited when the generated body or
  cause label changes. Recovered issues still auto-close as before.
- **Dashboard source-health recovery classification matches the sentinel.** If a
  durable source has a recent active window and every recent attempt succeeded,
  it is `healthy` even when the older 7-day cumulative counters still contain an
  old degraded/failed row.
- **`THEHEAT_GPM_SOURCE=s3` falls back to `datapool` before OPeNDAP.** S3 and
  datapool are distinct alternate hosts; an S3/STS/GetObject failure should not
  skip the simpler authenticated HTTPS grid fetch.

### Notes

- +3 regression tests: sentinel issue label/body reconciliation, durable
  source-health recovery, and s3 -> datapool -> opendap fallback ordering.
- Verification: pytest 1418 passed / 22 voice-replay deselected, dashboard 48/48,
  ruff targeted clean, mypy clean across 92 source files, `git diff --check` clean.

## [0.9.16.0] - 2026-06-08

The pending-queue TTL is now **per signal type**. A flat 7-day TTL was discarding
still-valid coral/DHW drafts — a bleaching event stays editorially current for
*weeks*, but the queue swept its drafts at 7 days (it lost 3 good coral drafts
while the grading routine was down in May). Slow continuous signals now get a
longer window; fast point-in-time records keep the short one.

### Changed

- **`apply_pending_ttl_sweep` computes the TTL per draft `type`.** Slow continuous
  signals (`SLOW_PENDING_TYPES` = `coral_bleaching`) use
  `PENDING_TTL_DAYS_SLOW_DEFAULT` (21d, env `THEHEAT_PENDING_TTL_DAYS_SLOW`); every
  other type keeps the 7-day default (env `THEHEAT_PENDING_TTL_DAYS`). Posting a
  day's temperature record weeks late would falsely imply recency, so fast signals
  stay short — but a coral bleaching alert is current for the duration of the
  heat-stress event, so its drafts shouldn't be swept at 7 days. The per-type
  pending cap still bounds the queue, so the longer window can't reintroduce a
  monoculture pile-up.

### Notes

- **Behavior change:** coral drafts now survive 21 days in pending (was 7). Tune
  the window with `gh variable set THEHEAT_PENDING_TTL_DAYS_SLOW --body N --repo andrewzp/theheat`
  (no deploy). Surfaced by the daily grading routine, which flagged that the 7-day
  sweep had discarded 3 good A- coral drafts during the May routine outage.
- +2 tests (per-type slow TTL + slow-TTL env override). pytest 1415 pass.

## [0.9.15.0] - 2026-06-06

gpm IMERG can now fetch the daily grid in **one request** off a different host,
escaping the gpm1.gesdisc OPeNDAP overload that was burning ~28-min ConnectTimeout
runs. Built behind `THEHEAT_GPM_SOURCE` and **defaulting to the existing `opendap`
path — zero behavior change until the operator flips the var.** On any failure the
new paths fall back to opendap, so gpm is never worse than before.

### Added

- **`THEHEAT_GPM_SOURCE` fetch dispatch** in `src/data/gpm_imerg.py`:
  `opendap` (legacy per-city subsets, default) | `datapool` (one authenticated
  HTTPS GET of the daily `.nc4` from `data.gesdisc.earthdata.nasa.gov`) | `s3`
  (direct `GetObject` from `gesdisc-cumulus-prod-protected`, us-west-2). The grid
  paths download the daily file once and subset every city locally with the
  existing `_lon_index`/`_lat_index` math — one request per run instead of 75 —
  then fall back to opendap on any failure.
- **`src/data/_s3credentials.py`** — mints + caches (55-min TTL) temporary AWS
  STS credentials from the Earthdata bearer token via the GES DISC
  `/s3credentials` endpoint.
- `boto3` + `h5py` dependencies (lazy-imported; only the grid paths load them, so
  the default opendap path and module import gain no new requirement).
- 21 tests: synthetic-HDF5 subset extraction, fill-value skips, `Grid`-group
  fallback, shape guard, date walk-back, datapool/s3 fetch + error mapping,
  source dispatch, and the s3 → opendap fallback.

### Notes

- **Default is `opendap`** — merging changes nothing in production. Activate with
  `gh variable set THEHEAT_GPM_SOURCE --body datapool --repo andrewzp/theheat`
  (or `s3`) and watch the next cron; the sentinel + dashboard already track gpm
  honestly. Flip back to revert instantly, no code push.
- O1/O2/O3 (s3credentials endpoint + bearer auth, exact S3 key + `.nc4` format,
  freshness) were resolved against NASA's CMR granule API, not guessed. The S3
  temp role has **no `s3:ListBucket`**, so keys are constructed (sharing the
  OPeNDAP filename builder) and probed by GetObject, treating 403/404 as "not
  published".
- The live S3/datapool round-trip is **not locally testable** (needs
  `EARTHDATA_TOKEN`); first real verification is the operator flip + cron run.
  Discovery worth noting: the data-pool host differs from the overloaded
  gpm1.gesdisc OPeNDAP host, so **`datapool` escapes the overload with no
  AWS/boto3/STS/egress** — likely the simpler robust fix; try it before `s3`.

## [0.9.14.0] - 2026-06-06

Dashboard tells the truth now — it matches the sentinel instead of contradicting
it. Most red/yellow on the source-health panel was upstream NASA/gov flakiness,
shown the same as a real bug; and idle low-cadence sources showed red on
days-old attempts. Both fixed.

### Added

- Dashboard **`external` (amber) health tier.** Sources failing because of
  NASA/gov (5xx, timeouts, connection errors, 403/429 rate-limits) render as
  "external" — not the red/yellow of a real defect — via a `classifyError` port
  of the sentinel's classifier. The Source Health header now shows an
  "N external (NASA/gov)" tally, and `stats.external_count` is exposed.

### Changed

- `dashboard/lib/source-health.js`: classification now matches
  `scripts/source_health_sentinel.py`. Recency is judged over the recent **run**
  window (skips included) — a source whose recent runs are all cadence skips is
  `idle` (not attempting → not failing), instead of being judged red on stale
  attempts from days ago. A recovering source (recent window all clean) reads
  `healthy`, not stuck-degraded. `degraded` status runs still classify as
  `degraded` (partial success, not a hard failure). Sort order and tab badges
  treat `external` as non-alarming.

### Notes

- The live panel that showed "2 unhealthy, 7 degraded" now reads ~0 unhealthy:
  ice_mass → idle (has its data, PO.DAAC recovered), the 403/timeout sources →
  external (amber, NASA/gov), gpm visible as external with its low % showing it's
  the one struggling. Dashboard tests 46 → 47.

## [0.9.13.1] - 2026-06-06

Sentinel: idle low-cadence sources are no longer flagged as failing on stale
attempts. The 0.9.13.0 classifier stripped cadence skips from the *entire* run
history and judged a source on its last N *actual* attempts — so a weekly source
(ice_mass, Mondays only) that succeeded, then had a redundant same-day fetch hit
a transient 502, kept showing `failing` for days while it sat idle and the cause
had long cleared (live issues #180/#181).

### Fixed

- `scripts/source_health_sentinel.py`: `classify_source` now judges the recent
  **run** window (skips included), not all-time active attempts. If the recent
  window is all cadence skips, the source is `idle` (not attempting → not
  currently failing); a recent *active* attempt that failed still classifies as
  `failing`. Daily sources are unaffected (they never have all-skip windows);
  only idle low-cadence sources stop being false-flagged. +2 tests.

### Notes

- Resolves the open ice_mass issues: confirmed PO.DAAC recovered (granule URL
  returns 303, not 502) and ice_mass holds its 06-01 monthly value, so it's idle,
  not broken. gpm_imerg's issue already auto-closed when it recovered (80% recent
  success) — the open/close loop working end-to-end.

## [0.9.13.0] - 2026-06-04

Sentinel rebuilt around the right principle: **every failure is our problem.** A
failing source is a gap in the product (a tweet we can't make), so it gets a
tracked issue — full stop. The earlier "is it upstream NASA? then stay silent /
wait N days" gate was wrong: if NASA goes dark, that IS our problem (find an
alternate feed, switch product, escalate), not something to ignore. The
upstream/ours classification now survives only as a **label** on the issue that
points at the right fix.

### Changed

- `scripts/source_health_sentinel.py`: a source is `failing` (→ issue) whenever
  it's broken right now — recent active success rate below 50%, regardless of
  cause or how long it's been down. No grace period. Each issue is labeled
  `ours` (patch our code/credential/endpoint) or `external` (NASA/gov down —
  confirm, then switch product/endpoint or find an alternate feed). A single
  transient blip (still mostly succeeding) does not open an issue; a degraded
  source (succeeding the majority of the time) doesn't either.
- **Per-source issues that auto-close.** New pure `plan_issue_actions()`
  reconciles the failing set against open sentinel issues: open one issue per
  newly-failing source (`Source down: <name>`, assigned), and **close the issue
  of any source that has recovered**. `main()` executes the plan via `gh` (live
  in CI, dry-run locally unless `--apply`). The open-issues list is now a
  self-maintaining view of what's broken.
- `.github/workflows/source-health-sentinel.yml`: runs every 4h (`30 */4 * * *`,
  after each bot cycle) so failures surface within ~4h and recoveries close
  within ~4h. Idempotent reconciliation means frequent runs never spam. Removed
  the `SENTINEL_OUTAGE_DAYS` grace knob (no grace anymore).

### Notes

- On live data: gpm_imerg + ice_mass antarctica/greenland (all `external`, NASA
  down) each get an issue immediately — exactly the visibility the grace-period
  versions were suppressing.

## [0.9.12.3] - 2026-06-04

Sentinel: sustained outages now escalate, fixing the 0.9.12.1 overcorrection.
0.9.12.0 escalated any 10-consecutive-failure source (false-flagged gpm on a
transient 503 stretch); 0.9.12.1 swung the other way and made hard-upstream
errors NEVER escalate — so a source dark for a week on 503s would have stayed
silent forever. Both were wrong. A *transient* upstream outage self-heals
(silent); one that lasts a *significant length of time* is no longer safely
"just NASA" — a moved/decommissioned endpoint or a persistently rejected request
that needs a look.

### Changed

- `scripts/source_health_sentinel.py`: the long-outage escalation is now keyed
  on **wall-clock days since last success** (`last_success_ts`), not a raw
  consecutive-failure count — which was a terrible proxy because cadence varies
  (10 failures ≈ 1.5 days for gpm but ≈ 10 weeks for weekly ice_mass). A
  currently-failing source escalates when the error is ours OR it has been dark
  ≥ `OUTAGE_DAYS` (default 3, tunable via the `SENTINEL_OUTAGE_DAYS` repo var) —
  regardless of whether the error is hard or soft upstream. A source that has
  never once succeeded and is failing also escalates. Removed the hard/soft
  distinction (the duration threshold replaces it). Test suite rewritten around
  the timestamp model (17 tests).
- `.github/workflows/source-health-sentinel.yml`: passes `SENTINEL_OUTAGE_DAYS`
  from a repo variable so the threshold is tunable without a code push.

### Notes

- On live data: gpm_imerg (dark 2.0 days) stays silent; ice_mass
  antarctica/greenland (dark 3.6 days on PO.DAAC 502s) now escalate — exactly
  the sustained-outage signal that 0.9.12.1 was suppressing.

## [0.9.12.2] - 2026-06-04

### Fixed

- Dashboard: the `@theheat control panel` wordmark is now a home control —
  clicking it (or Enter/Space when focused) returns to the Dashboard tab and
  scrolls to top, the way a logo is expected to behave. Previously it was inert
  text. Adds pointer cursor, hover, and a keyboard focus ring.

## [0.9.12.1] - 2026-06-04

Sentinel false-positive fix, caught on its own first live run. The 0.9.12.0
long-outage rule escalated *any* source dark for ≥10 consecutive attempts —
including gpm_imerg, which had hit 10 straight `HTTP 503`s from NASA GES DISC. A
sustained server outage is still upstream, not a moved endpoint, so the sentinel
cried wolf about the exact thing it exists to suppress (issue #174).

### Fixed

- `scripts/source_health_sentinel.py`: the long-outage escalation now applies
  only to **soft** upstream errors (403/429 rate-limits — a persistent one can
  signal a real access change). **Hard** upstream errors (5xx, read/connect
  timeouts, connection/network failures) never escalate on duration: NASA can be
  down for days and it is still not ours to fix. New `_is_hard_upstream()` +
  regression test covering sustained 503 / 502 / ReadTimeout. Re-verified on the
  live state that triggered #174: 0 our_bug, 3 upstream (silent).

## [0.9.12.0] - 2026-06-04

Daily source-health sentinel — stop hand-triaging the dashboard. Most red on the
source-health panel is upstream NASA/gov flakiness (GES DISC ReadTimeouts,
PO.DAAC 502s, gov 403 rate-limits) that self-heals; a few failures would be ours
to fix (a code error, an expired credential, a moved endpoint). The dashboard
renders both the same, so every NASA hiccup looked like an emergency. The
sentinel does that triage automatically and only escalates the real ones.

### Added

- `scripts/source_health_sentinel.py`: deterministic classifier over the gist
  `source_health`. Per source it decides healthy / degraded / idle / **upstream**
  (external, self-heals → silent) / **our_bug** (escalate). `our_bug` covers code
  exceptions, auth/token (401, `EARTHDATA_TOKEN`), moved endpoints (sustained
  404/410), an unrecognized error, or any source dark for ≥10 consecutive active
  attempts (a "transient" outage that long is probably a real endpoint/credential
  change). Cadence skips never consume the window or trip an alarm.
- `.github/workflows/source-health-sentinel.yml`: daily 13:00 UTC cron (after the
  12:00 bot run). Fetches the gist, classifies, and **stays silent on
  upstream-only days**. On a real `our_bug` it opens or updates one rolling
  GitHub issue (label `source-health-sentinel`) with the diagnosis and assigns
  the operator. Stdlib-only — no pip install, near-zero cost.
- `tests/test_source_health_sentinel.py`: 14 tests, including the production
  snapshot (gpm ReadTimeout + ice_mass 502 + gov 403s → silent day) and a
  synthetic `KeyError`/`401` that must escalate.

### Notes

- Verified against today's live `state.json`: 33 sources → 0 our_bug, 3 upstream
  (gpm_imerg, ice_mass_antarctica, ice_mass_greenland), 30 healthy. Correctly a
  silent day.
- The auto-fix→PR step (an LLM diagnosing and fixing the flagged bug in CI) is a
  follow-on; this ships the detection + triage + escalation, which is what gets
  the operator out of the monitoring loop. The complementary dashboard "external"
  (amber) tier for upstream failures is a separate fast-follow.

## [0.9.11.2] - 2026-06-04

Review follow-up hardening from the 2026-06-02 source/dash/triage sweep. The
prior fixes were directionally right, but three edge paths still violated their
operator contract: triage-off still ran the TTL rejection side effect, GPM
walk-back exhaustion could return an unprobed date, and documented repo-variable
knobs were not exported into the GitHub Actions process.

### Fixed

- `src/orchestrator/common.py`: pending-draft TTL sweep now respects
  `THEHEAT_TRIAGE_ENABLED`. When triage is disabled, the drain path is true
  legacy passthrough again: no ranking, no pending-type cap, and no TTL
  auto-rejection.
- `src/data/gpm_imerg.py`: `_resolve_available_date` now returns the oldest
  date it actually probed after exhausting `GPM_IMERG_MAX_LOOKBACK_DAYS`, never
  the next unprobed day.
- `dashboard/lib/source-health.js`: recency classification now samples the last
  five active attempts, not the last five total rows. Skipped cadence rows no
  longer push a recovering source's last active success out of the window.
- `.github/workflows/bot.yml`: exports the repo-variable knobs used by the new
  code paths: GPM timeout/backoff/lookback, pending type cap, pending TTL, and
  the triage kill-switch. `THEHEAT_TRIAGE_ENABLED` still defaults to on in
  production but can now be changed with a repo variable instead of a code push.
- `PIPELINE.md` / `BRIEFING.md`: current operator docs now point routine-beacon
  status at the `ROUTINE_BEACON` repository variable, clarify that disabled
  triage is true legacy passthrough, and describe skip-aware source-health
  recency.

### Tests

- Added regression coverage for disabled-triage TTL behavior, GPM walk-back
  exhaustion, and skip-aware source-health recency.

## [0.9.11.1] - 2026-06-03

Cap the cost of a doomed `gpm_imerg` fetch — PR 4 of the source-reliability
sweep. The 0.9.10.0/0.9.11.0 fixes did their job (the 404 and IPv6
`Network unreachable` failure classes are gone), but they surfaced a hidden
cost: when NASA's OPeNDAP service times out *intermittently*, the threaded
city fan-out kept running every doomed fetch to completion, so a single run
burned ~28 minutes before failing. The read-timeout itself is upstream and not
fixable on our side; the wasted wall-clock was ours.

### Fixed

- `src/data/gpm_imerg.py`: once the strict repeated-failure limit trips
  mid-fan-out, cancel the queued city fetches instead of waiting on them. The
  threaded branch previously exited through `with ThreadPoolExecutor()`, whose
  implicit `shutdown(wait=True)` drained every submitted future before the
  `SourceFetchError` could propagate — so an intermittent NASA outage paid the
  full 75-city timeout bill (~28 min) after the source had already decided to
  fail. Now it `shutdown(wait=False, cancel_futures=True)`s, capping the doomed
  tail at one in-flight wave (~130 s). The success path is unchanged (nothing
  is pending when all fetches complete). +1 regression test
  (`test_strict_fanout_cancels_pending_after_failure_limit`) covering the
  fan-out abort that the existing serial-probe short-circuit test didn't reach.

## [0.9.11.0] - 2026-06-02

Shared HTTP hardening — PR 2 of the source-reliability sweep (PR 1 was the
gpm_imerg date walk-back). Mops up the residual `[Errno 101] Network is
unreachable` failures (firms + a few gpm ConnectionErrors): GitHub-hosted
runners have broken IPv6, but NASA EOSDIS hosts (gpm1.gesdisc, firms.modaps)
publish AAAA records — confirmed via `dig` — so `requests` tries IPv6 first and
dies. (The 403s on coral_dhw/jtwc/river_gauges/copernicus_ems were tested and
are NOT User-Agent blocks — every UA returns 200 — so they're left alone as
intermittent rate-limits.)

### Changed

- `src/data/_http.py`:
  - New `force_ipv4()` flips `urllib3.util.connection.HAS_IPV6 = False`,
    forcing every connection onto IPv4. Called at import; the bot imports all
    source modules at startup (`src/main.py`), so it runs before any fetch.
    Strictly correct here — every source has an A record and the runner can't
    reach IPv6 anyway.
  - `fetch_with_retry` now injects a default `User-Agent`
    (`(theheat-bot, contact@theheat.app)`) when the caller doesn't set one, so
    no-UA callers (firms) stop sending a bare `python-requests` UA. A caller's
    explicit UA is preserved.
- `src/data/ice_mass.py`: the PO.DAAC data fetch (where the 502s land) now
  routes through `fetch_with_retry` — a transient 502 retries with backoff
  instead of dropping the whole region.
- `src/data/river_gauges.py`: the USGS gauge-height call routes through
  `fetch_with_retry` too (retry + polite UA), matching the NWPS flood-stage leg.

### Tests

- `tests/test_http_retry.py`: +3 — force_ipv4 flips the flag; default UA is
  injected; a caller's UA is preserved.
- `tests/test_ice_mass.py`: +1 (502 → 200 recovers on retry); existing 5xx test
  updated for the retry path.
- `tests/test_river_gauges.py`: USGS error test updated to assert the retry.
- 1368 → 1372 passing. mypy clean.

### Expected impact

The IPv6-unreachable failure class disappears on the runner; firms returns to
~100% and gpm sheds its ConnectionError tail (its 404 cause was already fixed in
0.9.10.0). ice_mass 502s now self-heal within a cycle. Remaining yellow
(NASA 503/502 overload, intermittent gov 403s) is upstream and self-recovers
next cron.

## [0.9.10.0] - 2026-06-02

gpm_imerg date walk-back — the single biggest source-reliability win. The GPM
IMERG "Late" daily product publishes ~1-2 days after the observation date, but
`fetch_daily_precip` always requested *yesterday* and treated the resulting
HTTP 404 as non-retryable (correctly) — so whenever NASA hadn't posted yet, the
entire source silently failed. This was the dominant gpm_imerg failure on the
source-health dashboard (the bulk of its 30+ failures over the 7-day window were
404s, not NASA outages). Source review on 2026-06-02 surfaced it after a tweet
went live and reliable precipitation signal became load-bearing.

### Changed

- `src/data/gpm_imerg.py`: on the default path (no explicit `target_date`),
  `fetch_daily_precip` now resolves the latest *published* date via a new
  `_resolve_available_date` probe that walks back day-by-day until a file
  exists:
  - HTTP 200 → published, use it.
  - HTTP 404 → not yet posted, try the day before.
  - anything else (5xx / timeout / connection error) → not a date-availability
    signal, so stop and use the current candidate; per-city fetches retry and
    surface transient outages exactly as before.
  - Walks back at most `GPM_IMERG_MAX_LOOKBACK_DAYS` (default 5), then degrades
    to the old fixed-"yesterday" behavior — never worse than before.
  - Explicit `target_date` callers (tests, backfill) bypass walk-back entirely,
    staying deterministic.

### Tests

- `tests/test_gpm_imerg.py`: +3 — walk-back past an unpublished 404 to the prior
  published day; stop (don't walk back) on a transient 5xx; default path routes
  through `_resolve_available_date`. 1365 → 1368 passing.

### Expected impact

gpm_imerg should climb from ~16% toward healthy whenever NASA is reachable —
the 404 "data not published yet" class is eliminated. Remaining gpm failures
(503 overload, occasional IPv6-unreachable) are addressed separately: 503 is
upstream; IPv6 is the next PR (shared HTTP IPv4 forcing).

## [0.9.9.0] - 2026-06-02

Dashboard source-health panel: fix the success-rate fraction denominator and
make the health badge recency-aware. Both surfaced from a review of the panel
on 2026-06-02, where it flagged "3 unhealthy / 2 degraded" — but the reds were
dominated by a one-day NASA GES DISC HTTP-503 storm (22 of gpm_imerg's 28
failures landed on 05-31), not bot bugs, and gpm_imerg was already recovering
(its last 4 runs all succeeded post-0.9.5.0). The 7-day cumulative window kept
it red anyway, and the displayed fraction was mathematically inconsistent for
cadence-gated sources.

### Changed

- `dashboard/lib/source-health.js`:
  - `addDerivedFields` now exposes `active` (= success + failed + degraded +
    partial_failures, i.e. non-skip attempts) — the shared denominator for
    both `success_rate` and the rendered "(N/M)" fraction.
  - `classifyHealth` is now recency-aware. When a recent sub-window is present
    (the durable `source_health` path), it classifies on the last
    `RECENT_WINDOW` (5) runs instead of the 7-day cumulative counters: a
    recovering source (recent runs mostly succeeding) is at worst `degraded`,
    never `unhealthy`; a freshly-degrading source (recent runs mostly failing)
    flips to `unhealthy` even if its cumulative history is good. The
    `run_history` fallback path is unchanged — it is already a recent window.
  - `aggregateFromSourceHealth` computes the recent sub-window
    (`recent_successes`, `recent_active`) from the runs array.
- `dashboard/app/page.js`: the Sources-tab table renders the fraction as
  `(successes/active)` with skips shown separately
  (e.g. `33% (1/3, 30 skipped)`), replacing `(successes/runs)`, which produced
  nonsensical displays like `33% (1/10)` and `100% (8/10)` for sources that
  skip most crons (ice_mass runs Mondays-only; ao is event-gated).

### Tests

- `dashboard/tests/source-health.test.js`: +4 tests — fraction uses `active`
  (skips excluded); recovering source → degraded not unhealthy; last-run-failed
  but recent-recovering → degraded; last-run-succeeded but recent-failing →
  unhealthy (early degradation). Dashboard suite 41 → 45 passing.

### Expected impact

On current production state the panel flips from "3 unhealthy / 2 degraded" to
"2 unhealthy / 3 degraded": gpm_imerg is correctly demoted from red to
recovering (degraded), while ice_mass greenland/antarctica stay red (real,
ongoing NASA 502s). No source-fetch code changed — NASA intermittency is
watched, not thrashed.

## [0.9.8.0] - 2026-06-01

Fact-check: skip claims with unknown `kind` instead of killing the whole
tweet. After 0.9.7.0 fixed the critic's "period of record too short" kill,
the next gate in the funnel — fact_check — turned out to have a different
structural failure: Gemini Flash sometimes returns `kind: "factual_assertion"`
or other off-script kinds not in the prompt's enumerated list (`number`,
`date`, `named_entity`, `comparison`, `era_anchor`, `peer_comparison`).
The old parser raised on any unknown kind, invalidating the whole response,
retrying once with the same result, then killing the candidate. Observed
2026-06-01: 14+ candidates killed across the day with reason "Unsupported
extracted claim kind: factual_assertion." Wrong failure mode — pass/fail
is independent of claim kinds.

### Changed

- `src/two_bot/fact_check.py`: `_parse_extracted_claims` now drops claims
  with unknown `kind` (with a logged warning) and continues parsing the
  rest of the response. Structural failures (missing fields, wrong types)
  still raise — those indicate the response is too malformed to trust.
- `src/two_bot/claim_extractor.py`: same fix in `_parse_claims_json` for
  consistency. (claim_extractor.py is the standalone path; fact_check.py
  is the combined path that's actually wired into the production pipeline.)

### Tests

- `tests/two_bot/test_fact_check.py`: +2 tests — one verifies unknown-
  kind claims are dropped while valid claims pass through and the tweet
  still ships; one verifies structurally-malformed claims (missing
  `kind` field entirely) still fail the response. 1361 → 1363 passing.

### Expected impact

The 14+ daily fact-check kills attributed to claim-kind-validation should
drop to ~0 immediately. Combined with 0.9.7.0's critic fix, the writer →
fact_check → critic funnel should now produce drafts at the editorial
rate the architecture was designed for, instead of the 0-drafts-for-5-days
silence caused by parser strictness.

## [0.9.7.0] - 2026-06-01

Critic prompt fix: assess signals relative to available data, not against
an implied "must have a 100-year baseline" bar. After 0.9.6.0 verified the
pipeline was running end-to-end and producing 0 drafts, the suppression
ledger showed every critic kill citing variations of "26-year period of
record is too short to be an extraordinary climate signal." That was
**wrong reasoning** by the critic — most weather-station histories are
25-50 years; the bot's job IS to surface records relative to available
data. Rejecting every station-record signal as "baseline too short" made
the bot structurally silent.

### Changed

- `src/two_bot/prompts/critic_prompt.py`: added an explicit
  "**Period-of-record length is NOT a kill condition**" bullet under
  Scale/impact. Clarified that the existing "Underwhelming numbers" rule
  is about *absolute magnitude* (a 70 MW fire, a 1.2°C anomaly, a DHW of
  2 — small in absolute terms), NOT about how long the underlying
  baseline is. The new bullet:
  - Cites the broken pattern verbatim ("a 26-year period of record is
    too short") so the model can't drift back into it
  - Frames the bar: assess relative to data that exists; a station record
    breaking its 26-year history IS the climate signal
  - Permits tweets that name the period explicitly ("hottest in 26 years
    of records") rather than dismissing them

### Tests

- `tests/two_bot/test_prompts.py`: +1 regression test
  `test_period_of_record_length_is_not_a_kill_condition` locking the new
  guidance into the prompt structure. 36 → 37 prompt tests passing.

### Expected impact

Station-record candidates from `open_meteo_extreme_signals` and other
finite-baseline sources can now pass the critic when the data warrants
it. The 0-drafts-for-5-days drought should end — pending queue will
diversify with non-coral signals as soon as the next cron's candidates
clear writer → fact_check → critic.

## [0.9.6.0] - 2026-06-01

Pending-queue diversity gate. The pre-0.9.0.0 unbounded coral_dhw promoter
left 10 coral_bleaching drafts in pending, drowning out the editorial goal
of "full picture of warming" — the queue read as a coral monoculture
instead of a balanced view of climate extremes. The per-category triage cap
(2/cycle) bounded INPUT but did nothing about pending-queue COMPOSITION
over many cycles. This release adds the queue-aware backstop.

### Added

- `src/orchestrator/triage.py`:
  - New `THEHEAT_PENDING_TYPE_CAP` env var (default 3). Triage refuses to
    promote a new candidate when the pending queue already holds N drafts
    of that `legacy_type`. Spilled candidates are recorded with
    `stage="triage_cap"` and `reasons=["pending_type_cap=N"]` so dashboard
    attribution can tell "queue saturated for this type" apart from "cycle
    cap hit" and "global cap hit".
  - New `apply_pending_ttl_sweep(bot_state, *, now=None)` function. Marks
    pending drafts older than `THEHEAT_PENDING_TTL_DAYS` (default 7) as
    `status="rejected"` with `rejected_reason="staleness_ttl_Nd"` and a
    `rejected_at` timestamp. Wired into `_drain_and_write_triage_queue`
    so it runs at the start of every cycle, freeing pending-type-cap slots
    for fresh candidates immediately. Errors here are caught — TTL must
    not block the rest of the pipeline.
  - Within `select_survivors`, the cap check increments a per-type cache
    after each survivor is admitted so consecutive same-type candidates in
    one cycle don't all squeeze into the last open slot.

### Tests

- `tests/test_triage.py`: +10 tests covering pending-type cap (admit/block,
  rejected-don't-count, consecutive-bump, env override) and TTL sweep
  (reject-old, preserve-fresh, only-pending, malformed-created-at,
  env override). 1348 → 1358 passing.

### Operational knobs

- `THEHEAT_PENDING_TYPE_CAP=3` — max pending drafts per `legacy_type`. Lower
  if 3 still feels too redundant. Higher if specific types feel
  under-represented.
- `THEHEAT_PENDING_TTL_DAYS=7` — auto-reject pending drafts older than this.

### Expected impact

Going forward, pending-queue concentration is a structural property of the
pipeline, not a manual operator burden. The May 2026 coral pile-up becomes
impossible by construction. Diverse-supply weeks produce diverse-pending
queues. Single-source-dominant weeks produce a small queue with no monoculture.

## [0.9.5.0] - 2026-06-01

GPM IMERG reliability fix. The precipitation source has been showing a 13%
success rate (1/8) on the source-health dashboard because NASA's GES DISC
OPeNDAP service is intermittently slow under load — its `.nc4.ascii` subset
generation routinely takes 30-55 seconds, but the bot's hardcoded 30s
timeout was too aggressive and the single-shot fetch had no retry. Result:
zero precipitation drafts ever, and the pending queue lost a whole story
class (flash floods, monsoon record days, atmospheric rivers), reinforcing
the coral-monoculture problem flagged in the diversity discussion.

### Changed

- `src/data/gpm_imerg.py`:
  - Default OPeNDAP request timeout raised from 30s to 60s. Configurable
    via `GPM_IMERG_TIMEOUT_S` env var (positive number; junk values fall
    back to default).
  - Added one retry per city on transient errors only: `ReadTimeout`,
    `ConnectionError`, and HTTP 5xx responses. 10s default backoff between
    attempts, configurable via `GPM_IMERG_RETRY_BACKOFF_S` (tests set to 0).
  - 4xx responses (401 auth, 404 not-found, 400 validation) raise
    immediately — they're persistent and re-trying wastes the source's
    runtime budget on guaranteed-to-fail repeats.
  - Strict-mode probe still fails fast after 3 same-signature failures, so
    a real NASA outage still kills the run quickly. The retry layer
    promotes a single transient blip from a city-skip into a recovered read.

### Tests

- `tests/test_gpm_imerg.py`: +4 tests covering retry-on-ReadTimeout,
  retry-on-5xx, no-retry-on-4xx, and the timeout env override. 16 → 20.

### Expected impact

NASA GES DISC's actual server-side behavior is unchanged, but the bot now
tolerates the transient slowness. Source-health success rate should rise
from ~13% to ~70-85% under current NASA conditions, surfacing
precipitation/flood drafts that the prior architecture silently dropped.

## [0.9.4.0] - 2026-05-26

Dead-code cleanup post-0.9.3.0. After the beacon migrated from the gist
to a repository variable in 0.9.3.0, the python `state.json` was still
carrying an `automation` field with a full schema type, default value,
and a special `_merge_state` "current wins" branch — all defending a
gist-beacon path that no longer exists. Nothing on the python side
writes or reads the field; the dashboard reads the repo variable, not
the gist. This release removes the vestigial scaffolding so the schema
is honest.

### Removed

- `src/state_schema.py`: `AutomationState` TypedDict + the `automation`
  field on `BotState`.
- `src/state.py`: `DEFAULT_STATE["automation"]` + the dedicated
  `automation` branch in `_merge_state`.
- `tests/test_state.py`: `TestAutomationMerge` class (3 tests that
  exercised the dead merge logic).

### Changed

- `BRIEFING.md`: replaced stale references to the gist-based beacon
  with the post-#160 repo-variable path; noted that the three previously
  parked `wip/` branches are now archived as `archive/wip/*` tags.
- `docs/IMPROVEMENT_PLAN.md`: updated the "Voice engine version" cell
  to describe the current beacon write path.

## [0.9.3.0] - 2026-05-26

Beacon storage moved from a gist file to a GitHub Actions repository
variable. The 0.9.1.0 routine prompt's Step 9.5 PATCHed
`routine_beacon.json` into the state gist, but the CCR environment's
stored gh token lacks `gist:write` scope — beacon writes silently failed
across the first four fires (5/23 through 5/26) and the dashboard's
routine indicator stayed gray despite a healthy routine. The routine
already has `repo` scope, which is also what `gh variable set` requires,
so this release moves the beacon to a single repository variable named
`ROUTINE_BEACON`. No new branches, no SHA management, no file paths —
one named string updated atomically by `gh variable set`.

### Changed

- `dashboard/lib/automation.js`: `readRoutineBeacon()` now fetches
  `GET /repos/.../actions/variables/ROUTINE_BEACON` and parses the
  variable's `value` field. 404 → null (gray dot).
- Routine prompt Step 9.5 (managed via RemoteTrigger, not in repo):
  writes the beacon via `gh variable set ROUTINE_BEACON --body "$JSON"`
  instead of a gist PATCH. Preserves the `|| exit 0` fallback so beacon
  write failures still log a warning and let the cycle succeed.

### Fixed

- Dashboard routine dot now actually flips green when the routine
  completes cleanly. Prior to this change, the gist PATCH silently
  failed every fire and the dot stayed gray indefinitely.

## [0.9.2.0] - 2026-05-22

Dashboard automation hardening. The automation strip now reports production
workflow status and posting-mode state more honestly, without creating a
GitHub API call storm from every open dashboard tab.

### Changed

- Scoped automation workflow "last run" reads to the production branch
  (`main` by default, configurable via `THEHEAT_AUTOMATION_BRANCH`) so PR
  workflow runs cannot masquerade as live bot health.
- Added a short server-side cache for `GET /api/automation`
  (`THEHEAT_AUTOMATION_CACHE_TTL_MS`, default 15s) so repeated dashboard
  polls share one status fetch instead of fanning out to GitHub on every
  browser refresh.

### Fixed

- The posting-mode pill now shows `posting status unavailable` when the
  state store cannot be read, instead of falsely reporting `0 manual / 0
  auto / 0 suggested`.
- Routine-beacon prompt examples now default to `no-fresh-drafts` unless
  the routine sets a real `ROUTINE_OUTCOME`, preventing copied prompt
  snippets from hard-coding `graded`.

## [0.9.1.0] - 2026-05-22 (late session)

The visibility-and-routine-hygiene release. Same-day follow-up to 0.9.0.0:
adds the dashboard's "Automation" status strip + a daily-plan routine
prompt rewrite that fixes two distinct routine bugs the prior session
surfaced. No pipeline architecture changes; bot workflows still paused
pending operator re-enable signal.

### Added — Dashboard automation status strip (PR #156)

New persistent strip at the top of every dashboard view: four colored
dots (one per automation: `theheat-bot`, `voice-regression`,
`refresh-thresholds`, daily-plan Claude routine) plus a posting-mode
pill (counts of pending drafts by approval mode). Read-only — no
buttons, no destructive actions. Dot colors:

- Green: workflow active + last run succeeded (or routine recently
  graded / no-fresh-drafts)
- Yellow: workflow active + last run failed (or routine outcome=error)
- Gray: workflow `disabled_manually` or routine beacon stale (>25h
  since last write)
- Red: dashboard API error reading state

Tooltip on hover shows full name + last-run UTC timestamp + last-run
conclusion. The posting-mode pill reads pending drafts and counts by
`approval_policy.mode`.

Implementation: new `dashboard/lib/automation.js` with read helpers
(`fetchWorkflowState`, `fetchWorkflowLastRun`, `readRoutineBeacon`,
`getAutomationStatus`). New `dashboard/app/api/automation/route.js` —
read-only `GET` endpoint, basic auth via the existing
`requireDashboardAuth` middleware. Status strip component in
`dashboard/app/page.js` with styled-jsx (no separate CSS file; matches
existing dashboard pattern). Fetch piggybacks on the existing 30-second
poll interval in `Dashboard.fetchData`, but lives in its **own**
try/catch outside the dashboard fetch so dashboard outages don't
suppress automation refresh and vice versa.

Read paths chosen to avoid race conditions:

- **Workflows** read from GitHub Actions API (`GET /repos/{owner}/{repo}/actions/workflows/{file}` and `/runs?per_page=1`).
- **Routine** reads from a NEW `routine_beacon.json` file in the gist
  (not `state.json.automation`) — lets the routine write its beacon
  via per-file `PATCH` without touching `state.json`, eliminating the
  lost-update race against concurrent python pipeline writers that an
  earlier design iteration would have introduced.
- **Posting mode** reads pending drafts via the existing
  `readStateStore` helper (the same path the rest of the dashboard
  uses).

Tests: 9 new unit + route tests in `dashboard/tests/automation.test.js`.
Dashboard suite 30 → 39 passing.

### Added — Python `AutomationState` schema (commits c4009bb, 011063a)

New `AutomationState` TypedDict in `src/state_schema.py` with two
optional fields (`routine_last_run_at`, `routine_last_run_outcome`).
Added to `BotState` adjacent to `source_health`. Added to
`DEFAULT_STATE` in `src/state.py` so `_fresh_state()` includes it.
`_merge_state()` extended to preserve the `automation` field with a
"current wins" rule — only the routine writes this field (and even
that goes to a separate gist file in v0.9.1.0, not `state.json`), so
the merge rule is defensive future-proofing: if anything ever does
write `automation` through python, concurrent crons can't erase it.
Three new tests cover the round-trip, current-wins ordering, and
missing-field defaulting.

mypy clean across 92 source files (was 91). pytest 1348 → 1351 (+3
merge-preservation tests).

### Changed — Daily-plan routine prompt: Step 0 + Step 9.5

Two new steps inserted into the live routine (`trig_016PGeHZgEYWmeQhx1xGmYg6`) via the claude.ai RemoteTrigger API:

- **New Step 0 — stale-snapshot sync.** Forces the routine to
  `git fetch origin main && git checkout -B main origin/main &&
  git reset --hard origin/main && git clean -fd` before any other
  work. Fixes the bug where the CCR environment reuses a stale git
  checkout across runs — this is what caused PR #152's confused
  re-grade on 2026-05-21 (the routine operated from a snapshot 4
  days behind main, re-graded drafts that main's `2026-05-19`
  corpus section had already graded with different verdicts).
- **New Step 9.5 — health beacon write.** Writes a 2-field JSON
  document (`routine_last_run_at`, `routine_last_run_outcome`) to
  `routine_beacon.json` in the gist regardless of grading outcome.
  Best-effort: on `gh api -X PATCH` failure (most likely cause:
  routine's stored token lacks `gist:write` scope), logs a warning
  and exits 0 to keep the cycle alive. Beacon outcomes:
  `"graded"`, `"no-fresh-drafts"`, `"error"`.

Step 9.5 uses `jq -nc` (compact) instead of pretty output. The
default pretty output produces invalid JSON when `--arg` nests a
multi-line string (the inner string ends up with literal newlines
rather than `\n` escapes), which would have shipped a broken Step
9.5. Caught by pre-push validation that ran `bash -n` on every
bash block and dry-ran the jq pipeline before pushing to the live
routine.

### Operator action this release (Andrew)

- Rejected 5 stale fire drafts from the gist pending queue (Mali,
  Campeche, Mongolia, BC, Siberia — all 4–10 days old with
  present-tense fire-detection or "today" language baked in). Cleaned
  via direct gist PATCH (the routine's stored token lacks
  `gist:write` scope in the managed CCR environment, so the routine
  itself can't bulk-reject).
- Consolidated three stacked daily-plan auto-PRs (#151, #152, #153)
  into one squash commit on main (PR #155) using the same pattern
  Codex used on 2026-05-19 (`ffb0a5c`). #152's section was skipped
  — it was a confused re-grade of drafts already in main's
  `2026-05-19` corpus section (the routine had run from a stale
  snapshot, which is what motivated the Step 0 fix above).
- Updated the routine prompt earlier in the session (before the v0.9.1.0
  scope was finalized) to use a rolling `daily-plan-current` branch +
  single persistent PR (the "Step 8" rewrite). Combined with the new
  Step 0 + Step 9.5, the routine now: (a) syncs to fresh main, (b)
  grades the queue, (c) writes a rolling PR, (d) writes the beacon.

### Notes on the design journey

The shipped scope is intentionally **less** than what the v1/v2 design
specs explored:

- v1 design proposed a full "Pause Everything" control plane that would
  pause workflows + the routine atomically. Codex adversarial review
  surfaced 11 issues including merge race, partial-failure traps, and
  python sqlite-roundtrip drops.
- v2 design pivoted to repo-variable + workflow `if:` guards. Codex
  round 2 surfaced 11 more issues — the merge race + two-store
  coordination didn't have clean fixes without a compare-and-swap
  layer.
- v3 (this release) descopes pause control entirely and ships only
  read-only indicators + routine fixes. The pause control space is
  parked; reopen if there's clear demand. Three spec versions
  (`docs/superpowers/specs/2026-05-22-dashboard-pause-and-automation-indicators-design{,-v2}.md` and `2026-05-22-dashboard-automation-indicators-design-v3-descoped.md`) and one plan
  (`docs/superpowers/plans/2026-05-22-dashboard-automation-indicators.md`) are retained for historical record.

### Production state at this release

bot workflows (`theheat-bot`, `voice-regression`) remain
`disabled_manually` pending Andrew's re-enable signal. `refresh-thresholds` continues. The new routine prompt fires for the first time at 2026-05-23T15:07 UTC.

mypy clean across 92 source files. pytest 1351 passing. Dashboard
test suite 39 passing (was 30). next build passes.

### Files added / modified

- `dashboard/lib/automation.js` (new, 141 lines)
- `dashboard/app/api/automation/route.js` (new, 16 lines)
- `dashboard/app/page.js` (+157 lines: `AutomationStatusStrip` component + dot helpers + styled-jsx)
- `dashboard/tests/automation.test.js` (new, 267 lines, 9 tests)
- `src/state_schema.py` (+17 lines: `AutomationState` TypedDict + field on `BotState`)
- `src/state.py` (+15 lines: `DEFAULT_STATE` entry + `_merge_state` copy block)
- `tests/test_state.py` (+61 lines: 3 new tests in `TestAutomationMerge`)
- `docs/superpowers/specs/2026-05-22-dashboard-pause-and-automation-indicators-design.md` (new, v1 retained for history)
- `docs/superpowers/specs/2026-05-22-dashboard-pause-and-automation-indicators-design-v2.md` (new, v2 retained for history)
- `docs/superpowers/specs/2026-05-22-dashboard-automation-indicators-design-v3-descoped.md` (new, the approved scope)
- `docs/superpowers/plans/2026-05-22-dashboard-automation-indicators.md` (new)
- `PIPELINE.md` (added "Automation status strip" + "Routine Health Beacon" subsections)
- Daily-plan routine prompt updated via RemoteTrigger (not in repo diff; `trig_016PGeHZgEYWmeQhx1xGmYg6`).

PRs merged: #155 (consolidate daily-plan refinements), #156 (dashboard
automation indicators + python schema). All other operator actions
(routine prompt update, gist draft rejection) are out-of-repo.

## [0.9.0.0] - 2026-05-22

The end-to-end-trustworthy-pipeline release. Five distinct work streams
landed in one multi-day push: source-to-writer evidence contract,
universal triage routing (all sources, not just `coral_dhw`),
pipeline efficiency tightening (fact-check now also extracts claims,
collapsing two Gemini calls into one), two dead-source resurrections
(`sea_ice` v3.0→v4.0 URL bump, `ice_mass` re-routed through NASA CMR
after PO.DAAC Drive decommissioning), and a consolidated daily-plan
analytics corpus.

Two operator actions completed alongside the code: **NASA GESDISC
DATA ARCHIVE** and **PO.DAAC Cumulus OPS** apps now authorized on
the Earthdata account, unblocking GPM-IMERG and GRACE-FO ice_mass
respectively. Both verified end-to-end with one-shot diagnostic
workflows that returned HTTP 200 against the production endpoints
(zero LLM credits, diagnostic workflows added + removed cleanly
across paired PRs).

Production state at this release: bot workflows (`theheat-bot`,
`voice-regression`) remain disabled pending Andrew's call to re-enable
under the new (all-sources-triage + evidence-contract + dual-purpose
fact_check) architecture. `refresh-thresholds` continues to fire
(data-only, no LLM). mypy clean across 91 source files; pytest 1348
passing on main.

### Added — Source-to-writer evidence contract (00837f2)

New `src/two_bot/evidence_contract.py` module defines a deterministic
pre-writer audit that scrutinizes a `StoryBundle` before any LLM call.
The audit returns an `EvidenceAudit(signal_kind, event_id, prompt_ready,
issues)` value; `issues` carry severity (`error` | `warning`), code,
field, and message. Errors block the writer (`prompt_ready=False`),
warnings pass through with a logged note.

Pipeline wiring at [/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/pipeline.py](/Users/andrewpuschel/Documents/Claude/theheat/src/two_bot/pipeline.py): new `_audit_bundle_for_generation`
helper called at the top of `generate_draft`. On error, the helper
records `kill_stage="evidence_contract"` and the writer is never
invoked. `kill_stage` docstring on `src/orchestrator/common.py`
extended to list the new stage as a source-of-truth signal for the
dashboard.

New `tests/two_bot/test_evidence_contract.py` (+593 lines) covers
every issue code with a representative bundle, plus regression
fixtures that prove a borderline-passing bundle still reaches the
writer.

Design context lives at
[/Users/andrewpuschel/Documents/Claude/theheat/docs/source-to-writer-evidence-contract.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/source-to-writer-evidence-contract.md)
and the eng-reviewed spec at
[/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-05-19-source-to-writer-evidence-contract.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/superpowers/specs/2026-05-19-source-to-writer-evidence-contract.md).
The motivating problem: bundles that passed the editorial score gate
could still reach the writer missing the source artifacts the writer
needed to ground its claims — producing tweets that fact-check
couldn't disprove but couldn't fully verify either. The contract
makes that boundary explicit at code level.

### Added — All sources routed through triage gateway (PR #150 / 13f8d64)

Completes the triage migration that 0.8.0.0 / #134 started for
`coral_dhw`. Every alert source (`climate_indices`, `co2`, `co_ops`,
`copernicus_ems`, `coral_dhw`, `drought`, `enso`, `firms`, `gdacs`,
`gpm_imerg`, `ice_mass`, `nhc`, `jtwc`, `nsidc_snow`, `ocean`,
`ocean_sst`, `open_meteo`, `ozone_hole`, `river_gauges`, `sea_ice`,
`synthesis`) now builds `TriageCandidateBundle` instances and enqueues
them via the new `_enqueue_story_candidate` helper instead of calling
`_try_two_bot_draft` directly.

The per-cycle drain at end of `run_alerts` ranks the entire cycle's
queue by `(score.total DESC, created_at DESC)`, applies per-category
+ global caps, and only then routes survivors to the writer. Source
runners' per-success side effects (e.g. `state.update_coral_dhw_tier`,
`increment_co2_annual_count`) moved into `on_draft_success` callbacks
on the candidate — so cooldown / counter ticks only fire on actual
drafts, not on cycle-cap spills. Pattern is now reusable.

GPM-IMERG also gained a `strict` fail-fast path in this commit: when
the fetcher can't get a single city reading, it now raises
`SourceFetchError` instead of silently emitting an empty bundle, so
operators see the failure on the dashboard instead of an
inexplicably empty cycle.

New `tests/test_source_triage_migration.py` covers the cross-source
boundary; existing `tests/test_coral_dhw.py`, `tests/test_gpm_imerg.py`,
`tests/test_main.py`, `tests/test_precip_snow_orchestrator.py`,
`tests/test_open_meteo_orchestrator.py`, and `tests/test_triage.py`
updated to mock the new enqueue path.

### Changed — Fact-check now extracts claims in-place (d2b5f53)

The Gemini Flash fact-checker now extracts the structured-claim list
itself instead of relying on a separate `claim_extractor` invocation.
Validation logic in `_parse_extracted_claims` accepts five claim
kinds (`number`, `date`, `named_entity`, `comparison`, `era_anchor`,
`peer_comparison`); malformed claims surface as a fact-check
rejection (with the standard JSON-parse retry budget from 0.7.1.0).

Net effect: ~1 Gemini Flash call per draft instead of 2 for the
extract→fact-check sequence. claim_extractor remains in
`src/two_bot/claim_extractor.py` for use elsewhere but is no longer on
the per-draft hot path. Cost win compounds with the 0.8.0.0 prompt
caching.

Touches: `src/two_bot/fact_check.py`, `src/two_bot/memory.py`,
`src/two_bot/pipeline.py`, `src/two_bot/prompts/fact_check_prompt.py`,
`src/two_bot/prompts/writer_prompt.py`, `src/state_schema.py`. Test
suite expanded: `tests/two_bot/test_fact_check.py` (+64 lines),
`tests/two_bot/test_memory.py` (+26), `tests/two_bot/test_pipeline.py`
(+20), new `tests/test_source_health.py` (+48).

### Fixed — `sea_ice` URLs bumped to v4.0 (PR #146)

NSIDC silently moved their daily sea-ice extent CSVs from `v3.0` to
`v4.0` in early 2026. The `noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v3.0.csv`
(and Antarctic equivalent) paths now return 404, while
`...v4.0.csv` returns 200 with the unchanged 4-column schema (Year,
Month, Day, Extent, Missing, Source Data). Both lanes had been
failing in production for at least 7 Monday crons (0 successes / 7
failures / no `last_success_ts` ever) — invisible because the lanes
only fire weekly. Surfaced during the dead-source audit triggered by
the GPM-IMERG operator action.

[/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/sea_ice.py)
constants bumped; parser untouched. Existing happy-path tests at
`tests/test_sea_ice.py` updated to mock the v4.0 URLs.

### Fixed — `ice_mass` re-routed through NASA CMR (PR #146)

PO.DAAC Drive (`podaac-tools.jpl.nasa.gov`) was decommissioned during
NASA's Earthdata Cloud migration; that domain now `ConnectTimeout`s.
GRACE-FO mascon ice mass anomaly time-series products migrated to
`archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/...`,
but the granule filenames now embed a data range (e.g.
`greenland_mass_200204_202603.txt`), making a single hardcoded URL
go stale every monthly data release.

[/Users/andrewpuschel/Documents/Claude/theheat/src/data/ice_mass.py](/Users/andrewpuschel/Documents/Claude/theheat/src/data/ice_mass.py)
rewritten to:
- Track CMR collection short_names (`GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4`
  and `ANTARCTICA_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4`) as
  constants instead of hardcoded URLs.
- Resolve the latest granule URL on each fetch via
  `cmr.earthdata.nasa.gov/search/granules.json` (`_resolve_latest_url`
  helper, returns `None` on any failure for graceful skip).
- Bearer-auth + parser unchanged.

Two new test methods cover CMR failure paths:
`test_cmr_returns_no_granules_skips`, `test_cmr_http_failure_skips`.
Existing happy-path tests updated to mock CMR + the new archive URL.

End-to-end verified post-merge via a one-shot GitHub Actions
diagnostic that hit both regions and confirmed HTTP 200 with real
DAP-headers + JPL RL06.3Mv4 mascon body content (PR #147 add + #149
remove, both admin-merged; zero LLM credits).

### Added — Earthdata operator actions completed (this session)

The two NASA Earthdata app authorizations the bot depends on are now
both on Andrew's account:
- **NASA GESDISC DATA ARCHIVE** — for GPM-IMERG OPeNDAP. Without it,
  bearer requests return 401 even with a valid token.
- **PO.DAAC Cumulus OPS** — for the new GRACE-FO ice_mass archive
  on `archive.podaac.earthdata.nasa.gov`. Same authorization pattern.

[/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md](/Users/andrewpuschel/Documents/Claude/theheat/BRIEFING.md)
`EARTHDATA_TOKEN` env-var documentation expanded to enumerate both
required apps and the Earthdata Cloud migration context.

Both authorizations verified end-to-end against the production
endpoints via paired diagnostic workflows that landed and were
removed cleanly (PRs #140–#149, several pairs).

### Added — Daily-plan analytics corpus (ffb0a5c + 73b0f9a)

[/Users/andrewpuschel/Documents/Claude/theheat/docs/DRAFT_CORPUS.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/DRAFT_CORPUS.md)
(+1228 lines, new) captures graded drafts across recent cycles.
[/Users/andrewpuschel/Documents/Claude/theheat/docs/IMPROVEMENT_PLAN.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/IMPROVEMENT_PLAN.md)
(+108 lines) and
[/Users/andrewpuschel/Documents/Claude/theheat/docs/QUALITY_TREND.md](/Users/andrewpuschel/Documents/Claude/theheat/docs/QUALITY_TREND.md)
(+63 lines) consolidate the trailing daily-plan refinement PRs.

These docs become the corpus the upcoming writer-payload-slimming
work (Tier B3 in the optimization test plan at
[/Users/andrewpuschel/.gstack/projects/andrewzp-theheat/test-plan-triage-optimization.md](/Users/andrewpuschel/.gstack/projects/andrewzp-theheat/test-plan-triage-optimization.md))
will evaluate prompt changes against.

### Operations notes

- Bot workflows (`theheat-bot`, `voice-regression`) **remain disabled**
  in CI. Re-enable via `gh workflow enable theheat-bot && gh workflow
  enable voice-regression`. Andrew has not yet given the
  re-enable signal under the new architecture.
- Two diagnostic workflow ghost records in GitHub's registry have
  been disabled (orphans from iCloud "keep both files" duplicates
  during the diagnostic add-and-remove cycles). `.gitignore`
  extended to cover `*" 2.yml"`, `*" 2.yaml"`, `*" 2.json"` so the
  pattern doesn't recur.
- Two `wip/` branches remain parked from 2026-05-17 awaiting
  editorial sign-off: [`wip/fact-check-disposition-tightening`](https://github.com/andrewzp/theheat/tree/wip/fact-check-disposition-tightening)
  (Theme 6) and [`wip/climate-indices-cadence`](https://github.com/andrewzp/theheat/tree/wip/climate-indices-cadence)
  (Codex #4). A third (and newer) parked branch
  [`wip/era-anchors-safety-curation`](https://github.com/andrewzp/theheat/tree/wip/era-anchors-safety-curation)
  carries an era-anchor curation policy change (removes deaths /
  politics from cultural-era scaffolding) — voice/editorial decision
  pending Andrew's review.

---

## [0.8.0.0] - 2026-05-19

The cost-and-cap release. Five PRs landed in one session: Anthropic
prompt caching on writer + evaluator (cuts cached-prefix input cost
~90%), deterministic pre-writer triage stage (spec'd as 0.7.2.0 / #129,
now shipped as MVP infrastructure in #132 and activated for `coral_dhw`
in #134), three orthogonal source-hardening bug fixes from a Codex
review pass (#133), and a cron-unblocking test-fixture date fix (#136).

Triage is now LIVE in production with the kill-switch ON: coral_bleaching
draft volume is capped at 2 per cron via `PER_CATEGORY_TRIAGE_CAP_DEFAULT=2`
plus a 3-per-cron global cap (`MAX_DRAFTS_PER_CYCLE` unchanged). The
target — source-growth-proof flat-line cost — is now structurally in
reach: doubling sources no longer doubles credit burn, because the writer
only fires for survivors.

Production verdict at session close: pipeline healthy, scheduled cron
unblocked (#136 fixed a 2026-05-19 day-rollover test failure that had
silently halted draft production for several crons), `coral_dhw` is the
first source on the new triage path, `THEHEAT_TRIAGE_ENABLED="1"` is
set in `.github/workflows/bot.yml`, and the next observability cycle
(3-6 hours) will produce the first real `triaged_in` / `triaged_out`
signal on coral candidates.

### Added — Anthropic prompt caching on writer + evaluator (#131)

Both Anthropic call sites — `src/two_bot/writer.py` (the dominant
cost driver) and `src/editorial/evaluator.py` — now mark their system
prompt with `cache_control={"type": "ephemeral"}` on a structured
content-block list. Cache reads cost ~0.1× base input price (~90% off
the cached portion); cache writes cost 1.25×; break-even at 2 reads.

The writer's system prompt is ~5,732 tokens and byte-stable across every
call. After the first call writes the cache, every subsequent call
within the 5-minute TTL pays ~0.1× on the cached portion. The writer
typically fires 5–30× per cron, so the cache pays for itself the same
cycle.

No behavioral change. Tests assert the system prompt text stays
byte-identical to the prior bare-string form — any future refactor that
silently invalidates the cache (e.g. interpolating `datetime.now()`
into the prompt) will fail these tests before it lands.

Surfaced by the Anthropic console dashboard showing "Prompt caching:
Not enabled" alongside 304% week-over-week token volume growth.

### Added — deterministic pre-writer triage stage MVP (#132)

New `src/orchestrator/triage.py` module implements `select_survivors()`
per the 2026-05-17 spec (post-`/plan-eng-review`). Ranks candidates by
`(score.total DESC, created_at DESC)`, applies per-category cap (default
2 via `THEHEAT_PER_CATEGORY_CAP` env override), applies global cap
(`MAX_DRAFTS_PER_CYCLE = 3` unchanged). Spilled candidates record
`kill_stage="triage_cap"` with their score and source for dashboard
attribution.

Type plumbing: new `TriageCandidateBundle` dataclass in
`src/two_bot/types.py` (NB: named distinctly from the pre-existing
`src/editorial/candidates.py::CandidateBundle` which is a different
type — collision avoided).

Orchestrator wiring: new `_enqueue_candidate()` and
`_drain_and_write_triage_queue()` helpers in `src/orchestrator/common.py`.
The drain runs at end-of-cycle. A two-guard pattern prevents queue
persistence bugs: `bot_state.pop("_triage_queue", None)` at the top of
`run_alerts.py` (drops stale queues from crashed prior crons) plus
intentional absence from `src/storage/sqlite_store.py::_METADATA_JSON_KEYS`
allowlist (queue never round-trips through sqlite).

Triage exceptions fall through to legacy passthrough: if
`select_survivors` raises, the drain writes everything in queue order
and logs `[triage] error: ...`. The cycle still produces drafts.

Kill-switch defaults OFF in code (`THEHEAT_TRIAGE_ENABLED="0"`). This
PR is infrastructure-only — no source migrates here.

### Added — Codex source-hardening bug fixes (#133)

Three orthogonal source-side fixes surfaced by a Codex review pass:

- **Copernicus EMS flood classifier** — `_classify_severity` no longer
  auto-promotes OPEN activations to "Major" regardless of impact. The
  trailing `or not closed` clause is removed; Major requires population
  ≥ 100K **OR** area ≥ 100 km². New filter in `detect_flood_events`
  drops claimed Major/Extreme activations that don't meet impact
  thresholds. New named constant `MAJOR_AREA_THRESHOLD_KM2 = 100.0`.
- **NSIDC Snow Today** — `assert_freshness(reading_date, "NSIDC Snow
  Today", 7)` rejects data older than 7 days (was silently used).
  `detect_snow_extremes` now skips `delta <= 0` (snow MELT no longer
  counts toward "record snow gain"). Record comparison requires
  `previous_mm > 0` (no zero-baseline false records). `update_snow_tracking`
  mirrors the same `delta > 0` guard.
- **Disasters scoring** — `score_global_flood` caps severity at 58
  (below the 60 promote-to-drafting gate) when impact thresholds
  aren't met. Belt-and-suspenders with the Copernicus filter above.

All three reject low-quality signals BEFORE they reach the writer,
which is the right direction for cost — every blocked draft saves a
writer call.

A fourth Codex change (remove the "1st of month only" cadence
restriction in `src/orchestrator/sources/climate_indices.py`) was
parked on `wip/climate-indices-cadence` for separate review — it's a
cadence behavior change, not a bug fix, and shipping it before triage
fully matures would have increased per-cron writer-call volume in the
wrong direction.

### Added — coral_dhw triage migration + I2 telemetry + kill-switch ON (#134)

First source migrated to the triage path:

- `src/orchestrator/sources/coral_dhw.py` no longer calls
  `_try_two_bot_draft` directly. Instead, it builds a
  `TriageCandidateBundle` and calls `_enqueue_candidate`. The drain step
  handles ranking, capping, and writing.
- `state.update_coral_dhw_tier` and `state.increment_coral_dhw_annual_count`
  are moved into a new `on_draft_success` callback field on
  `TriageCandidateBundle` so they fire ONLY on actual draft success
  (preserves the spec § 7 contract: spilled candidates must re-detect
  on next cron — for coral_dhw, the tier update IS the re-detection
  cooldown).
- New `_bump_source_drafted_in_run` helper in
  `src/orchestrator/common.py` credits `candidate.source` for the
  `drafted` counter in `current_run["sources"][source]` when the drain
  step successfully writes a survivor. Fixes I2 from PR #132's code
  review — without this, migrated sources would have shown `drafted: 0`
  in the dashboard even when their candidates shipped.
- `.github/workflows/bot.yml` sets `THEHEAT_TRIAGE_ENABLED: "1"` —
  triage is now active in production. Rollback: set to `"0"` and push.

The kill-switch default in code stays `"0"`; only the CI env override
flips it on.

### Fixed — cron-blocking stale test fixture (#136)

`tests/test_coral_dhw.py::test_fetch_coral_dhw_uses_index_and_station_byte_ranges`
hardcoded `2026-05-13` as its data point. The freshness check added by
the Codex source-hardening pass (`assert_freshness(..., max_age_days=5)`)
correctly rejected anything older than 5 days. After the 2026-05-19
day-rollover, the fixture became 6 days old → test failed → the `run`
job (gated on `test`) skipped → the bot silently produced no drafts
for several scheduled crons. Fix: build fixture dates dynamically from
`date.today()`.

### Parked (no PR, branches preserved on remote)

- **`wip/fact-check-disposition-tightening`** (commit `3bc54bd`) — the
  Theme 6 fact-check disposition reversal toward primary-source-required.
  Held: contradicts the "fact-checker is generous on world knowledge"
  memory hook and would compound with the critic to push A-rate lower
  before triage can lift the ceiling. Resume criteria: after triage
  rolls out further and per-category steady-state observes, if
  over-acceptance becomes a visible problem at the human approval gate.
- **`wip/climate-indices-cadence`** (commit `697caa4`) — Codex's
  removal of the "1st of month only" cadence restriction on NAO/AO/PDO.
  Held: cadence change, not a bug fix; would increase per-cron volume.
  Resume criteria: after triage migrates at least 2-3 more sources and
  per-category caps are bounding NAO/AO/PDO promotion adequately.

### Operator action queued

GPM-IMERG is failing every cron with HTTP 401 (surfaced cleanly by the
#128 diagnostic). Either rotate `EARTHDATA_TOKEN` (Earthdata profile →
"Generate Token" → `gh secret set EARTHDATA_TOKEN`) or authorize the
GES DISC application in the Earthdata profile (most likely cause — a
valid bearer token alone is not enough; GES DISC needs explicit app
authorization). Next scheduled cron after the fix flips `gpm_imerg`
from `failed` to `success` in `source_health`.

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
