"""Invented retained source/receipt; real handler, no renderer, store or authority calls."""
from copy import deepcopy
import base64
import json
from unittest.mock import Mock

import pytest

from src.dashboard_preview.errors import PreviewError
from src.dashboard_preview.preview import build_preview
from src.dashboard_preview.reader import Budget
from src.editorial import revisions
from src.media import gist_temperature_media as temperature
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.gist_media_helpers import saved_draft

POLICY, RUNTIME = "a" * 64, "b" * 64
AT = "2026-09-09T12:00:00Z"
# Explicit transport fixture, never a claimed rendered weather image.
RETAINED_BYTES = b"invented retained temperature bytes; rendering is mocked"
PROFILE = {"implementation_sha256": "c" * 64, "font_sha256": "d" * 64,
           "codec_sha256": "e" * 64, "png_codec": "canonical-png-fixed-huffman-1",
           "pillow": "fixture", "freetype": "fixture", "width": 1200, "height": 1500}


def request_for(draft):
    return {"draft_id": draft["id"], "format": "png", "delivered": True,
            "expected_revision": {**revisions.draft_identity(draft),
                                  "decision_revision": revisions.decision_revision(draft)},
            "expected_policy_source_sha256": POLICY, "expected_preview_runtime_sha256": RUNTIME}


def build(state, request):
    return json.loads(build_preview(request, policy_sha=POLICY, runtime_sha=RUNTIME,
                                    read_state=lambda: state, budget=Budget()))


def retained_temperature(monkeypatch):
    # Only the byte/profile boundary is replaced: qualification, descriptor checks,
    # revision history, receipt selection and the delivered handler remain real.
    png = Mock(return_value=RETAINED_BYTES)
    monkeypatch.setattr(temperature, "_png", png)
    monkeypatch.setattr(temperature, "renderer_identity", lambda: deepcopy(PROFILE))
    bundle = story_bundle_snapshot(graphic_bundles()[-1])
    draft = saved_draft(bundle, draft_id="invented-temperature-history", draft_type="all_time_high",
                        text="Invented retained station comparison.", created_at=AT)
    prepared = temperature.prepare_media(bundle)
    revisions.invalidate_media_attachment(draft, prepared["descriptor"], at=AT)
    # Invented confirmed receipt seeded as test input; no review/approval/send invoked.
    receipt = {**revisions.draft_identity(draft), "phase": "confirmed", "tweet_id": "invented-delivered",
               "text": draft["text"], "confirmed_at": AT}
    state = {"drafts": [draft], "publish_ledger": {draft["event_id"]: receipt}, "unrelated": ["preserved"]}
    return state, draft, receipt, prepared, png


@pytest.fixture
def retained(monkeypatch):
    return retained_temperature(monkeypatch)


@pytest.mark.parametrize("later_edit", [False, True])
def test_actual_delivered_handler_preserves_temperature_snapshot(retained, later_edit):
    state, draft, receipt, prepared, png = retained
    if later_edit:
        revisions.invalidate_text(draft, "A later edit must not replace delivered text.", at=AT)
        revisions.invalidate_media_attachment(draft, None, at=AT)
        # Current source can be unavailable: the receipt selects retained history.
        draft["review_context"] = {}
    draft["status"] = "posted"
    before = deepcopy(state)
    result = build(state, request_for(draft))
    assert state == before
    assert result["schema_version"] == 6
    assert result["media_kind"] == temperature.KIND
    assert result["media_descriptor"] == prepared["descriptor"]
    assert base64.b64decode(result["png_base64"]) == RETAINED_BYTES
    assert result["delivery_text"] == result["expanded_description"] == prepared["descriptor"]["alt_text"]
    assert result["png_sha256"] == prepared["descriptor"]["png_sha256"]
    assert result["source_context"]["valid_date"] == prepared["descriptor"]["valid_date"]
    assert result["source_context"]["station_id"] == prepared["descriptor"]["station_id"]
    assert result["source_context"]["reporting_interval_known"] is False
    assert result["source_context"]["timezone"] is None
    assert result["delivered"] == {"tweet_id": receipt["tweet_id"], "text": receipt["text"],
                                    "content_revision": receipt["content_revision"], "confirmed_at": AT}
    assert result["publication_approved"] is result["attachment"] is False
    assert png.call_count == 2


@pytest.mark.parametrize("change", ["receipt", "source", "alt", "bytes", "profile", "request"])
def test_delivered_temperature_refuses_drift_without_mutation(retained, monkeypatch, change):
    state, draft, receipt, _prepared, png = retained
    request = request_for(draft)
    if change == "receipt":
        receipt["phase"] = "submitted"
    elif change == "source":
        receipt["evidence_sha256"] = "0" * 64
    elif change == "alt":
        draft["media_attachment"]["alt_text"] += " altered"
    elif change == "bytes":
        png.return_value = RETAINED_BYTES + b" altered"
    elif change == "profile":
        monkeypatch.setattr(temperature, "renderer_identity", lambda: {**PROFILE, "pillow": "changed"})
    else:
        request["expected_revision"]["decision_revision"] += 1
    # An attachment change changes the draft identity too; bind the current request
    # while preserving the old receipt, so no later identity substitutes for it.
    if change == "alt":
        request = request_for(draft)
    before = deepcopy(state)
    with pytest.raises(PreviewError) as raised:
        build(state, request)
    if change in {"bytes", "profile"}:
        assert raised.value.code == "media_hold"
        assert raised.value.hold == "media_renderer_changed"
    assert state == before
