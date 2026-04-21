# Fire Footprint (GWIS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-fire-complex tier-crossing signal driven by GWIS (with NIFC fallback) so the bot tweets acreage milestones — "Dixie Complex crossed 100,000 hectares" — distinct from FIRMS point detections.

**Architecture:** New data module `src/data/fire_footprint.py` mirrors `firms.py` + `gdacs.py` patterns. GDACS-style tier dedup via an integer ladder stored in state. Once-per-day fetch gate. Manual-only approval (fires carry human-impact risk). All pure-logic pieces (tier classification, crossing detection, scoring, template, generator wiring) are TDD-first with no network. The actual HTTP fetch is the last task because the GWIS endpoint needs 60–90 min of recon first; if that timebox expires, the same fetch signature is implemented against NIFC instead.

**Tech Stack:** Python 3.11+, `requests`, `pytest`, `responses` (HTTP mocking), existing project patterns.

**Spec reference:** `docs/superpowers/specs/2026-04-20-fire-footprint-design.md`

---

## File Structure

**Create:**
- `src/data/fire_footprint.py` — fetch, tier classification, crossing detection
- `tests/test_fire_footprint.py` — module tests

**Modify:**
- `src/state.py` — add `fire_complex_tiers` to `DEFAULT_STATE`, add helper, update `_merge_state`
- `src/editorial/scoring.py` — add `score_fire_footprint`
- `src/editorial/approval.py` — add `fire_footprint` to the `manual_only` set
- `src/editorial/candidates.py` — add `fire_footprint` to `CATEGORY_HINTS`
- `src/voice/templates.py` — add `fire_footprint_template`
- `src/voice/generator.py` — add `generate_fire_footprint_tweet`
- `src/main.py` — import module + new section between FIRMS and CO2, plus import of `score_fire_footprint`
- `tests/test_state.py` — cover new state helper + merge
- `tests/test_editorial_scoring.py` — cover `score_fire_footprint`
- `tests/test_editorial_approval.py` — cover `fire_footprint` policy
- `tests/test_main.py` — cover run_alerts integration for fire_footprint
- `BRIEFING.md` — pipeline diagram row + secrets section notes
- `PIPELINE.md` — architecture mention

---

## Task 1: Module scaffold + tier classification

**Files:**
- Create: `src/data/fire_footprint.py`
- Create: `tests/test_fire_footprint.py`

- [ ] **Step 1: Write the failing test for `_classify_tier`**

Create `tests/test_fire_footprint.py`:

```python
"""Tests for fire footprint (GWIS) data."""

import pytest

from src.data.fire_footprint import (
    FireComplex,
    TIERS_HECTARES,
    _classify_tier,
)


class TestClassifyTier:
    def test_below_floor_returns_negative_one(self):
        assert _classify_tier(0) == -1
        assert _classify_tier(19_999) == -1

    def test_exact_tier_thresholds(self):
        assert _classify_tier(20_000) == 0
        assert _classify_tier(50_000) == 1
        assert _classify_tier(100_000) == 2
        assert _classify_tier(250_000) == 3
        assert _classify_tier(500_000) == 4
        assert _classify_tier(1_000_000) == 5

    def test_between_tiers_rounds_down(self):
        assert _classify_tier(49_999) == 0
        assert _classify_tier(99_999) == 1
        assert _classify_tier(249_999) == 2

    def test_above_top_tier_clamps_to_top(self):
        assert _classify_tier(5_000_000) == 5
        assert _classify_tier(25_000_000) == 5  # Black Summer-scale

    def test_tiers_ladder_is_monotonic(self):
        assert TIERS_HECTARES == sorted(TIERS_HECTARES)
        assert TIERS_HECTARES[0] == 20_000
        assert TIERS_HECTARES[-1] == 1_000_000


class TestFireComplexDataclass:
    def test_fields_present(self):
        fc = FireComplex(
            complex_id="GWIS_123",
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
            start_date=None,
            tier=3,
            event_id="fire_footprint_GWIS_123_tier3",
        )
        assert fc.complex_id == "GWIS_123"
        assert fc.name == "Dixie Complex"
        assert fc.tier == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fire_footprint.py -v`
Expected: FAIL with `ImportError: cannot import name ...`

- [ ] **Step 3: Write minimal implementation**

Create `src/data/fire_footprint.py`:

```python
"""GWIS fire footprint data — cumulative burned area per fire complex.

Complements FIRMS (point detections, "is there a fire at lat/lon?") by
answering the scale question: "how many hectares has this complex burned?"

Source decision (2026-04-20): primary GWIS (Global Wildfire Information
System, https://gwis.jrc.ec.europa.eu/). If mapping the endpoint
exceeds 60–90 minutes, the same module falls back to NIFC for US-only
coverage. Endpoint + auth posture documented in BRIEFING.md.
"""

from dataclasses import dataclass
from datetime import date

# Hectare thresholds for per-fire-complex tweet dedup. A complex is
# eligible for a draft each time it crosses into a higher tier. Integer
# indices (not hectare values) are stored in state so we can tune the
# ladder later without retroactively re-tweeting.
TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]


@dataclass
class FireComplex:
    complex_id: str
    name: str | None
    country: str
    region: str
    hectares: float
    start_date: date | None
    tier: int
    event_id: str


def _classify_tier(hectares: float) -> int:
    """Return the highest ladder index whose threshold is <= hectares.

    Returns -1 if below the floor (not tweet-worthy). Clamps at the top
    tier for megafires beyond 1M ha.
    """
    tier = -1
    for i, threshold in enumerate(TIERS_HECTARES):
        if hectares >= threshold:
            tier = i
    return tier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fire_footprint.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/data/fire_footprint.py tests/test_fire_footprint.py
git commit -m "Add fire_footprint module scaffold + tier classification"
```

