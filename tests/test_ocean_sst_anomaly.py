from __future__ import annotations

from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import pytest
import requests

from src.data.ocean_sst_anomaly import (
    NOAA_STAR_SSTA_LEG,
    REGION_REGISTRY,
    RegionDef,
    RegionalSSTReading,
    _area_weighted_mean,
    _build_url,
    _detect_tier,
    _latest_noaa_star_file_from_index,
    _parse_griddap_csv,
    _readings_from_noaa_star_netcdf_bytes,
    detect_regional_sst_anomaly_events,
    fetch_all_regions,
    fetch_region_sst,
)
from src.data.source_status import SourceFetchError
from src.state import DEFAULT_STATE, update_sst_anom_tier, increment_sst_anom_annual_count


def _fake_griddap_csv(date_iso: str, cells: list[tuple[float, float, float | str]]) -> str:
    head = (
        "time,latitude,longitude,sea_surface_temperature_anomaly\n"
        "UTC,degrees_north,degrees_east,degree_C\n"
    )
    body = "".join(
        f"{date_iso}T12:00:00Z,{lat},{lon},{val}\n" for lat, lon, val in cells
    )
    return head + body


def _response(text: str) -> Mock:
    return Mock(text=text)


def test_region_registry_exports_13_valid_unique_boxes():
    assert len(REGION_REGISTRY) == 13
    slugs = [region.slug for region in REGION_REGISTRY]
    assert len(slugs) == len(set(slugs))

    for region in REGION_REGISTRY:
        assert region.slug
        assert region.display_name
        assert region.lat_s < region.lat_n
        assert region.lon_w <= region.lon_e
        assert -90 <= region.lat_s <= 90
        assert -90 <= region.lat_n <= 90
        assert -180 <= region.lon_w <= 180
        assert -180 <= region.lon_e <= 180


def test_region_registry_has_marquee_basins():
    slugs = {region.slug for region in REGION_REGISTRY}
    assert {
        "north_atlantic",
        "subpolar_n_atlantic",
        "ne_pacific_blob",
        "mediterranean",
        "tasman_sea",
        "gulf_of_mexico",
        "caribbean",
        "western_indian_ocean",
        "bay_of_bengal",
        "coral_triangle",
        "great_barrier_reef",
        "california_current",
        "nino34",
    } <= slugs


def test_build_url_raises_on_dateline_crossing():
    bad = RegionDef("bad", "Bad Region", -10, 10, 170, -170)
    with pytest.raises(ValueError, match="dateline-crossing"):
        _build_url(bad)


def test_build_url_uses_descending_latitude_and_stride():
    region = RegionDef("test", "Test", -5, 5, -170, -120)
    url = _build_url(region, time_token="last")
    assert "sea_surface_temperature_anomaly[(last)]" in url
    assert "[(5):20:(-5)]" in url
    assert "[(-170):20:(-120)]" in url


def test_area_weighted_mean_equals_simple_for_single_latitude():
    assert _area_weighted_mean([(10.0, 3.0), (10.0, 5.0)]) == pytest.approx(4.0)


def test_area_weighted_mean_downweights_high_latitude():
    cells = [(0.0, 4.0), (60.0, 0.0)]
    assert _area_weighted_mean(cells) > 2.0


def test_parse_griddap_csv_skips_nan_and_blank_rows():
    text = _fake_griddap_csv(
        "2026-06-06",
        [(5.0, -160.0, 1.5), (5.0, -159.95, "NaN")],
    ) + "\n"

    iso_date, cells = _parse_griddap_csv(text)

    assert iso_date == "2026-06-06"
    assert cells == [(5.0, 1.5)]


def test_parse_griddap_csv_rejects_fill_value():
    text = _fake_griddap_csv(
        "2026-06-06",
        [(5.0, -160.0, 3.0), (5.0, -159.95, -327.68)],
    )
    _, cells = _parse_griddap_csv(text)
    assert cells == [(5.0, 3.0)]


