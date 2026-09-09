"""Bounded material ERA5 baseline revisions, with exact retained-claim links."""
from copy import deepcopy
from src.data.temperature_evidence import ARCHIVE_PRODUCT, finite, fingerprint
from src.data.temperature_history import record_claim_finding
from src.editorial.revisions import text_hash


def record_baseline_revision(state, sampling_key, before, after):
    if state is None or not before:
        return
    old, new = before.get("baseline", {}), after.get("baseline", {})
    changes = {field: {"previous": before.get(field), "current": after.get(field)}
               for field in ("all_time_max", "all_time_min", "monthly_max", "monthly_min", "calendar_max", "calendar_min", "monthly_mean", "wetbulb_max")
               if before.get(field) != after.get(field)}
    if not changes:
        return
    revision = {"kind": "baseline_revision", "sampling_key": sampling_key,
                "source_product": new.get("source_product"), "changes": changes,
                "previous_revision": old.get("revision_id"), "current_revision": new.get("revision_id"),
                "previous_interval": [old.get("requested_start"), old.get("requested_end")],
                "current_interval": [new.get("requested_start"), new.get("requested_end")],
                "publication_time_source_payload_recovered": False}
    revision_id = fingerprint(revision)
    state.setdefault("temperature_history", {}).setdefault(revision_id, {**revision, "retrieved_at": new["retrieved_at"]})
    same_interval = revision["previous_interval"] == revision["current_interval"]
    affected_variables = set()
    for field in changes:
        if field == "wetbulb_max":
            affected_variables.add("wet_bulb_temperature_2m_max")
        elif field == "monthly_mean":
            affected_variables.update(("temperature_2m_max", "temperature_2m_min"))
        elif field.endswith("_min"):
            affected_variables.add("temperature_2m_min")
        else:
            affected_variables.add("temperature_2m_max")
    old_grid, new_grid = old.get("provider_grid"), new.get("provider_grid")
    same_source = (
        bool(before.get("identity")) and before.get("identity") == after.get("identity")
        and old.get("source_product") == new.get("source_product") == ARCHIVE_PRODUCT
        and old.get("model") == new.get("model") == "era5"
        and bool(old.get("timezone")) and old.get("timezone") == new.get("timezone")
        and isinstance(old_grid, dict) and old_grid == new_grid
        and all(finite(old_grid.get(key)) for key in ("latitude", "longitude"))
    )
    # Losing a source cell can lower a computed maximum without disproving it.
    # Retain that finding, but only a complete like-for-like source interval can
    # invalidate an unpublished comparison as a verified source revision.
    coverage_qualified = all(
        (baseline.get("variables") or {}).get(variable, {}).get("complete") is True
        for baseline in (old, new) for variable in affected_variables
    )
    verified_change = same_interval and same_source and coverage_qualified
    for draft in state.get("drafts", []):
        if not isinstance(draft, dict):
            continue
        context = draft.get("review_context")
        if not isinstance(context, dict):
            continue
        two_bot = context.get("two_bot")
        bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
        raw = bundle.get("raw_signal_dump") if isinstance(bundle, dict) else None
        evidence = raw.get("evidence") if isinstance(raw, dict) else None
        baseline = evidence.get("baseline") if isinstance(evidence, dict) else None
        if not isinstance(baseline, dict) or baseline.get("revision_id") != old.get("revision_id"):
            continue
        claim = {"sampling_key": sampling_key, "valid_date": evidence.get("valid_date"),
                 "draft_id": draft.get("id"), "event_id": draft.get("event_id"),
                 "tweet_id": draft.get("tweet_id"), "text_sha256": text_hash(draft.get("text", "")),
                 "baseline": deepcopy(baseline)}
        record_claim_finding(state, claim, reason="reanalysis_baseline_changed",
                             source_revision=new["revision_id"], retrieved_at=new["retrieved_at"],
                             details={**revision, "same_query_interval": same_interval,
                                      "same_source_and_sampling": same_source,
                                      "affected_variable_coverage_complete": coverage_qualified,
                                      "historical_correctness": "source_comparator_revised" if verified_change else "not_determined",
                                      "limit": "An advancing archive cutoff is not a retroactive refutation of an earlier dated claim"},
                             verified_change=verified_change)
