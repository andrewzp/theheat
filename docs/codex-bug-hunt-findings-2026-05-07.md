# Codex Bug Hunt Findings - 2026-05-07

Scope: `src/`, `scripts/`, `dashboard/app`, and `dashboard/lib`, excluding `tests/`, `brand/`, and the stray `theheat/theheat/` artifact.

Verdict: no blocker found. The writer-side fixes from #39/#40/#41 are present, but the same boundary-failure shape still exists in adjacent LLM parsers, the FIRMS fire path, source health accounting, state serialization, and threshold refresh scripts.

## Summary table

| Severity | ~certain | likely | possible | edge | Total |
|---|---:|---:|---:|---:|---:|
| blocker | 0 | 0 | 0 | 0 | 0 |
| high | 0 | 4 | 3 | 0 | 7 |
| medium | 0 | 1 | 5 | 0 | 6 |
| low | 0 | 0 | 0 | 0 | 0 |
| Total | 0 | 5 | 8 | 0 | 13 |

## Findings

### FINDING: Claim extractor trusts strict JSON despite a prompt-only no-fence contract

LOCATION: `src/two_bot/claim_extractor.py:27`

SEVERITY: high

LIKELIHOOD: likely

EVIDENCE:

```py
27 def _parse_claims_json(raw: str) -> list[ExtractedClaim]:
28     try:
29         parsed = json.loads(raw)
30     except json.JSONDecodeError as exc:
31         print(f"[two_bot.claim_extractor] Invalid JSON response: {raw}")
```

