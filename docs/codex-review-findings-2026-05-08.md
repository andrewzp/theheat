# Codex Review Findings - 2026-05-08

Review target: `f96f4cb^..34459dc` on `main`, PRs #38-#45.

Note: while this review was running, `src/two_bot/intern.py`, `src/two_bot/prompts/writer_prompt.py`, and `tests/two_bot/test_intern.py` became dirty with uncommitted changes I did not make. Findings below are for the landed PR range at `34459dc`; any `src/two_bot/intern.py` line references are against `HEAD:src/two_bot/intern.py`.

## Findings

FINDING: Dashboard Gist draft actions still rewrite state through an old-key whitelist
LOCATION: `dashboard/lib/state-store.js:277`
SEVERITY: high
LIKELIHOOD: likely
EVIDENCE:
```js
277 function mergeState(current, incoming) {
280   return normalizeState({
281     last_hot10: structuredClone(next.last_hot10 || base.last_hot10),
292     suppressions: mergeSuppressions(base.suppressions, next.suppressions),
293   })
```
```js
669 nextDraft.updated_at = new Date().toISOString()
670 const latestState = await readGistState()
671 const mergedState = mergeDraftIntoState(latestState, nextDraft)
672 await writeGistState(mergedState)
```
CLAIM IN PR: 0.3.1.0 says the suppression ledger was mirrored in `dashboard/lib/state-store.js`, and the dashboard can safely read/write the shared state store.
WHAT'S WRONG: `mergeState()` reconstructs state from a fixed dashboard-era subset. On the Gist backend, every approve/reject/edit/auto-approve path goes through `updateDraftStore()` -> `mergeDraftIntoState()` -> `writeGistState()`, which rewrites `state.json` without Python-owned keys such as `memory`, `record_streaks`, `data_source_failures`, `ocean_sst_streak`, `ice_mass_*`, `fire_complex_tiers`, and `synthesis_*`. That means a dashboard click can erase the bot's continuity/reuse memory and source-failure counters.
FIX SKETCH: Change the JS merge to start from `structuredClone(base)` and overwrite only the keys it intentionally merges, or port the full Python `_merge_state()` key list into the dashboard store with tests for memory and lane-added keys.

FINDING: Python SQLite state round-trip drops two live state namespaces
LOCATION: `src/storage/sqlite_store.py:108`
SEVERITY: high
LIKELIHOOD: possible
EVIDENCE:
```py
108 _METADATA_JSON_KEYS = (
109     "co2_annual_count",
114     "record_streaks",
122     "synthesis_components",
123     "synthesis_cooldown",
124     "suppressions",
125 )
```
```py
154 # Lane-added JSON blobs...
156 for key in _METADATA_JSON_KEYS:
160     if row:
161         state[key] = json.loads(row["value_json"])
```
CLAIM IN PR: 0.3.1.0 says Python reuses `_METADATA_JSON_KEYS` for suppression persistence; 0.3.5.0 says state persistence now uses shared JSON serialization for future state values.
WHAT'S WRONG: `_METADATA_JSON_KEYS` still omits `memory` and `data_source_failures`, both live top-level keys in `src/state.py`. A local round-trip probe wrote non-empty values for both through `sqlite_store.write_state()` and read back defaults: empty memory lists and `{}` failure counters. On any sqlite-backed bot run, this resets the two-bot repetition guard and structural source-failure history at persistence time.
FIX SKETCH: Add `memory` and `data_source_failures` to `_METADATA_JSON_KEYS`, then add sqlite round-trip tests for both.

