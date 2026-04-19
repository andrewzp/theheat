"""Tests for CO2 milestone detection."""

from src.data.co2 import CO2Reading, detect_milestone, compute_weekly_comparison


class TestDetectMilestone:
    def test_new_integer_crossed(self):
        readings = [
            CO2Reading("2026-04-06", 428.7, "co2_1"),
            CO2Reading("2026-04-07", 429.1, "co2_2"),
        ]
        result = detect_milestone(readings)
        assert result is not None
        assert result.ppm_crossed == 429

    def test_no_new_integer(self):
        readings = [
            CO2Reading("2026-04-06", 428.3, "co2_1"),
            CO2Reading("2026-04-07", 428.7, "co2_2"),
        ]
        result = detect_milestone(readings)
        assert result is None

    def test_integer_already_crossed_before(self):
        readings = [
            CO2Reading("2026-04-05", 429.2, "co2_1"),
            CO2Reading("2026-04-06", 428.7, "co2_2"),
            CO2Reading("2026-04-07", 429.1, "co2_3"),
        ]
        result = detect_milestone(readings)
        assert result is None

    def test_single_reading(self):
        readings = [CO2Reading("2026-04-07", 429.1, "co2_1")]
        result = detect_milestone(readings)
        assert result is None

    def test_empty_readings(self):
        assert detect_milestone([]) is None


class TestWeeklyComparison:
    def _readings_with_avgs(
        self, current_avg: float, last_year_avg: float
    ) -> list[CO2Reading]:
        """Build readings that span today's current-week window and the
        matching week last year, with the requested averages."""
        from datetime import date, timedelta

        today = date.today()
        readings = []
        # Current week: today, yesterday — both in range [today-7, today]
        for offset in (0, 1):
            d = today - timedelta(days=offset)
            readings.append(
                CO2Reading(d.isoformat(), current_avg, f"co2_curr_{offset}")
            )
        # Same week last year
        last_year_today = today.replace(year=today.year - 1)
        for offset in (0, 1):
            d = last_year_today - timedelta(days=offset)
            readings.append(
                CO2Reading(d.isoformat(), last_year_avg, f"co2_prev_{offset}")
            )
        return readings

    def test_positive_diff_above_floor_returns_comparison(self):
        readings = self._readings_with_avgs(current_avg=432.5, last_year_avg=430.0)
        result = compute_weekly_comparison(readings)
        assert result is not None
        assert result.difference == 2.5

    def test_negative_diff_returns_none(self):
        """A week-over-year dip is noise in a monotonically rising signal —
        do not tweet it as 'the direction'."""
        readings = self._readings_with_avgs(current_avg=429.8, last_year_avg=430.1)
        assert compute_weekly_comparison(readings) is None

    def test_below_noise_floor_returns_none(self):
        """Sub-1ppm positive diffs are also noise-territory; skip."""
        readings = self._readings_with_avgs(current_avg=430.5, last_year_avg=430.0)
        assert compute_weekly_comparison(readings) is None

    def test_empty_readings(self):
        assert compute_weekly_comparison([]) is None
