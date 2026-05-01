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
[Stage 1] INTERN  (deterministic — NO LLM call in first build)
  Input: FireEvent
  Output: StoryBundle (signal facts only). historical_context is OMITTED
          in first build until real distributions are computed — see §6.
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
  Output: WriterResult — tweet text + kill_reason (None if shipping)
  │
  ▼
[Stage 3.5] CLAIM EXTRACTION  (Gemini Flash)
  Input: writer's tweet text
  Output: list of concrete claims (numbers, dates, named entities,
          comparisons, era anchors, peer comparisons) extracted from
          the text. This is the source of truth for what the writer
          ACTUALLY said — independent of writer's self-report. Catches
          undeclared era anchors.
  │
  ▼
[Stage 4] FACT-CHECKER  (Gemini Flash)
  Input: extracted claims + bundle + full state["memory"]
  Output: pass / fail + reasons
  Strict: any unverifiable claim or any reuse → kill
  │
  ▼
[Stage 5] MEMORY WRITE-BACK
  Persists: tweet text, era anchors and peer-class comparisons taken
  from the extracted-claims list (NOT writer self-report), framings
  used, ongoing-event state.
  │
  ▼
state.json drafts queue (status: pending)
```

**Concurrency note (A2 fix):** in `run_alerts`, fire signals are
processed **serially**. The existing `run_alerts` loop is already
serial; codex must add a comment marking the fire branch as
serial-by-contract to prevent future parallelization breaking memory
write-back. Optimistic locking on Gist writes is a follow-up, not
first build.

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
| `src/two_bot/claim_extractor.py` | Stage 3.5 — extracts concrete claims from tweet text via Gemini Flash |
| `src/two_bot/prompts/writer_prompt.py` | Full writer system prompt (constant) |
| `src/two_bot/prompts/fact_check_prompt.py` | Full fact-check system prompt (constant) |
| `src/two_bot/prompts/claim_extract_prompt.py` | Full claim-extraction system prompt (constant) |
| `tests/two_bot/__init__.py` | Package |
| `tests/two_bot/conftest.py` | Shared test fixtures: `_bundle()`, `_memory()`, `_state_with_memory()`, `_fake_writer_response()`, `_fake_fact_check_response()` helpers |
| `tests/two_bot/test_intern.py` | Stage 1 tests |
| `tests/two_bot/test_memory.py` | Stage 2/5 tests |
| `tests/two_bot/test_writer.py` | Stage 3 tests (mocked LLM) |
| `tests/two_bot/test_claim_extractor.py` | Stage 3.5 tests (mocked LLM) |
| `tests/two_bot/test_fact_check.py` | Stage 4 tests (mocked LLM) |
| `tests/two_bot/test_pipeline.py` | End-to-end integration tests including memory-loop test (T2) |

### Modified files

| Path | Change |
|---|---|
| `src/main.py` | In `run_alerts`, replace the fire branch (`generator.generate_fire_tweet(...)`) with `two_bot.pipeline.generate_fire_draft(...)`. Other categories untouched. |
| `src/state.py` | Extend `DEFAULT_STATE` with a `"memory"` key (schema in §7). Add helpers `get_memory(state)` / `set_memory(state, memory)`. |
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
    """The intern's output. Pure facts; no editorial angles.

    First-build note (A1): `historical_context` is an empty dict in the
    first build. The full schema (percentiles, seasonal peak, etc.) will
    be filled once real FIRMS distributions are computed in a follow-up
    PR. The writer prompt explicitly handles an empty historical_context
    by falling back to bundle facts + world-knowledge angles.
    """
    signal_kind: str  # "fire" for first build
    where: str  # "Mali", "Southwestern US", etc.
    when: str  # ISO date "2026-04-30"
    event_id: str
    headline_metric: dict[str, Any]  # {"label", "value", "unit"}
    current_facts: list[dict[str, Any]]  # [{"label", "value", "unit"?}]
    historical_context: dict[str, Any] = field(default_factory=dict)  # empty in first build
    raw_signal_dump: dict[str, Any] = field(default_factory=dict)

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
    """The writer's output.

    Q2 fix: tweet=None alone is ambiguous (kill decision vs. parse
    error vs. API failure). We split:
      - shipping a tweet: tweet=<str>, kill_reason=None
      - writer chose to kill: tweet=None, kill_reason=<reason str>
    System failures (parse error, API error, missing key) RAISE; they
    don't return WriterResult. The pipeline catches and logs.
    """
    tweet: str | None
    kill_reason: str | None  # None when tweet is non-None; required when tweet is None
    angle_chosen: str  # short label e.g. "off_season_irony", "" when killed
    era_anchor_used: str | None  # writer's self-report (advisory; canonical source is claim_extractor)
    peer_comparison_used: str | None  # writer's self-report (advisory)
    reasoning: str  # one-sentence explanation, used for debugging and grading

    def __post_init__(self):
        # Invariant: exactly one of tweet/kill_reason is non-None.
        if (self.tweet is None) == (self.kill_reason is None):
            raise ValueError(
                "WriterResult invariant violated: exactly one of tweet/kill_reason "
                "must be non-None"
            )

    def to_dict(self) -> dict:
        return {
            "tweet": self.tweet,
            "kill_reason": self.kill_reason,
            "angle_chosen": self.angle_chosen,
            "era_anchor_used": self.era_anchor_used,
            "peer_comparison_used": self.peer_comparison_used,
            "reasoning": self.reasoning,
        }


@dataclass
class ExtractedClaim:
    """One concrete claim extracted from tweet text by Stage 3.5."""
    text: str  # exact substring of the tweet
    kind: str  # "number" | "date" | "named_entity" | "comparison" | "era_anchor" | "peer_comparison"

    def to_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind}


@dataclass
class FactCheckResult:
    passed: bool
    failures: list[str]  # human-readable reasons
    raw_response: str  # full LLM response, for debugging
    extracted_claims: list[ExtractedClaim] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "raw_response": self.raw_response,
            "extracted_claims": [c.to_dict() for c in self.extracted_claims],
        }
```

