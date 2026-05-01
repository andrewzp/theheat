# Two-Bot Architecture — Codex Execution Spec

**Date:** 2026-04-30
**Status:** Approved design, ready for execution. Codex should be able
to implement this end-to-end without further questions.
**Scope:** First build = **fire signals only.** Replaces the entire
`fire` path in the generator pipeline. All other signal types (heat
records, CO2, ice, ocean, drought, etc.) remain on the existing
pipeline and are out of scope.

---

## 1. Context & motivation

TheHeat's current fire pipeline puts the cheapest model in the most
demanding seat. Gemini Flash receives a raw FIRMS detection and a
category-specific prompt, and is expected to do *both* editorial
judgment and writing. Sonnet 4.6 only enters as a rewriter when
Gemini's draft fails the evaluator — anchored on a bad starting point.

Result (see `docs/DRAFT_CORPUS.md`): drafts ship with textbook stock
formulas ("a large nuclear reactor generates 1,000 MW"), reused era
anchors, and no awareness of ongoing events. Posting paused since
Apr 12. Resumption bar (majority of cycle drafts earn A grades) is 0%.

The fix is a role inversion:

- **Cheap model = climate data engineer + fact-checker.** Gathers
  context, verifies claims. No prose generation.
- **Great model = senior editor + writer.** Picks the angle, writes
  the tweet using its own world knowledge. One pass.
- **Memory = persistent state across cycles.** No reuse of any
  era anchor, peer-class comparison, framing, or tweet text. Ever.

## 2. Pipeline overview

```
FIRMS detection
  │
  ▼
[Stage 1] INTERN  (Gemini Flash, structured JSON output)
  Input: FireEvent + access to historical FIRMS context
  Output: StoryBundle (facts only — no angle proposals)
  │
  ▼
[Stage 2] MEMORY AUGMENT
  Adds to bundle:
    - recent fire tweets about this country (last 30 days)
    - ongoing fire-event state for this region
    - do-not-reuse inventory
  │
  ▼
[Stage 3] WRITER  (Sonnet 4.6, configurable)
  Input: bundle + memory slice + voice prompt + Economist framing
  Output: final tweet text OR null
  │
  ▼
[Stage 4] FACT-CHECKER  (Gemini Flash)
  Input: writer's tweet + bundle + do-not-reuse inventory
  Output: pass / fail + reasons
  Strict: any unverifiable claim or any reuse → kill
  │
  ▼
[Stage 5] MEMORY WRITE-BACK
  Persists: tweet text, era anchors used, peer-class comparisons used,
  framings used, ongoing-event state.
  │
  ▼
state.json drafts queue (status: pending)
```

## 3. File inventory

### New files

| Path | Purpose |
|---|---|
| `src/two_bot/__init__.py` | Package |
| `src/two_bot/intern.py` | Stage 1 — story bundle assembly |
| `src/two_bot/memory.py` | Stage 2 + 5 — memory layer |
| `src/two_bot/writer.py` | Stage 3 — Sonnet writer |
| `src/two_bot/fact_check.py` | Stage 4 — Gemini fact-checker |
| `src/two_bot/pipeline.py` | Orchestrates all 5 stages |
| `src/two_bot/types.py` | Dataclasses: `StoryBundle`, `MemorySlice`, `WriterResult`, `FactCheckResult` |
| `src/two_bot/historical_context.py` | Computes `historical_context` fields from FIRMS archive |
| `src/two_bot/prompts/writer_prompt.py` | Full writer system prompt (constant) |
| `src/two_bot/prompts/fact_check_prompt.py` | Full fact-check system prompt (constant) |
| `src/two_bot/prompts/intern_prompt.py` | Full intern system prompt (constant) |
| `tests/two_bot/__init__.py` | Package |
| `tests/two_bot/test_intern.py` | Stage 1 tests |
| `tests/two_bot/test_memory.py` | Stage 2/5 tests |
| `tests/two_bot/test_writer.py` | Stage 3 tests (mocked LLM) |
| `tests/two_bot/test_fact_check.py` | Stage 4 tests (mocked LLM) |
| `tests/two_bot/test_pipeline.py` | End-to-end integration tests |
| `tests/two_bot/test_historical_context.py` | Historical computation tests |

### Modified files

