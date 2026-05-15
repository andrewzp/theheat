"""Tests for NASA Ozone Watch Antarctic ozone hole data."""

from datetime import date

import responses

from src.data.ozone_hole import (
    OZONE_ANNUAL_PEAKS_URL,
    OZONE_AREA_URL_TEMPLATE,
    OzoneHoleReading,
    detect_seasonal_peak,
    fetch_ozone_hole_annual_peaks,
    fetch_ozone_hole_data,
)


DAILY_SAMPLE = """Name: Ozone Hole Area
Units: Million km!U2!N
Source: toms+omi+omps
Missing: -9999.0
Climatology: 1979 to 2025
Date            Data   Minimum     10%     30%    Mean     70%     90% Maximum
2026-08-01      1.00      0.00    0.00    0.00    1.20    2.00    3.00    4.00
2026-09-20     23.00      0.00    0.00    0.00   20.00   24.00   26.00   29.00
2026-11-05     18.50      0.00    0.00    0.00   16.00   20.00   22.00   25.00
"""

ANNUAL_SAMPLE = """# Maximum of daily ozone hole area
         Ozone Hole Area       Minimum Ozone
          Date     Value      Date     Value
Year    (YYMM) (mil km2)    (YYMM)      (DU)
2023      0921      24.1      1005     112.0
2024      0917      25.4      1001     109.0
2025      0922      20.8      1003     121.0
2026      0920      23.0      1004     118.0
"""


def _reading(day: str, area: float) -> OzoneHoleReading:
    return OzoneHoleReading(
        date=day,
        area_million_km2=area,
        climatology_mean=None,
        climatology_max=None,
        event_id=f"ozone_hole_area_{day}",
    )


class TestFetchOzoneHole:
    @responses.activate
    def test_fetch_ozone_hole_data_parses_daily_area_rows(self):
        responses.add(
            responses.GET,
            OZONE_AREA_URL_TEMPLATE.format(year=2026),
            body=DAILY_SAMPLE,
            status=200,
        )

        readings = fetch_ozone_hole_data(year=2026, max_age_days=100000)

        assert len(readings) == 3
        assert readings[1].area_million_km2 == 23.0
        assert readings[1].climatology_mean == 20.0
        assert readings[1].climatology_max == 29.0

    @responses.activate
    def test_fetch_annual_peaks_parses_ytd_table(self):
        responses.add(responses.GET, OZONE_ANNUAL_PEAKS_URL, body=ANNUAL_SAMPLE, status=200)

        peaks = fetch_ozone_hole_annual_peaks()

        assert len(peaks) == 4
        assert peaks[-1].year == 2026
        assert peaks[-1].peak_date == "2026-09-20"
        assert peaks[-1].area_million_km2 == 23.0

    @responses.activate
    def test_fetch_ozone_hole_data_returns_empty_on_non_strict_error(self):
        responses.add(
            responses.GET,
            OZONE_AREA_URL_TEMPLATE.format(year=2026),
            status=404,
        )

        assert fetch_ozone_hole_data(year=2026, max_age_days=100000) == []


class TestDetectOzoneHolePeak:
    def test_detects_confirmed_seasonal_peak_with_comparisons(self):
        annual_peaks = fetch_ozone_hole_annual_peaks_from_text_for_test()
        readings = [
            _reading("2026-08-01", 1.0),
            _reading("2026-09-20", 23.0),
            _reading("2026-11-05", 18.5),
        ]

        event = detect_seasonal_peak(
            readings,
            annual_peaks,
            today=date(2026, 11, 5),
        )

        assert event is not None
        assert event.event_id == "ozone_hole_peak_2026"
        assert event.previous_year == 2025
        assert event.previous_area_million_km2 == 20.8
        assert event.record_year == 2024
        assert event.record_area_million_km2 == 25.4
        assert event.larger_than_previous_year is True

    def test_waits_for_confirmation_window(self):
        annual_peaks = fetch_ozone_hole_annual_peaks_from_text_for_test()
        readings = [_reading("2026-09-20", 23.0)]

        event = detect_seasonal_peak(
            readings,
            annual_peaks,
            today=date(2026, 9, 22),
        )

        assert event is None

    def test_waits_until_late_season_before_firing(self):
        annual_peaks = fetch_ozone_hole_annual_peaks_from_text_for_test()
        readings = [_reading("2026-09-20", 23.0), _reading("2026-09-30", 21.0)]

        event = detect_seasonal_peak(
            readings,
            annual_peaks,
            today=date(2026, 9, 30),
        )

        assert event is None

    def test_skips_when_same_peak_already_recorded(self):
        annual_peaks = fetch_ozone_hole_annual_peaks_from_text_for_test()
        readings = [_reading("2026-09-20", 23.0), _reading("2026-11-05", 18.5)]

        event = detect_seasonal_peak(
            readings,
            annual_peaks,
            last_peaks={"2026": {"peak_date": "2026-09-20", "area_million_km2": 23.0}},
            today=date(2026, 11, 5),
        )

        assert event is None

    def test_returns_none_without_seasonal_readings(self):
        readings = [_reading("2026-05-01", 0.0)]

        assert detect_seasonal_peak(readings, [], today=date(2026, 11, 5)) is None


def fetch_ozone_hole_annual_peaks_from_text_for_test():
    import responses

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, OZONE_ANNUAL_PEAKS_URL, body=ANNUAL_SAMPLE, status=200)
        return fetch_ozone_hole_annual_peaks()
