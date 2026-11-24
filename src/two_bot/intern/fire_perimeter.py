"""Source-qualified mapped footprints, not fire-spread or impact estimates."""
from __future__ import annotations

from src.two_bot.types import StoryBundle

KIND = "source_mapped_fire_perimeter"


def build_fire_perimeter_bundle(context):
    from src.data.nifc_perimeter import PRODUCT, SOURCE_URL
    from src.storage.fire_episodes import FireEpisodeContext
    from src.storage.cyclone_supply import instant
    if type(context) is not FireEpisodeContext:
        raise ValueError("resolved_fire_context_required")
    revision = context.validate(context.binding)
    derived = revision["derived"]
    if not derived["opportunities"]:
        raise ValueError("fire_opportunity_missing")
    opportunity = derived["opportunities"][-1]
    current = next(row for row in derived["maps"]
                   if row["source_revision_sha256"] == opportunity["current_map"])
    history = [row for row in derived["maps"]
               if instant(row["polygon_captured_at"]) < instant(current["polygon_captured_at"])]
    return StoryBundle(signal_kind=KIND, where=current["source_name"],
        when=current["polygon_captured_at"], event_id="mapped-fire:" + opportunity["opportunity_id"],
        headline_metric=dict(label="Source-recorded mapped polygon area", value=current["source_area_acres"],
                             unit="acres", source="NIFC WFIGS retained polygon view", as_of=current["polygon_captured_at"]),
        current_facts=[dict(label="Source-recorded mapped polygon area", value=current["source_area_acres"],
            unit="acres", source="NIFC WFIGS retained polygon view", url=SOURCE_URL,
            as_of=current["polygon_captured_at"]),
            dict(label="Mapping provenance", value=current["mapping_method"],
                 source=current["polygon_source"], as_of=current["polygon_captured_at"])],
        historical_context=dict(dated_source_maps=history,
            claim_limit="Separately dated source maps; not actual fire growth, duration or final area."),
        raw_signal_dump=dict(source_product=PRODUCT, source_url=SOURCE_URL,
            physical_episode=context.binding, mapped_perimeter=current,
            source_origin="operator_retained_capture_not_independently_authenticated"))


def bundle_hold(bundle, context):
    """A compact summary cannot replace live retained-member resolution."""
    try:
        from src.storage.fire_episodes import FireEpisodeContext
        if type(context) is not FireEpisodeContext:
            return "resolved_fire_context_required"
        context.validate(bundle.raw_signal_dump["physical_episode"])
        if bundle.to_dict() != build_fire_perimeter_bundle(context).to_dict():
            return "mapped_fire_bundle_changed"
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return "mapped_fire_evidence_unresolved"
    return None
