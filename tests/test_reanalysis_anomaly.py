"""Tests for the reanalysis regional-anomaly data layer (Part B / "reganom").

Covers the Rev-3 deltas:
  §A — curated REGION_WATCHLIST (16 regions, ~100 points)
  §B — trigger: +6C absolute AND mean z >= 2.0 AND >= 50% point support
  §C — dated fetch + complete-day scanning (skip the ERA5 archive lag)
"""

from __future__ import annotations

import json

import pytest

from src.data import reanalysis_anomaly as ra
from src.data.reanalysis_anomaly import (
    REGION_WATCHLIST,
    RegionDef,
    detect_regional_anomaly,
    fetch_all_reganom_t2m,
    load_daily_climatology,
)
from src.data.source_status import SourceSkipped


# --------------------------------------------------------------------------- #
# §A — curated watchlist
# --------------------------------------------------------------------------- #


class TestRegionWatchlist:
    def test_has_sixteen_curated_regions(self) -> None:
        assert len(REGION_WATCHLIST) == 16

    def test_total_points_in_curated_band(self) -> None:
        total = sum(len(r.points) for r in REGION_WATCHLIST)
        # §A bounds the curation to ~80-120 points; this list is exactly 100.
        assert total == 100
        assert 80 <= total <= 120

    def test_every_region_has_at_least_three_points(self) -> None:
        # The runtime startup assertion guarantees this; mirror it as a test.
        for r in REGION_WATCHLIST:
            assert len(r.points) >= 3, f"{r.name} has < 3 points"

    def test_region_slugs_are_unique(self) -> None:
        slugs = [r.slug for r in REGION_WATCHLIST]
        assert len(slugs) == len(set(slugs))

    def test_no_duplicate_points_within_a_region(self) -> None:
        for r in REGION_WATCHLIST:
            assert len(r.points) == len(set(r.points)), f"{r.name} has dup coords"

    def test_slug_replaces_spaces(self) -> None:
        assert RegionDef("Pacific Northwest", [(0.0, 0.0)]).slug == "Pacific_Northwest"

    def test_coords_are_plausible(self) -> None:
        for r in REGION_WATCHLIST:
            for lat, lon in r.points:
                assert -90 <= lat <= 90, f"{r.name} bad lat {lat}"
                assert -180 <= lon <= 180, f"{r.name} bad lon {lon}"


# --------------------------------------------------------------------------- #
# climatology cache loader
# --------------------------------------------------------------------------- #


class TestLoadDailyClimatology:
    def test_missing_file_raises_source_skipped(self, tmp_path) -> None:
        missing = tmp_path / "nope.json"
        with pytest.raises(SourceSkipped):
            load_daily_climatology(str(missing))

    def test_present_file_returns_dict(self, tmp_path) -> None:
        cache = {"Sahel": {"13.51,2.11": {"lat": 13.51, "lon": 2.11, "days": {}}}}
        path = tmp_path / "clim.json"
        path.write_text(json.dumps(cache), encoding="utf-8")
        assert load_daily_climatology(str(path)) == cache


# --------------------------------------------------------------------------- #
# detection helpers
# --------------------------------------------------------------------------- #


def _region(points):
    return RegionDef("Testland", list(points))


def _clim(region, *, mmdds, mean_c=20.0, std_c=2.0, mean_min_c=12.0):
    """Build a climatology cache for one region over the given MM-DD keys."""
    days = {mmdd: {"mean_c": mean_c, "std_c": std_c, "mean_min_c": mean_min_c} for mmdd in mmdds}
    return {
        region.slug: {
            f"{lat},{lon}": {"lat": lat, "lon": lon, "days": dict(days)}
            for (lat, lon) in region.points
        }
    }


def _live(points, rows):
    """rows: list[(date_iso, temp|None)] applied identically to every point."""
    return {pt: list(rows) for pt in points}


# --------------------------------------------------------------------------- #
# §B + §C — detection
# --------------------------------------------------------------------------- #