def test_parse_griddap_csv_rejects_out_of_valid_range():
    text = _fake_griddap_csv(
        "2026-06-06",
        [(5.0, -160.0, 3.0), (5.0, -159.95, 20.0), (5.0, -159.9, -20.0)],
    )
    _, cells = _parse_griddap_csv(text)
    assert cells == [(5.0, 3.0)]


def test_detect_tier_boundaries():
    assert _detect_tier(2.49) is None
    assert _detect_tier(2.5) == 1
    assert _detect_tier(3.49) == 1
    assert _detect_tier(3.5) == 2
    assert _detect_tier(4.5) == 3
    assert _detect_tier(5.1) == 3


def test_fetch_region_sst_success_tier2(monkeypatch):
    region = RegionDef("nino34", "Nino 3.4", -5, 5, -170, -120)
    text = _fake_griddap_csv(
        "2026-06-06",
        [(0.0, -160.0, 3.6), (0.0, -159.0, 3.6), (0.0, -158.0, 3.6)],
    )
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly.fetch_with_retry",
        lambda *args, **kwargs: _response(text),
    )

    reading = fetch_region_sst(region, min_valid_cells=3, today=date(2026, 6, 11))

    assert reading is not None
    assert reading.region_slug == "nino34"
    assert reading.date == "2026-06-06"
    assert reading.anomaly_c == pytest.approx(3.6)
    assert reading.tier == 2
    assert reading.cells_used == 3


def test_fetch_region_sst_uses_short_timeout_budget(monkeypatch):
    region = RegionDef("nino34", "Nino 3.4", -5, 5, -170, -120)
    text = _fake_griddap_csv(
        "2026-06-06",
        [(0.0, -160.0, 3.6), (0.0, -159.0, 3.6), (0.0, -158.0, 3.6)],
    )
    calls = []

    def _fake_fetch(*args, **kwargs):
        calls.append(kwargs)
        return _response(text)

    monkeypatch.setattr("src.data.ocean_sst_anomaly.fetch_with_retry", _fake_fetch)

    assert fetch_region_sst(region, min_valid_cells=3, today=date(2026, 6, 11)) is not None
    assert calls[0]["timeout"] == 10
    assert calls[0]["attempts"] == 1


def test_fetch_region_sst_below_floor_returns_none(monkeypatch):
    region = RegionDef("nino34", "Nino 3.4", -5, 5, -170, -120)
    text = _fake_griddap_csv(
        "2026-06-06",
        [(0.0, -160.0, 1.0), (0.0, -159.0, 1.0), (0.0, -158.0, 1.0)],
    )
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly.fetch_with_retry",
        lambda *args, **kwargs: _response(text),
    )

    assert fetch_region_sst(region, min_valid_cells=3) is None


def test_fetch_region_sst_returns_synthesis_floor_tier0(monkeypatch):
    region = RegionDef("coral_triangle", "Coral Triangle", -10, 10, 120, 150)
    text = _fake_griddap_csv(
        "2026-06-06",
        [(0.0, 140.0, 2.1), (0.0, 141.0, 2.1), (0.0, 142.0, 2.1)],
    )
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly.fetch_with_retry",
        lambda *args, **kwargs: _response(text),
    )

    reading = fetch_region_sst(region, min_valid_cells=3, today=date(2026, 6, 11))

    assert reading is not None
    assert reading.region_slug == "coral_triangle"
    assert reading.anomaly_c == pytest.approx(2.1)
    assert reading.tier == 0


def test_fetch_region_sst_rejects_low_valid_cell_coverage(monkeypatch):
    region = RegionDef("gbr", "Great Barrier Reef", -24, -10, 142, 154)
    text = _fake_griddap_csv("2026-06-06", [(-18.0, 148.0, 4.0)])
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly.fetch_with_retry",
        lambda *args, **kwargs: _response(text),
    )

    assert fetch_region_sst(region, min_valid_cells=2) is None


