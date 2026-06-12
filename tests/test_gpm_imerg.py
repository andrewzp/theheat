from datetime import date
import re
import time
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


def test_premint_failure_is_nonfatal(monkeypatch):
    from src.orchestrator.sources import gpm_imerg as runner
    from src.state import _fresh_state

    calls = []

    def fail_premint(token):
        calls.append("premint")
        assert token == "fake-token"
        raise RuntimeError("credential host down")

    def fake_fetch_daily_precip(**kwargs):
        calls.append("fetch")
        return []

    monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
    monkeypatch.setattr(runner.gpm_imerg, "get_s3_credentials", fail_premint)
    monkeypatch.setattr(runner.gpm_imerg, "fetch_daily_precip", fake_fetch_daily_precip)

    runner.run_gpm_imerg(_fresh_state(), {"sources": []}, [_PARIS])

    assert calls == ["premint", "fetch"]


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

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_resolve_available_date_walks_back_past_unpublished_404(self, _env):
        """The Late daily product lags 1-2 days, so 'yesterday' is often a 404.
        Walk back to the most recent date whose file is actually published."""
        from src.data.gpm_imerg import _resolve_available_date

        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG\.20260601.*\.ascii.*"),
            status=404,
            body="Not Found",
        )
        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG\.20260531.*\.ascii.*"),
            status=200,
            body="Dataset\nprecipitation[0][1799][1799], 1.0\n",
        )

        resolved = _resolve_available_date(
            start_date=date(2026, 6, 1),
            product="late",
            headers={"Authorization": "Bearer fake-token"},
            max_lookback=5,
        )

        assert resolved == date(2026, 5, 31)

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_resolve_available_date_exhaustion_returns_oldest_probed_date(self, _env):
        """The walk-back must never return a date it did not probe."""
        from src.data.gpm_imerg import _resolve_available_date

        for day in ("20260601", "20260531", "20260530"):
            responses.add(
                responses.GET,
                re.compile(rf".*3B-DAY-L\.MS\.MRG\.3IMERG\.{day}.*\.ascii.*"),
                status=404,
                body="Not Found",
            )

        resolved = _resolve_available_date(
            start_date=date(2026, 6, 1),
            product="late",
            headers={"Authorization": "Bearer fake-token"},
            max_lookback=2,
        )

        assert resolved == date(2026, 5, 30)
        assert len(responses.calls) == 3
        assert all("20260529" not in call.request.url for call in responses.calls)

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_resolve_available_date_stops_on_transient_error(self, _env):
        """A 5xx is NOT a date-availability signal. Don't walk back — keep the
        start date so the per-city fetches retry/surface it exactly as before."""
        from src.data.gpm_imerg import _resolve_available_date

        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG\.20260601.*\.ascii.*"),
            status=503,
            body="Service Unavailable",
        )

        resolved = _resolve_available_date(
            start_date=date(2026, 6, 1),
            product="late",
            headers={"Authorization": "Bearer fake-token"},
            max_lookback=5,
        )

        assert resolved == date(2026, 6, 1)

    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_default_path_resolves_available_date(self, _env, monkeypatch):
        """With no explicit target_date, the fetch resolves the latest published
        date via walk-back instead of blindly requesting yesterday."""
        import src.data.gpm_imerg as gpm

        monkeypatch.setattr(
            gpm, "_resolve_available_date", lambda **kw: date(2026, 5, 28), raising=False
        )
        monkeypatch.setattr(gpm, "_fetch_city_precip", lambda **kw: 3.0)

        readings = fetch_daily_precip(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            strict=False,
        )

        assert len(readings) == 1
        assert readings[0].date == "2026-05-28"

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

    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_daily_precip_parallel_fetch_preserves_input_order(self, _env, monkeypatch):
        import src.data.gpm_imerg as gpm

        def fake_fetch_city_precip(**kwargs):
            # Force completions to arrive out of order; the public result must
            # still match input city order for deterministic downstream state.
            if kwargs["lon"] == 0:
                time.sleep(0.03)
            return kwargs["lon"] + 1

        monkeypatch.setattr(gpm, "_fetch_city_precip", fake_fetch_city_precip)
        cities = [
            {"city": "Slow", "country": "Testland", "lat": "0", "lon": "0"},
            {"city": "Fast", "country": "Testland", "lat": "0", "lon": "1"},
            {"city": "Faster", "country": "Testland", "lat": "0", "lon": "2"},
        ]

        readings = fetch_daily_precip(
            cities,
            target_date=date(2026, 5, 14),
            strict=False,
            max_workers=3,
        )

        assert [reading.city for reading in readings] == ["Slow", "Fast", "Faster"]
        assert [reading.mm_total for reading in readings] == [1.0, 2.0, 3.0]

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

    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_strict_fanout_cancels_pending_after_failure_limit(self, _env, monkeypatch):
        """Once the strict failure limit trips mid-fan-out, queued city fetches
        must be cancelled rather than run to completion.

        The threaded fan-out exited via `with ThreadPoolExecutor()`, whose
        implicit shutdown(wait=True) blocked until every submitted future
        finished — so an intermittent NASA outage burned ~28 min running all 75
        doomed city fetches even after deciding to fail. Cancelling pending
        futures caps the doomed tail at one in-flight wave.
        """
        import pytest
        import requests
        from src.data.source_status import SourceFetchError

        import src.data.gpm_imerg as gpm

        calls = 0

        def fetch_city(**kwargs):
            nonlocal calls
            calls += 1
            # First three cities (the serial probe) succeed, forcing the abort
            # onto the threaded fan-out instead of short-circuiting serially.
            if kwargs["lon"] < 3:
                return 1.0
            # Doomed fetches block briefly so the bulk are still queued (not yet
            # started) when the limit trips and we cancel them.
            time.sleep(0.03)
            raise requests.Timeout("provider did not respond")

        monkeypatch.setattr(gpm, "_fetch_city_precip", fetch_city)

        cities = [
            {"city": f"City {i}", "country": "Testland", "lat": "0", "lon": str(i)}
            for i in range(40)
        ]

        with pytest.raises(SourceFetchError, match="3 repeated Timeout failures"):
            fetch_daily_precip(
                cities,
                target_date=date(2026, 5, 14),
                strict=True,
                max_workers=2,
            )

        # 3 serial-probe successes + a small fan-out wave before the trip; the
        # rest are cancelled. The bug ran all 40; the fix stops well short.
        assert calls < len(cities)

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

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_city_precip_retries_once_on_read_timeout(self, _env):
        """Transient ReadTimeout retries once. Second attempt's 200 yields a reading.

        NASA GES DISC OPeNDAP is intermittently slow under load — the 0.9.5.0
        retry layer turns a single transient timeout from a city-skip into a
        recovered read, materially improving end-to-end source success rate.
        """
        import requests as r

        url_pattern = re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*")
        responses.add(responses.GET, url_pattern, body=r.exceptions.ReadTimeout("flaky"))
        responses.add(
            responses.GET,
            url_pattern,
            body="Dataset\nprecipitation[0][1823][1388], 7.5\n",
            status=200,
        )

        readings = fetch_daily_precip(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            target_date=date(2026, 5, 14),
            strict=True,
        )

        assert len(responses.calls) == 2  # original + 1 retry
        assert len(readings) == 1
        assert readings[0].mm_total == 7.5

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_city_precip_retries_once_on_5xx(self, _env):
        """503 Server Error retries once. Same NASA-overload pattern as ReadTimeout."""
        url_pattern = re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*")
        responses.add(responses.GET, url_pattern, status=503, body="server overloaded")
        responses.add(
            responses.GET,
            url_pattern,
            body="Dataset\nprecipitation[0][1823][1388], 12.0\n",
            status=200,
        )

        readings = fetch_daily_precip(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            target_date=date(2026, 5, 14),
            strict=True,
        )

        assert len(responses.calls) == 2
        assert len(readings) == 1
        assert readings[0].mm_total == 12.0

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_fetch_city_precip_does_not_retry_on_4xx(self, _env):
        """Persistent 4xx (auth, 404) must not retry — wastes runtime budget on
        guaranteed-to-fail repeats. Single call, immediate fail-fast.
        """
        import pytest
        from src.data.source_status import SourceFetchError

        url_pattern = re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*")
        responses.add(responses.GET, url_pattern, status=401, body="Unauthorized")

        with pytest.raises(SourceFetchError):
            fetch_daily_precip(
                [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
                target_date=date(2026, 5, 14),
                strict=True,
            )

        assert len(responses.calls) == 1  # no retry

    @responses.activate
    @patch("src.data.gpm_imerg.os.environ.get", return_value="fake-token")
    def test_gpm_city_fetch_uses_shared_retry(self, _env, monkeypatch):
        import src.data.gpm_imerg as gpm

        calls = []
        real_fetch_with_retry = gpm.fetch_with_retry

        def spy_fetch_with_retry(url, **kwargs):
            calls.append((url, kwargs))
            return real_fetch_with_retry(url, **kwargs)

        monkeypatch.setattr(gpm, "fetch_with_retry", spy_fetch_with_retry)
        responses.add(
            responses.GET,
            re.compile(r".*3B-DAY-L\.MS\.MRG\.3IMERG.*\.ascii.*"),
            body="Dataset\nprecipitation[0][1823][1388], 9.5\n",
            status=200,
        )

        readings = fetch_daily_precip(
            [{"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}],
            target_date=date(2026, 5, 14),
            strict=True,
        )

        assert readings[0].mm_total == 9.5
        assert calls[0][1]["attempts"] == 2
        assert calls[0][1]["backoff_base"] == gpm._retry_backoff_s()
        assert responses.calls[0].request.headers["Authorization"] == "Bearer fake-token"
        assert "theheat" in responses.calls[0].request.headers["User-Agent"].lower()

    def test_request_timeout_env_override(self, monkeypatch):
        """GPM_IMERG_TIMEOUT_S overrides default; junk values fall back safely."""
        from src.data.gpm_imerg import DEFAULT_REQUEST_TIMEOUT_S, _request_timeout_s

        monkeypatch.delenv("GPM_IMERG_TIMEOUT_S", raising=False)
        assert _request_timeout_s() == DEFAULT_REQUEST_TIMEOUT_S

        monkeypatch.setenv("GPM_IMERG_TIMEOUT_S", "120")
        assert _request_timeout_s() == 120.0

        monkeypatch.setenv("GPM_IMERG_TIMEOUT_S", "not-a-number")
        assert _request_timeout_s() == DEFAULT_REQUEST_TIMEOUT_S  # ValueError → fallback

        monkeypatch.setenv("GPM_IMERG_TIMEOUT_S", "-5")
        assert _request_timeout_s() == DEFAULT_REQUEST_TIMEOUT_S  # negative → fallback

        monkeypatch.setenv("GPM_IMERG_TIMEOUT_S", "0")
        assert _request_timeout_s() == DEFAULT_REQUEST_TIMEOUT_S  # zero → fallback

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


def _make_grid_bytes(values_by_index, *, group=None, shape=None):
    """Serialize a synthetic IMERG-shaped HDF5 grid in memory.

    ``values_by_index`` maps ``(t, lon_idx, lat_idx)`` tuples to precip values;
    every other cell is 0.0. gzip keeps the all-zeros payload tiny.
    """
    import io as _io

    import h5py
    import numpy as np

    from src.data.gpm_imerg import LAT_CELLS, LON_CELLS

    if shape is None:
        shape = (1, LON_CELLS, LAT_CELLS)
    arr = np.zeros(shape, dtype="float32")
    for index, value in values_by_index.items():
        arr[index] = value

    buf = _io.BytesIO()
    with h5py.File(buf, "w") as handle:
        target = handle.create_group(group) if group else handle
        target.create_dataset(
            "precipitation", data=arr, compression="gzip", compression_opts=1
        )
    return buf.getvalue()


_PARIS = {"city": "Paris", "country": "France", "lat": "48.85", "lon": "2.35"}


class TestGpmGridFetch:
    def test_imerg_filename_and_relpath(self):
        from src.data.gpm_imerg import _imerg_filename, _imerg_relpath

        assert (
            _imerg_filename("late", date(2026, 6, 5))
            == "3B-DAY-L.MS.MRG.3IMERG.20260605-S000000-E235959.V07C.nc4"
        )
        assert (
            _imerg_filename("final", date(2025, 1, 1))
            == "3B-DAY.MS.MRG.3IMERG.20250101-S000000-E235959.V07B.nc4"
        )
        assert _imerg_relpath("late", date(2026, 6, 5)) == (
            "GPM_3IMERGDL.07/2026/06/3B-DAY-L.MS.MRG.3IMERG.20260605-S000000-E235959.V07C.nc4"
        )

    def test_gpm_source_resolution(self, monkeypatch):
        from src.data.gpm_imerg import _gpm_source

        monkeypatch.delenv("THEHEAT_GPM_SOURCE", raising=False)
        assert _gpm_source() == "opendap"

        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "s3")
        assert _gpm_source() == "s3"

        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "DataPool")  # case-insensitive
        assert _gpm_source() == "datapool"

        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "garbage")  # unknown → legacy
        assert _gpm_source() == "opendap"

    def test_datapool_chain_includes_s3(self):
        from src.data.gpm_imerg import _gpm_grid_source_chain

        assert _gpm_grid_source_chain("datapool") == ("datapool", "s3")

    def test_subset_grid_extracts_city_value(self):
        from src.data.gpm_imerg import _lat_index, _lon_index, _subset_grid

        lon_i, lat_i = _lon_index(2.35), _lat_index(48.85)
        grid = _make_grid_bytes({(0, lon_i, lat_i): 42.5})

        readings = _subset_grid(
            grid, [_PARIS], resolved_date=date(2026, 6, 5), product="late"
        )

        assert len(readings) == 1
        assert readings[0].mm_total == 42.5
        assert readings[0].date == "2026-06-05"
        assert readings[0].source_product == "late"
        assert readings[0].event_id == "gpm_imerg_france_paris_2026-06-05"

    def test_subset_grid_skips_fill_value(self):
        from src.data.gpm_imerg import FILL_VALUE, _lat_index, _lon_index, _subset_grid

        lon_i, lat_i = _lon_index(2.35), _lat_index(48.85)
        grid = _make_grid_bytes({(0, lon_i, lat_i): FILL_VALUE})

        readings = _subset_grid(
            grid, [_PARIS], resolved_date=date(2026, 6, 5), product="late"
        )

        assert readings == []

    def test_subset_grid_finds_precip_under_grid_group(self):
        from src.data.gpm_imerg import _lat_index, _lon_index, _subset_grid

        lon_i, lat_i = _lon_index(2.35), _lat_index(48.85)
        grid = _make_grid_bytes({(0, lon_i, lat_i): 12.0}, group="Grid")

        readings = _subset_grid(
            grid, [_PARIS], resolved_date=date(2026, 6, 5), product="late"
        )

        assert len(readings) == 1
        assert readings[0].mm_total == 12.0

    def test_subset_grid_rejects_unexpected_shape(self):
        import pytest

        from src.data.gpm_imerg import _GridParseError, _subset_grid

        grid = _make_grid_bytes({}, shape=(1, 100, 100))

        with pytest.raises(_GridParseError):
            _subset_grid(grid, [_PARIS], resolved_date=date(2026, 6, 5), product="late")

    def test_walkback_steps_past_not_found(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        probed = []

        def fake_fetch(source, *, target_date, product, token):
            probed.append(target_date)
            if target_date == date(2026, 6, 5):
                return b"GRID"
            raise gpm._GridNotFound("not published")

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fake_fetch)

        resolved, payload = gpm._fetch_grid_with_walkback(
            "datapool",
            start_date=date(2026, 6, 7),
            product="late",
            token="tok",
            max_lookback=5,
        )

        assert resolved == date(2026, 6, 5)
        assert payload == b"GRID"
        assert probed == [date(2026, 6, 7), date(2026, 6, 6), date(2026, 6, 5)]

    def test_walkback_stops_on_transient(self, monkeypatch):
        import pytest

        import src.data.gpm_imerg as gpm

        probed = []

        def fake_fetch(source, *, target_date, product, token):
            probed.append(target_date)
            raise gpm._GridTransient("5xx")

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fake_fetch)

        with pytest.raises(gpm._GridTransient):
            gpm._fetch_grid_with_walkback(
                "s3",
                start_date=date(2026, 6, 7),
                product="late",
                token="tok",
                max_lookback=5,
            )

        # A transient error is not a date signal — stop after the first probe.
        assert probed == [date(2026, 6, 7)]

    @responses.activate
    def test_datapool_fetch_returns_bytes_with_bearer(self):
        import src.data.gpm_imerg as gpm

        responses.add(
            responses.GET,
            re.compile(
                r"https://data\.gesdisc\.earthdata\.nasa\.gov/data/GPM_L3/"
                r"GPM_3IMERGDL\.07/2026/06/.*\.nc4$"
            ),
            body=b"NC4BYTES",
            status=200,
        )

        payload = gpm._fetch_grid_bytes_datapool(
            target_date=date(2026, 6, 5), product="late", token="tok"
        )

        assert payload == b"NC4BYTES"
        assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"

    @responses.activate
    def test_datapool_404_is_not_found(self):
        import pytest

        import src.data.gpm_imerg as gpm

        responses.add(
            responses.GET, re.compile(r".*GPM_3IMERGDL.*"), status=404, body="missing"
        )

        with pytest.raises(gpm._GridNotFound):
            gpm._fetch_grid_bytes_datapool(
                target_date=date(2026, 6, 5), product="late", token="tok"
            )

    @responses.activate
    def test_datapool_503_is_transient(self):
        import pytest

        import src.data.gpm_imerg as gpm

        responses.add(
            responses.GET, re.compile(r".*GPM_3IMERGDL.*"), status=503, body="overloaded"
        )

        with pytest.raises(gpm._GridTransient):
            gpm._fetch_grid_bytes_datapool(
                target_date=date(2026, 6, 5), product="late", token="tok"
            )

    def test_s3_fetch_builds_key_and_returns_bytes(self, monkeypatch):
        from datetime import datetime, timezone

        import boto3

        import src.data.gpm_imerg as gpm
        from src.data._s3credentials import S3Credentials

        monkeypatch.setattr(
            gpm,
            "get_s3_credentials",
            lambda token, **kw: S3Credentials(
                "AK", "SK", "ST", datetime(2030, 1, 1, tzinfo=timezone.utc)
            ),
        )

        captured = {}

        class _Body:
            def read(self):
                return b"S3BYTES"

        class _Client:
            def get_object(self, Bucket, Key):
                captured["bucket"] = Bucket
                captured["key"] = Key
                return {"Body": _Body()}

        monkeypatch.setattr(boto3, "client", lambda *a, **kw: _Client())

        payload = gpm._fetch_grid_bytes_s3(
            target_date=date(2026, 6, 5), product="late", token="tok"
        )

        assert payload == b"S3BYTES"
        assert captured["bucket"] == "gesdisc-cumulus-prod-protected"
        assert captured["key"] == (
            "GPM_L3/GPM_3IMERGDL.07/2026/06/"
            "3B-DAY-L.MS.MRG.3IMERG.20260605-S000000-E235959.V07C.nc4"
        )

    def test_s3_access_denied_treated_as_not_found(self, monkeypatch):
        from datetime import datetime, timezone

        import boto3
        from botocore.exceptions import ClientError
        import pytest

        import src.data.gpm_imerg as gpm
        from src.data._s3credentials import S3Credentials

        monkeypatch.setattr(
            gpm,
            "get_s3_credentials",
            lambda token, **kw: S3Credentials(
                "AK", "SK", "ST", datetime(2030, 1, 1, tzinfo=timezone.utc)
            ),
        )

        class _Client:
            def get_object(self, Bucket, Key):
                raise ClientError(
                    {
                        "Error": {"Code": "AccessDenied"},
                        "ResponseMetadata": {"HTTPStatusCode": 403},
                    },
                    "GetObject",
                )

        monkeypatch.setattr(boto3, "client", lambda *a, **kw: _Client())

        # No ListBucket perm → a missing key surfaces as 403; the walk-back must
        # treat it as "not published", not a hard error.
        with pytest.raises(gpm._GridNotFound):
            gpm._fetch_grid_bytes_s3(
                target_date=date(2026, 6, 5), product="late", token="tok"
            )

    def test_source_datapool_uses_grid_path(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")

        lon_i, lat_i = gpm._lon_index(2.35), gpm._lat_index(48.85)
        monkeypatch.setattr(
            gpm,
            "_fetch_grid_bytes",
            lambda *a, **kw: _make_grid_bytes({(0, lon_i, lat_i): 55.0}),
        )

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        assert len(readings) == 1
        assert readings[0].mm_total == 55.0
        assert readings[0].source_product == "late"

    def test_source_s3_falls_back_to_opendap_on_failure(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "s3")

        def boom(*a, **kw):
            raise gpm._GridTransient("s3 unavailable")

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", boom)
        monkeypatch.setattr(gpm, "_fetch_city_precip", lambda **kw: 3.0)

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        # Grid path failed → legacy OPeNDAP per-city path delivered the reading.
        assert len(readings) == 1
        assert readings[0].mm_total == 3.0

    def test_source_s3_tries_datapool_before_opendap(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "s3")

        calls = []
        lon_i, lat_i = gpm._lon_index(2.35), gpm._lat_index(48.85)

        def fake_fetch(source, *, target_date, product, token):
            calls.append(source)
            if source == "s3":
                raise gpm._GridTransient("s3 unavailable")
            return _make_grid_bytes({(0, lon_i, lat_i): 44.0})

        def fail_opendap(**kw):
            raise AssertionError("opendap should not run when datapool succeeds")

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fake_fetch)
        monkeypatch.setattr(gpm, "_fetch_city_precip", fail_opendap)

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        assert calls == ["s3", "datapool"]
        assert len(readings) == 1
        assert readings[0].mm_total == 44.0

    def test_chain_falls_through_to_opendap(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")

        calls = []

        def fail_grid(source, *, target_date, product, token):
            calls.append(source)
            raise gpm._GridTransient(f"{source} unavailable")

        def fake_opendap(**kw):
            calls.append("opendap")
            return 7.0

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fail_grid)
        monkeypatch.setattr(gpm, "_fetch_city_precip", fake_opendap)

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        assert calls == ["datapool", "s3", "opendap"]
        assert len(readings) == 1
        assert readings[0].mm_total == 7.0

    def test_grid_fallback_logs_serving_leg_position(self, monkeypatch, capsys):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")

        lon_i, lat_i = gpm._lon_index(2.35), gpm._lat_index(48.85)

        def fake_fetch(source, *, target_date, product, token):
            if source == "datapool":
                raise gpm._GridTransient("datapool unavailable")
            return _make_grid_bytes({(0, lon_i, lat_i): 41.0})

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fake_fetch)

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        assert len(readings) == 1
        assert "[gpm] grid source s3 served (chain position 2)" in capsys.readouterr().out

    def test_source_opendap_default_skips_grid_path(self, monkeypatch):
        import src.data.gpm_imerg as gpm

        monkeypatch.setenv("EARTHDATA_TOKEN", "fake-token")
        monkeypatch.delenv("THEHEAT_GPM_SOURCE", raising=False)

        def fail_if_called(*a, **kw):
            raise AssertionError("grid path must not run for the default opendap source")

        monkeypatch.setattr(gpm, "_fetch_grid_bytes", fail_if_called)
        monkeypatch.setattr(gpm, "_fetch_city_precip", lambda **kw: 9.0)

        readings = gpm.fetch_daily_precip([_PARIS], target_date=date(2026, 6, 5))

        assert len(readings) == 1
        assert readings[0].mm_total == 9.0
