# Changelog

All notable changes to this project will be documented in this file.

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