class TestDetectRegionalAnomaly:
    def test_fires_on_sustained_plus_six_with_support_and_sigma(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=2.0)
        # All points 27C => anomaly +7 (>=6), z=3.5 (>=2), fraction 1.0 (>=0.5).
        rows = [("2026-06-03", 27.0), ("2026-06-04", 27.0), ("2026-06-05", 27.0)]
        ev = detect_regional_anomaly(region, clim, _live(pts, rows))
        assert ev is not None
        assert ev.region == "Testland"
        assert ev.region_slug == "Testland"
        assert ev.sustained_days == 3
        assert ev.cities_sampled == 4
        assert ev.mean_anomaly_c == pytest.approx(7.0, abs=0.01)
        assert ev.window_start == "2026-06-03"
        assert ev.window_end == "2026-06-05"
        assert ev.event_id == "reganom_Testland_2026-06-05"
        assert ev.mean_zscore == pytest.approx(3.5, abs=0.01)

    def test_does_not_fire_below_six_degrees(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=2.0)
        rows = [("2026-06-03", 25.0), ("2026-06-04", 25.0), ("2026-06-05", 25.0)]  # +5
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None

    def test_does_not_fire_below_min_days(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-04", "06-05"], mean_c=20.0, std_c=2.0)
        rows = [("2026-06-04", 27.0), ("2026-06-05", 27.0)]  # only 2 days
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None

    def test_sigma_floor_blocks_high_variance_plus_six(self) -> None:
        # §B: +6C in a high-variance region (std 4 => z 1.5 < 2.0) must NOT fire.
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=4.0)
        rows = [("2026-06-03", 26.0), ("2026-06-04", 26.0), ("2026-06-05", 26.0)]  # +6, z=1.5
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None

    def test_fraction_support_blocks_single_hot_point(self) -> None:
        # §B: one scorching point can't drag the mean over if < 50% individually exceed +6.
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=2.0)
        # point0 = +18, others = +2. mean = +6 (passes), mean-z = 3 (passes),
        # but only 1/4 = 25% exceed +6 => fraction gate blocks it.
        live = {
            pts[0]: [("2026-06-03", 38.0), ("2026-06-04", 38.0), ("2026-06-05", 38.0)],
            pts[1]: [("2026-06-03", 22.0), ("2026-06-04", 22.0), ("2026-06-05", 22.0)],
            pts[2]: [("2026-06-03", 22.0), ("2026-06-04", 22.0), ("2026-06-05", 22.0)],
            pts[3]: [("2026-06-03", 22.0), ("2026-06-04", 22.0), ("2026-06-05", 22.0)],
        }
        assert detect_regional_anomaly(region, clim, live) is None

    def test_region_absent_from_climatology_returns_none(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = {"SomeOtherRegion": {}}  # Testland missing
        rows = [("2026-06-03", 27.0), ("2026-06-04", 27.0), ("2026-06-05", 27.0)]
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None

    def test_missing_mmdd_skips_that_day(self) -> None:
        # If a day's MM-DD is absent from the cache, that day is skipped (not a crash);
        # remaining complete days are too few to sustain => None.
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-05"], mean_c=20.0, std_c=2.0)  # 06-04 missing
        rows = [("2026-06-03", 27.0), ("2026-06-04", 27.0), ("2026-06-05", 27.0)]
        # 06-04 has no climatology => not a complete qualifying day => run broken => None.
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None

    def test_leap_day_falls_back_to_feb_28(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["02-26", "02-27", "02-28"], mean_c=10.0, std_c=2.0)
        # 2024 is a leap year; 02-29 must fall back to the 02-28 normal (mean 10 => +7).
        rows = [("2024-02-27", 17.0), ("2024-02-28", 17.0), ("2024-02-29", 17.0)]
        ev = detect_regional_anomaly(region, clim, _live(pts, rows))
        assert ev is not None
        assert ev.window_end == "2024-02-29"
        assert ev.sustained_days == 3

    def test_fewer_than_three_valid_points_returns_none(self) -> None:
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=2.0)
        # Only 2 points have live data => below min_points (3) => None.
        live = {
            pts[0]: [("2026-06-03", 27.0), ("2026-06-04", 27.0), ("2026-06-05", 27.0)],
            pts[1]: [("2026-06-03", 27.0), ("2026-06-04", 27.0), ("2026-06-05", 27.0)],
            pts[2]: None,
            pts[3]: None,
        }
        assert detect_regional_anomaly(region, clim, live) is None

    def test_skips_trailing_null_lag_days_and_anchors_on_complete_days(self) -> None:
        # §C: the most-recent days are null (archive lag). The scan must anchor on the
        # most-recent COMPLETE day and still find the qualifying run before it.
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(region, mmdds=["06-03", "06-04", "06-05"], mean_c=20.0, std_c=2.0)
        rows = [
            ("2026-06-03", 27.0),
            ("2026-06-04", 27.0),
            ("2026-06-05", 27.0),
            ("2026-06-06", None),  # lag
            ("2026-06-07", None),  # lag
        ]
        ev = detect_regional_anomaly(region, clim, _live(pts, rows))
        assert ev is not None
        assert ev.window_end == "2026-06-05"  # last COMPLETE day, not 06-07
        assert ev.sustained_days == 3

    def test_only_counts_run_ending_at_most_recent_complete_day(self) -> None:
        # A qualifying spell that ENDED days ago (anomaly since dropped) must NOT fire —
        # the signal is "ongoing as of the most-recent complete day".
        pts = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        region = _region(pts)
        clim = _clim(
            region,
            mmdds=["06-01", "06-02", "06-03", "06-04", "06-05"],
            mean_c=20.0,
            std_c=2.0,
        )
        rows = [
            ("2026-06-01", 27.0),  # hot
            ("2026-06-02", 27.0),  # hot
            ("2026-06-03", 27.0),  # hot
            ("2026-06-04", 21.0),  # cooled off (+1)
            ("2026-06-05", 21.0),  # still cool — most-recent complete day does NOT qualify
        ]
        assert detect_regional_anomaly(region, clim, _live(pts, rows)) is None