def test_fetch_region_sst_http_failure_returns_none(monkeypatch):
    region = RegionDef("nino34", "Nino 3.4", -5, 5, -170, -120)

    def _raise(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("src.data.ocean_sst_anomaly.fetch_with_retry", _raise)

    assert fetch_region_sst(region, strict=False) is None


def test_fetch_region_sst_http_failure_strict_raises(monkeypatch):
    region = RegionDef("nino34", "Nino 3.4", -5, 5, -170, -120)

    def _raise(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("src.data.ocean_sst_anomaly.fetch_with_retry", _raise)

    with pytest.raises(SourceFetchError, match="nino34"):
        fetch_region_sst(region, strict=True)


def test_fetch_all_regions_defaults_to_per_region_degradation(monkeypatch):
    def _fake_fetch_region(region, *, min_valid_cells=10):
        if region.slug == "north_atlantic":
            return RegionalSSTReading(
                "north_atlantic",
                "North Atlantic",
                "2026-08-20",
                3.6,
                2,
                120,
            )
        if region.slug == "mediterranean":
            raise SourceFetchError("mediterranean failed")
        return None

    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly._fetch_region_sst_strict",
        _fake_fetch_region,
    )

    readings = fetch_all_regions()

    assert readings == [
        RegionalSSTReading("north_atlantic", "North Atlantic", "2026-08-20", 3.6, 2, 120)
    ]


def test_fetch_all_regions_strict_raises_on_first_region_failure(monkeypatch):
    def _fake_fetch_region(region, *, min_valid_cells=10):
        if region.slug == "north_atlantic":
            return RegionalSSTReading(
                "north_atlantic",
                "North Atlantic",
                "2026-08-20",
                3.6,
                2,
                120,
            )
        raise SourceFetchError(f"{region.slug} failed")

    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly._fetch_region_sst_strict",
        _fake_fetch_region,
    )

    with pytest.raises(SourceFetchError):
        fetch_all_regions(strict=True)


def test_fetch_all_regions_returns_empty_when_all_regions_below_tier(monkeypatch):
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly._fetch_region_sst_strict",
        lambda region, *, min_valid_cells=10: None,
    )

    assert fetch_all_regions() == []


def test_fetch_all_regions_raises_when_all_regions_fail(monkeypatch):
    def _raise(region, *, min_valid_cells=10):
        raise SourceFetchError(f"{region.slug} failed")

    monkeypatch.setattr("src.data.ocean_sst_anomaly._fetch_region_sst_strict", _raise)

    with pytest.raises(SourceFetchError, match="all regions failed"):
        fetch_all_regions()


def test_fetch_all_regions_uses_noaa_star_nc_when_erddap_times_out(monkeypatch):
    def _raise(region, *, min_valid_cells=10):
        raise SourceFetchError(f"{region.slug} timed out")

    fallback = [
        RegionalSSTReading(
            "north_atlantic",
            "North Atlantic",
            "2026-06-14",
            3.7,
            2,
            42,
            source_leg=NOAA_STAR_SSTA_LEG,
        )
    ]
    monkeypatch.setattr("src.data.ocean_sst_anomaly._fetch_region_sst_strict", _raise)
    monkeypatch.setattr(
        "src.data.ocean_sst_anomaly._fetch_noaa_star_ssta_regions_strict",
        lambda *, min_valid_cells=10, today=None: fallback,
    )

    assert fetch_all_regions() == fallback


def test_fetch_all_regions_all_failure_includes_sampled_causes(monkeypatch):
    def _raise(region, *, min_valid_cells=10):
        raise SourceFetchError(f"{region.slug} schema drift")

    monkeypatch.setattr("src.data.ocean_sst_anomaly._fetch_region_sst_strict", _raise)

    with pytest.raises(SourceFetchError) as exc_info:
        fetch_all_regions()

    msg = str(exc_info.value)
    assert "all regions failed" in msg
    assert "north_atlantic schema drift" in msg
    assert "subpolar_n_atlantic schema drift" in msg


