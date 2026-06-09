"""Tests for the one-time ERA5 climatology backfill (Step 0 GATE).

Covers the pure helpers (MM-DD grouping, mean/std, leap-day presence), the
429-aware backoff wrapper (fetch_with_retry does NOT retry 429), and the
idempotent skip-detection / atomic checkpoint in build_cache. No network.
"""

from __future__ import annotations

import json

import pytest
import requests

from scripts import build_climatology_cache as bc
from src.data.reanalysis_anomaly import RegionDef


# --------------------------------------------------------------------------- #
# _compute_point_climatology
# --------------------------------------------------------------------------- #


class TestComputePointClimatology:
    def test_groups_by_mmdd_and_means(self) -> None:
        # 06-01 across 3 years: highs 20/22/24 (mean 22), lows 10/12/14 (mean 12).
        dates = ["1991-06-01", "1992-06-01", "1993-06-01"]
        tmax = [20.0, 22.0, 24.0]
        tmin = [10.0, 12.0, 14.0]
        days = bc._compute_point_climatology(dates, tmax, tmin)
        assert set(days) == {"06-01"}
        assert days["06-01"]["mean_c"] == pytest.approx(22.0)
        assert days["06-01"]["mean_min_c"] == pytest.approx(12.0)
        assert days["06-01"]["std_c"] > 0

    def test_includes_leap_day_when_present(self) -> None:
        dates = ["1992-02-29", "1996-02-29", "2000-02-29"]
        tmax = [5.0, 6.0, 7.0]
        tmin = [-1.0, 0.0, 1.0]
        days = bc._compute_point_climatology(dates, tmax, tmin)
        assert "02-29" in days

    def test_single_sample_has_zero_std(self) -> None:
        days = bc._compute_point_climatology(["1991-07-04"], [30.0], [18.0])
        assert days["07-04"]["std_c"] == 0.0

    def test_skips_null_readings(self) -> None:
        dates = ["1991-06-01", "1992-06-01"]
        days = bc._compute_point_climatology(dates, [20.0, None], [10.0, None])
        assert days["06-01"]["mean_c"] == pytest.approx(20.0)

    def test_builds_days_from_tmax_when_tmin_empty(self) -> None:
        # Regression: a 3-way zip(dates, tmax, tmin) truncated to ZERO rows when
        # tmin was empty (tmax-only backfill), silently producing an empty day-map.
        days = bc._compute_point_climatology(["1991-06-01", "1991-06-02"], [20.0, 22.0], [])
        assert set(days) == {"06-01", "06-02"}
        assert days["06-01"]["mean_c"] == pytest.approx(20.0)
        assert days["06-01"]["mean_min_c"] is None