| Path | Change |
|---|---|
| `src/main.py` | In `run_alerts`, replace the fire branch (`generator.generate_fire_tweet(...)`) with `two_bot.pipeline.generate_fire_draft(...)`. Other categories untouched. |
| `src/state.py` | Extend `DEFAULT_STATE` with a `"memory"` key (schema in §6). Add helpers `get_memory(state)` / `set_memory(state, memory)`. |
| `requirements.txt` | No new runtime deps. (anthropic, google-genai already present.) |
| `pytest.ini` or `pyproject.toml` | Ensure `tests/two_bot` is discovered (default config should already do this — verify). |

### Files NOT to modify

- `src/voice/generator.py` — `generate_fire_tweet` stays for now but is
  no longer called for fire. Leave it in place; other code paths (tests,
  manual tweet flow) may reference it. **Do not delete.** If it has no
  remaining callers after wiring, log that fact in the PR description but
  still do not delete in this PR.
- `src/editorial/evaluator.py` — untouched. Other categories still use
  the evaluator. The `evaluate_and_polish` rewrite loop runs only for
  non-fire categories.
- All other `src/data/*.py` — untouched.

## 4. Dataclasses (`src/two_bot/types.py`)

```python
"""Type definitions for the two-bot pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoryBundle:
    """The intern's output. Pure facts; no editorial angles."""
    signal_kind: str  # "fire" for first build
    where: str  # "Mali", "Southwestern US", etc.
    when: str  # ISO date "2026-04-30"
    event_id: str
    headline_metric: dict[str, Any]  # {"label", "value", "unit"}
    current_facts: list[dict[str, Any]]  # [{"label", "value", "unit"?}]
    historical_context: dict[str, Any]  # see §5
    raw_signal_dump: dict[str, Any]  # full source data

    def to_dict(self) -> dict:
        return {
            "signal_kind": self.signal_kind,
            "where": self.where,
            "when": self.when,
            "event_id": self.event_id,
            "headline_metric": self.headline_metric,
            "current_facts": self.current_facts,
            "historical_context": self.historical_context,
            "raw_signal_dump": self.raw_signal_dump,
        }


@dataclass
class MemorySlice:
    """The memory layer's contribution to the writer's context."""
    recent_tweets_same_country: list[str] = field(default_factory=list)
    ongoing_event: dict | None = None  # event id, days running, last seen
    used_era_anchors: list[str] = field(default_factory=list)
    used_peer_comparisons: list[str] = field(default_factory=list)
    used_framings: list[str] = field(default_factory=list)
    shipped_tweet_texts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "recent_tweets_same_country": self.recent_tweets_same_country,
            "ongoing_event": self.ongoing_event,
            "used_era_anchors": self.used_era_anchors,
            "used_peer_comparisons": self.used_peer_comparisons,
            "used_framings": self.used_framings,
            "shipped_tweet_texts": self.shipped_tweet_texts,
        }


@dataclass
class WriterResult:
    """The writer's output."""
    tweet: str | None  # None means "signal didn't earn extraordinary"
    angle_chosen: str  # short label e.g. "off_season_irony"
    era_anchor_used: str | None
    peer_comparison_used: str | None
    reasoning: str  # one-sentence explanation

    def to_dict(self) -> dict:
        return {
            "tweet": self.tweet,
            "angle_chosen": self.angle_chosen,
            "era_anchor_used": self.era_anchor_used,
            "peer_comparison_used": self.peer_comparison_used,
            "reasoning": self.reasoning,
        }


@dataclass
class FactCheckResult:
    passed: bool
    failures: list[str]  # human-readable reasons
    raw_response: str  # full LLM response, for debugging

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "raw_response": self.raw_response,
        }
```

## 5. Stage 1 — Intern (`src/two_bot/intern.py`)

### Responsibility

Take a `FireEvent` and produce a `StoryBundle`. The bundle is *pure
facts*: signal data + historical climate context. No editorial framings.

### Function

```python
def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a StoryBundle for a fire signal.

    Calls historical_context.compute_fire_context(fire) to populate
    historical_context. The intern model itself (Gemini Flash) is NOT
    called in this build — historical_context is computed deterministically
    from FIRMS archive queries. We reserve the intern-as-LLM role for
    future signal types where context is harder to specify.
    """
```

**Key design note:** in this first build, the intern does **not** call
Gemini. `build_fire_bundle` is deterministic — it pulls historical
context from `historical_context.compute_fire_context()`. We chose this
because (a) fire context is well-specified (percentiles, seasonal peak,
recent-similar-events) and (b) deterministic context is easier to test
and debug than LLM-generated context. The "intern as LLM" pattern is
preserved for later signal types if needed; the fact-checker role still
uses Gemini, which preserves the principle of using the cheap model for
structured low-creativity work.

