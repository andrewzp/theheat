"""Tests for NASA GRACE-FO ice mass data."""

from src.data.ice_mass import (
    IceMassReading,
    IceMassRecord,
    fetch_grace_mass,
    detect_monthly_record,
    detect_cumulative_milestone,
)


class TestModuleSurface:
    def test_ice_mass_reading_dataclass(self):
        r = IceMassReading(
            region="greenland",
            month="2026-03",
            mass_gt=-5432.1,
            uncertainty_gt=120.0,
            event_id="ice_mass_greenland_2026-03",
        )
        assert r.region == "greenland"
        assert r.month == "2026-03"
        assert r.mass_gt == -5432.1
        assert r.uncertainty_gt == 120.0
        assert r.event_id == "ice_mass_greenland_2026-03"

    def test_ice_mass_record_dataclass(self):
        rec = IceMassRecord(
            region="greenland",
            kind="monthly_loss_record",
            month="2026-08",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
            previous_worst_month="2019-07",
            threshold_gt=None,
            current_mass_gt=None,
            event_id="ice_mass_record_greenland_monthly_2026-08",
        )
        assert rec.region == "greenland"
        assert rec.kind == "monthly_loss_record"
        assert rec.month == "2026-08"
        assert rec.monthly_delta_gt == -423.0
        assert rec.previous_worst_gt == -350.0
        assert rec.previous_worst_month == "2019-07"
        assert rec.threshold_gt is None
        assert rec.current_mass_gt is None
        assert rec.event_id == "ice_mass_record_greenland_monthly_2026-08"


from src.data.ice_mass import _decimal_year_to_month


class TestDecimalYearToMonth:
    def test_january(self):
        assert _decimal_year_to_month(2026.04) == "2026-01"

    def test_august(self):
        # Aug = month index 7 (0-based). (7 + 0.5) / 12 ≈ 0.625
        assert _decimal_year_to_month(2026.625) == "2026-08"

    def test_december(self):
        assert _decimal_year_to_month(2026.96) == "2026-12"

    def test_exact_year_boundary(self):
        assert _decimal_year_to_month(2002.0) == "2002-01"


from unittest.mock import patch
import responses


# The fixture's TAIL rows must stay inside ice_mass.py's 75-day freshness
# gate no matter when the suite runs — fixed dates rot (the time-travel
# canary caught the old 2026.292 tail set to detonate ~2026-07-14). GRACE
# rows are mid-month decimal years: year + (month - 0.5) / 12.
from datetime import date, timedelta  # noqa: E402


def _mid_month_decimal(d: "date") -> str:
    return f"{d.year + (d.month - 0.5) / 12:.4f}"


_LATEST = date.today()
_PREV = _LATEST.replace(day=1) - timedelta(days=1)
_LATEST_MONTH = f"{_LATEST.year}-{_LATEST.month:02d}"

SAMPLE_GREENLAND = f"""HDR
HDR columns: time_decimal_year mass_gt uncertainty_gt
HDR
2002.0417   0.0    80.0
2019.541   -3200.0 100.0
2019.625   -3623.0 100.0
{_mid_month_decimal(_PREV)}   -5400.0 120.0
{_mid_month_decimal(_LATEST)}   -5500.0 120.0
"""

# Dataset URL the CMR lookup is expected to return for greenland in the new
# PO.DAAC Earthdata Cloud archive. The filename embeds a data range; we pick
# one representative spelling for tests.
NEW_GREENLAND_URL = (
    "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/"
    "GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4/"
    "greenland_mass_200204_202603.txt"
)


def _cmr_response(href: str) -> dict:
    """Build the minimal CMR /search/granules.json shape the resolver reads."""
    return {
        "feed": {
            "entry": [
                {
                    "title": "greenland_mass_200204_202603",
                    "links": [
                        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": href},
                    ],
                }
            ]
        }
    }


def _mock_cmr(short_name: str, href: str | None) -> None:
    """Register a CMR mock that returns one granule with `href` (or empty if None)."""
    body = _cmr_response(href) if href else {"feed": {"entry": []}}
    responses.add(
        responses.GET,
        "https://cmr.earthdata.nasa.gov/search/granules.json",
        json=body,
        status=200,
        match=[responses.matchers.query_param_matcher({"short_name": short_name, "page_size": "1", "sort_key": "-start_date"})],
    )