# --------------------------------------------------------------------------- #
# _fetch_archive_with_backoff (429-aware)
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class TestFetchArchiveWithBackoff:
    def test_retries_429_then_succeeds(self, monkeypatch) -> None:
        calls = {"n": 0}

        def _get(*a, **k):
            calls["n"] += 1
            return _Resp(429) if calls["n"] == 1 else _Resp(200, {"ok": True})

        monkeypatch.setattr(bc.requests, "get", _get)
        monkeypatch.setattr(bc.time, "sleep", lambda *_a, **_k: None)
        resp = bc._fetch_archive_with_backoff("http://x", {})
        assert resp.json() == {"ok": True}
        assert calls["n"] == 2

    def test_retries_5xx_then_succeeds(self, monkeypatch) -> None:
        calls = {"n": 0}

        def _get(*a, **k):
            calls["n"] += 1
            return _Resp(503) if calls["n"] == 1 else _Resp(200, {"ok": True})

        monkeypatch.setattr(bc.requests, "get", _get)
        monkeypatch.setattr(bc.time, "sleep", lambda *_a, **_k: None)
        assert bc._fetch_archive_with_backoff("http://x", {}).json() == {"ok": True}
        assert calls["n"] == 2

    def test_raises_after_persistent_429(self, monkeypatch) -> None:
        monkeypatch.setattr(bc.requests, "get", lambda *a, **k: _Resp(429))
        monkeypatch.setattr(bc.time, "sleep", lambda *_a, **_k: None)
        with pytest.raises(requests.HTTPError):
            bc._fetch_archive_with_backoff("http://x", {}, max_attempts=3)

    def test_honors_retry_after_header_on_429(self, monkeypatch) -> None:
        slept: list[float] = []
        calls = {"n": 0}

        def _get(*a, **k):
            calls["n"] += 1
            return _Resp(429, headers={"Retry-After": "37"}) if calls["n"] == 1 else _Resp(200, {"ok": True})

        monkeypatch.setattr(bc.requests, "get", _get)
        monkeypatch.setattr(bc.time, "sleep", lambda s, *a, **k: slept.append(s))
        assert bc._fetch_archive_with_backoff("http://x", {}).json() == {"ok": True}
        # The Retry-After value (37s) drives the wait, not the short exponential default.
        assert slept and slept[0] == pytest.approx(37.0)

    def test_429_wait_is_capped(self, monkeypatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(bc.requests, "get", lambda *a, **k: _Resp(429, headers={"Retry-After": "9999"}))
        monkeypatch.setattr(bc.time, "sleep", lambda s, *a, **k: slept.append(s))
        with pytest.raises(requests.HTTPError):
            bc._fetch_archive_with_backoff("http://x", {}, max_attempts=2)
        assert all(s <= bc._MAX_BACKOFF_SECONDS for s in slept)


# --------------------------------------------------------------------------- #
# build_cache — skip-detection + atomic checkpoint
# --------------------------------------------------------------------------- #


def _full_days(n: int = 366) -> dict:
    """A complete-enough days map (>= _MIN_DAY_KEYS keys) for the build_cache guard."""
    return {f"d{i:04d}": {"mean_c": 22.0, "std_c": 2.0, "mean_min_c": 12.0} for i in range(n)}


def _full_point(lat, lon):
    return {"lat": lat, "lon": lon, "days": _full_days()}


def _short_point(lat, lon):
    return {"lat": lat, "lon": lon, "days": {"06-01": {"mean_c": 22.0, "std_c": 2.0, "mean_min_c": 12.0}}}


class TestBuildCache:
    def test_skips_already_complete_points(self, tmp_path) -> None:
        region = RegionDef("Testland", [(0.0, 0.0), (0.0, 1.0)])
        path = tmp_path / "clim.json"
        # Pre-seed the first point as already COMPLETE.
        path.write_text(json.dumps({"Testland": {"0.0,0.0": _full_point(0.0, 0.0)}}), encoding="utf-8")

        fetched: list[tuple[float, float]] = []

        def _fetch(lat, lon):
            fetched.append((lat, lon))
            return _full_point(lat, lon)

        bc.build_cache([region], str(path), delay_ms=0, fetch=_fetch)
        # Only the un-cached point (0.0, 1.0) should be fetched.
        assert fetched == [(0.0, 1.0)]

    def test_re_fetches_poisoned_empty_point(self, tmp_path) -> None:
        # A previously-poisoned empty point must be RE-FETCHED, not skipped.
        region = RegionDef("Testland", [(0.0, 0.0)])
        path = tmp_path / "clim.json"
        path.write_text(json.dumps({"Testland": {"0.0,0.0": {"lat": 0.0, "lon": 0.0, "days": {}}}}), encoding="utf-8")

        fetched: list = []

        def _fetch(lat, lon):
            fetched.append((lat, lon))
            return _full_point(lat, lon)

        bc.build_cache([region], str(path), delay_ms=0, fetch=_fetch)
        assert fetched == [(0.0, 0.0)]
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert len(saved["Testland"]["0.0,0.0"]["days"]) >= bc._MIN_DAY_KEYS

    def test_does_not_checkpoint_a_short_fetch(self, tmp_path) -> None:
        # A short fetch result must never be written (it would poison the resume guard).
        region = RegionDef("Testland", [(0.0, 0.0)])
        path = tmp_path / "clim.json"
        bc.build_cache([region], str(path), delay_ms=0, fetch=_short_point)
        # Cache file is either absent or has no completed point for this region.
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            assert "0.0,0.0" not in saved.get("Testland", {})
        assert bc.incomplete_points(bc._load_cache(str(path)), [region]) == ["Testland/0.0,0.0"]

    def test_failed_fetch_is_left_for_re_run(self, tmp_path) -> None:
        region = RegionDef("Testland", [(0.0, 0.0)])
        path = tmp_path / "clim.json"

        def _boom(lat, lon):
            raise RuntimeError("rate limited")

        bc.build_cache([region], str(path), delay_ms=0, fetch=_boom)
        assert bc.incomplete_points(bc._load_cache(str(path)), [region]) == ["Testland/0.0,0.0"]

    def test_writes_cache_atomically_per_point(self, tmp_path) -> None:
        region = RegionDef("Testland", [(0.0, 0.0), (0.0, 1.0)])
        path = tmp_path / "clim.json"
        bc.build_cache([region], str(path), delay_ms=0, fetch=_full_point)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert set(saved["Testland"]) == {"0.0,0.0", "0.0,1.0"}

    def test_dry_run_writes_nothing(self, tmp_path) -> None:
        region = RegionDef("Testland", [(0.0, 0.0)])
        path = tmp_path / "clim.json"
        fetched: list = []
        bc.build_cache([region], str(path), delay_ms=0, dry_run=True,
                       fetch=lambda la, lo: fetched.append((la, lo)) or _full_point(la, lo))
        assert fetched == []
        assert not path.exists()


class TestFetchOnePointSoftEmpty:
    def test_retries_soft_empty_200_then_succeeds(self, monkeypatch) -> None:
        # A 200 with an empty daily block (soft rate-limit) is retried, not accepted.
        full_daily = {"time": [f"1991-{d:04d}" for d in range(366)],
                      "temperature_2m_max": [20.0] * 366}
        calls = {"n": 0}

        def _get(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(200, {"daily": {"time": [], "temperature_2m_max": []}})
            return _Resp(200, {"daily": full_daily})

        # _compute keys MM-DD; build a payload whose time has 366 distinct MM-DD.
        monkeypatch.setattr(bc.requests, "get", _get)
        monkeypatch.setattr(bc.time, "sleep", lambda *a, **k: None)
        # Replace the date strings with real distinct MM-DD so >=365 keys result.
        import datetime
        days = [(datetime.date(1992, 1, 1) + datetime.timedelta(days=i)).isoformat() for i in range(366)]
        full_daily["time"] = days
        point = bc._fetch_one_point(0.0, 0.0)
        assert len(point["days"]) >= bc._MIN_DAY_KEYS
        assert calls["n"] == 2  # retried once

    def test_raises_when_persistently_short(self, monkeypatch) -> None:
        monkeypatch.setattr(bc.requests, "get",
                            lambda *a, **k: _Resp(200, {"daily": {"time": [], "temperature_2m_max": []}}))
        monkeypatch.setattr(bc.time, "sleep", lambda *a, **k: None)
        with pytest.raises(RuntimeError):
            bc._fetch_one_point(0.0, 0.0, max_attempts=2)
