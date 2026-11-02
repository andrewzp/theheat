"""Invented point responses: coordinate arrays must never become rainfall."""

from datetime import date
from types import SimpleNamespace

import pytest

from src.data import gpm_imerg as gpm


@pytest.mark.parametrize("label", ["precipitation.lat[0]", "precipitation.lon[0]",
                                  "precipitation.time[0]", "precipitationCal[0][0][0]"])
def test_coordinate_or_other_variable_is_not_the_requested_precipitation(label: str) -> None:
    assert gpm._parse_ascii_value(f"{label}, 34.05\n") is None


@pytest.mark.parametrize("coordinate_first", [True, False])
def test_real_point_fetch_uses_the_data_scalar_not_its_coordinate(
    monkeypatch: pytest.MonkeyPatch, coordinate_first: bool,
) -> None:
    lines = ["precipitation.lat[0], 34.05", "precipitation[0][0][0], 12.5"]
    if not coordinate_first:
        lines.reverse()
    monkeypatch.setattr(gpm, "fetch_with_retry", lambda *a, **k: SimpleNamespace(text="\n".join(lines)))
    assert gpm._fetch_city_precip(lat=34.05, lon=-118.24, target_date=date(2026, 11, 1),
                                  product="late", headers={}) == 12.5


@pytest.mark.parametrize("raw", ["12.5", "1.25e1", "1.25E+01;"])
def test_exact_scalar_and_its_same_name_grid_member_are_supported(raw: str) -> None:
    assert gpm._parse_ascii_value(f"precipitation[0][0][0], {raw}") == 12.5
    assert gpm._parse_ascii_value(f"precipitation.precipitation[0][0][0], {raw}") == 12.5


def test_coordinate_annotated_grid_response_selects_the_data_array(monkeypatch: pytest.MonkeyPatch) -> None:
    # Invented values in the coordinate-labelled form documented in OPenDAP's
    # Quick Start. Grid maps can precede the requested array data.
    body = "\n".join([
        "Dataset: invented.nc4",
        "precipitation.lat, 34.05",
        "precipitation.lon, -118.25",
        "precipitation.precipitation[precipitation.time=123][precipitation.lon=-118.25], 12.5",
    ])
    monkeypatch.setattr(gpm, "fetch_with_retry", lambda *a, **k: SimpleNamespace(text=body))
    assert gpm._fetch_city_precip(lat=34.05, lon=-118.24, target_date=date(2026, 11, 1),
                                  product="late", headers={}) == 12.5


@pytest.mark.parametrize("selectors", ["[lat=34][lat=35]", "[time=1e999][lon=-118]"])
def test_invalid_coordinate_selectors_are_not_a_point(selectors: str) -> None:
    assert gpm._parse_ascii_value(f"precipitation.precipitation{selectors}, 12.5") is None


@pytest.mark.parametrize("second", ["12.5", "99.0", "not-a-number"])
def test_multiple_or_malformed_target_rows_are_not_a_single_point(second: str) -> None:
    body = f"precipitation[0][0][0], 12.5\nprecipitation[0][0][1], {second}"
    assert gpm._parse_ascii_value(body) is None


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "12.5, 99.0"])
def test_nonfinite_or_multi_value_target_is_not_a_scalar(raw: str) -> None:
    assert gpm._parse_ascii_value(f"precipitation[0][0][0], {raw}") is None


def test_coordinate_only_point_fetch_returns_no_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gpm, "fetch_with_retry", lambda *a, **k: SimpleNamespace(
        text="precipitation.lat[0], 34.05\nprecipitation.lon[0], -118.24"))
    assert gpm._fetch_city_precip(lat=34.05, lon=-118.24, target_date=date(2026, 11, 1),
                                  product="late", headers={}) is None
