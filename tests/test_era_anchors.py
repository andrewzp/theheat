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

    def test_default_anchors_respect_safety_curation_rules(self):
        # Mirrors data/era_anchors.json selection_criteria: do not use deaths,
        # disasters, political handovers, or divisive public-figure drama as
        # scaffolding for climate-record copy.
        banned_fragments = [
            "death stopped the world",
            "returned to China",
            "SARS swept",
            "Pope John Paul II died",
            "Heath Ledger died",
            "Michael Jackson died",
            "Steve Jobs died",
            "Pope Francis was elected",
            "Robin Williams died",
            "both died",
            "Notre Dame burned",
            "Greta Thunberg",
            "COVID lockdowns",
            "Queen Elizabeth II died",
            "fired Sam Altman",
            "Titan submersible imploded",
            "dating Travis Kelce",
        ]
        anchors = load_era_anchors()
        offenders = [
            (year, anchor, fragment)
            for year, year_anchors in anchors.items()
            for anchor in year_anchors
            for fragment in banned_fragments
            if fragment.lower() in anchor.lower()
        ]
        assert offenders == []

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
