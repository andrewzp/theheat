"""Invented saved source fixture; never read credentials or production state."""
from src.editorial.revisions import draft_identity, decision_revision
from tests.fire_graphic_helpers import graphic_bundle

POLICY = "a" * 64
RUNTIME = "b" * 64


def saved_preview():
    draft = {"id": "invented-fire", "status": "pending", "type": "fire",
             "text": "Invented thermal detections for a graphic test.",
             "review_context": {"two_bot": {"bundle": graphic_bundle().to_dict()}},
             "checks": {"retained": "unchanged"}, "approval": {"retained": "unchanged"}}
    request = {"draft_id": draft["id"],
               "expected_revision": {**draft_identity(draft), "decision_revision": decision_revision(draft)},
               "expected_policy_source_sha256": POLICY, "expected_preview_runtime_sha256": RUNTIME}
    return {"drafts": [draft], "publication_ledger": [], "unrelated": {"preserve": True}}, request


def saved_pm25_preview():
    from tests.air_quality_graphic_helpers import graphic_bundle as pm25_bundle

    state, request = saved_preview()
    draft = state["drafts"][0]
    draft.update(id="invented-pm25", type="air_quality_hazard",
                 text="Invented PM2.5 forecast for a graphic test.")
    draft["review_context"]["two_bot"]["bundle"] = pm25_bundle().to_dict()
    request["draft_id"] = draft["id"]
    request["expected_revision"] = {**draft_identity(draft), "decision_revision": decision_revision(draft)}
    return state, request


def saved_viirs_preview():
    """Four invented NOAA-20 detections in source order, with all three categories."""
    from tests.viirs_graphic_helpers import viirs_bundle

    state, request = saved_preview()
    draft = state["drafts"][0]
    draft.update(id="invented-viirs", text="Invented VIIRS thermal detections for a graphic test.")
    draft["review_context"]["two_bot"]["bundle"] = viirs_bundle(
        [125.75, 500.1234, 750.25, 250], categories=("high", "nominal", "low", "high"),
        coordinates=[(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]).to_dict()
    request["draft_id"] = draft["id"]
    request["expected_revision"] = {**draft_identity(draft), "decision_revision": decision_revision(draft)}
    return state, request


def saved_temperature_preview(*, direction="high", tier="all_time"):
    from tests.ghcn_graphic_helpers import graphic_bundles
    from src.media.temperature_graphic_adapter import story_bundle_snapshot

    bundle = graphic_bundles(direction=direction, tier=tier)[-1]
    state, request = saved_preview()
    draft = state["drafts"][0]
    legacy_type = {"open_meteo_archive_high": "all_time_high", "open_meteo_archive_low": "all_time_low",
                   "calendar_record": "record", "calendar_record_low": "record_low"}.get(bundle.signal_kind, bundle.signal_kind)
    draft.update(id="invented-station", type=legacy_type,
                 text="An invented station reading exceeds its available archive comparator.")
    draft["review_context"]["two_bot"]["bundle"] = story_bundle_snapshot(bundle)
    request["draft_id"] = draft["id"]
    request["expected_revision"] = {**draft_identity(draft), "decision_revision": decision_revision(draft)}
    return state, request
