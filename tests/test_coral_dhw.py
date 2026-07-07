"""Tests for NOAA Coral Reef Watch DHW source handling."""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from src.data import coral_dhw
from src.data._witness import tag_source_leg
from src.data.coral_dhw import CoralBleachingEvent, CoralDHWReading, detect_dhw_thresholds, fetch_coral_dhw
from src.data.source_status import SourceFetchError
from src.editorial.scoring import score_coral_bleaching
from src.state import DEFAULT_STATE
from src.two_bot.types import StoryBundle


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
    # Build dates dynamically so the freshness check (max_age_days=5 by default)
    # passes regardless of when CI runs. Previously hardcoded to 2026-05-13,
    # which began failing every cron after 2026-05-18 because `assert_freshness`
    # (added by the Codex source-hardening pass) rejected anything > 5 days old.
    today = date.today()
    yesterday = today - timedelta(days=1)
    index = f"""
Latest Data Date: {today:%b}. {today.day}, {today.year}
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
    tail = f"""
{yesterday.year} {yesterday.month:02d} {yesterday.day:02d} 27.8300 30.4600 29.6000      3.2680       0.0000    7.9000            2
{today.year} {today.month:02d} {today.day:02d} 28.0800 30.4800 29.7700      3.2560       0.1700    8.2000            3
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


def test_coral_primary_healthy_skips_erddap(monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)
    index = f"""
Latest Data Date: {today:%b}. {today.day}, {today.year}
<tr>
  <td><a href="timeseries/great_barrier_reef.php#gbr_northern">Northern GBR</a></td>
  <td style="background-color:#FF0000"><a href="gauges/gbr_northern.php">Alert Level 1</a></td>
  <td><a href="data/gbr_northern.txt">txt</a></td>
</tr>
"""
    tail = f"""
{yesterday.year} {yesterday.month:02d} {yesterday.day:02d} 27.8300 30.4600 29.6000      3.2680       0.0000    7.9000            2
{today.year} {today.month:02d} {today.day:02d} 28.0800 30.4800 29.7700      3.2560       0.1700    8.2000            3
"""
    head = """
Name:
Northern GBR

Polygon Middle Longitude:
145.9750

Polygon Middle Latitude:
-16.1000
"""

    def fake_fetch_text(url, *, source_name, byte_range=None):
        if url.endswith("data.php"):
            return index
        if byte_range == "bytes=-8192":
            return tail
        if byte_range == "bytes=0-2048":
            return head
        raise AssertionError(f"unexpected fetch {url} {byte_range}")

    monkeypatch.setattr(coral_dhw, "_fetch_text", fake_fetch_text)
    monkeypatch.setattr(
        coral_dhw,
        "_fetch_coral_dhw_erddap",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("witness should not be called")),
    )

    readings = fetch_coral_dhw(strict=True)

    assert readings
    assert all(reading.source_leg is None for reading in readings)


def test_coral_erddap_station_coord_mapping():
    station = coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"]

    assert station.region_full_name == "Northern GBR"
    assert station.lat == -16.1
    assert station.lon == 145.975


