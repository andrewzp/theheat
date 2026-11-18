"""Replay the producer's retained high/low observation set, with invented NOAA bytes."""
from copy import deepcopy
from datetime import UTC, date, datetime

import pytest

from src.data import ghcn
from src.data.ghcn_format import DailyObs
from src.data.ghcn_publication import current_draft_hold
from src.two_bot.intern import build_all_time_record_bundle, build_monthly_high_bundle, build_record_bundle
from tests.ghcn_graphic_helpers import AS_OF, STATION, source_archive
from tests.test_ghcn_publication_currentness import archive_http as archive_http, saved_draft
from tests.test_ghcn_publication_posting import approved_record, run_sender
from tests.test_gist_temperature_posting import (
    fake_transport as fake_transport, invented_clock as invented_clock, state_for,
)


@pytest.fixture(scope="module")
def paired_variants():
    station_id = STATION["station_id"]
    snapshot = ghcn._archive_snapshot(station_id, source_archive(), AS_OF)
    observations = [DailyObs(station_id, date(2026, 9, 8), "TMAX", 42.2),
                    DailyObs(station_id, date(2026, 9, 8), "TMIN", -22.2)]
    thresholds, checked = ghcn._thresholds_from_verified_archive(station_id, observations, snapshot)
    signals = ghcn._detect_signals_for_station(STATION, checked, thresholds)
    assert signals is not None
    result = {}
    for direction in ("high", "low"):
        for tier, builder in (("all_time", build_all_time_record_bundle),
                              ("monthly", build_monthly_high_bundle), ("calendar_date", build_record_bundle)):
            event = getattr(signals, f"{tier}_{direction}")
            assert event is not None
            draft = saved_draft(builder(event, source="ghcn"))
            evidence = draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]
            assert set(evidence["variables"]) == {"TMAX", "TMIN"}
            assert all(scope["candidate_accepted"] is True for scope in evidence["baseline"]["variables"].values())
            result[direction, tier] = draft
    return result


@pytest.mark.parametrize("key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")])
def test_current_source_accepts_real_producer_high_low_set(paired_variants, archive_http, key):
    draft = deepcopy(paired_variants[key])
    original = deepcopy(draft)
    clock = datetime(2026, 9, 9, 12, tzinfo=UTC)
    assert current_draft_hold(draft, now=clock) is None
    assert current_draft_hold(draft, live=True, now=clock) is None
    assert draft == original
    assert len(archive_http["calls"]) == 1 and archive_http["responses"][0].closed


@pytest.mark.parametrize("field,value", [
    ("value_c", -21.2), ("mflag", "X"), ("qflag", "S"), ("sflag", "X"),
    ("observation_time", "1200"), ("source_payload_sha256", "0" * 64),
])
def test_nonclaimed_retained_reading_cannot_supply_forged_context(paired_variants, archive_http, field, value):
    draft = deepcopy(paired_variants["high", "all_time"])
    evidence = draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]
    evidence["variables"]["TMIN"][field] = value
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is not None


def test_erasing_nonclaimed_reading_does_not_erase_its_provenance(paired_variants, archive_http):
    draft = deepcopy(paired_variants["high", "all_time"])
    del draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["variables"]["TMIN"]
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) == "ghcn_retained_source_invalid"


def test_unretained_rejected_original_is_not_invented_to_match_a_flag(archive_http):
    station_id = STATION["station_id"]
    snapshot = ghcn._archive_snapshot(station_id, source_archive(), AS_OF)
    # The source has -22.2. The producer discards this stale -21.2 candidate,
    # retaining its False provenance flag but not its original value. Replaying
    # that unavailable original must remain held, never manufactured or copied.
    observations = [DailyObs(station_id, date(2026, 9, 8), "TMAX", 42.2),
                    DailyObs(station_id, date(2026, 9, 8), "TMIN", -21.2)]
    thresholds, checked = ghcn._thresholds_from_verified_archive(station_id, observations, snapshot)
    signals = ghcn._detect_signals_for_station(STATION, checked, thresholds)
    assert signals is not None and signals.all_time_high is not None
    draft = saved_draft(build_all_time_record_bundle(signals.all_time_high, source="ghcn"))
    assert current_draft_hold(draft, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) == "ghcn_current_comparator_changed"


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
@pytest.mark.parametrize("key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")])
@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_real_senders_replay_high_low_source_before_invented_send(
    paired_variants, fake_transport, archive_http, monkeypatch, key, mode,
):
    draft = approved_record({("high", "all_time"): paired_variants[key]}, mode)
    original = deepcopy(draft)
    state = state_for(draft)
    run_sender(draft, state, mode, monkeypatch)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-receipt"
    assert len(archive_http["calls"]) == 2 and all(row.closed for row in archive_http["responses"])
    fake_transport.safety.assert_called_once_with(original["text"])
    assert fake_transport.calls == [("create", original["text"], {})]
    assert len(fake_transport.persisted) == 1
    assert draft["review_context"] == original["review_context"]
