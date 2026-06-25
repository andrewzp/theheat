"""Tests for coverage_log state helpers (Task 3).

Tests for: record_coverage_observation, _merge_coverage_log, COVERAGE_WINDOW_DAYS,
and SQLite round-trip persistence of coverage_log.
"""

import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

from src import state as state_mod
from src.state import DEFAULT_STATE, _fresh_state, record_coverage_observation


def _now(d: str = "2026-06-25") -> datetime:
    return datetime.fromisoformat(d + "T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Unit tests for record_coverage_observation
# ---------------------------------------------------------------------------


def test_record_appends_with_resolved_continent():
    s = _fresh_state()
    record_coverage_observation(
        s,
        cls="heat",
        event_id="e1",
        country="United States",
        when="2026-06-25",
        now=_now(),
    )
    assert s["coverage_log"] == [
        {
            "cls": "heat",
            "event_id": "e1",
            "country": "United States",
            "continent": "North America",
            "date": "2026-06-25",
        }
    ]


def test_record_dedups_on_event_id():
    s = _fresh_state()
    for _ in range(2):
        record_coverage_observation(
            s, cls="heat", event_id="e1", country="Spain", when="2026-06-25", now=_now()
        )
    assert len(s["coverage_log"]) == 1


def test_record_prunes_older_than_window():
    s = _fresh_state()
    record_coverage_observation(
        s, cls="heat", event_id="old", country="Spain", when="2026-05-01", now=_now()
    )
    record_coverage_observation(
        s, cls="heat", event_id="new", country="Spain", when="2026-06-25", now=_now()
    )
    assert {r["event_id"] for r in s["coverage_log"]} == {"new"}


def test_record_never_raises_on_bad_input():
    s = _fresh_state()
    record_coverage_observation(s, cls="heat", event_id="e1", country=None, when=None)
    assert s["coverage_log"][0]["continent"] == "Unknown"


def test_merge_dedups_concurrent_writers():
    a = [
        {
            "cls": "heat",
            "event_id": "e1",
            "country": "US",
            "continent": "North America",
            "date": "2026-06-25",
        }
    ]
    b = a + [
        {
            "cls": "heat",
            "event_id": "e2",
            "country": "Spain",
            "continent": "Europe",
            "date": "2026-06-25",
        }
    ]
    result = state_mod._merge_coverage_log(a, b)
    assert {r["event_id"] for r in result} == {"e1", "e2"}


# ---------------------------------------------------------------------------
# SQLite round-trip test — mirrors test_sst_anom_dedup_keys_survive_sqlite_round_trip
# ---------------------------------------------------------------------------


def test_coverage_log_survives_sqlite_round_trip():
    """coverage_log must be listed in _METADATA_JSON_KEYS to survive save→load."""
    from src.state import write_state, read_state

    sample_record = {
        "cls": "heat",
        "event_id": "rt_e1",
        "country": "Australia",
        "continent": "Oceania",
        "date": "2026-06-25",
    }
    sample = {
        **DEFAULT_STATE,
        "coverage_log": [sample_record],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/theheat.sqlite"

        with patch.multiple(
            "src.state",
            STATE_BACKEND="sqlite",
            DB_PATH=db_path,
            GIST_ID="",
            GITHUB_TOKEN="",
        ):
            assert write_state(sample) is True
            loaded = read_state()

    assert loaded["coverage_log"] == [sample_record]