### Bundle for fire — exact field list

```python
StoryBundle(
    signal_kind="fire",
    where=fire.nearest_city,  # may be country if no city
    when=date.today().isoformat(),
    event_id=fire.event_id,
    headline_metric={"label": "FRP", "value": fire.frp, "unit": "MW"},
    current_facts=[
        {"label": "satellite_confidence", "value": fire.confidence, "unit": "%"},
        {"label": "country", "value": fire.country},
        {"label": "nearest_region", "value": fire.nearest_city},
        {"label": "lat", "value": fire.lat},
        {"label": "lon", "value": fire.lon},
    ],
    historical_context={
        # All optional — None if not computable
        "frp_percentile_country_month": float | None,
        "is_country_april_record": bool,  # generic month, not just april
        "country_record_year": int | None,
        "country_fire_season_peak_month": int | None,
        "weeks_past_seasonal_peak": int | None,
        "similar_events_country_30d": int,
        "similar_events_country_365d": int,
    },
    raw_signal_dump={
        "lat": fire.lat, "lon": fire.lon,
        "confidence": fire.confidence, "frp": fire.frp,
        "nearest_city": fire.nearest_city, "country": fire.country,
        "event_id": fire.event_id,
    },
)
```

## 6. Historical context (`src/two_bot/historical_context.py`)

### Approach

For first build, use a **static reference table** of country-month FRP
distributions, computed once from FIRMS archive and committed to the
repo. Refresh quarterly via a separate script. Live FIRMS queries for
"recent similar events" use a 30/365-day rolling cache in
`state.json` under `state["memory"]["fire_archive_cache"]`.

This avoids per-tweet network round-trips to FIRMS archive, which can
be slow and rate-limited.

### Data file

```
data/fire_country_month_distribution.json
```

Schema:

```json
{
  "_meta": {
    "computed_at": "2026-04-30",
    "source": "FIRMS VIIRS archive 2012-2026",
    "method": "Per-country, per-month: count of detections, p50/p90/p95/p99 FRP"
  },
  "ML": {
    "1": {"count": 1234, "p50": 12.0, "p90": 80.0, "p95": 150.0, "p99": 320.0},
    "2": {...},
    ...
  },
  "US": {...},
  ...
}
```

For the **first build**, this file may be **stub data** (a small
hand-curated table covering the top 20 fire-prone countries). Codex
should:

1. Create a stub file with **at least 20 country codes**: US, CA, RU,
   AU, BR, ID, IN, MX, CN, AR, CL, MZ, AO, ZA, ML, NE, TD, SD, ET, KE.
2. For each, fill 12 months with placeholder values:
   `{"count": 1000, "p50": 10.0, "p90": 80.0, "p95": 200.0, "p99": 500.0}`.
3. Note in `_meta`: `"method": "PLACEHOLDER — replace with computed
   distribution before promoting beyond first build"`.
4. Add a `scripts/compute_fire_distribution.py` skeleton (file,
   docstring, NotImplementedError) for future actual computation.

### Functions

```python
def compute_fire_context(fire: FireEvent) -> dict:
    """Return the historical_context dict for the bundle.

    Pulls from data/fire_country_month_distribution.json and from the
    in-state recent-events cache. Returns dict matching the schema in
    StoryBundle.historical_context.
    """

def country_fire_season_peak_month(country_code: str) -> int | None:
    """Return the month (1-12) with the highest historical detection
    count for the country, or None if the country isn't in the table."""

def percentile_for_frp(country_code: str, month: int, frp: float) -> float | None:
    """Return the percentile (0-100) of an FRP value for that country
    and month. Linear interpolation between p50/p90/p95/p99. Returns
    None if the country isn't in the table."""

def is_country_record_for_month(
    country_code: str, month: int, frp: float, recent_events: list[dict]
) -> tuple[bool, int | None]:
    """Return (is_record, year_set). Compares the current FRP to the
    p99 cutoff and to recent events from cache. Approximate; refine
    when the static table is replaced by computed distributions."""
```

### Tests