FINDING: Claim extraction still has no Gemini request timeout
LOCATION: `src/two_bot/claim_extractor.py:58`
SEVERITY: high
LIKELIHOOD: possible
EVIDENCE:
```py
56 from google import genai
58 client = genai.Client(api_key=api_key)
60 response = call_with_retries(
```
```py
100 def test_fact_check_timeout_is_in_milliseconds_range(self):
119 def test_writer_gemini_fallback_timeout_is_in_milliseconds_range(self):
```
CLAIM IN PR: 0.3.6.0 fixed the google-genai timeout unit bug after every Gemini fact-check timed out, and added source-introspection tests for the fixed paths.
WHAT'S WRONG: The same SDK is used in the mandatory claim-extractor stage, but this client has no `HttpOptions(timeout=...)` at all. In the installed SDK, `HttpOptions.timeout` defaults to `None`, and request construction passes that through as an unbounded per-request timeout. The regression test only covers fact-check and Gemini writer fallback, not claim extraction.
FIX SKETCH:
```diff
- from google import genai
+ from google import genai
+ from google.genai import types as genai_types

- client = genai.Client(api_key=api_key)
+ client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=90000))
```

FINDING: Suppression `stage` is persisted but not surfaced by the dashboard
LOCATION: `dashboard/app/page.js:938`
SEVERITY: medium
LIKELIHOOD: ~certain
EVIDENCE:
```js
938 <div className="card full">
939   <h2>Suppressed Signals ({suppressions.length})</h2>
941   Events the editorial gate killed before they reached the draft queue.
954   <span className="draft-type">{s.source || "—"}</span>
958   {s.category && <span className="supp-cat">{s.category}</span>}
```
```js
52 const sourceCounts = {}
53 for (const s of filtered) {
54   const key = s.source || "unknown"
55   sourceCounts[key] = (sourceCounts[key] || 0) + 1
```
CLAIM IN PR: 0.3.2.0 says each downstream suppression carries a `stage` discriminator and would have made the date-serialization pipeline error visible in the dashboard within minutes.
WHAT'S WRONG: The API returns raw suppression rows, but stats aggregate only by source, and the UI renders source/category/reasons without `stage`. Worse, the copy says these are "editorial gate" kills, which is false for `writer`, `fact_check`, `pipeline_error`, `city_cooldown`, and `cycle_cap`. The new discriminator exists in state but is effectively invisible to the operator scanning the dashboard.
FIX SKETCH: Add stage counts/filtering in `/api/suppressions`, render `stage` as the primary pill next to source, and update the card copy to cover post-score pipeline/save kills.

FINDING: Bundle enrichment turns daily extrema into time-of-day facts
LOCATION: `src/two_bot/intern.py:67`
SEVERITY: medium
LIKELIHOOD: possible
EVIDENCE:
```py
79 - ``observation_kind``: "overnight low" for TMIN-based bundles and
80   "afternoon high" for TMAX-based bundles. GHCN TMAX/TMIN are
81   24-hour extremes; these labels let the writer say "overnight low"
90 if kind == "low":
91     extra.append({"label": "observation_kind", "value": "overnight low"})
92 elif kind == "high":
93     extra.append({"label": "observation_kind", "value": "afternoon high"})
```
CLAIM IN PR: 0.3.8.0 says "TMIN IS the overnight low" and adds `observation_kind` so the writer/fact-checker can accept "night"/"afternoon" prose.
WHAT'S WRONG: GHCN TMIN/TMAX are daily 24-hour extrema, not timestamped observations. A cold front can set the daily minimum after sunrise; a warm nighttime event can set the maximum outside the afternoon. The new fact makes the fact-checker accept time-of-day prose the data does not prove. Also, despite the comment saying non-GHCN paths get an empty list, the helper appends `observation_kind` whenever `kind` is `"low"` or `"high"` even if `state` is absent.
FIX SKETCH: Use a source-neutral fact such as `daily_minimum` / `daily_maximum` or `24h_low` / `24h_high`; only add "overnight"/"afternoon" if a source provides hourly timing.

