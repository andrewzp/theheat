"""Actual local fire intern/audit/memory/request preparation; no transport."""
from __future__ import annotations

from copy import deepcopy


def _unknown_delivery_fence(snapshot, episode, opportunities):
    from src.editorial.revisions import has_unresolved_publish
    from src.storage.cyclone_supply import require

    event_ids = {"mapped-fire:" + row["opportunity_id"] for row in opportunities}

    def related(row):
        if not isinstance(row, dict):
            return False
        identity = row.get("event_id") or row.get("id")
        if isinstance(identity, str) and identity in event_ids:
            return True
        candidates = [row]
        review = row.get("review_context")
        if isinstance(review, dict):
            candidates.append(review)
            if isinstance(review.get("two_bot"), dict):
                candidates.append(review["two_bot"])
        if isinstance(row.get("two_bot_metadata"), dict):
            candidates.append(row["two_bot_metadata"])
        for candidate in list(candidates):
            if isinstance(candidate.get("bundle"), dict):
                candidates.append(candidate["bundle"])
        for candidate in list(candidates):
            if isinstance(candidate.get("raw_signal_dump"), dict):
                candidates.append(candidate["raw_signal_dump"])
        return any(isinstance(candidate.get("physical_episode"), dict)
            and candidate["physical_episode"].get("episode_id") == episode for candidate in candidates)

    def explicit_unknown(row):
        # A numeric ID cannot silently erase an explicit unresolved outcome or
        # a preserved conflict. Bound this walk and refuse malformed/cyclic data.
        pending = [row]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if not isinstance(current, dict) or id(current) in seen or len(seen) >= 256:
                return True
            seen.add(id(current))
            if (current.get("publish_outcome") in ("submitted", "unknown")
                or current.get("phase") in ("submitted", "unknown")
                or current.get("delivery_state") in ("submitted", "unknown")):
                return True
            conflicts = current.get("attempt_conflicts", [])
            if not isinstance(conflicts, list):
                return True
            pending.extend(conflicts)
        return False

    drafts, ledger, memory = snapshot.get("drafts", []), snapshot.get("publish_ledger", {}), snapshot.get("memory", {})
    require(type(drafts) is list and type(ledger) is dict and type(memory) is dict, "invalid_fire_snapshot")
    shipped = memory.get("shipped_tweets", [])
    require(type(shipped) is list, "invalid_fire_snapshot")
    for row in drafts + shipped:
        if related(row):
            require(not explicit_unknown(row) and not has_unresolved_publish(row, snapshot), "fire_unknown_delivery")
    for event_id, entry in ledger.items():
        if event_id in event_ids or related(entry):
            draft = next((row for row in drafts if isinstance(row, dict)
                          and (row.get("event_id") or row.get("id")) == event_id),
                         {"event_id": event_id})
            require(not explicit_unknown(entry) and not has_unresolved_publish(draft, snapshot), "fire_unknown_delivery")


def prepare_fire_request(session, episode_id, revision_sha256, snapshot, *, now):
    from src.editorial import policy as editorial_policy
    from src.editorial.revisions import fingerprint
    from src.storage.cyclone_supply import instant, require
    from src.storage.fire_episodes import FireEpisodeSession
    from src.two_bot.bundle_capture import capture_bundle
    from src.two_bot.evidence_contract import audit_story_bundle
    from src.two_bot.intern.fire_perimeter import build_fire_perimeter_bundle
    from src.two_bot.memory import build_memory_slice
    from src.two_bot.writer import WRITER_PROVIDER, anthropic_writer_request, build_writer_user_prompt

    require(type(session) is FireEpisodeSession, "explicit_fire_session_required")
    require(type(snapshot) is dict, "invalid_fire_snapshot")
    detached = deepcopy(snapshot)
    context, revision = session.prepare_story_context(episode_id, revision_sha256, now=now)
    _unknown_delivery_fence(detached, episode_id, revision["derived"]["opportunities"])
    policy = editorial_policy.current_editorial_policy()
    require(policy is not None and WRITER_PROVIDER == "anthropic", "fire_request_configuration_unavailable")
    bundle = build_fire_perimeter_bundle(context)
    clock, observed = instant(now), instant(bundle.when)
    require(observed <= clock and (clock - observed).total_seconds() <= 48 * 3600,
            "fire_map_not_current")
    audit = audit_story_bundle(bundle, episode_context=context)
    require(audit.prompt_ready, "fire_story_evidence_held")
    captured = capture_bundle(bundle)
    memory = build_memory_slice(detached, bundle, now=clock, episode_context=context)
    request = anthropic_writer_request(build_writer_user_prompt(bundle, memory, episode_context=context))
    context.validate(context.binding)
    _unknown_delivery_fence(detached, episode_id, revision["derived"]["opportunities"])
    require(editorial_policy.current_editorial_policy() == policy, "fire_policy_changed")
    return dict(opportunity_id=revision["derived"]["opportunities"][-1]["opportunity_id"],
        bundle=captured.payload(), memory=memory.to_dict(), writer_request=request,
        bundle_sha256=fingerprint(captured.payload()), memory_sha256=fingerprint(memory.to_dict()),
        policy_sha256=fingerprint(policy), evidence_prompt_ready=True,
        provider_transport="not_attempted", callback_enrollment="not_supported")
