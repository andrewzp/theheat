"""Historical envelope structure only; no grant, current fit or science claim."""
from copy import deepcopy

import pytest

from src.commands import postgres_cost_projection as cost
from src.editorial.revisions import draft_identity


def packet(version):
    review = dict(schema_version=version, proposal_sha256="a"*64, packet_sha256="b"*64,
        review_sha256="c"*64, command_id="11111111-2222-4333-8444-555555555555")
    if version == 2:
        review["platform_description_sha256"] = "d"*64
    draft = dict(id="invented-cost-draft", text="Invented historical text.", content_revision=2, decision_revision=3,
        media_review_binding=review, media_attachment=dict(schema_version=2, published=dict(
            family="nws_local_standard_radar_v1", frame_minute_utc="2026-10-15T12:00:00Z",
            valid_end="2026-10-15T12:30:00Z", useful_until="2026-10-15T12:15:00Z")))
    target = dict(draft_id=draft["id"], **draft_identity(draft), decision_revision=3)
    return dict(schema_version=6, draft_target=target, checker_state=dict(drafts=[draft]),
        final_text=draft["text"], text_sha256=target["text_sha256"],
        media=dict(proposal_sha256=review["proposal_sha256"], packet_sha256=review["packet_sha256"],
            review_sha256=review["review_sha256"], review_command_id=review["command_id"]),
        captured_at="2026-10-15T12:01:00Z", useful_until="2026-10-15T12:15:00Z",
        source_useful_until="2026-10-15T12:30:00Z", provenance_useful_until="2026-10-15T12:30:00Z")


@pytest.mark.parametrize("version", [1, 2])
def test_historical_review_versions_need_no_current_profile_or_fit(monkeypatch, version):
    from src.media import platform_description
    from src.commands import postgres_delivery
    def refuse(*args, **kwargs):
        pytest.fail("Passive historical envelope consulted current delivery eligibility")
    for target, name in ((platform_description, "preflight"), (platform_description, "profiles"),
                         (postgres_delivery, "description_profiles")):
        monkeypatch.setattr(target, name, refuse)
    value = packet(version)
    before = deepcopy(value)
    cost._revision_media_envelope(value)
    assert value == before


@pytest.mark.parametrize("change", ["missing_hash", "bad_hash", "upper_hash", "unknown_field", "version3", "boolean_version", "legacy_extra", "command", "target", "deadline", "list_review", "null_review"])
def test_new_historical_review_shape_remains_strict(change):
    value = packet(2)
    review = value["checker_state"]["drafts"][0]["media_review_binding"]
    if change in {"list_review", "null_review"}:
        value["checker_state"]["drafts"][0]["media_review_binding"] = [] if change == "list_review" else None
    elif change == "missing_hash":
        review.pop("platform_description_sha256")
    elif change == "bad_hash":
        review["platform_description_sha256"] = None
    elif change == "upper_hash":
        review["platform_description_sha256"] = "D"*64
    elif change == "unknown_field":
        review["profile"] = "invented-live-pass"
    elif change in {"version3", "boolean_version", "legacy_extra"}:
        review["schema_version"] = {"version3":3, "boolean_version":True, "legacy_extra":1}[change]
    elif change == "command":
        value["media"]["review_command_id"] = "66666666-2222-4333-8444-555555555555"
    elif change == "target":
        value["draft_target"]["decision_revision"] += 1
    else:
        value["useful_until"] = "2026-10-15T12:16:00Z"
    with pytest.raises(ValueError):
        cost._revision_media_envelope(value)