def test_coral_erddap_point_fetch_is_bounded(monkeypatch):
    calls = []

    class Response:
        text = "time,latitude,longitude,degree_heating_week\n"

    def fake_fetch_with_retry(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(coral_dhw, "fetch_with_retry", fake_fetch_with_retry)

    coral_dhw._fetch_erddap_csv(coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"])

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert "degree_heating_week%5B(last)%5D%5B(-16.1)%5D%5B(145.975)%5D" in url
    assert kwargs["timeout"] == 20
    assert kwargs["attempts"] == 1


def test_coral_erddap_parses_fixture():
    today = date.today()
    csv_text = f"""time,latitude,longitude,degree_heating_week
UTC,degrees_north,degrees_east,degree_Celsius_weeks
{today.isoformat()}T12:00:00Z,-16.075,145.975,8.34
"""

    reading = coral_dhw._reading_from_erddap_csv(
        csv_text,
        coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"],
        max_age_days=5,
    )

    assert reading == CoralDHWReading(
        region_id="gbr_northern",
        region_full_name="Northern GBR",
        date=today.isoformat(),
        dhw_value=8.3,
        stress_level="Bleaching Alert Level 2",
        baa_7day_max=None,
        lat=-16.075,
        lon=145.975,
    )


@pytest.mark.parametrize(
    ("dhw", "expected"),
    [
        # Below the bleaching floor.
        (0.0, "No Stress"),
        (3.9, "No Stress"),
        # NOAA Coral Reef Watch Bleaching Alert Levels (matches
        # fact_check_prompt.py:25 — 4→L1, 8→L2, 12→L3, 16→L4, 20→L5).
        (4.0, "Bleaching Alert Level 1"),
        (7.9, "Bleaching Alert Level 1"),
        (8.0, "Bleaching Alert Level 2"),
        (11.9, "Bleaching Alert Level 2"),
        (12.0, "Bleaching Alert Level 3"),
        (15.9, "Bleaching Alert Level 3"),
        (16.0, "Bleaching Alert Level 4"),
        (19.9, "Bleaching Alert Level 4"),
        (20.0, "Bleaching Alert Level 5"),
        (25.0, "Bleaching Alert Level 5"),  # scale tops out at Level 5
    ],
)
def test_stress_level_for_dhw_full_noaa_scale(dhw, expected):
    # #403: _stress_level_for_dhw once capped at "Bleaching Alert Level 2",
    # under-labeling any reading >=12 C-weeks that NOAA (and the bot's own
    # fact-check prompt) puts at Alert Level 3/4/5.
    assert coral_dhw._stress_level_for_dhw(dhw) == expected


def test_coral_erddap_accepts_documented_grid_lag():
    lagged = date.today() - timedelta(days=6)
    csv_text = f"""time,latitude,longitude,degree_heating_week
UTC,degrees_north,degrees_east,degree_Celsius_weeks
{lagged.isoformat()}T12:00:00Z,-16.075,145.975,8.34
"""

    reading = coral_dhw._reading_from_erddap_csv(
        csv_text,
        coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"],
        max_age_days=5,
    )

    assert reading.date == lagged.isoformat()


def test_coral_erddap_nan_cell_raises_source_fetch_error():
    today = date.today()
    csv_text = f"""time,latitude,longitude,degree_heating_week
UTC,degrees_north,degrees_east,degree_Celsius_weeks
{today.isoformat()}T12:00:00Z,-16.075,145.975,NaN
"""

    with pytest.raises(SourceFetchError, match="non-finite"):
        coral_dhw._reading_from_erddap_csv(
            csv_text,
            coral_dhw.CRW_ERDDAP_STATIONS["gbr_northern"],
            max_age_days=5,
        )


def test_coral_falls_back_to_erddap_when_primary_raises(monkeypatch):
    witness_readings = tag_source_leg(
        [
            CoralDHWReading(
                region_id="gbr_northern",
                region_full_name="Northern GBR",
                date=date.today().isoformat(),
                dhw_value=8.3,
                stress_level="Bleaching Alert Level 2",
                baa_7day_max=None,
                lat=-16.075,
                lon=145.975,
            )
        ],
        "crw_erddap",
    )
    monkeypatch.setattr(
        coral_dhw,
        "_fetch_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(SourceFetchError("coral_dhw down")),
    )
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", lambda **kwargs: witness_readings)

    readings = fetch_coral_dhw(strict=True)

    assert readings == witness_readings
    assert readings[0].source_leg == "crw_erddap"


def test_detect_dhw_thresholds_propagates_coral_witness_source_leg():
    readings = [
        CoralDHWReading(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-06-08",
            dhw_value=8.3,
            stress_level="Bleaching Alert Level 2",
            baa_7day_max=None,
            lat=-16.075,
            lon=145.975,
            source_leg="crw_erddap",
        )
    ]

    events = detect_dhw_thresholds(readings, {})

    assert events
    assert events[0].source_leg == "crw_erddap"


def test_coral_erddap_bundle_marks_observed_alt_host():
    from src.two_bot.intern import build_coral_bleaching_bundle

    bundle = build_coral_bleaching_bundle(
        CoralBleachingEvent(
            region_id="gbr_northern",
            region_full_name="Northern GBR",
            date="2026-06-08",
            dhw_value=8.3,
            dhw_tier=8,
            bleaching_level="mass bleaching expected",
            stress_level="Bleaching Alert Level 2",
            lat=-16.075,
            lon=145.975,
            event_id="coral_dhw_gbr_northern_tier8",
            source_leg="crw_erddap",
        )
    )

    assert {"label": "evidence_grade", "value": "observed_alt_host"} in bundle.current_facts


def test_run_coral_dhw_records_degraded_when_erddap_served(fresh_state, monkeypatch):
    from src.orchestrator.sources import coral_dhw as runner

    readings = tag_source_leg(
        [
            CoralDHWReading(
                region_id="gbr_northern",
                region_full_name="Northern GBR",
                date=date.today().isoformat(),
                dhw_value=8.3,
                stress_level="Bleaching Alert Level 2",
                baa_7day_max=None,
                lat=-16.075,
                lon=145.975,
            )
        ],
        "crw_erddap",
    )
    monkeypatch.setattr(runner, "_fetch_strict", lambda *args, **kwargs: readings)
    monkeypatch.setattr(runner.coral_dhw, "detect_dhw_thresholds", lambda readings, last_tiers: [])

    current_run = {"sources": []}
    runner.run_coral_dhw(fresh_state, current_run)

    row = next(item for item in current_run["sources"] if item["source"] == "coral_dhw")
    assert row["status"] == "degraded"
    assert row["note"] == "served via crw_erddap"


# ---------------------------------------------------------------------------
# Source-runner migration tests — verify coral_dhw enqueues, not direct-calls
# ---------------------------------------------------------------------------

def _make_coral_event(
    region_id: str = "gbr_northern",
    region_full_name: str = "Northern GBR",
    dhw_value: float = 8.2,
    dhw_tier: int = 8,
    event_id: str = "coral_dhw_gbr_northern_tier8",
) -> CoralBleachingEvent:
    return CoralBleachingEvent(
        region_id=region_id,
        region_full_name=region_full_name,
        date="2026-05-17",
        dhw_value=dhw_value,
        dhw_tier=dhw_tier,
        bleaching_level="mass bleaching expected",
        stress_level="Alert Level 1",
        lat=-16.1,
        lon=145.975,
        event_id=event_id,
    )


def _make_reading(
    region_id: str = "gbr_northern",
    region_full_name: str = "Northern GBR",
    dhw_value: float = 8.2,
) -> CoralDHWReading:
    return CoralDHWReading(
        region_id=region_id,
        region_full_name=region_full_name,
        date="2026-05-17",
        dhw_value=dhw_value,
        stress_level="Alert Level 1",
        baa_7day_max=3,
        lat=-16.1,
        lon=145.975,
    )


def _make_bundle(event: CoralBleachingEvent) -> StoryBundle:
    return StoryBundle(
        signal_kind="coral_bleaching",
        where=event.region_full_name,
        when=event.date,
        event_id=event.event_id,
        headline_metric={"label": "Degree heating weeks", "value": event.dhw_value, "unit": "C-weeks"},
        current_facts=[
            {"label": "Region", "value": event.region_full_name},
            {"label": "DHW", "value": f"{event.dhw_value:.1f} C-weeks"},
            {"label": "Source", "value": "NOAA Coral Reef Watch"},
        ],
        raw_signal_dump={
            "source": "NOAA Coral Reef Watch",
            "region_id": event.region_id,
            "dhw_value": event.dhw_value,
        },
    )


class TestCoralDHWSourceRunnerMigration:
    """Verify that run_coral_dhw enqueues TriageCandidateBundles instead of
    calling _try_two_bot_draft directly (the triage migration pattern).

    These tests exercise the migrated source runner in isolation — they do NOT
    go through run_alerts. The key invariant: passing-score events become
    entries in bot_state['_triage_queue'], not immediate writer calls.
    """

    def test_single_passing_event_enqueues_not_drafts(self, monkeypatch):
        """A single event that passes the editorial score gate goes to the
        triage queue, NOT to _try_two_bot_draft directly.
        """
        from src.orchestrator.sources.coral_dhw import run_coral_dhw
        from src.two_bot.types import TriageCandidateBundle

        bot_state = deepcopy(DEFAULT_STATE)
        event = _make_coral_event()
        reading = _make_reading()

        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.fetch_coral_dhw",
            lambda **kw: [reading],
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.detect_dhw_thresholds",
            lambda readings, last_tiers: [event],
        )
        # Intercept bundle build so we don't need the full intern pipeline
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.build_coral_bleaching_bundle",
            _make_bundle,
        )

        # _try_two_bot_draft must NOT be called
        draft_called = []
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw._try_two_bot_draft",
            lambda *a, **kw: draft_called.append(1) or True,
        )

        current_run = {"sources": []}
        run_coral_dhw(bot_state, current_run)

        # No direct draft call
        assert draft_called == [], "Expected no _try_two_bot_draft call; candidate should be enqueued"

        # Candidate in queue
        queue = bot_state.get("_triage_queue", [])
        assert len(queue) == 1
        candidate = queue[0]
        assert isinstance(candidate, TriageCandidateBundle)
        assert candidate.source == "coral_dhw"
        assert candidate.legacy_type == "coral_bleaching"
        assert candidate.event_id == event.event_id
        assert candidate.cooldown_exempt is False
        assert candidate.created_at  # iso8601 string — must be non-empty

    def test_run_coral_dhw_records_marine_synthesis_component(self, monkeypatch):
        from src.orchestrator.sources.coral_dhw import run_coral_dhw

        bot_state = deepcopy(DEFAULT_STATE)
        event = _make_coral_event(region_id="fiji", region_full_name="Fiji", event_id="coral_dhw_fiji_tier8")
        reading = _make_reading(region_id="fiji", region_full_name="Fiji")

        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.fetch_coral_dhw",
            lambda **kw: [reading],
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.detect_dhw_thresholds",
            lambda readings, last_tiers: [event],
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.build_coral_bleaching_bundle",
            _make_bundle,
        )

        run_coral_dhw(bot_state, {"sources": []})

        component = bot_state["synthesis_components"]["corals"]["fiji"][0]
        assert component["event_id"] == "coral_dhw_fiji_tier8"
        assert component["dhw_tier"] == 8
        assert component["dhw_value"] == 8.2
        assert bot_state["coral_dhw_last_tier"] == {}

    def test_multiple_passing_events_each_enqueue(self, monkeypatch):
        """N passing events → N TriageCandidateBundles in the queue."""
        from src.orchestrator.sources.coral_dhw import run_coral_dhw
        from src.two_bot.types import TriageCandidateBundle

        bot_state = deepcopy(DEFAULT_STATE)
        events = [
            _make_coral_event(region_id=f"region_{i}", event_id=f"coral_dhw_region_{i}_tier8")
            for i in range(3)
        ]
        readings = [_make_reading(region_id=f"region_{i}") for i in range(3)]

        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.fetch_coral_dhw",
            lambda **kw: readings,
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.detect_dhw_thresholds",
            lambda readings, last_tiers: events,
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.build_coral_bleaching_bundle",
            _make_bundle,
        )

        current_run = {"sources": []}
        run_coral_dhw(bot_state, current_run)

        queue = bot_state.get("_triage_queue", [])
        assert len(queue) == 3
        for candidate in queue:
            assert isinstance(candidate, TriageCandidateBundle)
            assert candidate.source == "coral_dhw"

    def test_run_records_promoted_count_correctly(self, monkeypatch):
        """The source_run record shows promoted=N even when drafting is deferred."""
        from src.orchestrator.sources.coral_dhw import run_coral_dhw

        bot_state = deepcopy(DEFAULT_STATE)
        events = [
            _make_coral_event(region_id=f"region_{i}", event_id=f"coral_dhw_region_{i}_tier8")
            for i in range(2)
        ]
        readings = [_make_reading(region_id=f"region_{i}") for i in range(2)]

        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.fetch_coral_dhw",
            lambda **kw: readings,
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.detect_dhw_thresholds",
            lambda readings, last_tiers: events,
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.build_coral_bleaching_bundle",
            _make_bundle,
        )

        current_run = {"sources": []}
        run_coral_dhw(bot_state, current_run)

        source_entry = next(
            (s for s in current_run["sources"] if s["source"] == "coral_dhw"), None
        )
        assert source_entry is not None
        assert source_entry["promoted"] == 2

    def test_enqueue_does_not_update_tier_until_on_draft_success_fires(self, monkeypatch):
        """Tier updates and the annual count are gated on on_draft_success
        firing — NOT on enqueue. This preserves the spec § 7 contract:
        triage-spilled candidates re-detect on the next cron because the
        source's "cooldown" (tier update) is gated on actually drafting.
        """
        from src.orchestrator.sources.coral_dhw import run_coral_dhw

        bot_state = deepcopy(DEFAULT_STATE)
        event = _make_coral_event(region_id="gbr_northern", dhw_tier=8)
        reading = _make_reading(region_id="gbr_northern")

        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.fetch_coral_dhw",
            lambda **kw: [reading],
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.coral_dhw.detect_dhw_thresholds",
            lambda readings, last_tiers: [event],
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.coral_dhw.build_coral_bleaching_bundle",
            _make_bundle,
        )

        current_run = {"sources": []}
        run_coral_dhw(bot_state, current_run)

        # After enqueue but BEFORE on_draft_success fires, the tier must
        # NOT be in coral_dhw_last_tier — a spilled candidate must be
        # re-detectable on the next cron.
        last_tiers = bot_state.get("coral_dhw_last_tier", {})
        assert "gbr_northern" not in last_tiers or last_tiers.get("gbr_northern") != 8, (
            "Tier was updated on enqueue — spilled candidates will not re-detect "
            "on next cron, violating spec § 7"
        )

        # Now simulate the drain step firing the on_draft_success callback
        # for the enqueued candidate.
        queue = bot_state["_triage_queue"]
        assert len(queue) == 1
        candidate = queue[0]
        assert candidate.on_draft_success is not None
        candidate.on_draft_success()

        # After the callback fires, tier IS updated.
        last_tiers = bot_state.get("coral_dhw_last_tier", {})
        assert last_tiers.get("gbr_northern") == 8, (
            "Tier should be updated after on_draft_success fires"
        )
        # And annual count incremented (counts dict is keyed by year string).
        from datetime import date
        year = str(date.today().year)
        counts = bot_state.get("coral_dhw_annual_count", {})
        assert counts.get(year, 0) >= 1, (
            "Annual count should be incremented after on_draft_success"
        )


