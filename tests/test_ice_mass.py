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
        assert rec.kind == "monthly_loss_record"
        assert rec.monthly_delta_gt == -423.0
