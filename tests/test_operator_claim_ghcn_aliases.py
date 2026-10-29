"""Invented GHCN bytes through all six real intern/graphic/revision paths."""
from copy import deepcopy

import pytest

from src.editorial.revisions import (
    draft_identity, initialize_revision, invalidate_text, project_draft,
    record_joint_media_review, review_is_current,
)
from src.media.gist_temperature_media import prepare_media
from src.editorial.operator_claim_references import operator_claim_kind_matches
from tests.dashboard_graphic_helpers import saved_temperature_preview


@pytest.fixture(scope="module", params=[
    ("high", "all_time", "all_time_high", "open_meteo_archive_high"),
    ("low", "all_time", "all_time_low", "open_meteo_archive_low"),
    ("high", "monthly", "monthly_high", "monthly_high"),
    ("low", "monthly", "monthly_low", "monthly_low"),
    ("high", "calendar", "record", "calendar_record"),
    ("low", "calendar", "record_low", "calendar_record_low"),
], ids=["archive-high", "archive-low", "monthly-high", "monthly-low", "calendar-high", "calendar-low"])
def ghcn_variant(request):
    direction, tier, legacy, kind = request.param
    state, _ = saved_temperature_preview(direction=direction, tier=tier)
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    assert draft["type"] == legacy and bundle["signal_kind"] == kind
    draft["event_id"] = bundle["event_id"]
    initialize_revision(draft)
    quote = "invented station reading"
    start = draft["text"].index(quote)
    items = [{"claim": {"start": start, "end": start + len(quote), "text": quote},
              "sources": [{"pointer": "/current_facts/0"}]}]
    return draft, items


def test_all_six_real_ghcn_variants_save_and_project_exact_operator_references(ghcn_variant):
    original, items = ghcn_variant
    draft = deepcopy(original)
    before = draft_identity(draft)
    bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
    invalidate_text(draft, draft["text"], operator_claim_references=items)
    view = project_draft(draft)["operator_claim_reference_view"]
    assert view["status"] == "saved"
    assert view["items"][0]["claim"] == items[0]["claim"]
    assert view["items"][0]["sources"][0]["fact"]["value"] == bundle["current_facts"][0]["value"]
    assert draft["review_context"]["two_bot"]["bundle"] == bundle
    assert draft["content_revision"] == before["content_revision"] + 1
    assert draft_identity(draft)["evidence_sha256"] != before["evidence_sha256"]
    stale = deepcopy(draft)
    stale["review_context"]["operator_claim_references"]["text_sha256"] = "f" * 64
    assert project_draft(stale)["operator_claim_reference_view"]["status"] == "unavailable"
    stale = deepcopy(draft)
    stale["review_context"]["two_bot"]["bundle"]["current_facts"][0]["value"] = 901
    assert project_draft(stale)["operator_claim_reference_view"]["status"] == "unavailable"


def test_alias_reference_edit_preserves_actual_ghcn_media_but_revokes_joint_review(ghcn_variant):
    original, items = ghcn_variant
    draft = deepcopy(original)
    descriptor = prepare_media(draft["review_context"]["two_bot"]["bundle"])["descriptor"]
    draft["media_attachment"] = descriptor
    record_joint_media_review(draft)
    assert review_is_current(draft)
    invalidate_text(draft, draft["text"], operator_claim_references=items)
    assert draft["media_attachment"] == descriptor
    assert not review_is_current(draft)
    assert "review_binding" not in draft
    assert draft["revision_history"][-1]["review_binding"]["kind"] == "human_media"


def test_aliases_never_relax_event_or_unrelated_kind_checks(ghcn_variant):
    original, items = ghcn_variant
    for change in (
        lambda draft: draft.update(event_id="other-invented-event"),
        lambda draft: draft.update(type="unrelated_temperature_kind"),
        lambda draft: draft["review_context"]["two_bot"]["bundle"].update(signal_kind="other_source_kind"),
    ):
        draft = deepcopy(original)
        change(draft)
        before = deepcopy(draft)
        with pytest.raises(ValueError, match="snapshot does not match"):
            invalidate_text(draft, draft["text"], operator_claim_references=items)
        assert draft == before


@pytest.mark.parametrize("draft_type,bundle_kind,expected", [
    ("temperature", "temperature", True), ("record", "record", True),
    ("open_meteo_archive_high", "all_time_high", False),
    ("calendar_record", "record", False), ("record_low", "calendar_record", False),
    ("all_time_high", "open_meteo_archive_low", False), ("monthly_high", "open_meteo_archive_high", False),
    ("ALL_TIME_HIGH", "open_meteo_archive_high", False),
    (None, None, False), ("", "", False), (True, True, False), ([], [], False),
])
def test_kind_aliases_are_directional_exact_and_never_coerced(draft_type, bundle_kind, expected):
    assert operator_claim_kind_matches(draft_type, bundle_kind) is expected