FINDING: GHCN observed records still expose legacy forecast metric labels
LOCATION: `src/two_bot/intern.py:132`
SEVERITY: medium
LIKELIHOOD: likely
EVIDENCE:
```py
132 metric_label = "forecast_high_c" if ev.kind == "high" else "forecast_low_c"
138 headline_metric={
139     "label": metric_label,
140     "value": ev.new_temp_c,
```
```py
213 headline_metric={
214     "label": "forecast_high_c" if kind == "high" else "observed_low_c",
215     "value": ev.new_temp_c,
```
CLAIM IN PR: 0.3.8.0 says bundle enrichment grounds the writer in GHCN station facts so the fact-checker accepts accurate prose.
WHAT'S WRONG: The same event dataclasses now serve both Open-Meteo forecasts and GHCN observed station readings, but the bundle builders still label monthly/all-time/calendar highs and monthly lows as `forecast_*`. For the GHCN path, that is false source semantics inside the writer's primary metric. It invites "forecast" wording for an already-observed NOAA reading and makes the bundle less precise right where this PR is trying to reduce hallucinations.
FIX SKETCH: Add a source/observation flag to the event or bundle-builder call and emit `observed_high_c` / `observed_low_c` for GHCN, keeping `forecast_*` only for Open-Meteo.

FINDING: JSON cleanup fallback is not string-aware and can corrupt accepted output
LOCATION: `src/two_bot/json_utils.py:31`
SEVERITY: low
LIKELIHOOD: edge
EVIDENCE:
```py
31 _TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
137 payload = extract_json_payload(raw, expected=expected)
141 cleaned = _strip_json_comments(payload)
142 cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
```
CLAIM IN PR: 0.3.5.0 says `loads_model_json()` is comment- and trailing-comma-tolerant while preserving shared parser safety.
WHAT'S WRONG: The trailing-comma regex runs over the whole JSON text after the first parse fails. If the payload has a legitimate string containing `,}` plus a trailing comma elsewhere, the fallback silently changes the string value. Probe: `loads_model_json('{"tweet":"a,}","kill_reason":null,}')` returns `{"tweet": "a}"}`. `extract_json_payload()` also returns the first balanced `{...}` span without checking whether it parses; a preamble like `Reason: {not json}` before the real object still fails even though a valid object follows.
FIX SKETCH: Replace the regex fallback with a character walker that tracks quoted strings, and when an extracted span fails to parse, continue scanning later spans before giving up.

FINDING: Station normalization mangles active acronym station names
LOCATION: `src/data/ghcn.py:113`
SEVERITY: low
LIKELIHOOD: possible
EVIDENCE:
```py
131 text = (raw or "").strip()
134 text = _WFO_PREFIX_RE.sub("", text)
135 text = _COOP_SUFFIX_RE.sub("", text)
136 text = _AIRPORT_SUFFIX_RE.sub("", text)
140 return text.title()
```
CLAIM IN PR: 0.3.7.0 says station-name normalization makes writer/fact-checker see the same clean place name.
WHAT'S WRONG: `.title()` lowercases acronyms after suffix stripping. The local station DB has an active `JFK INTL AP`; `normalize_station_name("JFK INTL AP")` returns `Jfk`. That can surface as `Jfk, New York, United States` if the station fires. Similar names such as `L A DOWNTOWN USC` become `L A Downtown Usc`.
FIX SKETCH: Preserve all-caps tokens of length 2-4, or special-case known airport/IATA-style station names before title-casing.

## Verified Working As Claimed

