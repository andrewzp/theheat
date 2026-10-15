"""Explicit local NHC retained-evidence preparation through the real writer.

No queue drain, provider transport, success callback, operational state update
or publishing. Cyclone callback/urgent enrollment remains a separate contract.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from src.storage.cyclone_supply import CycloneSupplySession, environment, instant, require
from src.storage.physical_events import EVENTS, PhysicalEpisodeSession


def prepare_episode_requests(session, episode_id, revision_sha256, snapshot, *, now, report_context=None):
    """Resolve current authority, then consume the actual intern/audit/memory seam."""
    from src.data.cyclones import LandThreatEvent
    from src.orchestrator.cyclones import _bundle_for_cyclone_event
    from src.two_bot.bundle_capture import capture_bundle
    from src.two_bot.evidence_contract import audit_story_bundle
    from src.two_bot.intern import build_cyclone_land_threat_bundle
    from src.two_bot.memory import build_memory_slice
    from src.two_bot.writer import anthropic_writer_request, build_writer_user_prompt
    from src.two_bot.writer import WRITER_PROVIDER
    from src.editorial.policy import current_editorial_policy
    from src.editorial.revisions import fingerprint

    require(type(session) is PhysicalEpisodeSession, "explicit_episode_session_required")
    context, revision = session.prepare_story_context(episode_id, revision_sha256)
    clock = instant(now)
    observed = instant(revision["observed_at"])
    require(observed <= clock and (clock.date() - observed.date()).days <= 2, "episode_source_not_current")
    detached = deepcopy(snapshot)
    policy = current_editorial_policy()
    require(policy is not None and WRITER_PROVIDER == "anthropic", "episode_request_configuration_unavailable")
    results = []
    for opportunity in revision["opportunities"]:
        cls = EVENTS.get(opportunity["event_type"])
        if cls is None:
            raise ValueError("unsupported_episode_event")
        event = cls(**opportunity["event"])
        bundle = (build_cyclone_land_threat_bundle(event) if isinstance(event, LandThreatEvent)
                  else _bundle_for_cyclone_event(event))
        bundle.raw_signal_dump["physical_episode"] = context.binding
        # New bound inputs cannot borrow country/name-only news enrichment.
        audit = audit_story_bundle(bundle)
        require(audit.prompt_ready, "episode_story_evidence_held")
        captured = capture_bundle(bundle)
        memory = build_memory_slice(detached, bundle, now=clock, episode_context=context)
        request = anthropic_writer_request(build_writer_user_prompt(bundle, memory, episode_context=context))
        results.append(dict(opportunity_id=opportunity["opportunity_id"], bundle=captured.payload(),
            memory=memory.to_dict(), writer_request=request, evidence_prompt_ready=True,
            bundle_sha256=fingerprint(captured.payload()), memory_sha256=fingerprint(memory.to_dict()),
            policy_sha256=fingerprint(policy),
            provider_transport="not_attempted", callback_enrollment="not_supported"))
    if report_context is not None:
        from src.editorial.report_development import ReportContext
        require(type(report_context) is ReportContext, "explicit_report_context_required")
        for row in results:
            row["reports_for_evidence_review"] = report_context.annotations(context.binding)
    # Refuse drift during member resolution or construction; this read is the
    # preparation boundary, not permission for a later provider/check grant.
    session.read_current(episode_id, expected_head=revision_sha256)
    require(current_editorial_policy() == policy, "episode_policy_changed")
    return results


@dataclass(frozen=True)
class CycloneEpisodeLane:
    supply: CycloneSupplySession
    episodes: PhysicalEpisodeSession
    operation_id: str
    expected_heads: dict
    now: str
    cities: list

    def validate(self):
        require(type(self.supply) is CycloneSupplySession and type(self.episodes) is PhysicalEpisodeSession,
                "explicit_cyclone_episode_sessions_required")
        require(self.supply.repository is self.episodes.repository, "episode_repository_mismatch")
        environment(self.supply.repository)
        instant(self.now)

    def capture_prepare(self, snapshot, fetch_fn):
        from src.data import nhc
        from src.data.source_status import SourceFetchError
        self.validate()
        require(fetch_fn is nhc.fetch_active_cyclones, "explicit_nhc_source_required")
        observations = []
        try:
            advisories = fetch_fn(strict=True, retention_observer=lambda advisory, metadata: observations.append((advisory, metadata)))
            status = "success"
        except SourceFetchError:
            advisories, status = [row[0] for row in observations], "failed"
        receipt, _, _ = self.supply.capture(advisories, {"status": status}, observations=observations)
        return self.replay_prepare(snapshot, receipt.canonical_sha256)

    def replay_prepare(self, snapshot, run_sha256):
        self.validate()
        result = self.episodes.apply_retained_run(self.supply.supply_run_id, run_sha256,
            operation_id=self.operation_id, expected_heads=self.expected_heads,
            now=self.now, cities=self.cities)
        requests = []
        for outcome in result["episodes"]:
            if outcome["status"] == "committed":
                requests.extend(prepare_episode_requests(self.episodes, outcome["episode_id"],
                    outcome["revision_sha256"], snapshot, now=self.now))
        return dict(result, requests=requests, source_run_id=self.supply.supply_run_id,
            source_receipt_sha256=run_sha256, publication_eligible=False,
            operational_state_mutated=False, provider_transport="not_attempted")