---

## Task 2: Tier-crossing detection

**Files:**
- Modify: `src/data/fire_footprint.py`
- Modify: `tests/test_fire_footprint.py`

- [ ] **Step 1: Add tests for `detect_tier_crossings`**

Append to `tests/test_fire_footprint.py`:

```python
from src.data.fire_footprint import detect_tier_crossings


def _mk_complex(complex_id: str, hectares: float, name: str | None = None) -> FireComplex:
    tier = _classify_tier(hectares)
    return FireComplex(
        complex_id=complex_id,
        name=name,
        country="US",
        region="California",
        hectares=hectares,
        start_date=None,
        tier=tier,
        event_id=f"fire_footprint_{complex_id}_tier{tier}",
    )


class TestDetectTierCrossings:
    def test_new_complex_above_floor_emits(self):
        state = {"fire_complex_tiers": {}}
        complexes = [_mk_complex("A", 60_000)]  # tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
        assert crossings[0].complex_id == "A"
        assert crossings[0].tier == 1

    def test_new_complex_below_floor_suppressed(self):
        state = {"fire_complex_tiers": {}}
        complexes = [_mk_complex("A", 15_000)]  # below tier 0

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []

    def test_same_tier_second_run_suppressed(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 70_000)]  # still tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []

    def test_tier_upgrade_emits(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 150_000)]  # now tier 2

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
        assert crossings[0].tier == 2

    def test_shrink_is_not_a_crossing(self):
        state = {"fire_complex_tiers": {"A": 3}}
        complexes = [_mk_complex("A", 60_000)]  # shrunk to tier 1

        crossings = detect_tier_crossings(complexes, state)

        assert crossings == []  # don't tweet a fire getting smaller

    def test_does_not_mutate_input_state(self):
        state = {"fire_complex_tiers": {"A": 1}}
        complexes = [_mk_complex("A", 150_000)]

        detect_tier_crossings(complexes, state)

        assert state["fire_complex_tiers"] == {"A": 1}

    def test_multiple_complexes_independent(self):
        state = {"fire_complex_tiers": {"A": 2}}
        complexes = [
            _mk_complex("A", 260_000),   # upgrade to tier 3
            _mk_complex("B", 60_000),    # new at tier 1
            _mk_complex("C", 10_000),    # below floor
        ]

        crossings = detect_tier_crossings(complexes, state)
        emitted_ids = {c.complex_id for c in crossings}

        assert emitted_ids == {"A", "B"}

    def test_missing_state_key_treated_as_empty(self):
        state = {}  # no fire_complex_tiers key at all
        complexes = [_mk_complex("A", 60_000)]

        crossings = detect_tier_crossings(complexes, state)

        assert len(crossings) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fire_footprint.py::TestDetectTierCrossings -v`
Expected: FAIL with `ImportError: cannot import name 'detect_tier_crossings'`

- [ ] **Step 3: Implement `detect_tier_crossings`**

Append to `src/data/fire_footprint.py`:

```python
def detect_tier_crossings(
    complexes: list[FireComplex],
    state: dict,
) -> list[FireComplex]:
    """Return complexes whose current tier is strictly higher than the
    last tier we've already tweeted about.

    Does not mutate state. The caller writes the updated tier only after
    a draft is successfully saved.
    """
    last_tiers = state.get("fire_complex_tiers", {}) or {}
    crossings: list[FireComplex] = []
    for fc in complexes:
        if fc.tier < 0:
            continue
        previous = last_tiers.get(fc.complex_id, -1)
        if fc.tier > previous:
            crossings.append(fc)
    return crossings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fire_footprint.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/data/fire_footprint.py tests/test_fire_footprint.py
git commit -m "Add tier-crossing detection for fire complexes"
```

---

## Task 3: State helper + DEFAULT_STATE + merge semantics