```python
# tests/two_bot/test_historical_context.py
def test_country_fire_season_peak_month_known_country():
    # ML (Mali) peak should be in Jan-Mar (dry season)
    peak = country_fire_season_peak_month("ML")
    assert peak in {1, 2, 3, 4}

def test_country_fire_season_peak_month_unknown_country():
    assert country_fire_season_peak_month("ZZ") is None

def test_percentile_for_frp_p99_or_above():
    pct = percentile_for_frp("ML", 4, 1000.0)  # well above p99
    assert pct >= 99.0

def test_percentile_for_frp_unknown_country():
    assert percentile_for_frp("ZZ", 4, 100.0) is None

def test_compute_fire_context_returns_required_keys(monkeypatch):
    fire = FireEvent(lat=14.5, lon=-3.5, confidence=95, frp=361.0,
                     nearest_city="Timbuktu", country="ML",
                     event_id="fire_test")
    ctx = compute_fire_context(fire)
    required = {"frp_percentile_country_month", "is_country_april_record",
                "country_record_year", "country_fire_season_peak_month",
                "weeks_past_seasonal_peak", "similar_events_country_30d",
                "similar_events_country_365d"}
    assert required.issubset(ctx.keys())
```

## 7. Stage 2/5 — Memory layer (`src/two_bot/memory.py`)

### Storage

Memory lives in `state["memory"]`. The state object is already persisted
to GitHub Gist via `src/state.py`.

### Schema

Add to `DEFAULT_STATE` in `src/state.py`:

```python
"memory": {
    "ongoing_events": [],       # list of {event_id, region, country,
                                # first_seen, last_seen, days_running,
                                # signal_kind}
    "used_era_anchors": [],     # list of strings, lowercased, dedup
    "used_peer_comparisons": [], # list of strings, lowercased, dedup
    "used_framings": [],        # list of strings (short labels)
    "shipped_tweets": [],       # list of {tweet_text, signal_kind,
                                # event_id, country, shipped_at}
    "fire_archive_cache": {     # 30/365-day rolling FIRMS context
        "by_country": {},       # {country_code: [{event_id, frp,
                                # detected_at, lat, lon}, ...]}
        "last_refreshed": None,
    },
}
```

### Functions

```python
def build_memory_slice(state: dict, bundle: StoryBundle) -> MemorySlice:
    """Assemble the relevant memory for the writer.

    For fire signals:
    - recent_tweets_same_country: shipped_tweets where country matches,
      last 30 days. Limit 5 most recent.
    - ongoing_event: any ongoing_events row matching this region/event.
    - used_era_anchors / used_peer_comparisons / used_framings: 200
      most recent each, INCLUDED IN THE PROMPT to give the writer a
      visible do-not-reuse window. The full underlying lists (any
      length) are still authoritative for fact-checker enforcement —
      see fact_check.py, which reads memory directly via the
      authoritative state, not via the slice.
    - shipped_tweet_texts: last 100 shipped tweets (any category) for
      novelty cross-check in the writer prompt. Fact-checker again
      uses the full list from state for deterministic enforcement.
    """

def record_shipped(state: dict, bundle: StoryBundle, writer: WriterResult) -> None:
    """Stage 5 — write back. Mutates state in place.

    - Append to shipped_tweets.
    - If writer.era_anchor_used: lowercase + append to used_era_anchors.
    - If writer.peer_comparison_used: same.
    - Append writer.angle_chosen to used_framings.
    - Update or insert into ongoing_events for this event_id.
    """

def is_reuse(memory: MemorySlice, candidate: str, kind: str) -> bool:
    """Check if a candidate string matches a forever-banned element.
    Case-insensitive substring + token-overlap matching for era anchors
    and peer comparisons; exact-match for framings.
    kind: 'era_anchor' | 'peer_comparison' | 'framing' | 'tweet_text'
    """
```

### Tests

```python
def test_build_memory_slice_filters_by_country():
    state = _state_with_shipped_tweets([
        ("US fire tweet 1", "US"), ("Mali fire tweet 1", "ML"),
        ("Mali fire tweet 2", "ML"), ("Brazil tweet", "BR"),
    ])
    bundle = _bundle(country="ML")
    slice = build_memory_slice(state, bundle)
    assert len(slice.recent_tweets_same_country) == 2

def test_record_shipped_appends_era_anchor():
    state = _empty_memory_state()
    writer = WriterResult(tweet="...", angle_chosen="rarity",
                          era_anchor_used="Spider-Man 2002",
                          peer_comparison_used=None, reasoning="...")
    bundle = _bundle()
    record_shipped(state, bundle, writer)
    assert "spider-man 2002" in state["memory"]["used_era_anchors"]

def test_is_reuse_case_insensitive():
    memory = MemorySlice(used_era_anchors=["spider-man 2002"])
    assert is_reuse(memory, "Spider-Man 2002", "era_anchor")
    assert is_reuse(memory, "the year Spider-Man 2002 came out", "era_anchor")
    assert not is_reuse(memory, "Spider-Man 3", "era_anchor")

def test_is_reuse_framing_exact_match_only():
    memory = MemorySlice(used_framings=["off_season_irony"])
    assert is_reuse(memory, "off_season_irony", "framing")
    assert not is_reuse(memory, "off_season", "framing")
```

