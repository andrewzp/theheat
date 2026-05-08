# Codex Code Review — 2026-05-08 batch (PRs #38–#45)

Repo: `~/Documents/Claude/theheat` (github.com/andrewzp/theheat).
Date authored: 2026-05-08.

## Why this review exists

A 4-day production outage (drafts vanishing silently) was finally resolved over a single 13-hour debugging session. Nine PRs landed in that window, layered fast and reactively. The author of the change set is asking you for an independent code review specifically because the *pattern* of those bugs was "I missed the class of issue and only fixed the surface" — and that pattern probably hasn't fully stopped yet.

Your job: catch the bugs they didn't.

## Scope

Review every commit landed on `main` from the start of `f96f4cb` (PR #38) through HEAD. Concretely:

```bash
git log --oneline f96f4cb^..HEAD
```

The PR titles are:

- #38 — `feat: suppression ledger + dashboard health-calc fix`
- #39 — `fix(ghcn): date serialization in two-bot + downstream suppression capture`
- #40 — `fix(writer): strip markdown code fences from Sonnet output`
- #41 — `fix(writer): tolerant JSON extraction + bump timeout 90s -> 180s`
- #42 — `fix: codex bug-hunt sweep — boundary hardening + observability`
- #43 — `fix(gemini): HttpOptions.timeout is milliseconds — was passing 90ms instead of 90s`
- #44 — `fix(ghcn): normalize station names so fact-checker accepts shortened forms`
- #45 — `feat(bundle): enrich GHCN bundles with state name + observation kind`

Read the CHANGELOG entries 0.3.0.0 through 0.3.8.0 in `CHANGELOG.md` for the framing each PR claimed. **Then verify the claims hold.**

## What to focus on

Five lenses, ordered by leverage. Spend more time on the early ones.

### 1. Correctness & edge cases on the new shared modules

Three new files came out of #42 and got wired into many places. Review their internals AND every callsite.

- `src/two_bot/json_utils.py`
  - `json_default()` — does it cover every non-JSON-native type that could leak into the bundle or state? What about `pathlib.Path`, `uuid.UUID`, `numpy` scalars (we don't ship numpy now but check), `enum.Enum`, complex nested dataclass-of-dataclass cases?
  - `extract_json_payload()` — the `_matching_json_span` walker. Does it handle escaped quotes inside strings (`"foo \"bar\" baz"`)? Apostrophes? Multi-byte UTF-8? Strings containing `{` or `}` characters? What if the model emits an array followed by an object (returns first only — is that right)?
  - `loads_model_json()` — the comment-and-trailing-comma fallback. Does it accept comments INSIDE string values it shouldn't strip? Does the trailing-comma regex eat a comma inside a string?
  - `strip_markdown_fences()` — what if the model wraps in `\`\`\`python` or `\`\`\`text`? Currently only `\`\`\`json` and `\`\`\`` (no lang) are handled. Should non-json fences also strip?

- `src/two_bot/retry.py`
  - `call_with_retries()` — catches `Exception` broadly. That retries `ValueError` (e.g. invalid-JSON-after-retry-N), `RuntimeError` (e.g. missing API key), `TypeError`. Should these be non-retryable? What's the user-facing behavior when an API key is missing — 3 retries with 1s/2s/4s sleeps before failing? That's pure waste.
  - The `2 ** (attempt - 1)` backoff doesn't cap. With `attempts=5` you get 1, 2, 4, 8, 16 = 31s of sleep. Acceptable today, problematic if attempts ever increases.
  - No jitter. Multiple parallel callers retry in lockstep.

- `src/data/source_status.py`
  - Just two exception classes. Verify they're imported and raised consistently across `firms.py`, `fire_footprint.py`, and check whether OTHER source helpers (`co2.py`, `ocean.py`, `nws_alerts.py`, `gdacs.py`, `drought.py`, `enso.py`, `sea_ice.py`, `ice_mass.py`, `water_levels.py`, `river_gauges.py`, `ocean_sst.py`) should also be raising them. The Codex bug-hunt findings doc claimed they were standardized — verify.

### 2. The Gemini timeout fix (#43)

The bug was: `google-genai` `HttpOptions.timeout` is milliseconds, not seconds. Three sites were passing `90` (= 90ms) and `180` (= 180ms). All three were bumped to `90000` / `180000`.

Review:

- `src/two_bot/fact_check.py:63` — `timeout=90000`. Is 90s appropriate, or should it match writer's 180s? The fact-check prompt is shorter (single tweet + bundle JSON) so 90s seems fine, but verify by reading the prompt size in `src/two_bot/prompts/fact_check_prompt.py`.
- `src/two_bot/writer.py:112` — Gemini fallback writer at 180s. Fine.
- `src/voice/generator.py:743` — voice gen at 180s. The PR notes this is dead code — verify there are no live callers in `src/main.py` (the briefing claims the voice generator is no longer reached on any live path).
- `src/two_bot/claim_extractor.py:58` — `genai.Client(api_key=api_key)` with NO timeout config. Does it use the SDK default? What IS the SDK default — bounded or unbounded? If unbounded, this is a hang risk that the unit-of-measure fix didn't address.

The regression test at `tests/two_bot/test_fact_check.py::TestGeminiTimeoutUnit` introspects the source for `HttpOptions(timeout=NNN)`. **Does it cover `claim_extractor.py`?** If no — that's a gap.

### 3. Backward compatibility on the dataclass changes

Two PRs added optional fields with defaults:

- #39: `signal_date: date | None = None` on RecordEvent / MonthlyRecord / AllTimeRecord / AnomalyEvent / RecordStreakEvent / CountryRecord; `station_id` and `station_name` on `ExtremeSignalBundle`.
- #45: `state: str | None = None` on RecordEvent / MonthlyRecord / AllTimeRecord / AnomalyEvent.

For each: **check every callsite that constructs these dataclasses positionally instead of by keyword.** Python dataclasses with mixed required + optional fields are sensitive to positional construction. New optional fields appended at the end are safe; new optional fields inserted in the middle are not.

Search candidates:
```bash
grep -rn "RecordEvent(\|MonthlyRecord(\|AllTimeRecord(\|AnomalyEvent(\|CountryRecord(" src/ tests/ | grep -v "import"
```

Check that no callsite passes positional args that would silently shift onto the new field.

### 4. Suppression ledger semantics

Today's centerpiece. Review:

- `src/main.py::_record_suppression` (score_gate, the original) and `_record_downstream_suppression` (writer / fact_check / pipeline_error). Are the schemas actually compatible? Will the dashboard render both cleanly?
- The `stage` field discriminator was added in #42. Verify `dashboard/app/page.js` and `dashboard/app/api/suppressions/route.js` actually surface it in the UI. Schema is forward-compatible (additive), but if the dashboard sums/groups by category alone, the new stage info is invisible.
- Deduplication: 200-record cap with id-keyed merge. What if `_record_*_suppression` is called inside a loop over many bundles in a single cron — does the same `(stage, event_id)` pair get recorded multiple times across runs? Should it?
- Cycle-cap / city-cooldown / same-day-dedup kills are explicitly out of scope. Verify they're still *visible* somewhere (run logs, dashboard's per-bundle event log) so they're not double-invisible after this work.

### 5. Station-name normalization (#44)

The fix at `src/data/ghcn.py::normalize_station_name`:

- `_COOP_SUFFIX_RE` matches `\d+(?:\.\d+)?[NSEW]{1,3}$`. What about edge cases like:
  - `"FOO 123N"` — three-digit distance, only 1 letter. Matches.
  - `"FOO 1NNW"` — 3-letter compound direction. Matches per the regex.
  - `"FOO NNW"` (no distance) — does NOT match. Is that right?
  - `"FOO 1.5SSE 2"` — trailing whitespace + something else. Probably edge.
- `_AIRPORT_SUFFIX_RE` matches `(?:INTL|INTERNATIONAL|MUNI|...)?\s*AP$`. What about:
  - `"NEWARK INTERNATIONAL"` (no `AP` suffix) — pass-through. Is that what we want, or should we strip the modifier?
  - `"FOO AP" but not "AP" alone` — verify the leading `\s+` prevents whole-name match.
- `text.title()` mangling: `"JFK INTL AP"` → strips to `"JFK"` → `.title()` → `"Jfk"`. Bad output. The PR notes accept this. Should there be a follow-up special case for known IATA codes, or is the bundle's `where` field never going to surface "Jfk" anyway because... why? Verify.
- The fallback `if not text: return raw` — what if the input was `"   "`? After stripping it's empty. Returns the original whitespace? The test claims it returns empty. Verify which.

### 6. Bundle enrichment (#45)

`expand_us_state()` is US-only. Other countries (Canadian provinces, German Länder, Brazilian states, Indian states) get None. Is that the right call, or should the writer get *some* sub-national info for foreign stations? The fact-checker rejected "inland Pacific Northwest" — that's a *region* not a state, and the current solution doesn't address regions at all. The PR explicitly defers regional descriptors. Verify nothing else relies on the assumption that `state` would be set for non-US.

`_format_where()` always puts state in the middle: `"city, state, country"`. Does this read naturally for the writer prompt? The fact-check prompt says "verify exact match" — if the writer picks "Sissonville, WV" instead of "Sissonville, West Virginia", does the fact-checker reject the abbreviation? The PR adds the full name; verify there's no callsite where the abbreviation gets surfaced too.

The `observation_kind` value is hardcoded to "overnight low" / "afternoon high". GHCN TMIN/TMAX are 24-hour extremes — most of the time these labels are accurate, but in unusual weather (cold front passes through midday, warm air mass overnight) the actual extreme might be at the opposite time. Is the bot ever going to produce a tweet that says "overnight low of -2C" when the actual TMIN was at 10am? If so, mild factual hallucination. Acceptable? Document the known imprecision.

## Output format

Markdown report at `docs/codex-review-findings-2026-05-08.md`. Each finding:

```
FINDING: <short title>
LOCATION: <file:line>
SEVERITY: blocker | high | medium | low
LIKELIHOOD: ~certain | likely | possible | edge
EVIDENCE: <2-3 lines of code, with line numbers>
CLAIM IN PR: <what the PR description / changelog said about this code>
WHAT'S WRONG: <one-paragraph explanation>
FIX SKETCH: <inline diff if 1-3 lines, else 1-sentence direction>
```

Sort: blocker × ~certain first.

Also include:
- A "verified working as claimed" section for each PR with at least one observation that confirms the claim holds.
- A "deferred items still actually deferred" check — the PRs explicitly defer cycle-cap suppression / regional descriptors / writer-prompt tightening / etc. Verify those things are genuinely still missing rather than half-implemented.
- A "test coverage gaps" section — for each new file or function, list any obvious test cases that exist for similar code but not this code.

## What's off-limits

- Don't propose architectural rewrites (Anthropic tool-use / response_format mode, structured output schemas, decoupling intern from event dataclasses, etc.). Flag the bug *class* once if you see it; don't gate the report on a refactor.
- Don't review `brand/` (locked).
- Don't review tests of legacy code (`src/voice/generator.py`) unless you find evidence it's reachable from a live path.
- Don't ask for the runtime to verify against. Trust the test suite as the source-of-truth contract.
- Don't propose stylistic preferences. The author writes terse comments; respect that.

## What to spend extra time on

The author already missed at least four classes of bug today before getting to the actual root cause. The pattern was: fix the surface, miss the unit-of-measure / config / multi-call coverage / boundary-not-just-symptom.

If you find yourself thinking "well, this looks fine," try:
- Could this fail with a different value than the test happens to use?
- Could this fail in a future code path that's likely to be added?
- Is the fact-checker / writer / claim-extractor *actually* covered, or is one path symmetric to a fixed one but un-fixed?
- Does the dashboard / Gist / SQLite-roundtrip see the same thing as the in-process Python view?

## Working agreement

- 1-3 line diffs: include them inline.
- 4+ line changes: 1-sentence direction, no full diff.
- If you're <70% sure: include the finding with `LIKELIHOOD: possible` and let the author decide.
- If something is fine, say so explicitly — silence is ambiguous.
- The author runs `pytest -x -q` for verification. Targeted commands welcome.

The current state at the start of this review: 9 PRs landed, suite passing 800+, drafts not yet flowing as of the latest verification cycle (run on commit `34459dc`, mode=alerts). A natural next move after your review is whatever class of fix you flag highest, plus writer-prompt tightening for pure speculative hallucinations ("flowers up", "ground froze") that bundle enrichment cannot fix.
