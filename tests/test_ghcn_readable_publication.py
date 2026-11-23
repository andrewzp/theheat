"""Real retained/source/sender consumers with complete readable invented warrants."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.data.ghcn_publication import current_draft_hold
from src.two_bot.candidate_derivation import retained_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.ghcn_readable_warrant import encode_full
from src.two_bot.types import StoryBundle
from tests.test_ghcn_publication_currentness import archive_http as archive_http
from tests.test_ghcn_publication_observation_set import paired_variants as paired_variants
from tests.test_ghcn_publication_posting import approved_record, run_sender
from tests import test_ghcn_publication_posting as posting_cases
from tests.test_gist_temperature_posting import (
    fake_transport as fake_transport,
    invented_clock as invented_clock,
    state_for,
)


KEYS = [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar_date")]


@pytest.fixture(scope="module")
def readable_variants(paired_variants):
    result = {}
    for key, original in paired_variants.items():
        draft = deepcopy(original)
        draft["review_context"]["two_bot"]["bundle"] = encode_full(
            original["review_context"]["two_bot"]["bundle"]
        )
        result[key] = draft
    return result


@pytest.mark.parametrize("key", KEYS)
def test_saved_wire_restores_without_projecting_constructor(
    readable_variants, archive_http, monkeypatch, key
):
    draft = deepcopy(readable_variants[key])
    wire = deepcopy(draft["review_context"]["two_bot"]["bundle"])

    def forbid(_self):
        raise AssertionError(
            "Saved readable evidence must never pass through a projecting constructor"
        )

    monkeypatch.setattr(StoryBundle, "__post_init__", forbid)
    restored = retained_bundle(wire)
    assert restored.to_dict() == wire
    assert audit_story_bundle(restored).prompt_ready
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert draft["review_context"]["two_bot"]["bundle"] == wire
    assert len(archive_http["calls"]) == 1 and archive_http["responses"][0].closed


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_actual_senders_bind_saved_wire_and_recheck_full_source_twice(
    readable_variants,
    fake_transport,
    archive_http,
    monkeypatch,
    key,
    mode,
):
    # Keep the positive calendar-auto case inside its required observed profile.
    if mode == "auto" and key[1] == "calendar_date":
        monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    draft = approved_record({("high", "all_time"): readable_variants[key]}, mode)
    original = deepcopy(draft)
    state = state_for(draft)
    run_sender(draft, state, mode, monkeypatch)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-receipt"
    assert len(archive_http["calls"]) == 2 and all(row.closed for row in archive_http["responses"])
    assert draft["review_context"] == original["review_context"]
    fake_transport.safety.assert_called_once_with(original["text"])
    assert (
        fake_transport.calls == [("create", original["text"], {})]
        and len(fake_transport.persisted) == 1
    )


@pytest.mark.parametrize("kind", ["schema", "alias", "table", "mixed_reference"])
def test_malformed_reserved_wire_refuses_before_source_or_constructor(
    readable_variants, archive_http, monkeypatch, kind
):
    draft = deepcopy(readable_variants["high", "all_time"])
    wire = draft["review_context"]["two_bot"]["bundle"]
    baseline = wire["raw_signal_dump"]["evidence"]["baseline"]
    if kind == "schema":
        baseline["schema_version"] = "theheat-ghcn-unknown"
    elif kind == "alias":
        wire["historical_context"]["baseline"]["full_baseline_sha256"] = "0" * 64
    elif kind == "table":
        baseline["calendar_table"]["rows"][0][4] += 1
    else:
        wire["raw_signal_dump"]["ghcn_claim_view"] = {}
    assert (
        current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is not None
    )
    assert not archive_http["calls"]


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
@pytest.mark.parametrize("mode", ["manual", "auto"])
@pytest.mark.parametrize("boundary", ["before_safety", "after_safety", "after_intent"])
def test_saved_wire_keeps_real_sender_drift_refusals_and_next_edit_free(
    readable_variants,
    fake_transport,
    archive_http,
    monkeypatch,
    mode,
    boundary,
):
    posting_cases.test_current_archive_drift_never_sends_and_leaves_the_next_edit_free(
        readable_variants, fake_transport, archive_http, monkeypatch, mode, boundary
    )


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
@pytest.mark.parametrize("mode", ["manual", "auto"])
def test_saved_wire_never_erases_or_resends_unknown_transport(
    readable_variants,
    fake_transport,
    archive_http,
    monkeypatch,
    mode,
):
    posting_cases.test_full_source_guard_does_not_erase_or_resend_an_unknown_transport_outcome(
        readable_variants, fake_transport, archive_http, monkeypatch, mode
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("value_c", -21.2),
        ("mflag", "X"),
        ("qflag", "S"),
        ("sflag", "X"),
        ("observation_time", "1200"),
        ("source_payload_sha256", "0" * 64),
    ],
)
def test_complete_readable_secondary_observation_is_independently_verified(
    readable_variants, archive_http, field, value
):
    draft = deepcopy(readable_variants["high", "all_time"])
    wire = draft["review_context"]["two_bot"]["bundle"]
    wire["raw_signal_dump"]["evidence"]["variables"]["TMIN"][field] = value
    assert (
        current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is not None
    )


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
def test_source_to_real_generation_save_graphic_joint_review_and_fake_x_receipt(
    readable_variants,
    fake_transport,
    archive_http,
    monkeypatch,
):
    from freezegun import freeze_time
    from src.editorial import revisions
    from src.media import gist_temperature_media
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    from src.two_bot.candidate_derivation import retained_bundle
    from tests.test_observed_copy_guard_journey import _models
    from tests.test_refill import _score
    from tests.test_gist_temperature_posting import reviewed

    original = deepcopy(readable_variants["high", "all_time"])
    wire = original["review_context"]["two_bot"]["bundle"]
    bundle = retained_bundle(wire)
    text = "Graphic Fixture reached 42.2°C on 8 September, its archive high in the available GHCN archive through 2026-09-07."
    models = _models(monkeypatch, copy=text)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    state = state_for(original)
    state["drafts"] = []
    with freeze_time("2026-09-09T12:00:00Z", tick=True):
        assert _try_two_bot_draft(
            bundle,
            state,
            _score(category="all_time_high"),
            legacy_type="all_time_high",
            event_id=bundle.event_id,
            review_context={},
        )
        [draft] = state["drafts"]
        assert draft["review_context"]["two_bot"]["bundle"] == wire
        assert models.stages() == ["writer", "safety", "fact_check", "critic"]
        prepared = gist_temperature_media.prepare_media(wire)
        revisions.invalidate_media_attachment(
            draft, prepared["descriptor"], at="2026-09-09T12:00:00Z"
        )
        reviewed(draft)  # Explicit invented joint human-review fixture, never a live grant.
        run_sender(draft, state, "manual", monkeypatch)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-receipt"
    assert fake_transport.calls[0][0] == "upload" and fake_transport.calls[0][1] == prepared["png"]
    assert (
        fake_transport.calls[1][0] == "alt"
        and fake_transport.calls[1][2] == prepared["descriptor"]["alt_text"]
    )
    assert fake_transport.calls[2][0] == "create" and fake_transport.calls[2][1] == text
    assert len(archive_http["calls"]) == 2 and all(r.closed for r in archive_http["responses"])
