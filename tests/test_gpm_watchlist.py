"""P09a complete local grid discovery, with bounded remote fallback; no network."""
from datetime import date

import pytest

from src.data import gpm_imerg as gpm
from tests.test_gpm_imerg import _make_grid_bytes

DAY = date(2026, 6, 5)


def cities():
    return [dict(city=f"Fixture {i}", country="France", lat=10 + i * 0.2, lon=20.0) for i in range(80)]


@pytest.fixture(scope="module")
def grid():
    return _make_grid_bytes({
        (0, gpm._lon_index(row["lon"]), gpm._lat_index(row["lat"])): i + 1
        for i, row in enumerate(cities())
    })


@pytest.mark.parametrize("source", ["datapool", "s3"])
@pytest.mark.parametrize("reverse", [False, True])
def test_city_after_75_survives_complete_grid_discovery_with_one_download(monkeypatch, grid, source, reverse):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fixture-not-a-secret")
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", source)
    calls = []
    monkeypatch.setattr(gpm, "_fetch_grid_bytes", lambda *a, **kw: calls.append(a[0]) or grid)
    monkeypatch.setattr(gpm, "_fetch_city_precip", lambda **kw: pytest.fail("Grid success must not fan out"))
    rows = cities()
    if reverse:
        rows.reverse()
    readings = gpm.fetch_daily_precip(rows, target_date=DAY, today=DAY, strict=True)
    assert calls == [source]
    assert {r.city: r.mm_total for r in readings} == {f"Fixture {i}": float(i + 1) for i in range(80)}
    late = next(row for row in readings if row.city == "Fixture 79")
    tracking = {"precip_daily_records": {gpm._daily_record_key(late): {"mm": 30.0, "year": 2020}}}
    assert any(e.location == "Fixture 79" and e.mm_total == 80 for e in gpm.detect_precip_records(readings, tracking))


@pytest.mark.parametrize("limit,expected", [(None, 75), (500, 75), (3, 3), (0, 0)])
def test_grid_failure_keeps_remote_city_fanout_bounded(monkeypatch, limit, expected):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fixture-not-a-secret")
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")
    grid_calls, city_calls = [], []
    def unavailable(source, **kwargs):
        grid_calls.append(source)
        raise gpm._GridTransient("fixture provider unavailable")
    monkeypatch.setattr(gpm, "_fetch_grid_bytes", unavailable)
    monkeypatch.setattr(gpm, "_fetch_city_precip", lambda **kw: city_calls.append(kw) or 1.0)
    readings = gpm._fetch_daily_precip_primary(cities(), target_date=DAY, today=DAY, max_cities=limit, max_workers=1)
    assert grid_calls == ["datapool"]
    assert len(city_calls) == len(readings) == expected


def test_model_witness_also_retains_remote_city_bound(monkeypatch):
    calls = []
    monkeypatch.setattr(gpm, "_open_meteo_precip_with_agreement", lambda *args: calls.append(args) or 2.0)
    readings = gpm._fetch_precip_open_meteo(cities(), max_cities=None, today=DAY)
    assert len(readings) == len(calls) == 75
    assert all(r.source_leg == "open_meteo" for r in readings)


def test_invalid_grid_rows_cannot_abort_or_duplicate_qualified_readings(grid):
    valid = cities()[0]
    invalid = [{}, {**valid, "city": None}, {**valid, "lat": True}, {**valid, "lat": 91},
               {**valid, "lon": -181}, {**valid, "lat": float("nan")}, {**valid, "lon": float("inf")}]
    readings = gpm._subset_grid(grid, [*invalid, valid, dict(valid)], resolved_date=DAY, product="late")
    assert len(readings) == 1 and readings[0].mm_total == 1


def test_nonfinite_and_negative_grid_cells_are_missing_not_zero():
    rows = cities()[:5]
    values = [float("nan"), float("inf"), -1, gpm.FILL_VALUE, 0]
    payload = _make_grid_bytes({(0, gpm._lon_index(row["lon"]), gpm._lat_index(row["lat"])): value
                               for row, value in zip(rows, values)})
    readings = gpm._subset_grid(payload, rows, resolved_date=DAY, product="late")
    assert [(r.city, r.mm_total) for r in readings] == [("Fixture 4", 0.0)]