# --------------------------------------------------------------------------- #
# §C — fetch_all_reganom_t2m (batched, dated)
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _sample_event():
    from src.data.reanalysis_anomaly import RegionalAnomalyEvent

    return RegionalAnomalyEvent(
        region="France",
        region_slug="France",
        cities_sampled=6,
        mean_anomaly_c=7.2,
        mean_zscore=3.1,
        fraction_exceeding=0.83,
        sustained_days=4,
        window_start="2026-06-02",
        window_end="2026-06-05",
        event_id="reganom_France_2026-06-05",
    )


class TestBuildRegionalAnomalyBundle:
    """Honesty Layer 1: the bundle must frame the signal as a point index over
    N sampled cities, never a bare-region / area-weighted aggregate."""

    def test_where_names_sampled_cities_not_bare_region(self) -> None:
        from src.two_bot.intern import build_regional_anomaly_bundle

        b = build_regional_anomaly_bundle(_sample_event())
        assert b.where == "6 sampled cities in France"
        assert b.where != "France"

    def test_signal_kind_is_bare_literal_for_the_honesty_gate(self) -> None:
        # MUST be the bare literal "regional_anomaly" so the §F Layer-0 gate
        # condition (bundle.signal_kind == "regional_anomaly") fires.
        from src.two_bot.intern import build_regional_anomaly_bundle

        assert build_regional_anomaly_bundle(_sample_event()).signal_kind == "regional_anomaly"

    def test_headline_carries_cities_sampled_and_anomaly(self) -> None:
        from src.two_bot.intern import build_regional_anomaly_bundle

        h = build_regional_anomaly_bundle(_sample_event()).headline_metric
        assert h["label"] == "sampled_city_mean_anomaly_c"
        assert h["value"] == 7.2
        assert h["cities_sampled"] == 6

    def test_current_facts_flag_point_index_not_area_weighted(self) -> None:
        from src.two_bot.intern import build_regional_anomaly_bundle

        facts = {f["label"]: f["value"] for f in build_regional_anomaly_bundle(_sample_event()).current_facts}
        assert facts["data_kind"] == "point_index_not_area_weighted"
        assert facts["cities_sampled"] == 6

    def test_forbidden_claims_present_and_honest_form_safe(self) -> None:
        from src.two_bot.intern import build_regional_anomaly_bundle

        fc = build_regional_anomaly_bundle(_sample_event()).historical_context["forbidden_claims"]
        assert any(x.lower() == "national mean" for x in fc)
        assert any("area-weighted" in x.lower() for x in fc)
        # The honest framing must NOT contain any forbidden substring (else the
        # deterministic §F gate would false-kill honest drafts).
        honest = "6 sampled cities in France ran +7.2C above their daily normal"
        assert not any(x.lower() in honest.lower() for x in fc)

    def test_dishonest_aggregate_trips_a_forbidden_claim(self) -> None:
        from src.two_bot.intern import build_regional_anomaly_bundle

        fc = build_regional_anomaly_bundle(_sample_event()).historical_context["forbidden_claims"]
        dishonest = "France's national mean ran 7C above normal"
        assert any(x.lower() in dishonest.lower() for x in fc)


