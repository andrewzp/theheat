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


SAMPLE_GREENLAND = """HDR
HDR columns: time_decimal_year mass_gt uncertainty_gt
HDR
2002.0417   0.0    80.0
2019.541   -3200.0 100.0
2019.625   -3623.0 100.0
2026.208   -5400.0 120.0
2026.292   -5500.0 120.0
"""


class TestFetchGraceMass:
    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_happy_path_greenland(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            body=SAMPLE_GREENLAND,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 5
        assert all(isinstance(r, IceMassReading) for r in readings)
        assert readings[0].region == "greenland"
        assert readings[0].month == "2002-01"
        assert readings[0].mass_gt == 0.0
        assert readings[-1].month == "2026-04"
        assert readings[-1].mass_gt == -5500.0
        assert readings[-1].event_id == "ice_mass_greenland_2026-04"
        # Auth header must be set
        assert responses.calls[0].request.headers["Authorization"] == "Bearer fake-token"

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_http_error_returns_empty(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            status=500,
        )
        assert fetch_grace_mass(region="greenland") == []

    @responses.activate
    @patch("src.data.ice_mass.os.environ.get", return_value="fake-token")
    def test_unauthorized_returns_empty(self, _env):
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
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
            "2026.292   -5500.0   120.0\n"
        )
        responses.add(
            responses.GET,
            "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
            "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt",
            body=body,
            status=200,
        )
        readings = fetch_grace_mass(region="greenland")
        assert len(readings) == 2
        assert readings[0].month == "2019-07"
        assert readings[-1].month == "2026-04"

    def test_unknown_region_returns_empty(self):
        assert fetch_grace_mass(region="mars") == []


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
        readings = [_reading("greenland", "2026-04", -4850.0)]
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
