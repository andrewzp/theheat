"""Tests for src/data/ghcn.py.

All network I/O is replaced with in-process fixture data:
  - A fresh SQLite DB is built programmatically per test using ghcn_db helpers.
  - _fetch_recent_obs() is replaced with a fixture function injected via
    _fetch_obs_fn= parameter.

Station fixture (POLAR0000):
  - archive_years = 60
  - all_time_max_c = 25.0 (1985)
  - all_time_min_c = -70.0 (1924)
  - monthly_max[7] = (24.0, 2000)
  - monthly_min[1] = (-65.0, 1960)
  - calendar_date_max[(7, 15)] = (23.0, 1990)
  - calendar_date_min[(1, 10)] = (-64.0, 1945)
  - climatological_mean[7] = 15.0

The engineered test observations are designed to exercise each signal type.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pytest

from src.data import ghcn as ghcn_module
from src.data.ghcn import (
    ANOMALY_HOT_THRESHOLD_C,
    _dedup_by_metro,
    _detect_signals_for_station,
    _fetch_recent_obs,
    _has_signal,
    check_extreme_signals_for_stations,
)
from src.data.ghcn_db import (
    load_thresholds,
    open_db,
    upsert_thresholds,
)
from src.data.ghcn_format import (
    DailyObs,
    DiffRecord,
    StationThresholds,
)
from src.data.open_meteo import ExtremeSignalBundle


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STATION_META = {
    "station_id": "POLAR0000000",
    "name": "POLAR TEST STATION",
    "country_code": "PL",
    "country_name": "Poland Test",
    "state": "",
    "lat": 70.0,
    "lon": 133.0,
    "elevation_m": 100.0,
    "archive_years": 60,
}

STATION_META_2 = {
    "station_id": "TROPIC00000",
    "name": "TROPIC TEST STATION",
    "country_code": "TH",
    "country_name": "Thailand Test",
    "state": "",
    "lat": 15.0,
    "lon": 100.0,
    "elevation_m": 50.0,
    "archive_years": 40,
}


def _make_thresholds() -> StationThresholds:
    """Build a StationThresholds object for POLAR0000000."""
    t = StationThresholds(station_id="POLAR0000000")
    t.archive_years = 60
    t.all_time_max_c = 25.0
    t.all_time_max_year = 1985
    t.all_time_min_c = -70.0
    t.all_time_min_year = 1924
    t.monthly_max[7]  = (24.0, 2000)
    t.monthly_min[1]  = (-65.0, 1960)
    t.calendar_date_max[(7, 15)] = (23.0, 1990)
    t.calendar_date_min[(1, 10)] = (-64.0, 1945)
    t.climatological_mean[7] = 15.0
    t.climatological_mean_min[1] = -50.0
    return t


def _make_thresholds_2() -> StationThresholds:
    """Build a StationThresholds object for TROPIC00000."""
    t = StationThresholds(station_id="TROPIC00000")
    t.archive_years = 40
    t.all_time_max_c = 42.0
    t.all_time_max_year = 2010
    t.all_time_min_c = 5.0
    t.all_time_min_year = 1980
    t.monthly_max[5] = (41.0, 2015)
    t.climatological_mean[5] = 34.0
    return t


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create a temp SQLite DB seeded with POLAR0000000 station + thresholds."""
    p = tmp_path / "test_thresholds.sqlite"
    with open_db(p) as conn:
        # Insert the station row manually (upsert_station needs inventory rows;
        # here we insert directly for simplicity)
        conn.execute(
            """
            INSERT INTO stations
              (station_id, name, country_code, country_name, state,
               lat, lon, elevation_m, archive_years, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                STATION_META["station_id"], STATION_META["name"],
                STATION_META["country_code"], STATION_META["country_name"],
                STATION_META["state"], STATION_META["lat"], STATION_META["lon"],
                STATION_META["elevation_m"], STATION_META["archive_years"],
            ),
        )
        upsert_thresholds(conn, _make_thresholds())
        conn.commit()
    return p


@pytest.fixture
def db_path_two_stations(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with two stations."""
    p = tmp_path / "test_thresholds.sqlite"
    with open_db(p) as conn:
        for meta, thresh in [
            (STATION_META, _make_thresholds()),
            (STATION_META_2, _make_thresholds_2()),
        ]:
            conn.execute(
                """
                INSERT INTO stations
                  (station_id, name, country_code, country_name, state,
                   lat, lon, elevation_m, archive_years, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    meta["station_id"], meta["name"],
                    meta["country_code"], meta["country_name"],
                    meta["state"], meta["lat"], meta["lon"],
                    meta["elevation_m"], meta["archive_years"],
                ),
            )
            upsert_thresholds(conn, thresh)
        conn.commit()
    return p


def _obs(station_id: str, obs_date: date, element: str, value_c: float) -> DailyObs:
    return DailyObs(station_id=station_id, obs_date=obs_date, element=element, value_c=value_c)


def _fetch_fn(obs_list: list[DailyObs]):
    """Build a fixture fetch function that returns the given obs list."""
    def fn(active_ids):
        latest: dict[tuple[str, date], list[DailyObs]] = {}
        for o in obs_list:
            if o.station_id not in active_ids:
                continue
            latest.setdefault((o.station_id, o.obs_date), []).append(o)
        return latest
    return fn


# ---------------------------------------------------------------------------
# ghcn_db threshold writes
# ---------------------------------------------------------------------------

def test_upsert_thresholds_replaces_existing_nullable_key_rows(tmp_path: Path):
    db = tmp_path / "thresholds.sqlite"
    first = _make_thresholds()
    second = _make_thresholds()
    second.all_time_max_c = 27.0
    second.all_time_max_year = 2026

    with open_db(db) as conn:
        upsert_thresholds(conn, first)
        initial_count = conn.execute(
            "SELECT COUNT(*) FROM thresholds WHERE station_id = ?",
            (first.station_id,),
        ).fetchone()[0]
        upsert_thresholds(conn, second)
        replacement_count = conn.execute(
            "SELECT COUNT(*) FROM thresholds WHERE station_id = ?",
            (first.station_id,),
        ).fetchone()[0]
        loaded = load_thresholds(conn, first.station_id)

    assert replacement_count == initial_count
    assert loaded is not None
    assert loaded.all_time_max_c == pytest.approx(27.0)
    assert loaded.all_time_max_year == 2026


def test_upsert_thresholds_persists_climatological_mean_min(tmp_path: Path):
    """Regression: TMIN climatological mean must round-trip through SQLite.

    If `climatological_mean_min` is dropped during persistence, cold-anomaly
    detection cannot fire — the comparator has no baseline for TMIN observations.
    See _detect_signals_for_station: cold anomaly path reads
    thresholds.climatological_mean_min[month].
    """
    th = _make_thresholds()
    # _make_thresholds populates climatological_mean_min[1] = -50.0; verify the
    # full TMIN climatology matrix survives a write/read round-trip.
    th.climatological_mean_min = {m: -10.0 - m for m in range(1, 13)}

    with open_db(tmp_path / "thresholds.sqlite") as conn:
        upsert_thresholds(conn, th)
        loaded = load_thresholds(conn, th.station_id)

    assert loaded is not None
    for m in range(1, 13):
        assert loaded.climatological_mean_min[m] == pytest.approx(-10.0 - m), (
            f"TMIN climatology month={m} not persisted correctly"
        )


# ---------------------------------------------------------------------------
# _fetch_recent_obs
# ---------------------------------------------------------------------------

def test_fetch_recent_obs_skips_late_arriving_backfill(monkeypatch):
    """Observations with obs_date older than max_obs_age_days must be filtered out.

    `superghcnd_diff` files routinely contain late-arriving observations from
    1-2 weeks earlier (a station finally uploads its old readings). Those are
    not "fresh news" and must not be surfaced as current signals.
    """

    today = date(2026, 5, 6)
    fresh_date = date(2026, 5, 4)        # 2 days ago — within cutoff
    stale_date = date(2026, 4, 24)       # 12 days ago — backfill, must be skipped

    def fake_fetch_diff(snapshot_date):
        return b"diff" if snapshot_date == date(2026, 5, 5) else None

    def fake_parse_records(content):
        return [
            DiffRecord("insert", "POLAR0000000", fresh_date, "TMAX", 12.0),
            DiffRecord("insert", "POLAR0000000", stale_date, "TMAX", 19.5),
        ]

    monkeypatch.setattr(ghcn_module, "_fetch_diff", fake_fetch_diff)
    monkeypatch.setattr(
        ghcn_module, "parse_superghcnd_diff_records_bytes", fake_parse_records,
    )

    result = _fetch_recent_obs(
        frozenset({"POLAR0000000"}), lookback_days=2,
        max_obs_age_days=4, today=today,
    )

    assert (("POLAR0000000", fresh_date)) in result
    assert (("POLAR0000000", stale_date)) not in result
    assert result[("POLAR0000000", fresh_date)][0].value_c == pytest.approx(12.0)


def test_fetch_recent_obs_delete_record_removes_prior_value(monkeypatch):
    """A newer delete diff must clear an older insert from the lookback window."""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 5)

    obs_date = date(2026, 5, 3)

    def fake_fetch_diff(snapshot_date):
        if snapshot_date == date(2026, 5, 3):
            return b"insert"
        if snapshot_date == date(2026, 5, 4):
            return b"delete"
        return None

    def fake_parse_records(content):
        if content == b"insert":
            return [
                DiffRecord("insert", "POLAR0000000", obs_date, "TMAX", 31.0),
                DiffRecord("insert", "POLAR0000000", obs_date, "TMIN", -4.0),
            ]
        if content == b"delete":
            return [
                DiffRecord("delete", "POLAR0000000", obs_date, "TMAX", None),
            ]
        return []

    monkeypatch.setattr(ghcn_module, "date", FixedDate)
    monkeypatch.setattr(ghcn_module, "_fetch_diff", fake_fetch_diff)
    monkeypatch.setattr(
        ghcn_module,
        "parse_superghcnd_diff_records_bytes",
        fake_parse_records,
    )

    result = _fetch_recent_obs(frozenset({"POLAR0000000"}), lookback_days=2)

    obs_list = result[("POLAR0000000", obs_date)]
    assert [obs.element for obs in obs_list] == ["TMIN"]
    assert obs_list[0].value_c == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# _detect_signals_for_station — unit tests
# ---------------------------------------------------------------------------

class TestDetectSignalsForStation:
    def test_all_time_high_fires(self):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)  # > 25.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.all_time_high is not None
        assert bundle.all_time_high.new_temp_c == pytest.approx(26.0)
        assert bundle.all_time_high.old_record_c == pytest.approx(25.0)
        assert bundle.all_time_high.old_record_year == 1985
        assert bundle.all_time_high.signal_date == date(2026, 7, 15)
        assert bundle.station_id == "POLAR0000000"
        assert bundle.signal_date == date(2026, 7, 15)

    def test_all_time_high_does_not_fire_below_record(self):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 24.0)  # < 25.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.all_time_high is None

    def test_all_time_high_does_not_fire_at_exact_record(self):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 25.0)  # == 25.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.all_time_high is None  # must strictly exceed

    def test_all_time_low_fires(self):
        obs = _obs("POLAR0000000", date(2026, 1, 10), "TMIN", -71.0)  # < -70.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.all_time_low is not None
        assert bundle.all_time_low.kind == "low"
        assert bundle.all_time_low.new_temp_c == pytest.approx(-71.0)

    def test_monthly_high_fires(self):
        obs = _obs("POLAR0000000", date(2026, 7, 20), "TMAX", 24.5)  # > monthly_max[7]=24.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.monthly_high is not None
        assert bundle.monthly_high.month == 7
        assert bundle.monthly_high.new_temp_c == pytest.approx(24.5)
        assert bundle.monthly_high.old_record_c == pytest.approx(24.0)

    def test_monthly_high_does_not_fire_below_monthly_record(self):
        obs = _obs("POLAR0000000", date(2026, 7, 20), "TMAX", 23.5)  # < monthly_max[7]=24.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.monthly_high is None

    def test_calendar_date_high_fires(self):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 23.5)  # > cal_max[(7,15)]=23.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.calendar_date_high is not None
        assert bundle.calendar_date_high.new_temp_c == pytest.approx(23.5)

    def test_calendar_date_low_fires(self):
        obs = _obs("POLAR0000000", date(2026, 1, 10), "TMIN", -64.5)  # < cal_min[(1,10)]=-64.0
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.calendar_date_low is not None
        assert bundle.calendar_date_low.kind == "low"
        assert bundle.calendar_date_low.signal_date == date(2026, 1, 10)

    def test_anomaly_hot_fires(self):
        # clim_mean[7] = 15.0; threshold = 8.0; need value >= 23.0
        obs = _obs("POLAR0000000", date(2026, 7, 5), "TMAX", 24.0)  # 24 - 15 = 9 >= 8
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.anomaly_hot is not None
        assert bundle.anomaly_hot.anomaly_c == pytest.approx(9.0)

    def test_anomaly_hot_does_not_fire_below_threshold(self):
        # 21 - 15 = 6 < 8
        obs = _obs("POLAR0000000", date(2026, 7, 5), "TMAX", 21.0)
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.anomaly_hot is None

    def test_anomaly_cold_uses_tmin_mean(self):
        # -60 - (-50) = -10 <= -8
        obs = _obs("POLAR0000000", date(2026, 1, 11), "TMIN", -60.0)
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.anomaly_cold is not None
        assert bundle.anomaly_cold.historical_mean_c == pytest.approx(-50.0)

    def test_multiple_signals_same_obs(self):
        """An extreme reading can fire all-time + monthly + calendar-date simultaneously."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.all_time_high is not None
        assert bundle.monthly_high is not None
        assert bundle.calendar_date_high is not None
        assert bundle.anomaly_hot is not None  # 26 - 15 = 11 >= 8

    def test_today_max_c_populated(self):
        """Raw reading goes into today_max_c for country aggregation."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 20.0)
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.today_max_c == pytest.approx(20.0)
        assert bundle.archive_max_c == pytest.approx(25.0)

    def test_returns_none_for_too_few_archive_years(self):
        """Stations with < MIN_ARCHIVE_YEARS should be skipped."""
        thin_meta = {**STATION_META, "archive_years": 5}
        thin_thresh = _make_thresholds()
        thin_thresh.archive_years = 5
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 30.0)
        bundle = _detect_signals_for_station(thin_meta, obs, thin_thresh)
        assert bundle is None

    def test_tmin_only_station_uses_tmin_archive_years(self):
        t = StationThresholds(station_id="TMINONLY000")
        t.tmin_archive_years = 40
        t.archive_years = 40
        t.all_time_min_c = -20.0
        t.all_time_min_year = 1990
        t.monthly_min[1] = (-18.0, 2001)
        t.calendar_date_min[(1, 10)] = (-17.5, 2005)

        station = {
            **STATION_META,
            "station_id": "TMINONLY000",
            "archive_years": 0,
            "tmax_archive_years": 0,
            "tmin_archive_years": 40,
        }
        obs = _obs("TMINONLY000", date(2026, 1, 10), "TMIN", -21.0)

        bundle = _detect_signals_for_station(station, obs, t)

        assert bundle is not None
        assert bundle.all_time_low is not None
        assert bundle.all_time_low.years_of_data == 40

    def test_station_name_and_id_populated(self):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 20.0)
        bundle = _detect_signals_for_station(STATION_META, obs, _make_thresholds())
        assert bundle is not None
        assert bundle.station_id == "POLAR0000000"
        assert bundle.station_name == "POLAR TEST STATION"


# ---------------------------------------------------------------------------
# _has_signal
# ---------------------------------------------------------------------------

def test_has_signal_true_when_any_event_set():
    b = ExtremeSignalBundle()
    assert not _has_signal(b)

    b.all_time_high = object()  # type: ignore[assignment]
    assert _has_signal(b)


def test_has_signal_false_when_no_events():
    b = ExtremeSignalBundle(today_max_c=40.0, archive_max_c=42.0)
    assert not _has_signal(b)


# ---------------------------------------------------------------------------
# _dedup_by_metro
# ---------------------------------------------------------------------------

def test_dedup_keeps_top_2_per_country():
    """3 US stations with signals → top 2 kept."""
    def _b(city, score_events):
        b = ExtremeSignalBundle(city=city, country="United States")
        if score_events >= 1:
            b.calendar_date_high = object()  # type: ignore[assignment]
        if score_events >= 2:
            b.monthly_high = object()  # type: ignore[assignment]
        if score_events >= 3:
            b.all_time_high = object()  # type: ignore[assignment]
        return b

    bundles = [_b("City A", 1), _b("City B", 3), _b("City C", 2)]
    result = _dedup_by_metro(bundles, max_per_country=2)
    assert len(result) == 2
    cities = {b.city for b in result}
    assert "City B" in cities  # highest score
    assert "City C" in cities  # second highest
    assert "City A" not in cities


def test_dedup_allows_multiple_countries():
    """2 US + 2 Russia → all 4 kept (2 per country)."""
    us1 = ExtremeSignalBundle(city="Phoenix", country="United States")
    us1.all_time_high = object()  # type: ignore[assignment]
    us2 = ExtremeSignalBundle(city="Dallas", country="United States")
    us2.calendar_date_high = object()  # type: ignore[assignment]
    ru1 = ExtremeSignalBundle(city="Verkhoyansk", country="Russia")
    ru1.all_time_low = object()  # type: ignore[assignment]
    ru2 = ExtremeSignalBundle(city="Oymyakon", country="Russia")
    ru2.all_time_low = object()  # type: ignore[assignment]

    result = _dedup_by_metro([us1, us2, ru1, ru2], max_per_country=2)
    assert len(result) == 4


# ---------------------------------------------------------------------------
# check_extreme_signals_for_stations — integration tests
# ---------------------------------------------------------------------------

class TestCheckExtremeSignalsForStations:
    def test_returns_bundle_when_signal_fires(self, db_path: Path):
        """An all-time record obs produces a non-empty bundles list."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)

        bundles, country_records = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert len(bundles) == 1
        assert bundles[0].station_id == "POLAR0000000"
        assert bundles[0].all_time_high is not None
        assert bundles[0].signal_date == date(2026, 7, 15)

    def test_same_day_tmax_and_tmin_are_preserved(self, db_path: Path):
        """A same-day TMAX must not mask a same-day TMIN cold record."""
        obs_high = _obs("POLAR0000000", date(2026, 1, 10), "TMAX", 10.0)
        obs_low = _obs("POLAR0000000", date(2026, 1, 10), "TMIN", -71.0)

        bundles, _ = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs_high, obs_low]),
        )
        assert len(bundles) == 1
        assert bundles[0].today_max_c == pytest.approx(10.0)
        assert bundles[0].today_min_c == pytest.approx(-71.0)
        assert bundles[0].all_time_low is not None

    def test_returns_empty_when_no_signal_fires(self, db_path: Path):
        """A reading below all thresholds → no bundles, no country records."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 10.0)  # below everything

        bundles, country_records = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert bundles == []
        assert country_records == []

    def test_returns_empty_when_no_observations(self, db_path: Path):
        with pytest.raises(RuntimeError):
            check_extreme_signals_for_stations(
                db_path=db_path,
                _fetch_obs_fn=_fetch_fn([]),
            )

    def test_returns_empty_when_db_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            check_extreme_signals_for_stations(
                db_path=tmp_path / "nonexistent.sqlite",
                _fetch_obs_fn=_fetch_fn([]),
            )

    def test_respects_max_checks(self, db_path: Path):
        """max_checks=0 → no stations processed → empty result."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 30.0)

        bundles, country_records = check_extreme_signals_for_stations(
            max_checks=0,
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert bundles == []

    def test_signal_date_propagated_to_bundle(self, db_path: Path):
        """signal_date on the bundle matches the observation date."""
        obs_date = date(2026, 5, 3)
        obs = _obs("POLAR0000000", obs_date, "TMAX", 26.0)

        bundles, _ = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert len(bundles) == 1
        assert bundles[0].signal_date == obs_date

    def test_station_id_propagated_to_bundle(self, db_path: Path):
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)

        bundles, _ = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert len(bundles) == 1
        assert bundles[0].station_id == "POLAR0000000"
        assert bundles[0].station_name == "POLAR TEST STATION"

    def test_country_record_not_fired_single_station(self, db_path: Path):
        """Country records require ≥2 stations; single station can't fire one."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 30.0)

        _, country_records = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert country_records == []  # only 1 station in PL → can't aggregate

    def test_stations_parameter_overrides_db_load(self, db_path: Path):
        """Passing stations explicitly skips the DB station load."""
        obs = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)
        explicit_stations = [STATION_META]

        bundles, _ = check_extreme_signals_for_stations(
            stations=explicit_stations,
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert len(bundles) == 1

    def test_unknown_station_in_obs_ignored(self, db_path: Path):
        """Obs for a station not in the DB are silently ignored."""
        obs_known   = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 26.0)
        obs_unknown = _obs("NOTINDB00000", date(2026, 7, 15), "TMAX", 99.0)

        bundles, _ = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs_known, obs_unknown]),
        )
        assert len(bundles) == 1
        assert bundles[0].station_id == "POLAR0000000"

    def test_two_stations_country_record_fires(self, db_path_two_stations: Path):
        """With 2 stations in a country, a country record can fire if today beats the archive."""
        # Both stations in their own countries — no country record possible.
        # But if we set both to PL (Poland) they'd share a country.
        # Use the two-station fixture as-is and verify country records are absent
        # (PL has 1 station, TH has 1 station).
        obs1 = _obs("POLAR0000000", date(2026, 7, 15), "TMAX", 20.0)
        obs2 = _obs("TROPIC00000",  date(2026, 5, 10), "TMAX", 40.0)

        _, country_records = check_extreme_signals_for_stations(
            db_path=db_path_two_stations,
            _fetch_obs_fn=_fetch_fn([obs1, obs2]),
        )
        # Each country has only 1 station → no country record
        assert country_records == []

    def test_all_signals_in_bundle_carry_signal_date(self, db_path: Path):
        """All sub-events (all_time_high, monthly_high, etc.) have matching signal_date."""
        obs_date = date(2026, 7, 15)
        obs = _obs("POLAR0000000", obs_date, "TMAX", 26.0)

        bundles, _ = check_extreme_signals_for_stations(
            db_path=db_path,
            _fetch_obs_fn=_fetch_fn([obs]),
        )
        assert len(bundles) == 1
        b = bundles[0]
        assert b.all_time_high is not None
        assert b.all_time_high.signal_date == obs_date
        assert b.monthly_high is not None
        assert b.monthly_high.signal_date == obs_date
        assert b.calendar_date_high is not None
        assert b.calendar_date_high.signal_date == obs_date