- #38 / 0.3.1.0: Python suppression state exists, merges by id, sorts by timestamp, caps at 200, and sqlite round-trips `suppressions`. Dashboard `/api/suppressions` exists with auth, limit, source, and since filters.
- #39 / 0.3.2.0: Writer and fact-check bundle JSON use shared `json_default`, so `date` values in `raw_signal_dump` serialize as ISO strings instead of crashing `json.dumps()`. Downstream suppression capture writes `stage` and kill reason for writer/fact-check/pipeline-error paths.
- #40 / 0.3.3.0: `strip_markdown_fences()` strips bare fences, `json`, and uppercase `JSON`; `extract_json_payload()` also handles fenced payloads with preamble text.
- #41 / 0.3.4.0: Balanced extraction handles nested objects and text after the JSON object better than first-`{`/last-`}` slicing. Anthropic writer timeout is 180 seconds.
- #42 / 0.3.5.0: `SourceFetchError` / `SourceSkipped` are wired across the main source fetch helpers, and `_fetch_strict()` routes live fetches through strict mode while preserving old test-double compatibility.
- #43 / 0.3.6.0: Fact-check Gemini uses `HttpOptions(timeout=90000)`, Gemini writer fallback uses `180000`, and the legacy voice generator path uses `180000`. `src/main.py` has no live `generator.generate_*` calls, only an unused import and comments.
- #44 / 0.3.7.0: The intended station-name cases are covered: `SISSONVILLE 1SW`, decimal direction suffixes, airport suffixes, and `WFO` prefixes normalize as claimed.
- #45 / 0.3.8.0: US state enrichment is appended to `where` and `current_facts` for the four temperature builders when a full state name is present; non-US stations do not get US state expansion.

## Deferred Items Check

- Cycle-cap / city-cooldown / same-day-dedup are no longer fully deferred. `save_draft()` now records `duplicate_draft`, `same_day_posted`, `same_day_dedup`, `same_day_superseded`, and `city_cooldown`; `_prune_weakest_cycle_drafts()` records `cycle_cap`. Tests cover city cooldown and cycle cap.
- Regional descriptors are still deferred. There is no lat/lon to region table for "Pacific Northwest", "Sahel", etc.; `expand_us_state()` is only a US state-code expansion.
- Writer-prompt tightening for speculative physical claims is still mostly deferred. The prompt has a generic "traceable to bundle or 95% general knowledge" rule, but no explicit guard for claims like "flowers are already up" or "the ground froze."

## Test Coverage Gaps

- Add sqlite round-trip tests for `memory` and `data_source_failures`.
- Add dashboard state-store tests proving draft actions preserve unknown/Python-owned top-level keys on Gist and sqlite backends.
- Extend `TestGeminiTimeoutUnit` to cover `src/two_bot/claim_extractor.py::_call_gemini`.
- Add suppression API/UI tests for `stage` stats, filtering, and visible rendering.
- Add `json_utils` tests for escaped quotes, braces inside strings, trailing commas inside strings, non-JSON brace preambles before valid JSON, and arrays before objects.
- Add station-normalization tests for active acronym/IATA names (`JFK INTL AP`) and all-caps non-airport abbreviations.
- Add bundle tests that distinguish GHCN observed metrics from Open-Meteo forecast metrics and avoid time-of-day facts without hourly data.
- Source-status tests cover representative helpers but not every strict-mode branch; add focused failures for GDACS, drought, ENSO, sea ice, ocean SST, water levels, and river gauges.

## Verification

- `git fetch origin` completed; local `main` matched `origin/main`.
- `git log --oneline f96f4cb^..HEAD` matched PRs #38-#45 and ended at `34459dc`.
- Targeted probe confirmed Python sqlite drops `memory` and `data_source_failures` while preserving `suppressions`.
- Targeted probe confirmed `claim_extractor.py` constructs `genai.Client(api_key=api_key)` without timeout; local installed `google-genai` has `HttpOptions.timeout` default `None`.
- Targeted probe confirmed `loads_model_json('{"tweet":"a,}","kill_reason":null,}')` silently returns `{"tweet": "a}"}`.
- Targeted test command: `.venv/bin/python -m pytest tests/test_state.py tests/test_ghcn.py tests/test_open_meteo.py tests/two_bot -q` produced `236 passed, 4 failed`. At the time of the run, the failures were from dirty, uncommitted `src/two_bot/intern.py` changes adding `value_f` to `headline_metric` while the tests still asserted exact dict equality. I did not modify or revert those files.