## 8. Stage 3 — Writer (`src/two_bot/writer.py`)

### Configuration

```python
WRITER_MODEL = os.environ.get("THEHEAT_WRITER_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
```

If `WRITER_MODEL` starts with `claude-`, use the Anthropic SDK. If it
starts with `gemini-`, use the Google GenAI SDK. If it starts with
`gpt-` or `o`, raise `NotImplementedError("OpenAI writer not wired in
first build")` — config supports it but no SDK call yet.

### Function

```python
def write_fire_tweet(
    bundle: StoryBundle,
    memory: MemorySlice,
) -> WriterResult:
    """Call the writer model with the full prompt.

    Returns WriterResult. tweet=None means the signal didn't earn
    'extraordinary' — the writer explicitly returned a kill verdict.

    Output format: the writer is instructed to return a JSON object
    matching WriterResult schema. We parse and validate.

    On API error: raise. Caller (pipeline.py) decides whether to swallow.
    On parse failure: log raw response, raise ValueError.
    On API key missing: raise RuntimeError. No silent fallback.
    """
```

### System prompt (full, verbatim — `src/two_bot/prompts/writer_prompt.py`)

```python
WRITER_SYSTEM_PROMPT = """\
You write short factual posts about extraordinary climate and weather events for a Twitter account called The Heat. Write as if you are an Economist correspondent: plain-spoken authority, wry without precious, data-driven, compressed sentences, no first person, no hedging, irony used sparingly. Trust the reader. Never explain a punch line.

# YOUR JOB

You receive a JSON "story bundle" describing a single climate signal, plus a "memory slice" describing what The Heat has already said and which moves are forever-burned. You decide:

1. Is this signal extraordinary? In ONE of these ways or any other you can articulate:
   - Rarity: first/last/largest/smallest in some clean window. ("Largest April fire in Mali since records began in 2012.")
   - Scale: a peer-class comparison the reader can feel. ("About 1.4× the output of an average gas-fired power plant.")
   - Context: this signal is strange for this place at this time. ("Mali's fire season peaks in February. We're 10 weeks past peak.")
   - Or any other angle that makes a thoughtful reader pause.

2. If it earns extraordinary, write the tweet. Pick the angle YOU think works best for this signal.

3. If nothing earns extraordinary, return tweet=null. Better to say nothing than to ship filler.

# HARD RULES

- ≤ 280 characters.
- No first person ("we", "I", "us").
- No hedging ("seems", "may", "appears to be").
- No restate-padding. If a number is in the tweet, do not also restate it as "the new high: X. The old one: Y."
- No poetry-attempt closers. ("The river doesn't know." "Pointed at the sky.") The data carries the punch.
- No stock formulas. Specifically: never compare a fire's MW to "a typical/standard/average/large/small/commercial/industrial/mid-sized/high-capacity/usual nuclear/coal/gas/power plant/reactor that runs/generates/produces N MW." Use a SPECIFIC, NAMED, SIZED comparison or skip it.
- No throat-clearing openers. ("A wildfire in X is putting out N MW of radiative power.")
- Do not pre-explain or post-explain a punch line.
- Every concrete claim — number, date, named entity, comparison — must be either (a) traceable to the bundle or (b) a well-established general-knowledge fact you are CONFIDENT in. If you are unsure, leave it out.

# FOREVER-BANNED REUSE

The memory slice contains lists of moves that have ALREADY been used. Do not reuse any of them. Ever:

- used_era_anchors: every cultural / historical reference already used. Pick a different one or skip the era-anchor angle entirely.
- used_peer_comparisons: every named comparison object already used. Pick a different one.
- used_framings: every editorial frame already labeled. You may use the SAME EDITORIAL ANGLE (e.g. off-season irony) but the SPECIFIC FRAMING LABEL has already been spent — pick a fresh angle if you can.
- shipped_tweet_texts: every tweet already published. Do not echo any of them.

The bot's voice library shrinks monotonically. That is the design. If you cannot find a fresh angle, return tweet=null.

# OUTPUT FORMAT

Return ONLY a JSON object:

{
  "tweet": "<the tweet, or null>",
  "angle_chosen": "<short snake_case label, e.g. off_season_irony, named_comparison_scale, country_record_rarity, plain_number>",
  "era_anchor_used": "<exact phrasing of the era anchor if you used one, else null>",
  "peer_comparison_used": "<exact phrasing of the peer comparison if you used one, else null>",
  "reasoning": "<one sentence on why you chose this angle, or why you killed the draft>"
}

No markdown. No code fences. No prose outside the JSON.
"""
```