class TestFetchGraceMass:
    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_happy_path_greenland(self, _env):
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", NEW_GREENLAND_URL)
        responses.add(
            responses.GET,
            NEW_GREENLAND_URL,
            body=SAMPLE_GREENLAND,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 5
        assert all(isinstance(r, IceMassReading) for r in readings)
        assert readings[0].region == "greenland"
        assert readings[0].month == "2002-01"
        assert readings[0].mass_gt == 0.0
        assert readings[-1].month == _LATEST_MONTH
        assert readings[-1].mass_gt == -5500.0
        assert readings[-1].event_id == f"ice_mass_greenland_{_LATEST_MONTH}"
        # Auth header must be set on the data fetch (the 2nd call; 1st is CMR).
        assert responses.calls[1].request.headers["Authorization"] == "Bearer fake-token"

    @responses.activate
    @patch("src.data._http.time.sleep")
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_http_error_returns_empty(self, _env, _sleep):
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", NEW_GREENLAND_URL)
        # Data fetch is routed through fetch_with_retry, so a persistent 5xx is
        # retried before the source gives up and returns [].
        for _ in range(3):
            responses.add(responses.GET, NEW_GREENLAND_URL, status=500)
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data._http.time.sleep")
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_data_fetch_recovers_after_transient_5xx(self, _env, _sleep):
        # The PO.DAAC data fetch is routed through fetch_with_retry, so a
        # transient 502 (the observed ice_mass failure) recovers on retry
        # instead of dropping the whole region.
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", NEW_GREENLAND_URL)
        responses.add(responses.GET, NEW_GREENLAND_URL, status=502)
        responses.add(responses.GET, NEW_GREENLAND_URL, body=SAMPLE_GREENLAND, status=200)
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 5

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_unauthorized_returns_empty(self, _env):
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", NEW_GREENLAND_URL)
        responses.add(
            responses.GET,
            NEW_GREENLAND_URL,
            status=401,
        )
        assert fetch_grace_mass(region="greenland") == []

    @patch("src.data.ice_mass.os.environ.get", return_value="")
    def test_missing_token_returns_empty(self, _env):
        # No responses mock needed — must short-circuit before any HTTP call.
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_malformed_rows_skipped(self, _env):
        body = (
            "HDR columns: time mass unc\n"
            "2019.541   -3200.0   100.0\n"
            "not a number    bad    data\n"
            f"{_mid_month_decimal(_LATEST)}   -5500.0   120.0\n"
        )
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", NEW_GREENLAND_URL)
        responses.add(
            responses.GET,
            NEW_GREENLAND_URL,
            body=body,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 2
        assert readings[0].month == "2019-07"
        assert readings[-1].month == _LATEST_MONTH

    def test_unknown_region_returns_empty(self):
        assert fetch_grace_mass(region="mars") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_cmr_returns_no_granules_skips(self, _env):
        # When CMR returns an empty result, fetch_grace_mass must return [] and
        # never attempt a data fetch (so no responses mock for the data URL).
        _mock_cmr("GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4", None)
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_cmr_http_failure_skips(self, _env):
        responses.add(
            responses.GET,
            "https://cmr.earthdata.nasa.gov/search/granules.json",
            status=503,
        )
        assert fetch_grace_mass(region="greenland") == []


def _reading(region: str, month: str, mass_gt: float) -> IceMassReading:
    return IceMassReading(
        region=region,
        month=month,
        mass_gt=mass_gt,
        uncertainty_gt=100.0,
        event_id=f"ice_mass_{region}_{month}",
    )


class TestDetectMonthlyRecord:
    def test_fires_new_record(self):
        readings = [
            _reading("greenland", "2024-07", -3200.0),
            _reading("greenland", "2024-08", -3550.0),   # delta -350 (old record)
            _reading("greenland", "2026-07", -5000.0),
            _reading("greenland", "2026-08", -5423.0),   # delta -423 → new record
        ]
        state = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2024-08"},
            }
        }
        rec = detect_monthly_record(readings, state)
        assert rec is not None
        assert rec.kind == "monthly_loss_record"
        assert rec.region == "greenland"
        assert rec.month == "2026-08"
        assert rec.monthly_delta_gt == -423.0
        assert rec.previous_worst_gt == -350.0
        assert rec.previous_worst_month == "2024-08"
        assert rec.event_id == "ice_mass_record_greenland_monthly_2026-08"

    def test_no_fire_when_not_record(self):
        readings = [
            _reading("greenland", "2024-08", -3550.0),
            _reading("greenland", "2026-07", -5000.0),
            _reading("greenland", "2026-08", -5200.0),   # delta -200, weaker than stored -350
        ]
        state = {
            "ice_mass_max_loss": {
                "greenland": {"gt": -350.0, "month": "2024-08"},
            }
        }
        assert detect_monthly_record(readings, state) is None

    def test_seeds_state_on_first_run(self):
        # No prior record in state; first positive loss seeds the floor.
        readings = [
            _reading("greenland", "2026-07", -5000.0),
            _reading("greenland", "2026-08", -5423.0),
        ]
        state = {"ice_mass_max_loss": {}}
        rec = detect_monthly_record(readings, state)
        assert rec is not None
        assert rec.previous_worst_gt is None
        assert rec.previous_worst_month is None
        assert rec.monthly_delta_gt == -423.0

    def test_single_reading_returns_none(self):
        readings = [_reading("greenland", "2026-08", -5423.0)]
        assert detect_monthly_record(readings, {"ice_mass_max_loss": {}}) is None

    def test_positive_delta_no_fire(self):
        # Month-over-month gain (unusual but possible) must never fire.
        readings = [
            _reading("greenland", "2026-03", -5500.0),
            _reading("greenland", "2026-04", -5400.0),  # +100 gain
        ]
        state = {"ice_mass_max_loss": {}}
        assert detect_monthly_record(readings, state) is None

    def test_empty_readings_returns_none(self):
        assert detect_monthly_record([], {"ice_mass_max_loss": {}}) is None


