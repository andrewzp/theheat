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
