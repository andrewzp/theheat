"""Tests for NOAA GML methane milestone detection."""

from unittest.mock import patch

from src.data.methane import (
    MethaneReading,
    detect_milestone,
    fetch_ch4_milestones,
)
from src.editorial.scoring import score_ch4_milestone


class TestMethaneMilestone:
    def test_new_10ppb_milestone_crossed(self):
        readings = [
            MethaneReading("2026-03-01", 1938.0, "ch4_1"),
            MethaneReading("2026-04-01", 1942.3, "ch4_2"),
        ]
        result = detect_milestone(readings)
        assert result is not None
        assert result.ppb_crossed == 1940
        assert result.actual_ppb == 1942.3

    def test_prior_crossing_suppresses_repeat(self):
        readings = [
            MethaneReading("2026-02-01", 1941.1, "ch4_1"),
            MethaneReading("2026-03-01", 1938.0, "ch4_2"),
            MethaneReading("2026-04-01", 1942.3, "ch4_3"),
        ]
        assert detect_milestone(readings) is None

    def test_state_last_milestone_suppresses_repeat(self):
        readings = [
            MethaneReading("2026-03-01", 1938.0, "ch4_1"),
            MethaneReading("2026-04-01", 1942.3, "ch4_2"),
        ]
        assert detect_milestone(readings, last_milestone=1940) is None

    def test_scoring_passes_low_sensitivity_threshold(self):
        score = score_ch4_milestone(1940, 1942.3)
        assert score.passes
        assert score.category == "ch4_milestone"
        assert score.confidence >= 95


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kwargs):
        return self.response


def test_fetch_ch4_milestones_parses_noaa_text():
    payload = """
# year   month       decimal       average   average_unc         trend     trend_unc
  2026       3      2026.208       1938.00          1.00       1938.50          1.00
  2026       4      2026.292       1942.30          1.00       1941.90          1.00
"""
    with patch("src.data._http._get_session", return_value=_FakeSession(_FakeResponse(payload))):
        readings = fetch_ch4_milestones(strict=True)

    assert [reading.date for reading in readings] == ["2026-03-01", "2026-04-01"]
    assert readings[-1].ppb == 1942.3
