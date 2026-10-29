"""Closed media dispatch: deployed temperature compatibility and refusal of every other kind.

Invented GHCN data only. The dispatcher must return the temperature module's exact
bytes/description and keep that module's own validator in force; an unknown kind
never reaches review, approval or the X adapter, while removal stays available.
"""
from copy import deepcopy
import json
from unittest.mock import MagicMock

from freezegun import freeze_time
import pytest

from src.editorial import revisions
from src.media import gist_hazard_media as hazard, gist_media, gist_temperature_media as temperature
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.gist_media_helpers import approve, attach, install_fake_x, run_manual, saved_draft, state_for


@pytest.fixture(autouse=True)
def invented_clock():
    with freeze_time("2026-09-09T12:00:00Z"):
        yield


@pytest.fixture(scope="module")
def station():
    bundle = story_bundle_snapshot(graphic_bundles()[-1])
    return bundle, temperature.prepare_media(bundle)


def temperature_draft(station):
    bundle, _prepared = station
    return saved_draft(bundle, draft_id="invented-gist-temperature", draft_type="all_time_high",
                       text="Invented station comparison for a saved observed reading.",
                       created_at="2026-09-09T11:00:00Z")


def test_dispatch_returns_the_deployed_temperature_bytes_and_recipe_unchanged(station):
    bundle, direct = station
    routed = gist_media.prepare_media(deepcopy(bundle))
    assert routed["png"] == direct["png"] and routed["descriptor"] == direct["descriptor"]
    assert routed["title"] == direct["title"] and set(routed) == {"descriptor", "png", "title"}
    assert gist_media.validate_descriptor(direct["descriptor"], bundle) == direct["descriptor"]
    assert gist_media.KINDS == frozenset({temperature.KIND, *hazard.KINDS})
    assert temperature.KIND not in hazard.KINDS
    draft = attach(temperature_draft(station), direct["descriptor"])
    assert gist_media.media_for_draft(draft) == temperature.media_for_draft(draft) == (
        direct["png"], direct["descriptor"]["alt_text"])


def test_temperature_validator_and_date_rule_stay_in_force_through_dispatch(station, monkeypatch):
    bundle, direct = station
    changed = deepcopy(direct["descriptor"])
    changed["alt_text"] += " "
    with pytest.raises(ValueError, match="description changed"):
        gist_media.validate_descriptor(changed, bundle)
    draft = attach(temperature_draft(station), direct["descriptor"])
    with freeze_time("2026-12-31T12:00:00Z"), pytest.raises(ValueError, match="future or stale"):
        gist_media.media_for_draft(draft)
    # The dispatcher resolves the temperature module at call time.
    spy = MagicMock(return_value=(b"invented", "invented"))
    monkeypatch.setattr(temperature, "media_for_draft", spy)
    assert gist_media.media_for_draft(draft) == (b"invented", "invented")
    spy.assert_called_once_with(draft)


HAZARD_KIND_NAMES = ("gist_pm25_forecast_v1", "gist_modis_locator_v1", "gist_viirs_locator_v1")


@pytest.mark.parametrize("attachment", [
    *({"kind": name, "schema_version": 1} for name in HAZARD_KIND_NAMES),
    {"kind": "gist_temperature_comparator_v2", "schema_version": 1},
    {"kind": "postgres_editor_media_v1"}, {"kind": None}, {}, {"kind": ["gist_temperature_comparator_v1"]},
    {"kind": "GIST_TEMPERATURE_COMPARATOR_V1"}, "gist_temperature_comparator_v1", None, [],
])
def test_unknown_malformed_or_not_yet_enabled_kinds_never_review_approve_or_send(station, attachment, monkeypatch):
    bundle, _direct = station
    with pytest.raises(ValueError, match="unsupported attachment"):
        gist_media.validate_descriptor(attachment, bundle)
    draft = temperature_draft(station)
    if attachment is None or isinstance(attachment, (str, list)):
        draft["media_attachment"] = deepcopy(attachment)
    else:
        attach(draft, attachment)
    assert not revisions.review_is_current(draft)
    assert revisions.project_draft(draft)["review_status"] == "media_review_required"
    with pytest.raises(ValueError):
        revisions.record_joint_media_review(draft)
    with pytest.raises(ValueError):
        revisions.record_human_review(draft)
    with pytest.raises(ValueError):
        revisions.authorize_draft(draft, "manual", "invented-intent")
    # A forged current-looking binding still cannot reach the X adapter.
    draft.update(review_binding={**revisions.draft_identity(draft), "kind": "human_media",
                                 "media_sha256": "0" * 64}, status="approved", publish_intent_id="forged")
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    assert fake.posting.post_approved(draft, state) == "failed"
    assert fake.calls == []
    # Removal stays available for a present broken attachment.
    removed = revisions.invalidate_media_attachment(draft, None, at="2026-09-09T12:01:00Z")
    assert "media_attachment" not in removed and removed["status"] == "pending"
    assert removed["revision_history"][-1]["media_attachment"] == attachment


def test_sender_refuses_unsupported_attachment_after_intent_without_fallback(station, monkeypatch):
    bundle, direct = station
    draft = approve(attach(temperature_draft(station), direct["descriptor"]))
    # Swap in a future kind name after approval: the stored review no longer binds.
    draft["media_attachment"] = dict(draft["media_attachment"], kind="gist_pm25_forecast_v1")
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [] and draft["status"] == "approved"
    assert "publish_ledger" not in state or draft["event_id"] not in state["publish_ledger"]


def test_temperature_manual_journey_through_dispatch_uploads_exact_reviewed_bytes(station, monkeypatch):
    _bundle, direct = station
    draft = approve(attach(temperature_draft(station), direct["descriptor"]))
    original = deepcopy(draft)
    fake = install_fake_x(monkeypatch)
    state = state_for(draft)
    run_manual(monkeypatch, fake, state, draft)
    assert fake.calls == [
        ("upload", direct["png"], "hot10.png"),
        ("alt", "98765", direct["descriptor"]["alt_text"]),
        ("create", original["text"], {"media_ids": ["98765"]}),
    ]
    assert draft["status"] == "posted" and state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert json.dumps(state, ensure_ascii=False).count('"png_base64"') == 0