class TestHonestyGateLayer0:
    """§F: the deterministic, bundle-aware gate that runs BEFORE fact-check.
    Load-bearing honesty layer — substring-matches forbidden_claims."""

    def _bundle(self):
        from src.two_bot.intern import build_regional_anomaly_bundle

        return build_regional_anomaly_bundle(_sample_event())

    def test_rejects_dishonest_aggregate(self) -> None:
        from src.two_bot.pipeline import _forbidden_claim_violation

        hit = _forbidden_claim_violation("France's national mean ran 7C above normal", self._bundle())
        assert hit is not None

    def test_passes_honest_sampled_cities_form(self) -> None:
        from src.two_bot.pipeline import _forbidden_claim_violation

        honest = "6 sampled cities in France ran +7.2C above their daily normal"
        assert _forbidden_claim_violation(honest, self._bundle()) is None

    def test_case_insensitive(self) -> None:
        from src.two_bot.pipeline import _forbidden_claim_violation

        assert _forbidden_claim_violation("AREA-WEIGHTED nonsense", self._bundle()) is not None

    def test_straight_apostrophe_possessive_is_caught(self) -> None:
        from src.two_bot.pipeline import _forbidden_claim_violation

        assert _forbidden_claim_violation("France's average ran +7C above normal", self._bundle()) is not None

    def test_curly_apostrophe_possessive_is_caught(self) -> None:
        # Gemini emits U+2019; the possessive forbidden_claim must still match.
        from src.two_bot.pipeline import _forbidden_claim_violation

        curly = "France’s average ran +7C above normal"
        assert "’" in curly
        assert _forbidden_claim_violation(curly, self._bundle()) is not None

    def test_ignores_non_regional_anomaly_bundles(self) -> None:
        # The gate keys on signal_kind; other bundles are never checked here.
        from src.two_bot.pipeline import _forbidden_claim_violation
        from src.two_bot.types import StoryBundle

        other = StoryBundle(
            signal_kind="absolute_extreme_hot",
            where="Paris",
            when="2026-06-05",
            event_id="x",
            headline_metric={},
            current_facts=[],
            historical_context={"forbidden_claims": ["national mean"]},
        )
        assert _forbidden_claim_violation("national mean whatever", other) is None


class TestScoreRegionalAnomaly:
    def test_minimal_event_clears_threshold_at_78(self) -> None:
        from src.editorial.scoring import score_regional_anomaly

        s = score_regional_anomaly(6.0, 3, 3)
        assert s.total == 78
        assert s.threshold == 76
        assert s.passes

    def test_elite_event_scores_83(self) -> None:
        from src.editorial.scoring import score_regional_anomaly

        s = score_regional_anomaly(8.0, 7, 6)
        assert s.total == 83

    def test_category_is_regional_anomaly(self) -> None:
        from src.editorial.scoring import score_regional_anomaly

        assert score_regional_anomaly(6.0, 3, 3).category == "regional_anomaly"


class TestFetchAllReganomT2m:
    def test_returns_dated_rows_in_coord_order(self, monkeypatch) -> None:
        coords = [(48.86, 2.35), (40.42, -3.70)]
        payload = [
            {"daily": {"time": ["2026-06-04", "2026-06-05"], "temperature_2m_max": [30.0, 31.0]}},
            {"daily": {"time": ["2026-06-04", "2026-06-05"], "temperature_2m_max": [28.0, 29.0]}},
        ]
        monkeypatch.setattr(ra, "fetch_with_retry", lambda *a, **k: _FakeResp(payload))
        out = fetch_all_reganom_t2m(coords)
        assert out[(48.86, 2.35)] == [("2026-06-04", 30.0), ("2026-06-05", 31.0)]
        assert out[(40.42, -3.70)] == [("2026-06-04", 28.0), ("2026-06-05", 29.0)]

    def test_total_failure_returns_empty_dict(self, monkeypatch) -> None:
        import requests

        def _boom(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(ra, "fetch_with_retry", _boom)
        assert fetch_all_reganom_t2m([(1.0, 2.0)]) == {}

    def test_missing_daily_block_maps_to_none(self, monkeypatch) -> None:
        coords = [(48.86, 2.35), (40.42, -3.70)]
        payload = [
            {"daily": {"time": ["2026-06-05"], "temperature_2m_max": [30.0]}},
            {},  # no daily block for the second coord
        ]
        monkeypatch.setattr(ra, "fetch_with_retry", lambda *a, **k: _FakeResp(payload))
        out = fetch_all_reganom_t2m(coords)
        assert out[(48.86, 2.35)] == [("2026-06-05", 30.0)]
        assert out[(40.42, -3.70)] is None

    def test_single_object_response_is_wrapped(self, monkeypatch) -> None:
        coords = [(48.86, 2.35)]
        payload = {"daily": {"time": ["2026-06-05"], "temperature_2m_max": [30.0]}}
        monkeypatch.setattr(ra, "fetch_with_retry", lambda *a, **k: _FakeResp(payload))
        out = fetch_all_reganom_t2m(coords)
        assert out[(48.86, 2.35)] == [("2026-06-05", 30.0)]
