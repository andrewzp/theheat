"""Tests for NOAA Coral Reef Watch DHW source handling."""

from src.data import coral_dhw
from src.data.coral_dhw import CoralDHWReading, detect_dhw_thresholds, fetch_coral_dhw
from src.editorial.scoring import score_coral_bleaching


def test_detect_dhw_threshold_crosses_highest_new_tier():
    readings = [
        CoralDHWReading(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-05-13",
            dhw_value=8.2,
            stress_level="Alert Level 1",
            baa_7day_max=3,
        )
    ]

    events = detect_dhw_thresholds(readings, {"gbr_northern": 4})

    assert len(events) == 1
    assert events[0].dhw_tier == 8
    assert events[0].bleaching_level == "mass bleaching expected"
    assert events[0].event_id == "coral_dhw_gbr_northern_tier8"


def test_detect_dhw_threshold_dedupes_prior_tier():
    readings = [
        CoralDHWReading(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-05-13",
            dhw_value=8.2,
            stress_level="Alert Level 1",
            baa_7day_max=3,
        )
    ]

    assert detect_dhw_thresholds(readings, {"gbr_northern": 8}) == []


def test_score_coral_bleaching_passes_warning_threshold():
    score = score_coral_bleaching(4.3, 4, "Florida Keys")
    assert score.passes
    assert score.category == "coral_bleaching"
    assert score.threshold == 72


def test_fetch_coral_dhw_uses_index_and_station_byte_ranges(monkeypatch):
    index = """
Latest Data Date: May. 13, 2026
<tr>
  <td><a href="timeseries/great_barrier_reef.php#gbr_northern">Northern GBR</a></td>
  <td style="background-color:#FF0000"><a href="gauges/gbr_northern.php">Alert Level 1</a></td>
  <td><a href="data/gbr_northern.txt">txt</a></td>
</tr>
<tr>
  <td><a href="timeseries/florida.php#florida_keys">Florida Keys</a></td>
  <td style="background-color:#C8FAFA"><a href="gauges/florida_keys.php">No Stress</a></td>
  <td><a href="data/florida_keys.txt">txt</a></td>
</tr>
"""
    tail = """
2026 05 12 27.8300 30.4600 29.6000      3.2680       0.0000    7.9000            2
2026 05 13 28.0800 30.4800 29.7700      3.2560       0.1700    8.2000            3
"""
    head = """
Name:
Northern GBR

Polygon Middle Longitude:
145.9750

Polygon Middle Latitude:
-16.1000
"""
    calls = []

    def fake_fetch_text(url, *, source_name, byte_range=None):
        calls.append((url, byte_range))
        if url.endswith("data.php"):
            return index
        if byte_range == "bytes=-8192":
            return tail
        if byte_range == "bytes=0-2048":
            return head
        raise AssertionError(f"unexpected fetch {url} {byte_range}")

    monkeypatch.setattr(coral_dhw, "_fetch_text", fake_fetch_text)

    readings = fetch_coral_dhw(strict=True)

    assert len(readings) == 1
    assert readings[0].region_id == "gbr_northern"
    assert readings[0].dhw_value == 8.2
    assert readings[0].lat == -16.1
    assert readings[0].lon == 145.975
    assert not any("florida_keys.txt" in url for url, _range in calls)
