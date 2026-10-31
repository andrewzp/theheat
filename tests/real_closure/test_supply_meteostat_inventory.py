"""Hot10 supply: the Meteostat station list's year-only monthly inventory, and self-explaining partitions.

Root's real run kept only 3,194 of 15,931 station rows: the released parser
refused every row whose ``monthly_start``/``monthly_end`` columns carry a bare
year (``2003``), which is how ``stations/slim.csv.gz`` actually ships them. Those
are exactly the stations with a monthly inventory, so every point was resolved
from stations without one and most normals files answered 404. The pinned SDK
(meteostat 1.7.6) reads those columns with pandas ``parse_dates``, so ``2003``
means 2003-01-01; the reproduction must read them the same way. Rows here are
invented in the real column layout; no retained provider bytes are used.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.data import meteostat_normals as mn, normals_acquisition as na
from tests import live_content_harness as h
from tests.final_closure import supply_http_fixture as fx

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
FAST = {"poll_seconds": 0.05, "backoff_seconds": 0.01, "connect_wait": 2.0}

# The real slim layout: id,name,country,region,wmo,icao,lat,lon,elevation,timezone,
# hourly_start,hourly_end,daily_start,daily_end,monthly_start,monthly_end
REAL_SHAPE = (
    "XQ001,Invented Field,XX,AB,99001,XQHD,53.19,-112.25,688,America/Edmonton,"
    "2020-01-01,2024-12-07,2002-11-01,2024-03-13,2003,2022\n"
    "XQ002,Invented Ridge,XX,AB,,,54.72,-113.29,515,America/Edmonton,,,2000-01-01,2022-07-12,2000,2010\n"
    "99003,Invented Island,XX,,99003,XQJA,70.9333,-8.6667,10,Europe/Oslo,"
    "1931-01-01,2025-03-20,1921-12-31,2026-02-27,1922,2022\n"
    "99004,Invented Bay,XX,SJ,99004,,79.7833,14.4667,0,Europe/Oslo,1986-11-09,2025-03-20,2010-10-07,2020-08-17,,\n"
)


def test_year_only_monthly_inventory_is_read_as_the_pinned_sdk_reads_it():
    stations, counts = mn.parse_stations(REAL_SHAPE)
    assert counts == {"rows": 4, "invalid_rows": 0, "ambiguous_ids": 0, "stations": 4}
    by_id = {s.id: s for s in stations}
    # pandas parse_dates: a bare year is that year's first day.
    assert (by_id["XQ001"].monthly_start, by_id["XQ001"].monthly_end) == (date(2003, 1, 1), date(2022, 1, 1))
    assert (by_id["99003"].monthly_start, by_id["99003"].monthly_end) == (date(1922, 1, 1), date(2022, 1, 1))
    assert by_id["99004"].monthly_start is None and by_id["99004"].monthly_end is None


@pytest.mark.parametrize("start,end", [("2003-01-01", "2022-12-01"), ("2003", "2022")])
def test_iso_and_year_inventory_both_parse(start, end):
    row = f"XQ009,Invented,XX,,,,10.0,20.0,5,UTC,,,,,{start},{end}\n"
    stations, counts = mn.parse_stations(row)
    assert counts["invalid_rows"] == 0 and stations[0].monthly_start == date(2003, 1, 1)


@pytest.mark.parametrize("bad", ["20x3", "203", "2003-13-01", "02003", "-2003", "1"])
def test_unreadable_inventory_dates_are_still_refused_and_counted(bad):
    text = f"XQ010,Invented,XX,,,,10.0,20.0,5,UTC,,,,,{bad},2022\nXQ011,Kept,XX,,,,10.0,20.0,5,UTC,,,,,,\n"
    stations, counts = mn.parse_stations(text)
    assert [s.id for s in stations] == ["XQ011"] and counts["invalid_rows"] == 1


def _row(sid, lat, lon, elevation, start, end):
    return f"{sid},Invented {sid},XX,,,,{lat},{lon},{elevation},UTC,,,,,{start},{end}\n"


def test_a_station_with_period_inventory_is_selected_and_the_sdk_end_rule_holds():
    """WMO-like stations (year-only inventory) were invisible to the released parser."""
    text = (_row("NOINV", 24.70, 46.70, 600, "", "")            # nearest, no monthly inventory
            + _row("WMO01", 24.72, 46.70, 610, "1951", "2021")  # spans 1991-2020 (2021-01-01 >= 2020-12-31 - 1d)
            + _row("ENDS20", 24.74, 46.70, 615, "1951", "2020"))  # 2020-01-01 + 1 day < 2020-12-31: not spanning
    stations, counts = mn.parse_stations(text)
    assert counts["stations"] == 3
    selected, _alt = mn.select_stations(stations, 24.70, 46.70, 1991, 2020, NOW)
    ids = [item["station"].id for item in selected]
    assert "WMO01" in ids
    spanning = [s.id for s in stations if s.monthly_start and s.monthly_end
                and s.monthly_start <= date(1991, 1, 1) and s.monthly_end + mn.INVENTORY_ALLOWANCE >= date(2020, 12, 31)]
    assert spanning == ["WMO01"]


# ---------------------------------------------------------------------------
# partitions that did not complete now say why (root's 624 no_data / 6 invalid had nothing)
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    fixture = fx.Fixture()
    yield fixture
    fixture.close()


def _world(tmp_path):
    cities = tmp_path / "cities.csv"
    h.write_catalogue(cities, ["Riyadh"])
    installed = tmp_path / "installed" / "normals.csv"
    installed.parent.mkdir()
    installed.write_text("city,month,avg_high_c\nInventedtown,1,21.5\n")
    return installed, na.build_plan(cities, installed, dependency=None)


def _provider(server):
    return mn.MeteostatBulkProvider(endpoint=f"{server.origin}/v2/", now=lambda: NOW, transport_options=FAST)


def _limits():
    return na.Limits(max_requests=50, max_bytes=500_000, deadline_seconds=30, max_retries=1,
                     max_decoded_bytes=2_000_000)


def test_no_data_partition_retains_the_stations_it_considered(tmp_path, server):
    installed, plan = _world(tmp_path)
    point = plan["points"][0]
    server.route("/v2/stations/slim.csv.gz", fx.ok(fx.gz(_row("WMO01", point["lat"] + 0.01, point["lon"], 600,
                                                                "1951", "2021"))))
    server.route("/v2/normals/WMO01.csv.gz", fx.status(404))
    out = tmp_path / "out"
    na.acquire(plan, out, _provider(server), _limits(), installed_path=installed)
    record = __import__("json").loads(next((out / "partitions").glob("*.json")).read_text())
    assert record["status"] == "no_data" and "source_provenance" not in record
    attempts = record["attempt_provenance"]
    assert [a["period"] for a in attempts] == [[1991, 2020], [1961, 1990]]
    assert attempts[0]["selected_stations"][0]["station"] == "WMO01"
    assert attempts[0]["selected_stations"][0]["normals_file"]["status"] == "missing"
    assert attempts[0]["stations_file"]["invalid_rows"] == 0


def test_invalid_product_partition_names_the_station_row_and_field(tmp_path, server):
    installed, plan = _world(tmp_path)
    point = plan["points"][0]
    server.route("/v2/stations/slim.csv.gz", fx.ok(fx.gz(_row("WMO02", point["lat"] + 0.01, point["lon"], 600,
                                                                "1951", "2021"))))
    body = "1991,2020,1,10.0,30.1,1.0,,,\n1991,2020,2,10.0,31.1,1.0,,,,\n"  # row 2 has ten columns
    server.route("/v2/normals/WMO02.csv.gz", fx.ok(fx.gz(body)))
    out = tmp_path / "out"
    na.acquire(plan, out, _provider(server), _limits(), installed_path=installed)
    record = __import__("json").loads(next((out / "partitions").glob("*.json")).read_text())
    assert record["status"] == "invalid_product"
    assert record["attempted_periods"] == [[1991, 2020, "normals_station_file_invalid"]]
    assert record["invalid_detail"] == {"station": "WMO02", "url": f"{server.origin}/v2/normals/WMO02.csv.gz",
                                        "row": 2, "field": "column_count", "columns": 10}