## 5. Stage 1 — Intern (`src/two_bot/intern.py`)

### Responsibility

Take a `FireEvent` and produce a `StoryBundle`. The bundle is *pure
signal facts*. No editorial framings. **No historical_context in first
build — A1 fix.**

### Function

```python
def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a StoryBundle for a fire signal.

    First-build (A1): purely deterministic. No LLM call. No historical
    archive lookup. The bundle contains the FireEvent's signal data; the
    writer falls back to bundle facts + its own world knowledge for
    framing (peer-class comparisons it can recall, country-level
    geographic context it knows from training, etc.).

    Future build: when real country-month FRP distributions are computed
    (see scripts/compute_fire_distribution.py — separate PR), this
    function will populate historical_context with verified percentile,
    seasonal-peak, and rarity data.
    """
```

### Bundle for fire — exact field list (first build)

```python
StoryBundle(
    signal_kind="fire",
    where=fire.nearest_city or fire.country,
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
    historical_context={},  # A1: empty in first build; writer prompt handles this
    raw_signal_dump={
        "lat": fire.lat, "lon": fire.lon,
        "confidence": fire.confidence, "frp": fire.frp,
        "nearest_city": fire.nearest_city, "country": fire.country,
        "event_id": fire.event_id,
    },
)
```

## 6. Historical context — DEFERRED (A1 fix)

**This module is NOT built in the first build.** The original draft
proposed a static stub table of country-month FRP distributions with
placeholder p99 values. That was unsafe: the writer would treat
placeholder percentiles as authoritative and write confident "largest
fire since records began" claims based on garbage data.

### First-build behavior

