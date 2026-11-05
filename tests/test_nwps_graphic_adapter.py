from copy import deepcopy
from datetime import timedelta

import pytest

from src.data.nwps_major_forecasts import verify_major_forecast
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import validate_graphic
from src.media.evidence_graphic_render import render_svg
from src.media.nwps_graphic_adapter import nwps_graphic_spec
from src.two_bot.intern.nwps_forecast import build_nwps_forecast_bundle
from tests.test_nwps_major_forecasts import NOW, source


@pytest.fixture
def retained():
    hint, metadata, forecast = source()
    bundle = build_nwps_forecast_bundle(verify_major_forecast(hint, metadata, forecast, NOW)).to_dict()
    return bundle, {"metadata": metadata, "forecast": forecast, "checked_at": NOW.isoformat(), "synthetic": True}


def prepare(bundle, capture):
    return nwps_graphic_spec(bundle, capture, expected_bundle_sha256=fingerprint(bundle),
                             expected_capture_sha256=fingerprint(capture))


def test_issued_series_first_major_point_and_alt_text_share_one_binding(retained):
    spec = prepare(*retained)
    evidence = spec["evidence"]
    assert [point["value"] for point in evidence["points"]] == [16, 17, 17.5]
    assert evidence["first_major_at"] == "2026-07-02T18:00:00+00:00"
    result = render_svg(**spec)
    assert result == render_svg(**spec)
    assert b"First major point: 17.0 ft" in result["svg"]
    assert b"Major threshold: 17.0 ft" in result["svg"]
    assert "17.0 feet at 2026-07-02 18:00:00 UTC" in result["alt_text"]
    assert "3 forecast points" in result["alt_text"]
    assert result["synthetic"] is True and result["publication_approved"] is False


def test_canonical_numeric_encoding_has_identical_render_bytes(retained):
    spec = prepare(*retained)
    expected = render_svg(**spec)
    spec["evidence"]["major_threshold_ft"] = 17
    spec["evidence"]["first_major_ft"] = 17
    assert fingerprint(spec["evidence"]) == spec["expected_evidence_sha256"]
    assert render_svg(**spec) == expected


def test_changed_bytes_refuse_against_the_retained_capture_hash(retained):
    bundle, capture = retained
    original = fingerprint(capture)
    capture["forecast"]["data"][0]["primary"] = 16.5
    with pytest.raises(ValueError, match="review binding changed"):
        nwps_graphic_spec(bundle, capture, expected_bundle_sha256=fingerprint(bundle),
                         expected_capture_sha256=original)


@pytest.mark.parametrize("change", ["unit", "gauge", "stale", "selected_point", "story"])
def test_source_and_story_disagreements_refuse_even_with_new_hashes(retained, change):
    bundle, capture = retained
    if change == "unit":
        capture["forecast"]["primaryUnits"] = "m"
    elif change == "gauge":
        capture["metadata"]["lid"] = "FAKF2"
    elif change == "stale":
        capture["checked_at"] = (NOW + timedelta(hours=12)).isoformat()
    elif change == "selected_point":
        capture["forecast"]["data"][1]["primary"] = 16.8
    else:
        bundle["where"] = "A different river"
    with pytest.raises(ValueError, match="nwps_|NWPS"):
        prepare(bundle, capture)


@pytest.mark.parametrize("field,value", [("major_threshold_ft", 18), ("first_major_ft", 16), ("unit", "m"), ("synthetic", False)])
def test_edited_chart_fields_cannot_pass_by_recomputing_the_outer_hash(retained, field, value):
    spec = prepare(*retained)
    altered = deepcopy(spec["evidence"])
    altered[field] = value
    with pytest.raises(ValueError, match="differs from the retained"):
        validate_graphic(spec["template"], altered, expected_evidence_sha256=fingerprint(altered))
