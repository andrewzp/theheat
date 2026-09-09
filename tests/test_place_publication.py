"""Offline release-boundary tests: identity migration cannot bypass send safety."""

from copy import deepcopy
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import places, open_meteo
from src.data.place_migration import migrate_cache
from src.orchestrator import posting, draft_save
from tests.revision_helpers import bind_reviewed_draft


OLD_POINT = "alltime_high_Barcelona_2026-09-08"
NEW_POINT = "alltime_high_" + places.event_location_key("Barcelona", "Spain") + "_2026-09-08"
EVENT_PAIRS = [
    (OLD_POINT, NEW_POINT),
    ("country_high_Thailand_2026-09-08", "country_high_TH_2026-09-08"),
    ("country_low_United_Arab_Emirates_2026-09-08", "country_low_AE_2026-09-08"),
    ("gpm_precip_country_thailand_2026-09-08", "gpm_precip_country_th_2026-09-08"),
]


@pytest.fixture
def externals(monkeypatch):
    importlib.reload(posting)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "p04-test-release-one")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    monkeypatch.setenv("THEHEAT_MIN_TWEET_SPACING_MIN", "0")
    mocks = {}
    for name, result in [
        ("post_tweet", {"id": "receipt"}),
        ("post_to_bluesky", None),
        ("run_safety_pipeline", (True, None)),
    ]:
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(posting, name, mocks[name])
    mocks["write"] = Mock(return_value=True)
    monkeypatch.setattr(posting.state, "write_state", mocks["write"])
    return mocks


def approved(event_id=NEW_POINT, mode="auto"):
    return bind_reviewed_draft(
        {
            "id": "current",
            "event_id": event_id,
            "text": "Barcelona reached 40°C.",
            "status": "pending",
            "auto_approve_at": "2020-01-01T00:00:00Z",
            "approval_policy": {"mode": "armed_auto", "can_auto_approve": True},
            "review_context": {
                "two_bot": {
                    "bundle": {
                        "raw_signal_dump": {
                            "city": "Barcelona",
                            "country": "Spain",
                            **places.event_identity(event_id),
                        }
                    }
                }
            },
        },
        mode,
        "manual-intent" if mode == "manual" else None,
    )


@pytest.mark.parametrize("path", ["direct", "due"])
@pytest.mark.parametrize(
    "event_id",
    [
        OLD_POINT,
        "country_high_Thailand_2026-09-08",
        "gpm_precip_thailand_bangkok_2026-09-08",
        "hot10_2026-09-08",
    ],
)
def test_legacy_auto_evidence_blocked_even_with_current_review_and_epoch(externals, path, event_id):
    item = approved(event_id)
    evidence = deepcopy(item["review_context"])
    bot_state = {"drafts": [item], "publish_ledger": {}}
    if path == "direct":
        assert posting.post_approved(item, bot_state) == "failed"
    else:
        posting.process_due_drafts(bot_state)
    assert "identity review" in item["post_error"]
    assert item["review_context"] == evidence
    assert bot_state["publish_ledger"] == {}
    for mock in externals.values():
        mock.assert_not_called()


@pytest.mark.parametrize("path", ["direct", "due"])
def test_canonical_current_epoch_can_publish_through_real_sender(externals, path):
    item = approved()
    bot_state = {"drafts": [item], "publish_ledger": {}}
    if path == "direct":
        assert posting.post_approved(item, bot_state) == "posted"
    else:
        posting.process_due_drafts(bot_state)
    externals["post_tweet"].assert_called_once_with(item["text"], media_png=None, alt_text=None)
    assert bot_state["publish_ledger"][NEW_POINT]["tweet_id"] == "receipt"
    externals["write"].assert_called_once()
    assert externals["write"].call_args.kwargs["expected_draft"]["event_id"] == NEW_POINT


def test_canonical_identity_does_not_bypass_retired_release(externals, monkeypatch):
    item = approved()
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "p04-test-release-two")
    assert posting.post_approved(item, {"drafts": [item]}) == "failed"
    assert "release epoch" in item["post_error"]
    for mock in externals.values():
        mock.assert_not_called()


@pytest.mark.parametrize("old,new", EVENT_PAIRS)
@pytest.mark.parametrize("shape", ["ledger", "draft", "conflict"])
def test_unresolved_legacy_attempts_block_candidate_without_posted_events(old, new, shape):
    legacy = {
        "id": "old",
        "event_id": old,
        "status": "pending",
        "text": "Original uncertain text",
        "publish_outcome": "unknown",
        "autoship_attempted": True,
    }
    unknown = {"phase": "unknown", "text": legacy["text"], "intent_id": "old-intent"}
    bot_state = {
        "posted_events": [],
        "drafts": [legacy] if shape == "draft" else [],
        "publish_ledger": {old: unknown}
        if shape == "ledger"
        else {old: {"phase": "confirmed", "tweet_id": "receipt", "attempt_conflicts": [unknown]}}
        if shape == "conflict"
        else {},
    }
    original = deepcopy(bot_state)
    assert places.legacy_publication_status(bot_state, new) == "unresolved"
    assert draft_save.can_draft_candidate(bot_state, SimpleNamespace(event_id=new)) == (
        False,
        "legacy_publish_unresolved",
    )
    assert not draft_save.save_draft("New text", bot_state, "all_time_high", new)
    assert bot_state == original