### User prompt template (also in `writer_prompt.py`)

```python
WRITER_USER_PROMPT_TEMPLATE = """\
STORY BUNDLE:
{bundle_json}

MEMORY SLICE:
{memory_json}

Write the tweet, or return tweet=null.
"""
```

### Tests

```python
def test_write_fire_tweet_calls_anthropic_with_prompt(mock_anthropic):
    mock_anthropic.return_value = _fake_response(json.dumps({
        "tweet": "Mali fire test", "angle_chosen": "rarity",
        "era_anchor_used": None, "peer_comparison_used": None,
        "reasoning": "test",
    }))
    result = write_fire_tweet(_bundle(), _memory())
    assert result.tweet == "Mali fire test"
    assert mock_anthropic.called

def test_write_fire_tweet_returns_null_tweet():
    # writer can decide to kill
    ...

def test_write_fire_tweet_raises_on_invalid_json():
    # parse failure
    ...

def test_write_fire_tweet_raises_on_missing_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError):
        write_fire_tweet(_bundle(), _memory())
```

## 9. Stage 4 — Fact-checker (`src/two_bot/fact_check.py`)

### Configuration

```python
FACT_CHECKER_MODEL = os.environ.get("THEHEAT_FACT_CHECK_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
```

### Function

```python
def fact_check(
    tweet: str,
    bundle: StoryBundle,
    state: dict,  # full state — for AUTHORITATIVE memory access
) -> FactCheckResult:
    """Run the cheap model as a strict fact-checker.

    Returns FactCheckResult with passed=True if and only if every concrete
    claim verifies. Strict: any unverified claim or any reuse → fail.

    On API error: raise. Caller decides whether to fail-open (don't ship)
    or fail-closed.
    On parse failure: log raw, raise ValueError.

    Reuse checks (era-anchor / peer-comparison / shipped-tweet) are run
    DETERMINISTICALLY in Python against the FULL authoritative lists
    in state["memory"] (not the capped slice the writer saw). Only
    world-knowledge verification goes to the LLM.
    """
```

### Implementation outline

```python
def fact_check(tweet, bundle, state):
    failures = []
    mem = state.get("memory", {})

    # Deterministic reuse checks first — against the FULL lists.
    for shipped in mem.get("shipped_tweets", []):
        if _normalized(tweet) == _normalized(shipped.get("tweet_text", "")):
            failures.append(f"reuse: tweet text duplicates shipped tweet")
    for ea in mem.get("used_era_anchors", []):
        if _contains_phrase(tweet, ea):
            failures.append(f"reuse: era anchor '{ea}' already used")
    for pc in mem.get("used_peer_comparisons", []):
        if _contains_phrase(tweet, pc):
            failures.append(f"reuse: peer comparison '{pc}' already used")

    if failures:
        return FactCheckResult(passed=False, failures=failures, raw_response="(local checks)")

    # LLM verification of bundle facts and world-knowledge claims.
    raw = _call_gemini(tweet, bundle)  # see prompt below
    parsed = _parse_fact_check_json(raw)  # {"passed": bool, "failures": [...]}
    return FactCheckResult(
        passed=parsed["passed"],
        failures=parsed.get("failures", []),
        raw_response=raw,
    )
```

### Fact-check prompt (full — `src/two_bot/prompts/fact_check_prompt.py`)

