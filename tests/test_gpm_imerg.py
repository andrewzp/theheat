from datetime import date
import re
from unittest.mock import patch

import responses

from src.data.gpm_imerg import (
    CityPrecipReading,
    DEFAULT_CITY_LIMIT,
    PrecipExtremeEvent,
    _ascii_subset_url,
    _lat_index,
    _lon_index,
    detect_precip_records,
    fetch_daily_precip,
    update_precip_tracking,
)


def _reading(city="Paris", country="France", mm=55.0, day="2026-05-14"):
    return CityPrecipReading(
        city=city,
        country=country,
        lat=48.85,
        lon=2.35,
        date=day,
        mm_total=mm,
        source_product="late",
        event_id=f"gpm_imerg_{country}_{city}_{day}",
    )


class TestGpmFetch:
    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_daily_precip_parses_opendap_ascii(self, _env):
        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG\.20260514.*\.ascii.*"),
            body="Dataset\n---------------------------------------------\nprecipitation[0][1823][1388], 42.5\n",
            status=200,
        )

        readings = fetch_daily_precip(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            target_date=date(2026, 5, 14),
            strict=True,
        )

        assert len(readings) == 1
        assert readings[0].mm_total == 42.5
        assert readings[0].event_id == "gpm_imerg_france_paris_2026-05-14"
        assert responses.calls[0].request.headers["Authorization"] == "Bearer fake-token"

    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_daily_precip_defaults_to_bounded_city_limit(self, _env, monkeypatch):
        import src.data.gpm_imerg as gpm

        calls = []

        def fake_fetch_city_precip(**kwargs):
            calls.append(kwargs)
            return 1.0

        monkeypatch.setattr(gpm, "_fetch_city_precip", fake_fetch_city_precip)
        cities = [
            {"city": f"City {i}", "country": "Testland", "lat": "0", "lon": "0"}
            for i in range(DEFAULT_CITY_LIMIT + 10)
        ]

        readings = fetch_daily_precip(cities, target_date=date(2026, 5, 14), strict=True)

        assert len(readings) == DEFAULT_CITY_LIMIT
        assert len(calls) == DEFAULT_CITY_LIMIT

    @patch("src.data.gpm_imerg.os.environ.get", return_value="")
    def test_missing_token_strict_raises_skipped(self, _env):
        import pytest
        from src.data.source_status import SourceSkipped

        with pytest.raises(SourceSkipped):
            fetch_daily_precip([{"city": "Paris", "country": "France", "lat": 1, "lon": 1}], strict=True)

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_strict_auth_failure_fails_fast_with_http_status(self, _env):
        """Auth-class failures must fail fast instead of looping through
        every monitored city with the same broken token.
        """
        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*"),
            status=401,
            body="Unauthorized",
        )

        import pytest
        from src.data.source_status import SourceFetchError

        with pytest.raises(SourceFetchError) as exc_info:
            fetch_daily_precip(
                [
                    {"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"},
                    {"city": "Tokyo", "country": "Japan", "lat": "35.68", "lon": "139.69"},
                ],
                target_date=date(2026, 5, 14),
                strict=True,
            )

        msg = str(exc_info.value)
        assert "1 failed" in msg
        assert "HTTP 401" in msg
        # URL of the first failure must be in the error for diagnosability.
        assert "GPM_3IMERGDL.07" in msg
        assert len(responses.calls) == 1

    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_strict_repeated_provider_failure_stops_early(self, _env, monkeypatch):
        import pytest
        import requests
        from src.data.source_status import SourceFetchError

        import src.data.gpm_imerg as gpm

        calls = 0

        def fail_city(**kwargs):
            nonlocal calls
            calls += 1
            raise requests.Timeout("provider did not respond")

        monkeypatch.setattr(gpm, "_fetch_city_precip", fail_city)

        cities = [
            {"city": f"City {i}", "country": "Testland", "lat": "0", "lon": "0"}
            for i in range(10)
        ]

        with pytest.raises(SourceFetchError, match="3 repeated Timeout failures"):
            fetch_daily_precip(
                cities,
                target_date=date(2026, 5, 14),
                strict=True,
            )

        assert calls == 3

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_strict_single_city_failure_surfaces_http_status(self, _env):
        """The single-city short-circuit path also needs the diagnostic
        — it is the path the orchestrator's debug helpers use."""
        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*"),
            status=404,
            body="Not Found",
        )

        import pytest
        from src.data.source_status import SourceFetchError

        with pytest.raises(SourceFetchError, match="HTTP 404"):
            fetch_daily_precip(
                [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
                target_date=date(2026, 5, 14),
                strict=True,
            )

    def test_late_product_url_uses_month_folder_and_v07c(self):
        url = _ascii_subset_url(
            lat=48.85,
            lon=2.35,
            target_date=date(2026, 5, 14),
            product="late",
            variable="precipitation",
        )

        assert "/GPM_3IMERGDL.07/2026/05/" in url
        assert "3B-DAY-L.MS.MRG.3IMERG.20260514-S000000-E235959.V07C.nc4.ascii" in url

    def test_final_product_url_uses_archive_product_and_v07b(self):
        url = _ascii_subset_url(
            lat=48.85,
            lon=2.35,
            target_date=date(2025, 1, 1),
            product="final",
            variable="precipitation",
        )

        assert "/GPM_3IMERGDF.07/2025/01/" in url
        assert "3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4.ascii" in url

    def test_grid_indices_are_clamped(self):
        assert _lat_index(91.0) == 1799
        assert _lat_index(-91.0) == 0
        assert _lon_index(180.0) == 0


class TestPrecipDetection:
    def test_daily_record_requires_20mm_margin(self):
        events = detect_precip_records(
            [_reading(mm=55.0)],
            {"precip_daily_records": {"france:paris:05-14": {"mm": 34.0, "year": 2024}}},
        )

        assert len(events) == 1
        assert events[0].kind == "daily_record"
        assert events[0].deviation_from_record_mm == 21.0

    def test_daily_record_does_not_seed_as_event(self):
        assert detect_precip_records([_reading(mm=55.0)], {"precip_daily_records": {}}) == []

    def test_multi_day_accumulation_uses_recent_state(self):
        state = {
            "precip_recent_by_city": {
                "france:paris": [
                    {"date": "2026-05-12", "mm": 55.0},
                    {"date": "2026-05-13", "mm": 50.0},
                ]
            }
        }
        events = detect_precip_records([_reading(mm=60.0)], state)

        rolling = [event for event in events if event.kind == "multi_day_accumulation"]
        assert len(rolling) == 1
        assert rolling[0].period_days == 3
        assert rolling[0].mm_total == 165.0

    def test_country_event_requires_ten_daily_records(self):
        readings = [
            _reading(city=f"City {i}", country="France", mm=60.0 + i)
            for i in range(10)
        ]
        state = {
            "precip_daily_records": {
                f"france:city_{i}:05-14": {"mm": 30.0, "year": 2020}
                for i in range(10)
            }
        }

        events = detect_precip_records(readings, state)

        country = [event for event in events if event.kind == "country_precip_event"]
        assert len(country) == 1
        assert country[0].city_count == 10
        assert country[0].sample_cities[:2] == ["City 0", "City 1"]

    def test_update_precip_tracking_records_daily_and_recent_rows(self):
        state = {"precip_daily_records": {}, "precip_recent_by_city": {}}
        update_precip_tracking(state, [_reading(mm=25.0), _reading(mm=35.0, day="2026-05-15")])

        assert state["precip_daily_records"]["france:paris:05-14"]["mm"] == 25.0
        assert state["precip_daily_records"]["france:paris:05-15"]["mm"] == 35.0
        assert len(state["precip_recent_by_city"]["france:paris"]) == 2

    def test_precip_event_dataclass_surface(self):
        event = PrecipExtremeEvent(
            kind="daily_record",
            location="Paris",
            country="France",
            date="2026-05-14",
            mm_total=55.0,
            period_days=1,
            deviation_from_record_mm=22.0,
            previous_record_mm=33.0,
            previous_record_year=2020,
            lat=48.85,
            lon=2.35,
            city_count=None,
            sample_cities=[],
            event_id="gpm_precip_record_france_paris_2026-05-14",
        )

        assert event.mm_total == 55.0
        assert event.previous_record_year == 2020