class TestDrainTelemetry:
    """Verify _drain_and_write_triage_queue correctly credits per-source drafted
    counters after survivors are written.

    This is the I2 telemetry gap from PR #132. Without this fix, migrated
    sources show drafted=0 in the dashboard even when their candidates ship.
    """

    def test_successful_draft_increments_source_drafted_counter(self, monkeypatch):
        """After drain: existing coral_dhw source run entry gets drafted incremented."""
        from src.orchestrator import common

        bot_state = deepcopy(DEFAULT_STATE)

        # Simulate the source run record that coral_dhw writes before drain
        current_run = {
            "sources": [
                {
                    "source": "coral_dhw",
                    "status": "success",
                    "observed": 2,
                    "promoted": 1,
                    "drafted": 0,  # written by source runner before triage drain
                    "error": None,
                    "note": None,
                    "duration_ms": 100,
                }
            ]
        }

        from src.two_bot.types import TriageCandidateBundle, StoryBundle
        from src.editorial.scoring._shared import EditorialScore

        bundle = StoryBundle(
            signal_kind="coral_bleaching",
            where="Northern GBR",
            when="2026-05-17",
            event_id="coral_dhw_gbr_northern_tier8",
            headline_metric={"label": "DHW", "value": 8},
            current_facts=[],
        )
        score = EditorialScore(
            category="coral_bleaching",
            severity=80, novelty=80, timeliness=80, confidence=80,
            shareability=80, sensitivity=0, total=80, threshold=60, reasons=[],
        )
        candidate = TriageCandidateBundle(
            bundle=bundle, score=score,
            event_id="coral_dhw_gbr_northern_tier8",
            source="coral_dhw",
            review_context={},
            city="", tweet_date="2026-05-17",
            cooldown_exempt=False,
            legacy_type="coral_bleaching",
            created_at="2026-05-17T12:00:00Z",
        )
        bot_state["_triage_queue"] = [candidate]

        # _try_two_bot_draft returns True (draft saved)
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda *a, **kw: True,
        )
        # Triage disabled so all candidates pass through
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")

        common._drain_and_write_triage_queue(bot_state, current_run)

        source_entry = next(
            (s for s in current_run["sources"] if s["source"] == "coral_dhw"), None
        )
        assert source_entry is not None, "Expected coral_dhw entry in current_run['sources']"
        assert source_entry["drafted"] == 1, (
            f"Expected drafted=1 after successful triage drain, got {source_entry['drafted']}"
        )

    def test_failed_draft_does_not_increment_source_drafted_counter(self, monkeypatch):
        """If _try_two_bot_draft returns False, drafted counter stays at 0."""
        from src.orchestrator import common

        bot_state = deepcopy(DEFAULT_STATE)
        current_run = {
            "sources": [
                {
                    "source": "coral_dhw",
                    "status": "success",
                    "observed": 1,
                    "promoted": 1,
                    "drafted": 0,
                    "error": None,
                    "note": None,
                    "duration_ms": 50,
                }
            ]
        }

        from src.two_bot.types import TriageCandidateBundle, StoryBundle
        from src.editorial.scoring._shared import EditorialScore

        bundle = StoryBundle(
            signal_kind="coral_bleaching", where="Test", when="2026-05-17",
            event_id="evt_fail", headline_metric={"label": "DHW", "value": 4},
            current_facts=[],
        )
        score = EditorialScore(
            category="coral_bleaching",
            severity=75, novelty=75, timeliness=75, confidence=75,
            shareability=75, sensitivity=0, total=75, threshold=60, reasons=[],
        )
        candidate = TriageCandidateBundle(
            bundle=bundle, score=score, event_id="evt_fail",
            source="coral_dhw", review_context={}, city="", tweet_date="2026-05-17",
            cooldown_exempt=False, legacy_type="coral_bleaching",
            created_at="2026-05-17T11:00:00Z",
        )
        bot_state["_triage_queue"] = [candidate]

        # _try_two_bot_draft returns False (draft rejected)
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda *a, **kw: False,
        )
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")

        common._drain_and_write_triage_queue(bot_state, current_run)

        source_entry = next(
            (s for s in current_run["sources"] if s["source"] == "coral_dhw"), None
        )
        assert source_entry["drafted"] == 0, (
            f"Expected drafted=0 after failed draft, got {source_entry['drafted']}"
        )

    def test_multiple_candidates_same_source_accumulate_drafted(self, monkeypatch):
        """Two survivors from coral_dhw that both draft → drafted=2."""
        from src.orchestrator import common

        bot_state = deepcopy(DEFAULT_STATE)
        current_run = {
            "sources": [
                {
                    "source": "coral_dhw",
                    "status": "success",
                    "observed": 3,
                    "promoted": 2,
                    "drafted": 0,
                    "error": None,
                    "note": None,
                    "duration_ms": 200,
                }
            ]
        }

        from src.two_bot.types import TriageCandidateBundle, StoryBundle
        from src.editorial.scoring._shared import EditorialScore

        def _make_candidate(event_id: str, total: int) -> TriageCandidateBundle:
            b = StoryBundle(
                signal_kind="coral_bleaching", where="GBR", when="2026-05-17",
                event_id=event_id, headline_metric={"label": "DHW", "value": 8},
                current_facts=[],
            )
            s = EditorialScore(
                category="coral_bleaching",
                severity=total, novelty=total, timeliness=total, confidence=total,
                shareability=total, sensitivity=0, total=total, threshold=60, reasons=[],
            )
            return TriageCandidateBundle(
                bundle=b, score=s, event_id=event_id, source="coral_dhw",
                review_context={}, city="", tweet_date="2026-05-17",
                cooldown_exempt=False, legacy_type="coral_bleaching",
                created_at="2026-05-17T12:00:00Z",
            )

        bot_state["_triage_queue"] = [
            _make_candidate("evt_a", 90),
            _make_candidate("evt_b", 85),
        ]

        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda *a, **kw: True,
        )
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")

        common._drain_and_write_triage_queue(bot_state, current_run)

        source_entry = next(
            (s for s in current_run["sources"] if s["source"] == "coral_dhw"), None
        )
        assert source_entry["drafted"] == 2