```python
FACT_CHECK_SYSTEM_PROMPT = """\
You are a strict fact-checker for a Twitter account about climate and weather events. You receive a tweet draft and a JSON "story bundle" of source data. Your only job is to identify any concrete claim in the tweet that cannot be verified.

A "concrete claim" is any number, date, year, named entity, comparison, or factual assertion. Examples: "361 MW", "since 2012", "Mali's fire season peaks in February", "average gas-fired power plant", "first time since 2002".

For EACH concrete claim in the tweet, classify it:
1. BUNDLE_FACT — the claim appears in the bundle. Verify exact match (number, unit, date). Mismatches = failure.
2. WORLD_KNOWLEDGE — the claim is a general-knowledge fact (cultural reference, well-known number, geography). Verify against your training data. If you are not 95%+ confident, mark as failure.
3. UNVERIFIABLE — the claim is neither in the bundle nor a verifiable general-knowledge fact. Failure.

Return ONLY a JSON object:

{
  "passed": true | false,
  "failures": [
    {"claim": "<exact substring of tweet>", "category": "BUNDLE_FACT|WORLD_KNOWLEDGE|UNVERIFIABLE", "reason": "<why it failed>"}
  ]
}

passed=true ONLY if failures is empty. No markdown, no code fences.
"""

FACT_CHECK_USER_PROMPT_TEMPLATE = """\
TWEET DRAFT:
{tweet}

STORY BUNDLE:
{bundle_json}

Fact-check.
"""
```

### Tests

```python
def test_fact_check_deterministic_tweet_reuse():
    state = {"memory": {
        "shipped_tweets": [{"tweet_text": "A wildfire in Mali..."}],
        "used_era_anchors": [], "used_peer_comparisons": [],
    }}
    result = fact_check("A wildfire in Mali...", _bundle(), state)
    assert not result.passed
    assert any("reuse" in f.lower() for f in result.failures)

def test_fact_check_deterministic_era_anchor_reuse():
    state = {"memory": {
        "shipped_tweets": [],
        "used_era_anchors": ["spider-man 2002"],
        "used_peer_comparisons": [],
    }}
    tweet = "Last time it was this hot, the first Spider-Man 2002 movie was new."
    result = fact_check(tweet, _bundle(), state)
    assert not result.passed

def test_fact_check_calls_llm_when_local_passes(mock_gemini):
    mock_gemini.return_value = '{"passed": true, "failures": []}'
    state = {"memory": {"shipped_tweets": [], "used_era_anchors": [],
                        "used_peer_comparisons": []}}
    result = fact_check("Some clean tweet.", _bundle(), state)
    assert result.passed
    assert mock_gemini.called

def test_fact_check_propagates_llm_failure(mock_gemini):
    mock_gemini.return_value = json.dumps({
        "passed": False,
        "failures": [{"claim": "since 2012", "category": "BUNDLE_FACT",
                      "reason": "bundle says 2014"}],
    })
    state = {"memory": {"shipped_tweets": [], "used_era_anchors": [],
                        "used_peer_comparisons": []}}
    result = fact_check("...since 2012", _bundle(), state)
    assert not result.passed
```

## 10. Stage Pipeline (`src/two_bot/pipeline.py`)

### Function

```python
def generate_fire_draft(
    fire: FireEvent,
    state: dict,
) -> dict | None:
    """Run the 5-stage pipeline. Returns a draft dict for save_draft, or None.

    Mutates state in place on success (Stage 5 memory write-back).

    Failure modes (return None):
    - Writer returned tweet=None (signal didn't earn extraordinary)
    - Fact-checker rejected
    - Any stage raised — caught, logged, return None

    The draft dict (when successful) has keys compatible with save_draft:
    {
      "type": "fire",
      "text": <tweet>,
      "event_id": fire.event_id,
      "two_bot_metadata": {
        "angle_chosen": ...,
        "era_anchor_used": ...,
        "peer_comparison_used": ...,
        "reasoning": ...,
        "fact_check": {"passed": true, "failures": []},
        "writer_model": ...,
        "fact_checker_model": ...,
      },
    }
    """
```

### Wiring in `src/main.py`

In `run_alerts`, locate the fire branch (currently around line 994).
Replace the body that calls `generator.generate_fire_tweet(...)` and
`save_draft(...)` with:

```python
# Two-bot pipeline for fire (replaces generator.generate_fire_tweet)
from src.two_bot.pipeline import generate_fire_draft

draft = generate_fire_draft(fire, bot_state)
if draft is not None:
    save_draft(
        bot_state,
        tweet_text=draft["text"],
        tweet_type="fire",
        event_id=fire.event_id,
        review_context={"two_bot": draft["two_bot_metadata"]},
        # ... preserve other args from existing call ...
    )
```