WHY IT BITES: a valid Gemini response wrapped in ```json fences or preceded by "Here is the JSON" kills every otherwise-valid draft after the writer succeeds.

FIX SKETCH: introduce one shared tolerant JSON extractor that supports both top-level objects and arrays, then use it before `json.loads()` here.

### FINDING: Fact-checker trusts strict JSON despite the same model-actual mismatch

LOCATION: `src/two_bot/fact_check.py:33`

SEVERITY: high

LIKELIHOOD: likely

EVIDENCE:

```py
33 def _parse_fact_check_json(raw: str) -> tuple[bool, list[str]]:
34     try:
35         parsed = json.loads(raw)
36     except json.JSONDecodeError as exc:
37         print(f"[two_bot.fact_check] Invalid JSON response: {raw}")
```

WHY IT BITES: a fenced or prefaced Gemini fact-check response becomes a pipeline exception, so the draft dies instead of being accepted/rejected on content.

FIX SKETCH: reuse the same shared tolerant object parser that the writer now effectively has, and keep the type validation after parsing.

### FINDING: FIRMS fire drafts bypass downstream suppression capture

LOCATION: `src/main.py:1495`

SEVERITY: high

LIKELIHOOD: likely

EVIDENCE:

```py
1493 from src.two_bot.pipeline import generate_fire_draft
1495 draft = generate_fire_draft(fire, bot_state)
1496 if draft is None:
1497     continue
```

WHY IT BITES: writer kills, fact-check rejections, JSON parse failures, and API timeouts on the fire path still collapse to `None` and stdout, not a queryable suppression row.

FIX SKETCH: route FIRMS through `_try_two_bot_draft(...)` like every other two-bot source, or extend `generate_fire_draft(..., result_out=...)` and call `_record_downstream_suppression` on `None`.

### FINDING: Open-Meteo per-city failures disappear inside a green source run

LOCATION: `src/data/open_meteo.py:421`

SEVERITY: high

LIKELIHOOD: likely

EVIDENCE:

```py
421     except (requests.RequestException, KeyError, IndexError, ValueError):
422         return None
596 for city in to_check:
604     if bundle is None:
605         continue
```

WHY IT BITES: a partial Open-Meteo/archive outage can drop hundreds of city checks while `main.py` records `status="success"` using only promoted signal counts.

FIX SKETCH: return per-city attempt/failure metrics from `check_extreme_signals_for_cities()` and include them in `_record_source_run(details=...)`, marking the source degraded or failed when failures dominate.

### FINDING: Extreme-signal bundle build failures are swallowed before suppression recording

LOCATION: `src/main.py:645`

SEVERITY: high

LIKELIHOOD: possible

EVIDENCE:

```py
645 try:
656 except Exception as exc:
657     print(f"[two_bot.dispatch] Bundle build failed for {strongest_type}: {exc}")
658 return None
```

WHY IT BITES: a signal can pass scoring, then vanish before `_try_two_bot_draft()` has a chance to write a downstream suppression.

FIX SKETCH: when `_two_bot_bundle_for_extreme_signal()` returns `None` for a scored signal, record a suppression with `stage="bundle_build"` and the exception or missing-builder reason.

### FINDING: Fire footprint fetch errors are recorded as a successful once-daily run

LOCATION: `src/data/fire_footprint.py:105`

SEVERITY: high

LIKELIHOOD: possible

EVIDENCE:

```py
105 try:
106     resp = requests.get(GWIS_URL, timeout=30)
109 except Exception:
110     return []
1577 bot_state["fire_footprint_last_run"] = today_iso
```

WHY IT BITES: a NIFC/network/schema failure looks exactly like "no large fire complexes today" and also sets the once-per-day gate, preventing retry until tomorrow.

FIX SKETCH: make fetch failures distinguishable from empty results, record `status="failed"` or `status="degraded"`, and only update `fire_footprint_last_run` after a confirmed fetch.

### FINDING: FIRMS missing-key and request failures look like successful zero-fire days

LOCATION: `src/data/firms.py:73`

SEVERITY: high

LIKELIHOOD: possible

EVIDENCE:

```py
73 if not FIRMS_API_KEY:
74     return []
114 except (requests.RequestException, csv.Error, KeyError):
115     return []
```

WHY IT BITES: a missing `NASA_FIRMS_API_KEY` or FIRMS outage makes the dashboard source tile green with `observed=0`, while fire detection is actually disabled or broken.

FIX SKETCH: return a typed skipped/failed result from `fetch_fires()` or raise a source error so `main.py` can record `skipped` for no key and `failed` for transport/schema failures.

### FINDING: City cooldown and cycle-cap kills remain stdout-only

LOCATION: `src/main.py:547`

SEVERITY: medium

LIKELIHOOD: likely

EVIDENCE:

```py
547 if (
551     and _posted_city_within_days(drafts, city, CITY_COOLDOWN_DAYS)
552 ):
553     print(f"[draft] {city} in {CITY_COOLDOWN_DAYS}-day cooldown, skipping")
554     return False
```

WHY IT BITES: signals that pass the editorial score and writer/fact-check can still disappear due to cooldown, same-day collision, duplicate, or cycle pruning with no suppression-ledger explanation.

FIX SKETCH: add suppression records for `save_draft()` rejects and `_prune_weakest_cycle_drafts()` pruned drafts, with stages like `city_cooldown`, `same_day_dedup`, and `cycle_cap`.

### FINDING: LLM API boundaries still have no retry on timeout or transient provider failure

LOCATION: `src/two_bot/writer.py:152`

SEVERITY: medium

LIKELIHOOD: possible

EVIDENCE:

```py
152 client = anthropic.Anthropic(api_key=api_key, timeout=180.0)
153 response = client.messages.create(
159 return response.content[0].text
```

WHY IT BITES: a single transient `ReadTimeout`, 529, or Gemini transport blip still kills the draft; the suppression ledger may surface it, but the bot does not retry the boundary.

FIX SKETCH: wrap writer, claim extraction, and fact-check calls in a small bounded retry for provider timeout/temporary-unavailable errors, preserving the final failure reason if all attempts fail.

### FINDING: GHCN partial diff fetch failures are not visible in source telemetry

LOCATION: `src/data/ghcn.py:137`

SEVERITY: medium

LIKELIHOOD: possible

EVIDENCE:

```py
137 except requests.RequestException as e:
138     last_error = e
139     log.warning("GHCN diff fetch failed for %s via %s: %s", d, url, e)
142 return None
176 content = fut.result()
```

WHY IT BITES: if one lookback date fails but another succeeds, the GHCN source can still record success while silently missing station/date groups from the failed diff.

FIX SKETCH: include `diff_dates_attempted`, `diff_dates_fetched`, and `diff_dates_failed` in `ghcn_pipeline_metrics`, and mark the source degraded when any expected diff date fails.

### FINDING: Python state serializers still lack a JSON default and do not catch serialization TypeError

LOCATION: `src/state.py:596`

SEVERITY: medium

LIKELIHOOD: possible

EVIDENCE:

```py
592 normalized = _normalize_state(state)
596 json={"files": {STATE_FILENAME: {"content": json.dumps(normalized, indent=2)}}},
620 def write_state(state: dict) -> bool:
621     normalized = _normalize_state(state)
```

WHY IT BITES: any future date/datetime/set/dataclass that slips into drafts, run details, suppressions, or metadata can crash state persistence before the request is sent.

FIX SKETCH: move `_json_default` into a neutral shared utility and use it from `state.py` and `storage/sqlite_store.py`; catch `TypeError` as a state-write failure with a logged source error.

### FINDING: Other feed helpers collapse transport/schema failure into empty data and green runs

LOCATION: `src/data/nws_alerts.py:117`

SEVERITY: medium

LIKELIHOOD: possible

EVIDENCE:

```py
117 except (requests.RequestException, ValueError, KeyError):
118     return []
1702 _record_source_run(
1704     status="success", observed=len(alerts), promoted=source_promoted, drafted=source_drafted
```

WHY IT BITES: NWS, GDACS, CO2, sea ice, ocean SST, ocean, water-level, and river-gauge outages are indistinguishable from legitimately quiet feeds in dashboard health.

FIX SKETCH: standardize source fetch results as `{status, items, error, observed_attempts}` or raise typed source errors so `main.py` can distinguish `success`, `skipped`, `failed`, and `degraded`.

### FINDING: Incremental threshold updater can advance the watermark past failed diff dates

LOCATION: `scripts/update_thresholds_incremental.py:140`

SEVERITY: medium

LIKELIHOOD: possible

EVIDENCE:

```py
140 content = _fetch_diff(d)
141 if content is None:
142     print(f"  {d}: not available (NOAA may not have published yet)", flush=True)
143     continue
221 new_watermark = max(successful_dates) if successful_dates else watermark
225 set_meta(conn, META_WATERMARK_KEY, new_watermark.isoformat())
```

WHY IT BITES: a transient fetch failure for an earlier date can be treated like "not published" while a later date succeeds, permanently skipping the failed diff in the threshold DB.

FIX SKETCH: track attempted-but-missing dates separately and refuse to advance the watermark past the earliest missing date unless the operator explicitly allows gaps.

## No-finding notes by pattern

Pattern A - JSON serialization without `default=`:

- `src/two_bot/writer.py` uses `default=_json_default` for bundle and memory JSON.
- `src/two_bot/fact_check.py` uses `default=_json_default` when embedding the bundle JSON for Gemini.
- `src/two_bot/intern.py` still has many `asdict(...)` calls over dataclasses with `date | None` fields (`RecordEvent`, `MonthlyRecord`, `AllTimeRecord`, `AnomalyEvent`, `CountryRecord`, `FireComplex`), but current downstream serialization through writer/fact-check is protected. The remaining live risk is state persistence if non-native values are ever copied into state; see the state serializer finding.
- `dashboard/lib/state-store.js` uses `JSON.stringify`; I found `Date` construction only to produce ISO strings before storage and no `BigInt` writes.

Pattern B - `json.loads()` on LLM responses without tolerance:

- Writer parsing is tolerant for object responses via `_extract_json_payload`.
- Claim extractor and fact-checker are not tolerant; both are findings.
- `src/editorial/evaluator.py` strips fences but not preamble/postamble; I did not flag it because the legacy voice generator is not called from live `main.py` paths.
- Dashboard manual compose does not parse LLM JSON; it trims returned tweet text.

Pattern C - silent `except Exception: return None`:

- The two-bot live helper `generate_draft(..., result_out=...)` now preserves kill stage/reason when callers use it.
- The FIRMS fire path still bypasses that helper and is a finding.
- Top-level source loops generally record failed `_record_source_run(...)` when exceptions escape, but many source fetch helpers return empty data before exceptions can escape; those are covered in the source-health findings.

Pattern D - tight API timeouts/no retry:

- Anthropic writer timeout is now 180s, matching the new floor.
- Gemini writer remains 90s if `THEHEAT_WRITER_MODEL` is switched to a Gemini model; current default provider is Anthropic.
- Gemini fact-check is 90s and claim extraction has no explicit timeout. I did not flag the 90s value alone for Flash, but lack of retry across LLM calls is a finding.

Pattern E - prompt-strict vs model-actual mismatch:

- Writer prompt mismatch is covered by writer parser hardening.
- Claim extractor and fact-check prompts still say "Return ONLY" / "No markdown" while their parsers trust that instruction; both are findings.
- Voice-generator line-output parsing is not live in `main.py`; no live finding there.

Pattern F - source-level "OK" hides per-item failures:

- GHCN has source details and a capped event log, but partial diff fetch failure is not surfaced; finding included.
- Open-Meteo per-city failures are not counted or surfaced; finding included.
- Fire footprint and many other feed helpers flatten fetch failure into empty lists; findings included.

## Next steps

Needs code changes:

1. Shared tolerant JSON extraction for object and array outputs, wired into claim extraction and fact-check.
2. Route FIRMS through `_try_two_bot_draft` or otherwise record downstream suppressions on `generate_fire_draft() == None`.
3. Add typed source fetch results/errors so empty data, skipped credentials, transport failure, schema failure, and per-item failure are different states.
4. Add suppression stages for bundle-build failures, cooldown/same-day/dedup rejects, and cycle-cap pruning.
5. Add JSON-safe state dumping for Python Gist and SQLite state writes.
6. Harden `scripts/update_thresholds_incremental.py` watermark advancement around missing/failed diff dates.

Acceptable as-is for now:

- `asdict(...)` in `src/two_bot/intern.py` as long as all serialization paths continue using the writer/fact-check default handler and raw bundles are not persisted into state.
- 90s Gemini Flash timeout for fact-check if it stays a short structured-output call, but only after adding retry and structured failure recording.
- `src/voice/generator.py` parser weaknesses, provided no live code path starts calling it again.