@pytest.mark.parametrize("old,new", EVENT_PAIRS)
@pytest.mark.parametrize("mode", ["auto", "manual", "due"])
def test_final_and_due_paths_preserve_unknown_legacy_receipts_and_refuse_send(
    externals, old, new, mode
):
    item = approved(new, "manual" if mode == "manual" else "auto")
    legacy = {
        "id": "old",
        "event_id": old,
        "status": "pending",
        "text": "Original uncertain text",
        "publish_outcome": "unknown",
        "autoship_attempted": True,
    }
    ledger = {old: {"phase": "unknown", "text": legacy["text"], "intent_id": "old-intent"}}
    bot_state = {"drafts": [legacy, item], "publish_ledger": deepcopy(ledger), "posted_events": []}
    prior = deepcopy(legacy)
    if mode == "due":
        posting.process_due_drafts(bot_state)
    else:
        assert posting.post_approved(item, bot_state) == "failed"
    assert "unresolved" in item["post_error"]
    assert bot_state["publish_ledger"] == ledger
    assert legacy == prior
    for mock in externals.values():
        mock.assert_not_called()


@pytest.mark.parametrize("old,new", EVENT_PAIRS[1:])
@pytest.mark.parametrize("shape", ["posted_events", "ledger"])
def test_country_alias_confirmed_receipts_suppress_duplicate_without_draft(old, new, shape):
    bot_state = {
        "posted_events": [old] if shape == "posted_events" else [],
        "publish_ledger": {old: {"phase": "confirmed", "tweet_id": "receipt"}}
        if shape == "ledger"
        else {},
    }
    original = deepcopy(bot_state)
    assert places.legacy_publication_status(bot_state, new) == "duplicate"
    assert not draft_save.can_draft_candidate(bot_state, SimpleNamespace(event_id=new))[0]
    assert bot_state == original


def test_known_not_sent_legacy_attempt_does_not_block_or_relabel():
    bot_state = {"publish_ledger": {OLD_POINT: {"phase": "not_sent"}}}
    assert places.legacy_publication_status(bot_state, NEW_POINT) == "clear"


def test_runtime_unregistered_inventory_round_trips_to_budget_selection(tmp_path):
    path = tmp_path / "cities.csv"
    path.write_text("city,country,lat,lon\nNew Example Place,US,40.123,-100.123\n")
    loaded = places.load_cities(str(path))
    assert loaded[0]["place_id"].startswith("ux")
    assert open_meteo.select_world_budget_cities(loaded) == loaded
    assert places.place_for_row(loaded[0])["place_id"] == loaded[0]["place_id"]
    with pytest.raises(ValueError, match="conflicts"):
        places.place_for_row({**loaded[0], "lat": 41})


@pytest.mark.parametrize(
    "field", ["place_id", "sampling_point_id", "city", "country", "country_code", "source_product"]
)
@pytest.mark.parametrize("value", [None, 3, [], {}, False])
def test_malformed_cache_identity_types_quarantine_idempotently(field, value):
    place = places.resolve_place("Barcelona", "Spain")
    key = places.cache_key("Barcelona", "Spain")
    row = {
        "identity": {**place, "source_product": places.CACHE_PRODUCT},
        "all_time_max": [45, 2020],
    }
    row["identity"][field] = value
    original = deepcopy(row)
    once = migrate_cache({key: row})
    assert set(once) == {"_meta"}
    assert once["_meta"]["quarantined_count"] == 1
    assert once == migrate_cache(once)
    assert next(iter(once["_meta"]["identity_quarantine"].values()))["entry"] == original
    assert row == original


@pytest.mark.parametrize("old,new", EVENT_PAIRS[1:])
@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_confirmed_country_alias_refused_by_final_sender(externals, old, new, mode):
    item = approved(new, mode)
    ledger = {old: {"phase": "confirmed", "tweet_id": "original-receipt", "text": "Published text"}}
    original = deepcopy(ledger)
    assert posting.post_approved(item, {"drafts": [item], "publish_ledger": ledger}) == "failed"
    assert "already published" in item["post_error"]
    assert ledger == original
    for mock in externals.values():
        mock.assert_not_called()


def test_valid_unregistered_cache_row_survives_migration():
    place = places.resolve_place("New Example Place", "US", 40.123, -100.123)
    key = places.cache_key(place["city"], place["country"], place["lat"], place["lon"])
    row = {"identity": {**place, "source_product": places.CACHE_PRODUCT}}
    result = migrate_cache({key: row})
    assert result[key] == row
    assert result["_meta"]["cached_count"] == 1


@pytest.mark.parametrize(
    "row", [None, [], {"phase": "confirmed", "tweet_id": "receipt", "attempt_conflicts": [None]}]
)
def test_malformed_retained_legacy_attempt_cannot_be_cleared(row):
    assert (
        places.legacy_publication_status({"publish_ledger": {OLD_POINT: row}}, NEW_POINT)
        == "unresolved"
    )