def test_multiday_grid_is_not_silently_treated_as_one_daily_file():
    payload = _make_grid_bytes({}, shape=(2, gpm.LON_CELLS, gpm.LAT_CELLS))
    with pytest.raises(gpm._GridParseError):
        gpm._subset_grid(payload, cities()[:1], resolved_date=DAY, product="late")


@pytest.mark.parametrize("missing", ["lat", "lon"])
def test_invalid_registered_row_cannot_hide_later_explicit_sampling_point(missing):
    from src.data import places
    valid = places.resolve_place("Paris", "France")
    invalid = {**valid, missing: None}
    rows = [invalid, valid]
    assert gpm._network_watchlist(rows, 1) == [valid]
    payload = _make_grid_bytes({(0, gpm._lon_index(valid["lon"]), gpm._lat_index(valid["lat"])): 25.0})
    readings = gpm._subset_grid(payload, rows, resolved_date=DAY, product="late")
    assert len(readings) == 1 and readings[0].mm_total == 25.0
    assert (readings[0].lat, readings[0].lon) == (valid["lat"], valid["lon"])


def identity(row):
    return gpm.places.event_location_key(row['city'], row['country'], row['lat'], row['lon'])


def population(count):
    return [dict(city=f"Synthetic {i}", country="Testland", lat=-30 + i / 10, lon=0)
            for i in range(count)]


@pytest.mark.parametrize("size,limit", [(1,1), (5,1), (8,3), (17,4), (75,75), (76,75), (80,75), (151,75)])
def test_every_identity_has_a_bounded_daily_opportunity_from_every_start(size, limit):
    from datetime import timedelta
    from math import ceil
    rows = population(size)
    all_ids = {identity(row) for row in rows}
    # Every date residue covers all possible window starts, including gcd(N,K)>1.
    selections = [gpm._network_watchlist(rows, limit, scan_date=DAY + timedelta(days=day))
                  for day in range(size + ceil(size / limit))]
    for selected in selections:
        assert len(selected) == min(size, limit)
        assert len({identity(row) for row in selected}) == len(selected)
    for start in range(size):
        seen = {identity(row) for selected in selections[start:start + ceil(size / limit)]
                for row in selected}
        assert seen == all_ids


@pytest.mark.parametrize("limit", [0,1,3,75,None,500])
def test_remote_selection_is_order_independent_and_restart_stable(limit):
    from random import Random
    rows = population(80)
    original = [dict(row) for row in rows]
    chosen = gpm._network_watchlist(rows, limit, scan_date=DAY)
    shuffled = list(rows)
    Random(19).shuffle(shuffled)
    assert chosen == gpm._network_watchlist(shuffled, limit, scan_date=DAY)
    assert chosen == gpm._network_watchlist(reversed(rows), limit, scan_date=DAY)
    assert rows == original
    assert len(chosen) == min(75, limit if limit is not None else 75)


def test_bad_and_duplicate_alias_rows_cannot_change_the_sampling_window():
    valid = gpm.places.resolve_place('Paris', 'France')
    alias = {**valid, 'city':'PARIS', 'lat':str(valid['lat'])}
    assert identity(valid) == identity(alias)
    candidates = [*population(80), valid, alias, {}, {**valid, 'lat':True},
                  {**valid, 'lon':float('inf')}, {**valid, 'country':''}]
    a = gpm._network_watchlist(candidates, 75, scan_date=DAY)
    b = gpm._network_watchlist(reversed(candidates), 75, scan_date=DAY)
    assert a == b
    qualified = gpm._qualified_watchlist(candidates, canonical_order=True)
    assert len(qualified) == 81
    assert next(row for row in qualified if identity(row) == identity(valid))['city'] == 'PARIS'


@pytest.mark.parametrize('bad', [-1, True, 2.5, '3'])
def test_invalid_remote_limits_still_refuse(bad):
    with pytest.raises(ValueError, match='max_cities'):
        gpm._network_watchlist(population(80), bad, scan_date=DAY)


