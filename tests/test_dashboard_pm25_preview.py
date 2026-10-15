"""Saved PM2.5 uses the same protected read-only preview without source repair."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.dashboard_preview.errors import PreviewError
from src.editorial.revisions import draft_identity
from tests.dashboard_graphic_helpers import saved_pm25_preview
from tests.test_dashboard_graphic_preview import preview


def test_complete_forecast_preserves_all_samples_context_and_state():
    state, request = saved_pm25_preview()
    before = deepcopy(state)
    result = json.loads(preview(state, request))
    assert state == before and result["schema_version"] == 2
    assert result["source"] == "CAMS via Open-Meteo" and "source_time" not in result
    assert result["source_context"] == {
        "kind": "pm25_forecast_day", "valid_date": "2026-06-08", "timezone": "Asia/Kathmandu",
        "valid_start": "2026-06-07T18:15:00Z", "valid_end": "2026-06-08T18:15:00Z",
        "requested_at": "2026-06-08T12:00:00Z", "retrieved_at": "2026-06-08T12:00:01Z",
    }
    assert result["revision_identity"] == request["expected_revision"]
    assert result["binding"]["template"] == "pm25_forecast_day"
    assert result["svg_sha256"] == hashlib.sha256(result["svg_utf8"].encode()).hexdigest()
    assert result["attachment"] is False and result["publication_approved"] is False
    for hour in range(24):
        assert f"2026-06-08T{hour:02}:00: {160 + hour}.0" in result["alt_text"]
    for qualification in ("171.5", "SYNTHETIC", "not city-wide measurements", "not original HTTP",
                          "native resolution unknown", "no extrapolation or hourly safety threshold", "[27.75, 85.25]"):
        assert qualification in result["alt_text"]
    assert "raw_signal_dump" not in result and "drafts" not in result


def test_saved_bundle_kind_controls_adapter_not_ui_type():
    state, request = saved_pm25_preview()
    state["drafts"][0]["type"] = "fire"
    request["expected_revision"].update(draft_identity(state["drafts"][0]))
    assert json.loads(preview(state, request))["source_context"]["kind"] == "pm25_forecast_day"


@pytest.mark.parametrize("change", ["legacy", "incomplete", "dust", "station", "related", "extension",
                                   "oversize", "malformed", "unit", "mean"])
def test_ineligible_saved_forecast_never_renders_or_repairs(monkeypatch, change):
    state, request = saved_pm25_preview()
    draft = state["drafts"][0]
    bundle = draft["review_context"]["two_bot"]["bundle"]
    raw = bundle["raw_signal_dump"]
    if change == "legacy":
        del raw["forecast_window"]
    elif change == "incomplete":
        raw["forecast_window"]["series"]["pm2_5"]["values"][0] = None
    elif change == "dust":
        bundle["signal_kind"] = "dust_event"
    elif change == "station":
        raw["evidence_grade"] = "model_corroborated_by_station"
    elif change == "related":
        bundle["related_signals"] = [{"signal_kind": "dust_event", "event_id": "invented-related"}]
    elif change == "extension":
        bundle["unreviewed_context"] = "invented additional claim"
    elif change == "oversize":
        bundle["unreviewed_context"] = "x" * 1_000_001
    elif change == "malformed":
        raw["forecast_window"] = ["not a source window"]
    elif change == "unit":
        raw["forecast_window"]["series"]["pm2_5"]["unit"] = "mg/m3"
    else:
        raw["pm25_24h_mean"] += 1
    request["expected_revision"].update(draft_identity(draft))
    before = deepcopy(state)
    monkeypatch.setattr("src.dashboard_preview.preview.render_svg", lambda **_: pytest.fail("unqualified render"))
    with pytest.raises(PreviewError) as error:
        preview(state, request)
    assert error.value.code == "graphic_unavailable" and state == before


def test_client_cannot_select_adapter_or_replace_saved_window():
    state, request = saved_pm25_preview()
    request["template"] = "pm25_forecast_day"
    with pytest.raises(PreviewError) as error:
        preview(state, request, read_state=lambda: pytest.fail("client selection read state"))
    assert error.value.code == "bad_request"