def test_latest_noaa_star_file_from_index_ignores_md5_placeholders():
    selected = _latest_noaa_star_file_from_index(
        """
        <a href="ct5km_ssta_v3.1_20260613.nc">ct5km_ssta_v3.1_20260613.nc</a>
        <a href="ct5km_ssta_v3.1_20260614.nc.md5">ct5km_ssta_v3.1_20260614.nc.md5</a>
        <a href="ct5km_ssta_v3.1_20260614.nc">ct5km_ssta_v3.1_20260614.nc</a>
        """
    )

    assert selected.data_date == "2026-06-14"
    assert selected.url.endswith("/2026/ct5km_ssta_v3.1_20260614.nc")


def test_noaa_star_netcdf_parser_computes_region_mean_and_tags_source_leg(tmp_path):
    from netCDF4 import Dataset
    import numpy as np

    nc_path = tmp_path / "ssta.nc"
    with Dataset(nc_path, "w") as dataset:
        dataset.createDimension("time", 1)
        dataset.createDimension("lat", 41)
        dataset.createDimension("lon", 41)
        dataset.createVariable("time", "i4", ("time",))[:] = [0]
        dataset.createVariable("lat", "f4", ("lat",))[:] = np.linspace(1.0, -1.0, 41)
        dataset.createVariable("lon", "f4", ("lon",))[:] = np.linspace(-1.0, 1.0, 41)
        ssta = dataset.createVariable(
            "sea_surface_temperature_anomaly",
            "f4",
            ("time", "lat", "lon"),
            fill_value=-32768,
        )
        grid = np.full((41, 41), 3.6)
        grid[20, :] = 3.8
        ssta[0, :, :] = grid

    readings = _readings_from_noaa_star_netcdf_bytes(
        nc_path.read_bytes(),
        data_date="2026-06-14",
        regions=(RegionDef("test", "Test Region", -1, 1, -1, 1),),
        min_valid_cells=3,
        today=date(2026, 6, 16),
    )

    assert readings == [
        RegionalSSTReading(
            "test",
            "Test Region",
            "2026-06-14",
            3.67,
            2,
            9,
            source_leg=NOAA_STAR_SSTA_LEG,
        )
    ]


def test_detect_events_fires_only_on_tier_increase():
    readings = [
        RegionalSSTReading("north_atlantic", "North Atlantic", "2026-08-01", 3.6, 2, 50),
        RegionalSSTReading("mediterranean", "Mediterranean Sea", "2026-08-01", 4.6, 3, 50),
        RegionalSSTReading("nino34", "Nino 3.4", "2026-08-01", 2.6, 1, 50),
    ]

    events = detect_regional_sst_anomaly_events(
        readings,
        {"north_atlantic": 2, "mediterranean": 1},
    )

    assert [event.region_slug for event in events] == ["mediterranean", "nino34"]
    assert events[0].event_id == "sst_anom_mediterranean_tier3_2026-08-01"
    assert events[1].event_id == "sst_anom_nino34_tier1_2026-08-01"


def test_tier0_reading_does_not_fire_regional_event():
    readings = [
        RegionalSSTReading("coral_triangle", "Coral Triangle", "2026-08-01", 2.1, 0, 50),
    ]

    assert detect_regional_sst_anomaly_events(readings, {}) == []


def test_annual_tier_key_rotation_uses_reading_date():
    bot_state = deepcopy(DEFAULT_STATE)

    update_sst_anom_tier(bot_state, "north_atlantic", 2, "2025-12-31")
    update_sst_anom_tier(bot_state, "north_atlantic", 1, "2026-01-02")
    increment_sst_anom_annual_count(bot_state, "2025-12-31")

    assert bot_state["sst_anom_last_tier"]["2025/north_atlantic"] == 2
    assert bot_state["sst_anom_last_tier"]["2026/north_atlantic"] == 1
    assert bot_state["sst_anom_annual_count"] == {"2025": 1}