@pytest.mark.parametrize('bad', ['', '2026-06-05', True, 0])
def test_invalid_scan_dates_do_not_silently_change_the_window(bad):
    with pytest.raises(ValueError, match='scan_date'):
        gpm._network_watchlist(population(80), 75, scan_date=bad)


def test_empty_or_zero_remote_window_cannot_manufacture_a_reading():
    assert gpm._network_watchlist([{}, {'lat':0}], 75, scan_date=DAY) == []
    assert gpm._network_watchlist(population(80), 0, scan_date=DAY) == []


def test_actual_remote_legs_visit_same_window_and_ignore_source_walkback(monkeypatch):
    from datetime import timedelta
    monkeypatch.setenv('EARTHDATA_TOKEN', 'fixture-not-a-secret')
    monkeypatch.setenv('THEHEAT_GPM_SOURCE', 'opendap')
    rows = population(80)
    chosen = gpm._network_watchlist(rows, 7, scan_date=DAY)
    wanted_points = [(float(row['lat']), float(row['lon'])) for row in chosen]
    primary_calls, witness_calls = [], []
    monkeypatch.setattr(gpm, '_fetch_city_precip', lambda **kw: primary_calls.append(kw) or 4.0)
    monkeypatch.setattr(gpm, '_open_meteo_precip_with_agreement',
                        lambda *args: witness_calls.append(args) or 4.0)
    older = DAY - timedelta(days=3)
    monkeypatch.setattr(gpm, '_resolve_available_date', lambda **kw: older)
    primary = gpm._fetch_daily_precip_primary(rows, today=DAY, max_cities=7, max_workers=1)
    assert [(kw['lat'],kw['lon']) for kw in primary_calls] == wanted_points
    assert all(kw['target_date'] == older for kw in primary_calls)
    assert all(row.date == older.isoformat() for row in primary)
    witness = gpm._fetch_precip_open_meteo(list(reversed(rows)), today=DAY, max_cities=7)
    assert witness_calls == wanted_points
    assert {row.city for row in witness} == {row.city for row in primary}
    assert all(row.source_leg == 'open_meteo' for row in witness)
    assert all(row.date == (DAY - timedelta(days=1)).isoformat() for row in witness)
    assert len(primary) == len(witness) == 7  # No unsampled city becomes a zero.


def test_wrapper_freezes_one_utc_date_when_failure_crosses_midnight(monkeypatch):
    from datetime import datetime, timezone
    clock_calls, dates = [], []

    class Clock:
        @staticmethod
        def now(tz):
            assert tz == timezone.utc
            clock_calls.append(tz)
            return datetime(2026,6,5,23,59,tzinfo=timezone.utc) if len(clock_calls) == 1 else datetime(2026,6,6,tzinfo=timezone.utc)

    def primary(*args, **kwargs):
        dates.append(kwargs['today'])
        Clock.now(timezone.utc)  # Network failure finishes the following UTC day.
        raise gpm.requests.Timeout('Synthetic timeout')

    def witness(*args, **kwargs):
        dates.append(kwargs['today'])
        return []

    monkeypatch.setattr(gpm, 'datetime', Clock)
    monkeypatch.setattr(gpm, '_fetch_daily_precip_primary', primary)
    monkeypatch.setattr(gpm, '_fetch_precip_open_meteo', witness)
    assert gpm.fetch_daily_precip(population(80), strict=True) == []
    assert dates == [DAY, DAY] and len(clock_calls) == 2


def test_direct_model_witness_selection_uses_utc_not_local_calendar(monkeypatch):
    from datetime import datetime, timezone
    calls = []

    class Clock:
        @staticmethod
        def now(tz):
            assert tz == timezone.utc
            return datetime(2026,6,5,0,1,tzinfo=timezone.utc)

    monkeypatch.setattr(gpm, 'datetime', Clock)
    monkeypatch.setattr(gpm, '_open_meteo_precip_with_agreement', lambda *args: calls.append(args) or 1.0)
    rows = population(80)
    result = gpm._fetch_precip_open_meteo(rows, max_cities=3)
    assert calls == [(float(row['lat']),float(row['lon']))
                     for row in gpm._network_watchlist(rows, 3, scan_date=DAY)]
    assert all(row.date == '2026-06-04' for row in result)
