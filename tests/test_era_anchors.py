"""Tests for src/voice/era_anchors.py — JSON loader + pick function."""

import json
import os

import pytest

from src.voice.era_anchors import (
    load_era_anchors,
    pick_anchors,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Make every test see a fresh load — global cache shouldn't leak."""
    reset_cache()
    yield
    reset_cache()


class TestLoadEraAnchors:
    def test_loads_default_path(self):
        anchors = load_era_anchors()
        assert isinstance(anchors, dict)
        assert len(anchors) >= 30  # 1995-2025 inclusive

    def test_every_year_has_at_least_3_anchors(self):
        # The whole point is variety — a year with one anchor produces
        # the same framing every cycle. Curation target is 8.
        anchors = load_era_anchors()
        for year, items in anchors.items():
            assert len(items) >= 3, f"{year} has only {len(items)} anchors"

    def test_meta_key_excluded_from_year_index(self):
        anchors = load_era_anchors()
        for year in anchors:
            assert isinstance(year, int)

    def test_year_coverage_is_contiguous_1995_to_recent(self):
        anchors = load_era_anchors()
        years = sorted(anchors.keys())
        assert years[0] == 1995
        # Every year between min and max should be present — gaps mean
        # records from those years get no anchor and the framing rots.
        for y in range(years[0], years[-1] + 1):
            assert y in anchors, f"missing year {y}"

    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = load_era_anchors(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_malformed_json_returns_empty_dict(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ this is not json")
        result = load_era_anchors(str(bad))
        assert result == {}

    def test_skips_non_year_keys(self, tmp_path):
        good = tmp_path / "anchors.json"
        good.write_text(json.dumps({
            "_meta": {"note": "ignored"},
            "1999": ["Y2K loomed"],
            "not-a-year": ["should be skipped"],
        }))
        result = load_era_anchors(str(good))
        assert 1999 in result
        assert "not-a-year" not in result
        assert len(result) == 1

    def test_strips_empty_anchor_strings(self, tmp_path):
        path = tmp_path / "anchors.json"
        path.write_text(json.dumps({
            "1999": ["Y2K loomed", "", "  "],
        }))
        result = load_era_anchors(str(path))
        assert result[1999] == ["Y2K loomed"]

    def test_cache_serves_repeat_default_calls(self, tmp_path):
        # Default-path calls are cached. Mutating the cache shouldn't
        # affect the file on disk, but a second call should return the
        # cached object (same identity).
        first = load_era_anchors()
        second = load_era_anchors()
        assert first is second


class TestPickAnchors:
    def test_returns_at_most_k(self):
        result = pick_anchors(1999, k=3)
        assert len(result) <= 3
        assert all(isinstance(x, str) for x in result)

    def test_unknown_year_returns_empty(self):
        result = pick_anchors(1850, k=4)
        assert result == []

    def test_year_outside_coverage_returns_empty(self):
        # 2026 (current year) is intentionally absent — records FROM the
        # current year don't get anchors because the data hasn't aged
        # enough to feel historical.
        result = pick_anchors(2026, k=4)
        assert result == []

    def test_seed_is_deterministic(self):
        a = pick_anchors(1999, k=4, seed="city-1999-2026-04-25")
        b = pick_anchors(1999, k=4, seed="city-1999-2026-04-25")
        assert a == b

    def test_different_seeds_pick_different_subsets(self):
        # Statistically unlikely but possible for any 2 seeds to coincide —
        # sample 20 seeds and assert at least 2 distinct subsets exist.
        attempts = [pick_anchors(1999, k=4, seed=f"seed-{i}") for i in range(20)]
        unique_subsets = {tuple(sorted(x)) for x in attempts}
        assert len(unique_subsets) >= 2  # at least 2 distinct subsets across 20 seeds

    def test_k_larger_than_available_returns_all(self, tmp_path):
        path = tmp_path / "small.json"
        path.write_text(json.dumps({"1999": ["a", "b"]}))
        result = pick_anchors(1999, k=10, seed="test", path=str(path))
        assert sorted(result) == ["a", "b"]


class TestEraAnchorOneInTenGate:
    """Era anchors are parked at 1-in-10 per user direction (2026-04-29)
    after Apr 27 + Apr 29 corpora showed every record draft converging
    on era-anchor framing. The gate enforces structurally; prose-only
    de-emphasis didn't hold."""

    def test_gate_rate_close_to_ten_percent(self):
        # Statistical: across many seeds, gate fires at ~10%.
        from src.voice.generator import _era_anchor_should_fire
        fires = sum(1 for i in range(10000) if _era_anchor_should_fire(f"seed-{i}"))
        # Binomial 95% CI for n=10000, p=0.1 is ~[940, 1060]; widen slightly.
        assert 850 < fires < 1150, f"Gate fired {fires}/10000 times, expected ~1000"

    def test_gate_is_deterministic_per_seed(self):
        from src.voice.generator import _era_anchor_should_fire
        for seed in ("a", "b", "c", "city-1999-2026-04-26"):
            assert _era_anchor_should_fire(seed) == _era_anchor_should_fire(seed)

    def test_gate_rate_parameter_works(self):
        # Higher rate should fire more often.
        from src.voice.generator import _era_anchor_should_fire
        fires_at_50 = sum(1 for i in range(2000) if _era_anchor_should_fire(f"r50-{i}", rate=0.5))
        assert 800 < fires_at_50 < 1200, f"At rate=0.5, fires={fires_at_50}/2000"


def _find_seed(should_fire: bool, prefix: str = "find") -> str:
    """Find a seed where the gate matches the desired bool. Test helper."""
    from src.voice.generator import _era_anchor_should_fire
    for i in range(10000):
        seed = f"{prefix}-{i}"
        if _era_anchor_should_fire(seed) == should_fire:
            return seed
    raise RuntimeError(f"Couldn't find seed where fire={should_fire}")


class TestEraAnchorIntegrationWithGenerator:
    """Verify the anchor hint flows correctly into the prompt — both
    when the gate fires (curated content) and when it doesn't (steer-
    away message)."""

    def test_helper_steers_away_when_gate_skips(self):
        # 90% of calls should return the explicit "parked" steer-away
        # message naming alternative specificity vehicles.
        from src.voice.generator import _era_anchor_hint
        seed_no_fire = _find_seed(should_fire=False)
        hint = _era_anchor_hint(1999, seed_key=seed_no_fire)
        # Steer-away includes parking signal AND the alternative vehicles
        assert "parked" in hint.lower() or "1 per 10" in hint or "1 in 10" in hint
        # Names at least 2 of the 5 alternative vehicles
        alternatives = ["accelerating-warming", "past-tense personification",
                        "place-as-punchline", "absolute scale", "ecosystem context"]
        named = sum(1 for alt in alternatives if alt in hint.lower())
        assert named >= 3, f"Only {named} alternative vehicles named in steer-away"

    def test_helper_steers_away_does_not_use_year_label_as_anchor(self):
        # When gate skips, hint should NOT present the curated year-anchor list.
        from src.voice.generator import _era_anchor_hint
        seed_no_fire = _find_seed(should_fire=False)
        hint = _era_anchor_hint(1999, seed_key=seed_no_fire)
        # The curated content for 1999 includes "Y2K", "Matrix", etc.
        # The steer-away should NOT list them (would defeat the parking).
        assert "Y2K" not in hint and "Matrix" not in hint

    def test_helper_returns_curated_when_gate_fires(self):
        from src.voice.generator import _era_anchor_hint
        seed_fires = _find_seed(should_fire=True)
        hint = _era_anchor_hint(1999, seed_key=seed_fires)
        assert "1999" in hint
        # Curated content for 1999 (any one of these should appear)
        anchors_1999 = ("Y2K", "Matrix", "Napster", "Star Wars", "dot-com")
        named = sum(1 for a in anchors_1999 if a in hint)
        assert named >= 1, f"Curated 1999 content missing from gate-fire path: {hint}"

    def test_helper_returns_curated_includes_one_in_ten_messaging(self):
        # When gate fires, the hint frames it as "your 1-in-10 turn"
        # so Gemini knows this is the rare permitted draft.
        from src.voice.generator import _era_anchor_hint
        seed_fires = _find_seed(should_fire=True)
        hint = _era_anchor_hint(1999, seed_key=seed_fires)
        assert "1-in-10" in hint or "1 in 10" in hint or "your" in hint.lower()

    def test_helper_returns_empty_for_unknown_year_when_gated_in(self):
        # Even when the gate fires, an unknown year (1850) has no
        # curated content — return empty string. Caller's prompt
        # then degrades gracefully.
        from src.voice.generator import _era_anchor_hint
        seed_fires = _find_seed(should_fire=True)
        hint = _era_anchor_hint(1850, seed_key=seed_fires)
        assert hint == ""