class TestDetectCumulativeMilestone:
    def test_fires_on_first_crossing(self):
        readings = [
            _reading("greenland", "2026-03", -4900.0),
            _reading("greenland", "2026-04", -5050.0),   # crosses -5000
        ]
        state = {"ice_mass_last_milestone": {}}
        rec = detect_cumulative_milestone(readings, state)
        assert rec is not None
        assert rec.kind == "cumulative_milestone"
        assert rec.threshold_gt == -5000.0
        assert rec.current_mass_gt == -5050.0
        assert rec.event_id == "ice_mass_record_greenland_cumulative_-5000"

    def test_no_refire_once_fired(self):
        readings = [_reading("greenland", "2026-04", -5100.0)]
        state = {"ice_mass_last_milestone": {"greenland": -5000.0}}
        assert detect_cumulative_milestone(readings, state) is None

    def test_subsequent_milestone_fires(self):
        readings = [_reading("greenland", "2028-07", -6042.0)]
        state = {"ice_mass_last_milestone": {"greenland": -5000.0}}
        rec = detect_cumulative_milestone(readings, state)
        assert rec is not None
        assert rec.threshold_gt == -6000.0
        assert rec.current_mass_gt == -6042.0

    def test_no_fire_if_not_yet_crossed(self):
        # -850 Gt is below the first -1000 Gt milestone threshold — no fire.
        readings = [
            _reading("greenland", "2026-03", -700.0),
            _reading("greenland", "2026-04", -850.0),
        ]
        state = {"ice_mass_last_milestone": {}}
        assert detect_cumulative_milestone(readings, state) is None

    def test_empty_readings_returns_none(self):
        assert detect_cumulative_milestone([], {"ice_mass_last_milestone": {}}) is None

    def test_positive_mass_no_fire(self):
        # At mission start mass is near the baseline (≈0). No negative
        # threshold to report.
        readings = [_reading("greenland", "2002-04", 12.0)]
        state = {"ice_mass_last_milestone": {}}
        assert detect_cumulative_milestone(readings, state) is None