**Files:**
- Modify: `src/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add tests for state additions**

Append to `tests/test_state.py`:

```python
class TestFireComplexTiers:
    def test_default_state_has_fire_complex_tiers(self):
        from src.state import DEFAULT_STATE
        assert "fire_complex_tiers" in DEFAULT_STATE
        assert DEFAULT_STATE["fire_complex_tiers"] == {}

    def test_update_fire_complex_tier_sets_new(self):
        from src.state import update_fire_complex_tier
        s = {"fire_complex_tiers": {}}
        update_fire_complex_tier(s, "A", 2)
        assert s["fire_complex_tiers"]["A"] == 2

    def test_update_fire_complex_tier_takes_max(self):
        from src.state import update_fire_complex_tier
        s = {"fire_complex_tiers": {"A": 3}}
        update_fire_complex_tier(s, "A", 2)  # lower value ignored
        assert s["fire_complex_tiers"]["A"] == 3
        update_fire_complex_tier(s, "A", 4)
        assert s["fire_complex_tiers"]["A"] == 4

    def test_update_fire_complex_tier_initializes_dict(self):
        from src.state import update_fire_complex_tier
        s = {}  # no key at all
        update_fire_complex_tier(s, "A", 1)
        assert s["fire_complex_tiers"]["A"] == 1

    def test_merge_takes_max_tier(self):
        from src.state import _merge_state
        base = {"fire_complex_tiers": {"A": 2, "B": 1}}
        incoming = {"fire_complex_tiers": {"A": 1, "B": 3, "C": 0}}
        merged = _merge_state(base, incoming)
        assert merged["fire_complex_tiers"] == {"A": 2, "B": 3, "C": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py::TestFireComplexTiers -v`
Expected: FAIL on the default-state and helper imports.

- [ ] **Step 3: Add `fire_complex_tiers` to `DEFAULT_STATE`**

In `src/state.py`, inside the `DEFAULT_STATE = { ... }` dict, add a new entry (place it after `record_streaks`, preserving comment style):

```python
    # Per-complex tier dedup for fire footprint (GWIS). Integer index into
    # TIERS_HECTARES. Prevents re-tweeting the same fire at every update;
    # only tier upgrades trigger a new draft.
    "fire_complex_tiers": {},
```

- [ ] **Step 4: Add `update_fire_complex_tier` helper**

Append to `src/state.py` (near the bottom, alongside `update_record_streak`):

```python
def update_fire_complex_tier(state: dict, complex_id: str, tier: int) -> dict:
    """Record the highest tier we've tweeted for a fire complex.

    Takes max so concurrent cron runs don't lose a tier bump.
    """
    tiers = state.setdefault("fire_complex_tiers", {})
    current = int(tiers.get(complex_id, -1))
    if tier > current:
        tiers[complex_id] = int(tier)
    return state
```

- [ ] **Step 5: Update `_merge_state` to handle `fire_complex_tiers`**

In `src/state.py`, find the `_merge_state` function. After the existing `record_streaks` merge line, add:

```python
    # Take max tier per complex across concurrent writes so a tier bump
    # on one cron run isn't lost to a stale concurrent run.
    merged["fire_complex_tiers"] = {}
    for cid in set(
        list(base.get("fire_complex_tiers", {}).keys())
        + list(next_state.get("fire_complex_tiers", {}).keys())
    ):
        merged["fire_complex_tiers"][cid] = max(
            int(base.get("fire_complex_tiers", {}).get(cid, -1)),
            int(next_state.get("fire_complex_tiers", {}).get(cid, -1)),
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_state.py::TestFireComplexTiers -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Run the full state test suite to catch regressions**

Run: `pytest tests/test_state.py -v`
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "Add fire_complex_tiers state + max-merge semantics"
```

---

## Task 4: `score_fire_footprint` in scoring

**Files:**
- Modify: `src/editorial/scoring.py`
- Modify: `tests/test_editorial_scoring.py`

- [ ] **Step 1: Add tests**

Append to `tests/test_editorial_scoring.py`:

```python
from src.editorial.scoring import score_fire_footprint


class TestScoreFireFootprint:
    def test_large_fire_passes_threshold(self):
        score = score_fire_footprint(
            hectares=213_000,
            tier=3,
            region="California",
            has_name=True,
        )
        assert score.passes
        assert score.threshold == 72
        assert score.category == "fire_footprint"

    def test_floor_tier_may_not_pass(self):
        # Floor hit during peak season, no name — should be below threshold
        import unittest.mock
        from datetime import date
        with unittest.mock.patch("src.editorial.scoring.date") as mock_date:
            mock_date.today.return_value = date(date.today().year, 7, 15)
            score = score_fire_footprint(
                hectares=20_000,
                tier=0,
                region="Unknown",
                has_name=False,
            )
        assert score.threshold == 72
        # Floor fires are intentionally borderline — we care about the scale story
        assert score.total < 80

    def test_named_complex_scores_higher(self):
        named = score_fire_footprint(hectares=150_000, tier=2, has_name=True)
        unnamed = score_fire_footprint(hectares=150_000, tier=2, has_name=False)
        assert named.total >= unnamed.total

    def test_top_tier_mega_fire_is_elite(self):
        score = score_fire_footprint(
            hectares=2_500_000,
            tier=5,
            region="Siberia",
            has_name=False,
        )
        assert score.passes
        assert score.label in {"strong", "elite"}

    def test_region_hook_surfaces_in_reasons(self):
        score = score_fire_footprint(
            hectares=200_000,
            tier=2,
            region="Yakutia",
            has_name=False,
        )
        assert any("Yakutia" in r for r in score.reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_editorial_scoring.py::TestScoreFireFootprint -v`
Expected: FAIL — `cannot import name 'score_fire_footprint'`.

- [ ] **Step 3: Implement `score_fire_footprint`**

Append to `src/editorial/scoring.py`:

```python
def score_fire_footprint(
    hectares: float,
    tier: int,
    *,
    region: str = "",
    has_name: bool = False,
) -> EditorialScore:
    """Score a fire-complex tier crossing.

    Signal is the cumulative burn area (hectares) and which tier we've
    just crossed. Named complexes score slightly higher because the name
    itself is a shareability hook. Out-of-season fires score higher on
    novelty, matching the existing FIRMS pattern.
    """
    shoulder_season = date.today().month in {1, 2, 3, 4, 11, 12}
    severity = 58 + tier * 6 + min(hectares, 1_500_000) / 30_000
    novelty = 52 + tier * 4 + (12 if shoulder_season else 0)
    timeliness = 88
    confidence_score = 82  # GWIS is authoritative
    shareability = 58 + tier * 5 + (10 if has_name else 0)
    reasons = [f"{int(hectares):,} ha cumulative burn area"]
    if has_name:
        reasons.append("named fire complex")
    if shoulder_season:
        reasons.append("out-of-season fire signal")
    if tier >= 3:
        reasons.append("top-tier historical scale")
    if region and region != "Unknown":
        reasons.append(f"location hook: {region}")
    return _build_score(
        "fire_footprint",
        severity=severity,
        novelty=novelty,
        timeliness=timeliness,
        confidence=confidence_score,
        shareability=shareability,
        sensitivity=34,
        threshold=72,
        reasons=reasons[:3],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_editorial_scoring.py::TestScoreFireFootprint -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full scoring test suite**

Run: `pytest tests/test_editorial_scoring.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/editorial/scoring.py tests/test_editorial_scoring.py
git commit -m "Add score_fire_footprint with named/shoulder-season multipliers"
```

---

## Task 5: Approval policy for `fire_footprint`

**Files:**
- Modify: `src/editorial/approval.py`
- Modify: `tests/test_editorial_approval.py`

- [ ] **Step 1: Add test**

Append to `tests/test_editorial_approval.py`:

```python
    def test_fire_footprint_requires_manual_review(self):
        policy = recommend_approval_policy(
            "fire_footprint",
            signal_total=88,
            candidate_score={"total": 82},
        )
        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_editorial_approval.py::TestApprovalPolicy::test_fire_footprint_requires_manual_review -v`
Expected: FAIL — policy returns `default_review`, not `manual_only`.

- [ ] **Step 3: Add `fire_footprint` to the manual_only set**

In `src/editorial/approval.py`, locate the set:

```python
    if tweet_type in {"fire", "severe_weather", "global_disaster", "storm_surge", "river_flood", "drought"}:
```

Replace with:

```python
    if tweet_type in {"fire", "fire_footprint", "severe_weather", "global_disaster", "storm_surge", "river_flood", "drought"}:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_editorial_approval.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/approval.py tests/test_editorial_approval.py
git commit -m "Require manual approval for fire_footprint drafts"
```

---

## Task 6: Category hint for the candidate ranker

**Files:**
- Modify: `src/editorial/candidates.py`
- Modify: `tests/test_editorial_candidates.py`

- [ ] **Step 1: Add test**

Append to `tests/test_editorial_candidates.py`:

```python
class TestFireFootprintCategoryHint:
    def test_candidate_with_footprint_keywords_scores_higher(self):
        from src.editorial.candidates import score_candidate_text

        aligned = score_candidate_text(
            "The Dixie Complex has burned 213,000 hectares in California.",
            "fire_footprint",
        )
        generic = score_candidate_text(
            "A large fire is going on somewhere in California right now.",
            "fire_footprint",
        )
        assert aligned.context > generic.context
```

(If `tests/test_editorial_candidates.py` already imports `score_candidate_text`, skip the inline import.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_editorial_candidates.py::TestFireFootprintCategoryHint -v`
Expected: FAIL — both candidates currently score the same because there's no hint set for `fire_footprint`.

- [ ] **Step 3: Add the category hint entry**

In `src/editorial/candidates.py`, inside `CATEGORY_HINTS`, add:

```python
    "fire_footprint": ("hectares", "burned", "complex"),
```

(Place after the existing `"fire"` entry to keep related entries together.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_editorial_candidates.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/editorial/candidates.py tests/test_editorial_candidates.py
git commit -m "Add fire_footprint category hint to candidate ranker"
```

---

## Task 7: `fire_footprint_template` fallback

**Files:**
- Modify: `src/voice/templates.py`
- Modify: `tests/test_generator.py` (or create dedicated template test if preferred)

- [ ] **Step 1: Add tests**

Append to `tests/test_generator.py`:

```python
class TestFireFootprintTemplate:
    def test_named_fire_leads_with_name(self):
        from src.voice.templates import fire_footprint_template
        text = fire_footprint_template(
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
        )
        assert "Dixie Complex" in text
        assert "213,000" in text
        assert "hectares" in text

    def test_unnamed_fire_uses_region_fallback(self):
        from src.voice.templates import fire_footprint_template
        text = fire_footprint_template(
            name=None,
            country="Russia",
            region="Yakutia",
            hectares=300_000,
        )
        assert "Yakutia" in text
        assert "Russia" in text
        assert "300,000" in text

    def test_includes_acre_conversion(self):
        from src.voice.templates import fire_footprint_template
        text = fire_footprint_template(
            name="Test Fire",
            country="US",
            region="California",
            hectares=100_000,  # ≈ 247,105 acres
        )
        # At least one variant mentions acres; others may not.
        # Run many times so at least one acre-bearing variant appears.
        from src.voice.templates import fire_footprint_template as f
        produced = {f(name="Test Fire", country="US", region="California", hectares=100_000) for _ in range(50)}
        assert any("acres" in t for t in produced)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generator.py::TestFireFootprintTemplate -v`
Expected: FAIL — `cannot import name 'fire_footprint_template'`.

- [ ] **Step 3: Implement the template**

Append to `src/voice/templates.py`:

```python
def fire_footprint_template(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
) -> str:
    """Safety-net fallback when Gemini fails.

    Named complexes lead with the name. Unnamed complexes use a regional
    descriptor. Every variant leads with acreage — the scale IS the story.
    """
    subject = name if name else f"A fire complex in {region}"
    hectares_str = f"{int(hectares):,}"
    acres_str = f"{int(round(hectares * 2.47105, 0)):,}"
    variants = [
        f"{subject}, {country} has burned {hectares_str} hectares. That's {acres_str} acres.",
        f"{subject}: {hectares_str} hectares burned. {country}.",
        f"Fire footprint update. {subject} in {country} is now at {hectares_str} hectares.",
    ]
    return random.choice(variants)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generator.py::TestFireFootprintTemplate -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/voice/templates.py tests/test_generator.py
git commit -m "Add fire_footprint_template fallback for named + unnamed complexes"
```

---

## Task 8: `generate_fire_footprint_tweet` generator

**Files:**
- Modify: `src/voice/generator.py`
- Modify: `tests/test_generator.py`

- [ ] **Step 1: Add tests**

Append to `tests/test_generator.py`:

```python
class TestGenerateFireFootprintTweet:
    def test_uses_fire_footprint_category(self):
        from unittest.mock import patch, MagicMock
        from src.voice import generator

        with patch.object(generator, "generate_tweet") as mock_gen:
            mock_gen.return_value = "mocked tweet"
            generator.generate_fire_footprint_tweet(
                name="Dixie Complex",
                country="US",
                region="California",
                hectares=213_000,
                tier_hectares=100_000,
            )
            args, kwargs = mock_gen.call_args
            assert kwargs["category"] == "fire_footprint"
            # fallback args must carry all four fields
            assert kwargs["fallback_args"]["name"] == "Dixie Complex"
            assert kwargs["fallback_args"]["country"] == "US"
            assert kwargs["fallback_args"]["region"] == "California"
            assert kwargs["fallback_args"]["hectares"] == 213_000

    def test_data_description_contains_key_facts(self):
        from unittest.mock import patch
        from src.voice import generator

        with patch.object(generator, "generate_tweet") as mock_gen:
            mock_gen.return_value = "mocked tweet"
            generator.generate_fire_footprint_tweet(
                name=None,
                country="Russia",
                region="Yakutia",
                hectares=300_000,
                tier_hectares=250_000,
            )
            args, kwargs = mock_gen.call_args
            data_description = args[0]
            assert "Yakutia" in data_description
            assert "Russia" in data_description
            assert "300,000" in data_description
            assert "250,000" in data_description  # the crossed threshold
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generator.py::TestGenerateFireFootprintTweet -v`
Expected: FAIL — `cannot import name 'generate_fire_footprint_tweet'`.

- [ ] **Step 3: Implement the generator**

Append to `src/voice/generator.py` (next to `generate_fire_tweet`):

```python
def generate_fire_footprint_tweet(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
    tier_hectares: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a fire complex crossing a hectare tier.

    Lead with acreage. No "ravaging" / "raging" / meta-commentary — the
    number is the story. Honest framing: largest complex of this year,
    not "largest ever."
    """
    subject = name if name else f"A fire complex in {region}"
    acres = int(round(hectares * 2.47105, 0))
    data = (
        f"Fire complex: {subject}. Country: {country}. Region: {region}. "
        f"Cumulative burned area: {int(hectares):,} hectares ({acres:,} acres). "
        f"Just crossed the {tier_hectares:,}-hectare threshold. "
        f"Source: GWIS (EFFIS Global Wildfire Information System). "
        f"Lead with the acreage and the subject. No 'ravaging' / 'raging' — "
        f"the number is the story. Frame honestly: the largest complex of "
        f"{date.today().year}, not 'largest ever.'"
    )
    return generate_tweet(
        data,
        category="fire_footprint",
        return_bundle=return_bundle,
        fallback_fn=templates.fire_footprint_template,
        fallback_args={
            "name": name,
            "country": country,
            "region": region,
            "hectares": hectares,
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generator.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/voice/generator.py tests/test_generator.py
git commit -m "Add generate_fire_footprint_tweet with acreage-first framing"
```

---

## Task 9: GWIS / NIFC fetch (timeboxed recon; HTTP-mocked tests)

**Files:**
- Modify: `src/data/fire_footprint.py`
- Modify: `tests/test_fire_footprint.py`

**Pre-task: endpoint recon (timeboxed to 60–90 minutes)**

Before writing code, spend up to 90 min mapping a live GWIS endpoint that returns structured per-complex burn-area data. Open `https://gwis.jrc.ec.europa.eu/` and inspect the Active Fires Viewer's network traffic for endpoints that return JSON or GeoJSON. Document:
- Full URL with parameters
- Response shape (sample JSON stored in a test fixture)
- Auth posture (none / token / referrer-locked)
- Rate limits noted in terms of service

If at 90 min you still do not have a working endpoint, switch to NIFC:
- US-only
- Endpoint: the NIFC Situation Report / Active Incidents API (currently served under `https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0/query?where=...&outFields=...&f=json`). Confirm by visiting the public NIFC dashboard.
- Record the decision in a comment at the top of `fire_footprint.py` and in `BRIEFING.md`.

Regardless of source, the test contract below does not change — we mock HTTP with `responses` and feed the module synthetic payloads.

- [ ] **Step 1: Add tests for `fetch_active_fire_perimeters`**

Append to `tests/test_fire_footprint.py` (use the actual endpoint URL chosen during recon — placeholder below shows a GWIS-style URL; substitute when the real one is known):

```python
import responses
from unittest.mock import patch

from src.data.fire_footprint import fetch_active_fire_perimeters, GWIS_URL


# A minimal fake GWIS-shape payload. Adjust the shape in Step 3 to match
# the real endpoint identified during recon; keep the test contract.
SAMPLE_PAYLOAD = {
    "features": [
        {
            "properties": {
                "id": "GWIS_AAA",
                "name": "Dixie Complex",
                "country": "US",
                "region": "California",
                "area_ha": 213_000,
                "start_date": "2026-07-14",
            }
        },
        {
            "properties": {
                "id": "GWIS_BBB",
                "name": None,
                "country": "Russia",
                "region": "Yakutia",
                "area_ha": 60_000,
                "start_date": None,
            }
        },
        {
            "properties": {  # below floor — should be filtered
                "id": "GWIS_CCC",
                "name": None,
                "country": "Canada",
                "region": "BC",
                "area_ha": 5_000,
                "start_date": None,
            }
        },
    ]
}


class TestFetchActiveFirePerimeters:
    @responses.activate
    def test_happy_path_returns_complexes_above_floor(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)

        complexes = fetch_active_fire_perimeters()

        assert len(complexes) == 2  # Canada complex below floor filtered
        ids = {c.complex_id for c in complexes}
        assert ids == {"GWIS_AAA", "GWIS_BBB"}

    @responses.activate
    def test_complex_tier_classified_correctly(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)
        complexes = fetch_active_fire_perimeters()
        by_id = {c.complex_id: c for c in complexes}
        assert by_id["GWIS_AAA"].tier == 3  # 213k ha → tier 3 (250k floor)  # sanity-check in step 3 against actual ladder
        assert by_id["GWIS_BBB"].tier == 1  # 60k ha → tier 1

    @responses.activate
    def test_event_id_includes_complex_and_tier(self):
        responses.add(responses.GET, GWIS_URL, json=SAMPLE_PAYLOAD, status=200)
        complexes = fetch_active_fire_perimeters()
        dixie = next(c for c in complexes if c.complex_id == "GWIS_AAA")
        assert dixie.event_id == f"fire_footprint_GWIS_AAA_tier{dixie.tier}"

    @responses.activate
    def test_http_error_returns_empty(self):
        responses.add(responses.GET, GWIS_URL, status=500)
        assert fetch_active_fire_perimeters() == []

    @responses.activate
    def test_malformed_rows_skipped_not_raised(self):
        bad_payload = {"features": [{"properties": {"id": "X"}}]}  # missing area
        responses.add(responses.GET, GWIS_URL, json=bad_payload, status=200)
        assert fetch_active_fire_perimeters() == []

    def test_network_exception_returns_empty(self):
        # No responses registration — any HTTP call raises ConnectionError
        with patch("src.data.fire_footprint.requests.get", side_effect=Exception("boom")):
            assert fetch_active_fire_perimeters() == []
```

**Important:** before running Step 2, adjust `SAMPLE_PAYLOAD` in the test file to match the real endpoint's shape. The test contract (counts, tier classifications, error behavior) stays the same.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fire_footprint.py::TestFetchActiveFirePerimeters -v`
Expected: FAIL — `cannot import name 'fetch_active_fire_perimeters' / 'GWIS_URL'`.

- [ ] **Step 3: Implement the fetch**

Modify `src/data/fire_footprint.py`. Add at the top (after the existing imports) the three source-config constants, then append the fetch function. Replace the URL, env-var names, and field accessors with the real values identified during recon. Template skeleton below:

```python
import os

import requests

# Set at recon time. If the GWIS timebox expires, swap this block for
# the NIFC equivalent and note the decision in BRIEFING.md.
GWIS_URL = "https://gwis.jrc.ec.europa.eu/PLACEHOLDER_REAL_ENDPOINT"
GWIS_API_KEY = os.environ.get("GWIS_API_KEY", "")  # empty string if none required
HECTARES_FLOOR = TIERS_HECTARES[0]


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_start_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def fetch_active_fire_perimeters() -> list[FireComplex]:
    """Fetch active fire complexes with cumulative burn area >= floor.

    Returns [] on any network, parse, or shape error — a source failure
    never takes the alert cycle down.
    """
    try:
        resp = requests.get(
            GWIS_URL,
            timeout=30,
            headers={"Authorization": f"Bearer {GWIS_API_KEY}"} if GWIS_API_KEY else {},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    complexes: list[FireComplex] = []
    for feature in data.get("features", []) or []:
        props = feature.get("properties", {}) or {}
        hectares = _safe_float(props.get("area_ha"))
        if hectares < HECTARES_FLOOR:
            continue
        complex_id = str(props.get("id") or "").strip()
        if not complex_id:
            continue
        tier = _classify_tier(hectares)
        complexes.append(FireComplex(
            complex_id=complex_id,
            name=(props.get("name") or None),
            country=str(props.get("country") or "Unknown"),
            region=str(props.get("region") or "Unknown"),
            hectares=hectares,
            start_date=_parse_start_date(props.get("start_date")),
            tier=tier,
            event_id=f"fire_footprint_{complex_id}_tier{tier}",
        ))
    return complexes
```

(If NIFC is the chosen source: the field names become ArcGIS-style — `attributes.IncidentName`, `attributes.DailyAcres`, etc. — and the module converts acres → hectares before classification. Update the sample payload and field accessors accordingly.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fire_footprint.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data/fire_footprint.py tests/test_fire_footprint.py
git commit -m "Add fire perimeter fetch against GWIS (or NIFC fallback)"
```

---

## Task 10: main.py orchestrator integration

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Add integration tests**

Append to `tests/test_main.py` (near the other source-specific sections):

```python
class TestFireFootprintIntegration:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_tier_crossing_creates_draft_and_updates_state(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        from src.data.fire_footprint import FireComplex

        complex = FireComplex(
            complex_id="GWIS_AAA",
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
            start_date=None,
            tier=3,
            event_id="fire_footprint_GWIS_AAA_tier3",
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = [complex]
        mock_ff.detect_tier_crossings.return_value = [complex]
        mock_ff.TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
        mock_state.is_duplicate.return_value = False
        mock_gen.generate_fire_footprint_tweet.return_value = "mocked tweet"
        mock_draft.return_value = True

        state_dict = _fresh_state()
        run_alerts(state_dict)

        mock_gen.generate_fire_footprint_tweet.assert_called_once()
        # State updated with tier
        assert state_dict.get("fire_complex_tiers", {}).get("GWIS_AAA") == 3

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_same_day_second_run_gated_out(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = []

        state_dict = _fresh_state()
        state_dict["fire_footprint_last_run"] = date.today().isoformat()

        run_alerts(state_dict)

        mock_ff.fetch_active_fire_perimeters.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_fetch_error_is_logged_not_fatal(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.side_effect = RuntimeError("boom")

        state_dict = _fresh_state()

        # Must not raise
        run_alerts(state_dict)
        mock_state.log_error.assert_any_call(state_dict, "fire_footprint", "boom")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py::TestFireFootprintIntegration -v`
Expected: FAIL — `src.main` has no `fire_footprint` attribute yet.

- [ ] **Step 3: Add the import and scoring import in `src/main.py`**

In `src/main.py`, locate the existing line:

```python
from src.data import open_meteo, firms, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
```

Replace with:

```python
from src.data import open_meteo, firms, fire_footprint, co2, nws_alerts, gdacs, sea_ice, drought, enso, ocean, water_levels, river_gauges
```

In the scoring import block a few lines below, add `score_fire_footprint`:

```python
from src.editorial.scoring import (
    EditorialScore,
    score_all_time_record,
    score_anomaly,
    score_co2_milestone,
    score_drought,
    score_enso_transition,
    score_extreme_wave,
    score_fire_event,
    score_fire_footprint,
    ...
)
```

- [ ] **Step 4: Add the fire-footprint section in `run_alerts`**

In `src/main.py`, locate the FIRMS block (starting at the comment `# 2. Wildfire alerts via NASA FIRMS`). Immediately after the FIRMS `except` block, insert a new section:

```python
    # 2b. Fire footprint / acreage (GWIS, once per day)
    today_iso = date.today().isoformat()
    if bot_state.get("fire_footprint_last_run") != today_iso:
        print("[alerts] Checking fire footprints (GWIS)...")
        ff_start = time.perf_counter()
        source_promoted = 0
        source_drafted = 0
        try:
            complexes = fire_footprint.fetch_active_fire_perimeters()
            crossings = fire_footprint.detect_tier_crossings(complexes, bot_state)
            for fc in crossings:
                if state.is_duplicate(bot_state, fc.event_id):
                    continue
                score = score_fire_footprint(
                    hectares=fc.hectares,
                    tier=fc.tier,
                    region=fc.region,
                    has_name=bool(fc.name),
                )
                if not _should_draft(score, fc.event_id):
                    continue
                source_promoted += 1
                tier_threshold = fire_footprint.TIERS_HECTARES[fc.tier]
                generated = generator.generate_fire_footprint_tweet(
                    name=fc.name,
                    country=fc.country,
                    region=fc.region,
                    hectares=fc.hectares,
                    tier_hectares=tier_threshold,
                    return_bundle=True,
                )
                review_context = _review_context(
                    source="GWIS",
                    source_key="fire_footprint",
                    headline=f"Fire complex crossed {tier_threshold:,} ha",
                    current_run=current_run,
                    facts=[
                        _fact("Complex", fc.name or fc.complex_id),
                        _fact("Country", fc.country),
                        _fact("Region", fc.region),
                        _fact("Cumulative burn area", f"{int(fc.hectares):,} ha"),
                        _fact("Tier crossed", f"{tier_threshold:,} ha"),
                        _fact("Ignition date", fc.start_date.isoformat() if fc.start_date else "—"),
                    ],
                )
                if _save_generated_draft(generated, bot_state, "fire_footprint", fc.event_id, score, review_context=review_context):
                    state.record_event(bot_state, fc.event_id)
                    state.update_fire_complex_tier(bot_state, fc.complex_id, fc.tier)
                    drafted += 1
                    source_drafted += 1
            bot_state["fire_footprint_last_run"] = today_iso
            _record_source_run(
                current_run, "fire_footprint", ff_start,
                status="success", observed=len(complexes),
                promoted=source_promoted, drafted=source_drafted,
            )
        except Exception as e:
            print(f"[alerts] Fire footprint error: {e}")
            state.log_error(bot_state, "fire_footprint", str(e))
            _record_source_run(
                current_run, "fire_footprint", ff_start,
                status="failed", error=str(e),
            )
    else:
        ff_skipped_start = time.perf_counter()
        _record_source_run(
            current_run, "fire_footprint", ff_skipped_start,
            status="skipped", note="Already ran today",
        )
```

- [ ] **Step 5: Run the new integration tests**

Run: `pytest tests/test_main.py::TestFireFootprintIntegration -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full test suite to catch regressions**

Run: `pytest -q`
Expected: ALL PASS. If any existing `test_main.py` case breaks because of the new section, patch its mocks to include `mock_ff = MagicMock()` with empty returns.

- [ ] **Step 7: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "Wire fire_footprint into run_alerts with once-per-day gate"
```

---

## Task 11: BRIEFING + PIPELINE doc updates

**Files:**
- Modify: `BRIEFING.md`
- Modify: `PIPELINE.md`

- [ ] **Step 1: Update `BRIEFING.md` pipeline diagram**

Locate the ASCII pipeline block. Under the existing NASA FIRMS line, add:

```
│   ├── GWIS ────────────────── fire-complex cumulative burn area (daily; tier-crossing only)
```

- [ ] **Step 2: Update the scoring table in `BRIEFING.md`**

Locate the list of scoring functions / thresholds. Add:

```
- score_fire_footprint → threshold 72 → manual_only approval
```

- [ ] **Step 3: Update the Secrets section in `BRIEFING.md`**

Record the endpoint + auth posture picked during Task 9 recon. Example:

```
### GWIS (fire footprint)
- Endpoint: <actual URL chosen during recon>
- Auth: <none / token / referrer-locked>
- Rate limit: <documented limits>
- Fallback: NIFC (US only) if GWIS access degrades
```

- [ ] **Step 4: Update `PIPELINE.md`**

Add a short section describing the per-complex tier-dedup mechanic (mirrors the GDACS cyclone-tier description).

- [ ] **Step 5: Commit**

```bash
git add BRIEFING.md PIPELINE.md
git commit -m "Document fire_footprint source, scoring, and secrets"
```

---

## Task 12: Full-suite verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: ALL PASS. Count should be ≥320 (pre-change count was 310 per BRIEFING).

- [ ] **Step 2: Sanity-run the orchestrator in dry-run mode if available**

Run: `python -m src.main --dry-run 2>&1 | head -40` (or whatever dry-run invocation the project supports).
Expected: `[alerts] Checking fire footprints (GWIS)...` appears once, no exception.

- [ ] **Step 3: Final commit if any doc tweaks needed**

```bash
git status
# if clean, nothing to do
# if residual notes edits:
git add -A
git commit -m "Finalize fire_footprint lane"
```

- [ ] **Step 4: Push the branch**

```bash
git push -u origin andrewzp/fire-footprint-gwis
```

---

## Rollback / follow-up notes

If the GWIS endpoint proves flaky in production:
- Switch `GWIS_URL` to the NIFC ArcGIS endpoint in `src/data/fire_footprint.py` and adjust the field accessors. Tests mock HTTP so no test changes are needed beyond updating `SAMPLE_PAYLOAD`.
- The `fire_complex_tiers` state is safe to keep; if we change the source, we should namespace the `complex_id` (e.g. `nifc_<id>`) to avoid collision with any prior GWIS ids.

Deferred follow-up:
- Country-YTD percentile detector (Lane 3 spec item 2). Needs GWIS historical monthly stats 1985+ and day-of-year interpolation. Build once the per-complex signal has been observed in production for ≥30 days.