Preserve all existing logic *around* the call: the `_should_draft`
gate, duplicate checks, syn_state recording. The two-bot replacement is
strictly the writing/evaluation portion.

### End-to-end test

```python
def test_pipeline_happy_path(mock_writer, mock_fact_check):
    """Full pipeline with mocked LLMs. Verifies state.memory updates."""
    mock_writer.return_value = WriterResult(
        tweet="Mali fire is 1.4× the output of a 250 MW gas plant.",
        angle_chosen="named_comparison_scale",
        era_anchor_used=None,
        peer_comparison_used="250 MW gas plant",
        reasoning="...",
    )
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="...",
    )
    fire = FireEvent(...)
    state = _empty_memory_state()
    draft = generate_fire_draft(fire, state)

    assert draft is not None
    assert draft["text"].startswith("Mali")
    # Memory write-back happened
    assert "250 mw gas plant" in state["memory"]["used_peer_comparisons"]

def test_pipeline_writer_returns_null():
    # writer.tweet=None → return None, no memory write
    ...

def test_pipeline_fact_check_fails():
    # fact_check.passed=False → return None, no memory write
    ...

def test_pipeline_writer_raises():
    # exception → log + return None, no memory write
    ...
```

## 11. Acceptance criteria

The build is complete when ALL of the following are true:

1. **All new files exist** at the paths in §3.
2. **All tests pass** locally: `python -m pytest tests/two_bot/ -v` returns 0.
3. **Full suite still passes**: `python -m pytest tests/ -q` returns
   ≥ (current baseline + new test count) passing, 0 failed. Current
   baseline is 570 (after PR #16 fix-calendar-tipover-tests merges).
4. **Fire branch in `src/main.py`** uses `two_bot.pipeline.generate_fire_draft`,
   not `generator.generate_fire_tweet`.
5. **`DEFAULT_STATE`** in `src/state.py` includes the `"memory"` key per §7.
6. **A test running with mocked LLMs** demonstrates an end-to-end fire
   draft producing a `state.json`-compatible draft dict and updating
   memory state.
7. **Manual smoke test** documented in PR description: run the pipeline
   once locally with real API keys against a synthetic FireEvent, verify
   the produced tweet and memory updates by hand. Include the tweet
   text in the PR description.

## 12. Out of scope

Codex must not do any of the following in this PR:

- Touch other signal types (heat records, CO2, ice, ocean, drought, etc.).
- Delete `generator.generate_fire_tweet` or any other existing function.
- Change `evaluate_and_polish` or the evaluator path for non-fire categories.
- Modify the corpus loop, daily plan-refinement agent, or any docs
  outside this spec file and the PR description.
- Implement the actual FIRMS-archive distribution computation. The
  static stub table is correct for first build.
- Add a writer-model bake-off, multi-pass voice critique, or any A/B
  flagging.
- Touch posting logic; posting remains paused regardless of this PR.
- Replace the memory backend with mempalace or any vector store. State
  lives in state.json for this build.

## 13. PR & branching

- Branch name: `two-bot-fire-pipeline`
- Base: `main`
- Branch off latest `main` (after PR #16 merges; check first).
- Commits: at least one logical commit per stage (intern, memory,
  writer, fact-checker, pipeline wiring, tests). Conventional commits.
- PR title: `feat: two-bot pipeline for fire signals`
- PR description must include:
  - Summary of what changed
  - Acceptance criteria checklist (§11) with each box checked
  - The smoke-test tweet output (§11 item 7)
  - Confirmation that no out-of-scope items (§12) were touched

Do NOT push to `main` directly. Do NOT merge the PR; the user reviews
and merges.

## 14. Voice rules carried forward

These rules are baked into `WRITER_SYSTEM_PROMPT` (§8). Do NOT also
duplicate them as Python regex filters — those filters were the band-
aid for the old architecture. The writer prompt is now the source of
truth; the fact-checker is the enforcement.

For reference, here are the voice rules being carried forward:

- Wodehouse rule (don't sound like you're trying)
- No stock formulas (power plant comparisons by adjective, not name)
- No restate-padding ("The new high: X. The old one: Y.")
- No poetry-attempt closers ("The river doesn't know.")
- No throat-clearing openers ("A wildfire in X is radiating...")
- No first person, no hedging
- ≤ 280 chars
- Forever-banned reuse (era anchors, peer comparisons, framings, tweets)
- Economist house style anchor

---

**End of spec.**
