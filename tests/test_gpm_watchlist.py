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
    assert grid_calls == ["datapool", "s3"]
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