`StoryBundle.historical_context = {}` always. Writer prompt explicitly
handles the empty case (see §8 — "If historical_context is empty, do
not invent percentile / record-year / seasonal-peak claims. Use bundle
facts and your own world knowledge only.").

### Future build (separate PR)

When real distributions are computed:

1. Create `scripts/compute_fire_distribution.py` that pulls VIIRS
   archive 2012-current and computes per-country-per-month
   {count, p50, p90, p95, p99}. Output to
   `data/fire_country_month_distribution.json`.
2. Create `src/two_bot/historical_context.py` with the functions
   originally specified (compute_fire_context, percentile_for_frp,
   etc.) — populated from the real table only.
3. Wire `build_fire_bundle` to call `compute_fire_context` and
   populate `historical_context`.
4. Update writer prompt to reference the new fields.

That work is its own PR. Codex must NOT bundle it into the first
build, even with stub data.

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
    # NOTE (A4): no fire_archive_cache in first build. The original
    # draft included a 30/365-day rolling FIRMS cache here, but Gist
    # is KB-scale storage and the cache could blow MB. Since
    # historical_context is also deferred to a future PR (§6), there
    # is nothing to cache for now. The cache will be reintroduced
    # alongside historical_context in its own PR, with the cache
    # capped at 30 days OR moved to SQLite via THEHEAT_STATE_BACKEND.
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

def record_shipped(
    state: dict,
    bundle: StoryBundle,
    writer: WriterResult,
    extracted: list[ExtractedClaim],
) -> None:
    """Stage 5 — write back. Mutates state in place.

    Q1 fix: era anchors and peer comparisons are taken from `extracted`
    (Stage 3.5 output), NOT from writer.era_anchor_used /
    writer.peer_comparison_used. The writer's self-report is advisory
    only; if the writer slipped in a reference without declaring it,
    we still capture it.

    - Append the tweet to shipped_tweets.
    - For each ExtractedClaim with kind=="era_anchor":
        normalize(claim.text) → append to used_era_anchors (dedup).
    - For each ExtractedClaim with kind=="peer_comparison":
        normalize(claim.text) → append to used_peer_comparisons (dedup).
    - Append writer.angle_chosen to used_framings (dedup, exact match).
    - Update or insert into ongoing_events for this event_id.
    """

def is_reuse(state: dict, candidate: str, kind: str) -> bool:
    """Check if a candidate string matches a forever-banned element.
    Reads the FULL authoritative lists from state["memory"], not the
    capped slice the writer saw.

    Q3 fix — exact algorithms by kind:

    - 'tweet_text': exact match after _normalize().
    - 'era_anchor', 'peer_comparison': two checks, EITHER triggers reuse:
        (a) Normalized substring: _normalize(stored) is a substring of
            _normalize(candidate).
        (b) Token overlap: tokens(stored) is a non-empty subset of
            tokens(candidate). Tokens are word-character runs after
            lowercasing, with a stopword list of {"the","a","an","of",
            "in","on","at","to","for","is","was","were","this","that"}
            removed. Empty token sets do NOT trigger reuse.
    - 'framing': exact match on the snake_case label after lowercase.
      No substring, no tokenization.

    kind: 'era_anchor' | 'peer_comparison' | 'framing' | 'tweet_text'
    """

def _normalize(s: str) -> str:
    """Lowercase, strip leading/trailing whitespace, collapse internal
    whitespace runs to single space, remove trailing punctuation."""
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

def test_record_shipped_uses_extracted_claims_not_writer_self_report():
    """Q1: era_anchor_used in memory must come from the extracted-claims
    list, not the writer's self-report. Catches undeclared anchors."""
    state = _empty_memory_state()
    writer = WriterResult(
        tweet="In 2002, Spider-Man was new. Today, Mali burned.",
        kill_reason=None,
        angle_chosen="rarity",
        era_anchor_used=None,  # writer LIED about not using one
        peer_comparison_used=None,
        reasoning="...",
    )
    extracted = [
        ExtractedClaim(text="2002 Spider-Man", kind="era_anchor"),
    ]
    bundle = _bundle()
    record_shipped(state, bundle, writer, extracted)
    assert "2002 spider-man" in state["memory"]["used_era_anchors"]

def test_is_reuse_normalized_substring():
    state = {"memory": {"used_era_anchors": ["spider-man 2002"],
                        "used_peer_comparisons": [], "used_framings": [],
                        "shipped_tweets": []}}
    assert is_reuse(state, "Spider-Man 2002", "era_anchor")
    assert is_reuse(state, "the year Spider-Man 2002 came out", "era_anchor")

def test_is_reuse_token_overlap():
    """Token-overlap branch: 'spider-man came out in 2002' tokens fully
    present in 'in 2002 spider-man was new'."""
    state = {"memory": {"used_era_anchors": ["spider-man came out in 2002"],
                        "used_peer_comparisons": [], "used_framings": [],
                        "shipped_tweets": []}}
    assert is_reuse(state, "in 2002 spider-man was new on screens", "era_anchor")

def test_is_reuse_no_match_when_year_differs():
    state = {"memory": {"used_era_anchors": ["spider-man 2002"],
                        "used_peer_comparisons": [], "used_framings": [],
                        "shipped_tweets": []}}
    assert not is_reuse(state, "Spider-Man 3 was 2007", "era_anchor")

def test_is_reuse_framing_exact_match_only():
    state = {"memory": {"used_era_anchors": [], "used_peer_comparisons": [],
                        "used_framings": ["off_season_irony"],
                        "shipped_tweets": []}}
    assert is_reuse(state, "off_season_irony", "framing")
    assert not is_reuse(state, "off_season", "framing")
```

## 8. Stage 3 — Writer (`src/two_bot/writer.py`)

### Configuration

```python
WRITER_MODEL = os.environ.get("THEHEAT_WRITER_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# A5 fix: validate at module import — fail loudly at startup, not at first call.
_SUPPORTED_PREFIXES = {
    "claude-": "anthropic",
    "gemini-": "google",
}
_UNSUPPORTED_BUT_ALLOWED = ("gpt-", "o")  # config-supported, raise NotImplementedError on call

def _resolve_provider(model: str) -> str:
    for prefix, provider in _SUPPORTED_PREFIXES.items():
        if model.startswith(prefix):
            return provider
    if any(model.startswith(p) for p in _UNSUPPORTED_BUT_ALLOWED):
        return "unsupported_openai"
    raise RuntimeError(
        f"THEHEAT_WRITER_MODEL={model!r} does not match any supported "
        f"prefix ({', '.join(_SUPPORTED_PREFIXES)}). "
        "Set the env var to a supported model id."
    )

WRITER_PROVIDER = _resolve_provider(WRITER_MODEL)
```

If `WRITER_PROVIDER == "anthropic"`, use the Anthropic SDK. If
`"google"`, use the Google GenAI SDK. If `"unsupported_openai"`,
`write_fire_tweet` raises `NotImplementedError` at call time.

### Function

```python
def write_fire_tweet(
    bundle: StoryBundle,
    memory: MemorySlice,
) -> WriterResult:
    """Call the writer model with the full prompt.

    Returns WriterResult with the invariant from §4: exactly one of
    tweet / kill_reason is non-None.

    Output format: the writer is instructed to return a JSON object
    matching WriterResult schema. We parse and construct the dataclass;
    its __post_init__ enforces the invariant.

    Errors:
    - Missing ANTHROPIC_API_KEY (when provider==anthropic) → raise RuntimeError.
    - Missing GEMINI_API_KEY (when provider==google) → raise RuntimeError.
    - WRITER_PROVIDER == 'unsupported_openai' → raise NotImplementedError.
    - SDK call fails → raise.
    - Response can't be parsed as JSON → log raw, raise ValueError.
    - Parsed JSON doesn't satisfy WriterResult invariants → raise ValueError.

    The pipeline (§11) catches and logs.
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

3. If nothing earns extraordinary, set tweet=null and supply a one-line kill_reason. Better to say nothing than to ship filler.

# IF historical_context IS EMPTY

In this build, the `historical_context` field of the bundle is **always empty**. The intern has not yet been wired to compute percentile, seasonal-peak, or rarity data. You MUST NOT invent claims of that kind.

Specifically, do NOT write:
- "Largest [time-window] fire in [country] since [year]."
- "First time the FRP has crossed [threshold]."
- "[country]'s fire season peaks in [month]."
- Any percentile or rarity claim.

You MAY use, from your own training:
- General geographic knowledge ("Mali is in the Sahel").
- Well-known cultural era anchors with confident dates.
- Well-known named, sized peer-class comparisons (specific named power plants, dams, etc.) — if you are 95%+ confident in the number.

If your only available angles are historical-context claims, return tweet=null with kill_reason="no historical_context available; nothing else earned extraordinary".

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

Return ONLY a JSON object. Exactly one of `tweet` and `kill_reason` must be non-null:

{
  "tweet": "<the tweet text, or null if killing>",
  "kill_reason": "<one-line reason if tweet is null, else null>",
  "angle_chosen": "<short snake_case label, e.g. off_season_irony, named_comparison_scale, country_record_rarity, plain_number; empty string if killed>",
  "era_anchor_used": "<exact phrasing of the era anchor if you used one, else null>",
  "peer_comparison_used": "<exact phrasing of the peer comparison if you used one, else null>",
  "reasoning": "<one sentence on why you chose this angle, or why you killed the draft>"
}

Note: the era_anchor_used and peer_comparison_used fields are advisory.
A separate extraction step will independently scan the tweet for these
elements; you cannot hide a reuse by omitting it from the self-report.

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

Test fixtures `_bundle()`, `_memory()`, `_fake_writer_response()` live
in `tests/two_bot/conftest.py` (see §3 — added to file inventory).

```python
def test_write_fire_tweet_returns_tweet(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response({
        "tweet": "Mali fire test", "kill_reason": None,
        "angle_chosen": "rarity",
        "era_anchor_used": None, "peer_comparison_used": None,
        "reasoning": "test",
    })
    result = write_fire_tweet(_bundle(), _memory())
    assert result.tweet == "Mali fire test"
    assert result.kill_reason is None
    assert mock_anthropic.called

def test_write_fire_tweet_returns_kill(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response({
        "tweet": None, "kill_reason": "no historical_context available",
        "angle_chosen": "", "era_anchor_used": None,
        "peer_comparison_used": None, "reasoning": "...",
    })
    result = write_fire_tweet(_bundle(), _memory())
    assert result.tweet is None
    assert result.kill_reason

def test_write_fire_tweet_raises_on_both_tweet_and_kill_set(mock_anthropic):
    """WriterResult.__post_init__ enforces the invariant."""
    mock_anthropic.return_value = _fake_writer_response({
        "tweet": "x", "kill_reason": "y",  # invariant violation
        "angle_chosen": "x", "era_anchor_used": None,
        "peer_comparison_used": None, "reasoning": "x",
    })
    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())

def test_write_fire_tweet_raises_on_invalid_json(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response_raw("not json")
    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())

def test_write_fire_tweet_raises_on_missing_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError):
        write_fire_tweet(_bundle(), _memory())

def test_writer_provider_resolved_at_import(monkeypatch):
    """A5: unsupported model id should fail at import, not at call time."""
    monkeypatch.setenv("THEHEAT_WRITER_MODEL", "totally-fake-model")
    with pytest.raises(RuntimeError):
        # forcing reimport
        import importlib, src.two_bot.writer
        importlib.reload(src.two_bot.writer)
```

## 9. Stage 3.5 — Claim extractor (`src/two_bot/claim_extractor.py`)

### Responsibility

Take the writer's tweet text and extract every concrete claim into a
structured list. This is the source of truth for what the writer
ACTUALLY said. The writer's self-report (`era_anchor_used`,
`peer_comparison_used`) is advisory and may be incomplete; the
extractor is authoritative.

### Function

```python
def extract_claims(tweet: str) -> list[ExtractedClaim]:
    """Extract concrete claims from tweet text via Gemini Flash.

    Returns a list of ExtractedClaim, each with:
    - text: exact substring of the tweet
    - kind: one of "number", "date", "named_entity", "comparison",
            "era_anchor", "peer_comparison"

    On API error: raise.
    On parse failure: log raw, raise ValueError.
    On missing GEMINI_API_KEY: raise RuntimeError.
    """
```

### Prompt (`src/two_bot/prompts/claim_extract_prompt.py`)

```python
CLAIM_EXTRACT_SYSTEM_PROMPT = """\
You extract concrete claims from short tweets about climate and weather. Read the tweet and produce a structured list.

A "concrete claim" is anything specific the reader could fact-check:
- number: any quantity ("361 MW", "47 inches", "1.4×")
- date: any specific date or year ("April 30", "2002", "since 2012")
- named_entity: a specific named place / event / object ("Mali", "Hoover Dam", "Hurricane Katrina")
- comparison: a "X compared to Y" structure ("warmer than 1929", "twice the size of Manhattan")
- era_anchor: a cultural / historical / pop-culture reference used to convey time ("Spider-Man came out", "Adele's 21 was top of the charts")
- peer_comparison: a sized peer-class object used as a benchmark ("a 250 MW gas plant", "the Hoover Dam at 2,080 MW")

Extract every claim. Each gets exactly one kind label. If the same substring could fit two kinds, prefer the more specific (era_anchor > date; peer_comparison > comparison; named_entity > date for "Hurricane Katrina").

Return ONLY a JSON list:

[
  {"text": "<exact substring>", "kind": "number|date|named_entity|comparison|era_anchor|peer_comparison"},
  ...
]

No markdown. No code fences. No prose outside the JSON.
"""

CLAIM_EXTRACT_USER_PROMPT_TEMPLATE = """\
TWEET:
{tweet}

Extract the claims.
"""
```

### Tests

```python
def test_extract_claims_returns_list(mock_gemini):
    mock_gemini.return_value = json.dumps([
        {"text": "361 MW", "kind": "number"},
        {"text": "Mali", "kind": "named_entity"},
        {"text": "Spider-Man came out", "kind": "era_anchor"},
    ])
    claims = extract_claims("Mali fire is 361 MW. Spider-Man came out the last time.")
    assert len(claims) == 3
    assert claims[2].kind == "era_anchor"

def test_extract_claims_raises_on_invalid_json(mock_gemini):
    mock_gemini.return_value = "not json"
    with pytest.raises(ValueError):
        extract_claims("anything")
```

## 10. Stage 4 — Fact-checker (`src/two_bot/fact_check.py`)

### Configuration

```python
FACT_CHECKER_MODEL = os.environ.get("THEHEAT_FACT_CHECK_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
```

### Function

```python
def fact_check(
    tweet: str,
    extracted: list[ExtractedClaim],
    bundle: StoryBundle,
    state: dict,  # full state — for AUTHORITATIVE memory access
) -> FactCheckResult:
    """Run the cheap model as a strict fact-checker.

    Q1 fix: takes pre-extracted claims (Stage 3.5 output) so reuse
    checks can match against the EXTRACTED claim text (which is what
    the writer actually wrote), not the writer's self-report.

    Returns FactCheckResult with passed=True if and only if every concrete
    claim verifies. Strict: any unverified claim or any reuse → fail.

    On API error: raise. Caller decides handling.
    On parse failure: log raw, raise ValueError.

    Reuse checks are run DETERMINISTICALLY via memory.is_reuse() against
    the FULL authoritative lists in state["memory"]. The extracted-claims
    list is the canonical source of "what era anchor / peer comparison
    did the writer use?" — not writer.era_anchor_used.

    Only bundle-fact and world-knowledge verification go to the LLM.
    """
```

### Implementation outline

```python
def fact_check(tweet, extracted, bundle, state):
    failures = []

    # 1) Deterministic tweet-text reuse (full text duplicates).
    if memory.is_reuse(state, tweet, "tweet_text"):
        failures.append("reuse: tweet text duplicates shipped tweet")

    # 2) Deterministic reuse on EVERY extracted era_anchor / peer_comparison.
    for claim in extracted:
        if claim.kind == "era_anchor" and memory.is_reuse(state, claim.text, "era_anchor"):
            failures.append(f"reuse: era anchor '{claim.text}' already used")
        if claim.kind == "peer_comparison" and memory.is_reuse(state, claim.text, "peer_comparison"):
            failures.append(f"reuse: peer comparison '{claim.text}' already used")

    if failures:
        return FactCheckResult(
            passed=False, failures=failures,
            raw_response="(local reuse checks)", extracted_claims=extracted,
        )

    # 3) LLM verification of bundle facts and world-knowledge claims.
    raw = _call_gemini(tweet, bundle)
    parsed = _parse_fact_check_json(raw)  # {"passed": bool, "failures": [...]}
    return FactCheckResult(
        passed=parsed["passed"],
        failures=parsed.get("failures", []),
        raw_response=raw,
        extracted_claims=extracted,
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
    state = _state_with_memory(shipped_tweets=[{"tweet_text": "A wildfire in Mali..."}])
    result = fact_check("A wildfire in Mali...", [], _bundle(), state)
    assert not result.passed
    assert any("reuse" in f.lower() for f in result.failures)

def test_fact_check_deterministic_era_anchor_reuse_via_extraction():
    """Q1: reuse is detected via the EXTRACTED claim, not writer self-report."""
    state = _state_with_memory(used_era_anchors=["spider-man 2002"])
    extracted = [ExtractedClaim(text="Spider-Man 2002", kind="era_anchor")]
    result = fact_check(
        "Last time it was this hot, the first Spider-Man 2002 movie was new.",
        extracted, _bundle(), state,
    )
    assert not result.passed

def test_fact_check_calls_llm_when_local_passes(mock_gemini):
    mock_gemini.return_value = '{"passed": true, "failures": []}'
    state = _state_with_memory()
    result = fact_check("Some clean tweet.", [], _bundle(), state)
    assert result.passed
    assert mock_gemini.called

def test_fact_check_propagates_llm_failure(mock_gemini):
    mock_gemini.return_value = json.dumps({
        "passed": False,
        "failures": [{"claim": "since 2012", "category": "BUNDLE_FACT",
                      "reason": "bundle says 2014"}],
    })
    state = _state_with_memory()
    result = fact_check("...since 2012", [], _bundle(), state)
    assert not result.passed
```

## 11. Stage Pipeline (`src/two_bot/pipeline.py`)

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
# Two-bot pipeline for fire (replaces generator.generate_fire_tweet).
# This loop is SERIAL by contract — see Concurrency note in §2. Memory
# write-back in generate_fire_draft mutates state["memory"]; concurrent
# invocations would race on Gist persistence.
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
def test_pipeline_happy_path(mock_writer, mock_extract, mock_fact_check):
    """Full pipeline with mocked LLMs. Verifies state.memory updates."""
    mock_writer.return_value = WriterResult(
        tweet="Mali fire is 1.4× a 250 MW gas plant.",
        kill_reason=None,
        angle_chosen="named_comparison_scale",
        era_anchor_used=None,
        peer_comparison_used="250 MW gas plant",
        reasoning="...",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="250 MW gas plant", kind="peer_comparison"),
        ExtractedClaim(text="Mali", kind="named_entity"),
    ]
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="...",
        extracted_claims=mock_extract.return_value,
    )
    fire = _fire_event()
    state = _state_with_memory()
    draft = generate_fire_draft(fire, state)

    assert draft is not None
    assert draft["text"].startswith("Mali")
    # Memory write-back happened — used_peer_comparisons populated from
    # EXTRACTED claim, not writer self-report
    assert "250 mw gas plant" in state["memory"]["used_peer_comparisons"]

def test_pipeline_writer_kills():
    # writer returns kill_reason → return None, no memory write
    ...

def test_pipeline_fact_check_fails():
    # fact_check.passed=False → return None, no memory write
    ...

def test_pipeline_writer_raises():
    # exception → log + return None, no memory write
    ...

def test_pipeline_memory_loop_blocks_reuse(mock_writer, mock_extract, mock_fact_check):
    """T2 — the LINCHPIN test. Run pipeline once, memory updates, run again
    with the writer trying to reuse the same era anchor → fact-check kills
    the second draft."""
    state = _state_with_memory()
    fire = _fire_event(event_id="fire_first")

    # First run: writer uses Spider-Man 2002.
    mock_writer.return_value = WriterResult(
        tweet="Mali burned. The last time, Spider-Man 2002 was new.",
        kill_reason=None, angle_chosen="rarity",
        era_anchor_used="Spider-Man 2002",
        peer_comparison_used=None, reasoning="...",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="Spider-Man 2002", kind="era_anchor"),
    ]
    mock_fact_check.return_value = FactCheckResult(
        passed=True, failures=[], raw_response="ok",
        extracted_claims=mock_extract.return_value,
    )
    draft1 = generate_fire_draft(fire, state)
    assert draft1 is not None
    assert "spider-man 2002" in state["memory"]["used_era_anchors"]

    # Second run: writer tries Spider-Man 2002 again (slipped in without
    # declaring it). Pipeline must catch via extraction + fact-check.
    fire2 = _fire_event(event_id="fire_second")
    mock_writer.return_value = WriterResult(
        tweet="Another Mali fire. Spider-Man 2002 was new last time.",
        kill_reason=None, angle_chosen="rarity",
        era_anchor_used=None,  # writer LIED: didn't declare reuse
        peer_comparison_used=None, reasoning="...",
    )
    mock_extract.return_value = [
        ExtractedClaim(text="Spider-Man 2002", kind="era_anchor"),
    ]
    # Don't mock fact-check this time — let the real deterministic reuse
    # check run against state["memory"].
    from src.two_bot.fact_check import fact_check as real_fact_check
    mock_fact_check.side_effect = real_fact_check
    draft2 = generate_fire_draft(fire2, state)
    assert draft2 is None  # killed by reuse detection
```

## 12. Acceptance criteria

The build is complete when ALL of the following are true:

1. **All new files exist** at the paths in §3.
2. **All tests pass** locally: `python -m pytest tests/two_bot/ -v` returns 0.
3. **Full suite still passes**: `python -m pytest tests/ -q` returns
   ≥ (current baseline + new test count) passing, 0 failed. Current
   baseline is 570 (after PR #16 fix-calendar-tipover-tests merges).
4. **Fire branch in `src/main.py`** uses `two_bot.pipeline.generate_fire_draft`,
   not `generator.generate_fire_tweet`.
5. **`DEFAULT_STATE`** in `src/state.py` includes the `"memory"` key per §7.
6. **`tests/test_main.py::TestRunAlerts::test_drafts_fire_alert`** is
   updated (T1 fix). The current test mocks `src.main.generator` and
   asserts `generate_fire_tweet` was called once. Because main.py now
   calls `two_bot.pipeline.generate_fire_draft` for fire, codex must
   either (a) rewrite this test to mock `two_bot.pipeline.generate_fire_draft`
   and assert the new call path, or (b) replace it with an equivalent test
   in `tests/two_bot/test_pipeline.py`. The acceptance test runs from a
   clean clone and passes.
7. **End-to-end memory-loop test passes** (T2 fix). The
   `test_pipeline_memory_loop_blocks_reuse` test in §11 exercises the
   forever-ban memory loop end-to-end with mocked LLMs. This is the
   linchpin test — if it passes, the architecture's core claim is
   validated.
8. **Manual smoke test** documented in PR description: run the pipeline
   once locally with real API keys against a synthetic FireEvent, verify
   the produced tweet and memory updates by hand. Include the tweet
   text in the PR description.

## 13. Out of scope

Codex must not do any of the following in this PR:

- Touch other signal types (heat records, CO2, ice, ocean, drought, etc.).
- Delete `generator.generate_fire_tweet` or any other existing function.
- Change `evaluate_and_polish` or the evaluator path for non-fire categories.
- Modify the corpus loop, daily plan-refinement agent, or any docs
  outside this spec file and the PR description.
- **Build `src/two_bot/historical_context.py`**. A1 fix — that module is
  deferred to a separate PR after real FIRMS distributions are computed.
  Stub tables and `is_placeholder` flags are NOT acceptable substitutes.
- Add `fire_archive_cache` to `state["memory"]`. A4 fix — deferred to
  the same PR as historical_context.
- Add a writer-model bake-off, multi-pass voice critique, or any A/B
  flagging.
- Touch posting logic; posting remains paused regardless of this PR.
- Replace the memory backend with mempalace or any vector store. State
  lives in state.json for this build.

## 14. PR & branching

- Branch name: `two-bot-fire-pipeline`
- Base: `main`
- Branch off latest `main` (after PR #16 merges; check first).
- Commits: at least one logical commit per stage (intern, memory,
  writer, fact-checker, pipeline wiring, tests). Conventional commits.
- PR title: `feat: two-bot pipeline for fire signals`
- PR description must include:
  - Summary of what changed
  - Acceptance criteria checklist (§12) with each box checked
  - The smoke-test tweet output (§12 item 8)
  - Confirmation that no out-of-scope items (§13) were touched

Do NOT push to `main` directly. Do NOT merge the PR; the user reviews
and merges.

## 15. Voice rules carried forward

These rules are baked into `WRITER_SYSTEM_PROMPT` (§8). Do NOT also
duplicate them as Python regex filters — those filters were the band-
aid for the old architecture. The writer prompt is now the source of
truth; the fact-checker (§10) is the enforcement.

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
