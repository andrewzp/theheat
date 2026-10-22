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


def plan_episode_portfolio(session, targets, snapshot, assessments, *, now, writing_attempts,
                           planning_policy=None):
    """Plan from freshly resolved retained episodes, without authorizing writing.

    Assessments are explicit operator judgments bound to exact prepared evidence.
    A caller's JSON cannot stand in for a repository head or a scientific gate.
    """
    from src.data.places import country_key
    from src.editorial.policy import current_editorial_policy
    from src.editorial.portfolio import (BINDING_KEYS, DIMENSIONS, MAX_CANDIDATES,
        PlanningCandidate, plan_portfolio, require as planning_require, validate_binding)
    from src.editorial.revisions import fingerprint

    planning_require(type(session) is PhysicalEpisodeSession, "portfolio_episode_session_required")
    environment(session.repository)
    instant(now)
    planning_require(type(targets) is list and len(targets) <= 16
        and all(type(t) is dict and set(t) == {"episode_id", "revision_sha256"} for t in targets),
        "portfolio_targets_invalid")
    planning_require(type(snapshot) is dict, "portfolio_snapshot_invalid")
    planning_require(type(assessments) is list and len(assessments) <= MAX_CANDIDATES,
                     "portfolio_assessments_invalid")
    # Capture all caller-owned inputs before any repository or prompt preparation.
    targets, snapshot, assessments = deepcopy((targets, snapshot, assessments))
    planning_require(all(type(t["episode_id"]) is str and type(t["revision_sha256"]) is str
                         for t in targets), "portfolio_targets_invalid")
    targets.sort(key=lambda target: target["episode_id"])
    planning_require(len({t["episode_id"] for t in targets}) == len(targets),
                     "portfolio_duplicate_episode")
    policy = current_editorial_policy()
    planning_require(policy is not None, "portfolio_editorial_policy_unavailable")
    policy_sha = fingerprint(policy)
    by_binding = {}
    for assessment in assessments:
        planning_require(type(assessment) is dict
            and set(assessment) == {"binding", "dimensions", "exceptional_reason"},
            "portfolio_assessment_invalid")
        binding = validate_binding(assessment["binding"])
        identity = fingerprint(binding)
        planning_require(identity not in by_binding, "portfolio_duplicate_assessment")
        by_binding[identity] = assessment
    candidates: list[PlanningCandidate] = []
    prepared: dict[str, dict] = {}
    empty: list[dict] = []
    for target in sorted(targets, key=lambda t: t["episode_id"]):
        rows = prepare_episode_requests(session, target["episode_id"], target["revision_sha256"],
                                        snapshot, now=now)
        planning_require(len(candidates) + len(rows) <= MAX_CANDIDATES,
                         "portfolio_candidate_bound")
        if not rows:
            empty.append(dict(target))
        for row in rows:
            episode = row["bundle"]["raw_signal_dump"]["physical_episode"]
            binding = dict(event_group_id=episode["episode_id"],
                event_revision_sha256=episode["revision_sha256"],
                opportunity_id=row["opportunity_id"], bundle_sha256=row["bundle_sha256"],
                policy_sha256=row["policy_sha256"])
            planning_require(set(binding) == BINDING_KEYS and binding["policy_sha256"] == policy_sha,
                             "portfolio_editorial_policy_changed")
            identity = fingerprint(binding)
            judgment = by_binding.pop(identity, None)
            country = row["bundle"].get("country")
            # This is source-scoped editorial geography, never observed impact.
            regions = ((country_key(country),) if country else
                       ("basin:" + episode["episode_id"].rsplit(":", 1)[1][:2],))
            candidates.append(PlanningCandidate(binding, "cyclone", regions,
                {key: None for key in DIMENSIONS} if judgment is None else judgment["dimensions"],
                None if judgment is None else judgment["exceptional_reason"]))
            prepared[identity] = row
    planning_require(not by_binding, "portfolio_assessment_binding_mismatch")
    portfolio = plan_portfolio(candidates, writing_attempts=writing_attempts, policy=planning_policy)
    # Recheck every target, including empty/unselected ones. This report is not a
    # lease, a database snapshot transaction, or a later provider/check grant.
    for target in targets:
        session.prepare_story_context(target["episode_id"], target["revision_sha256"])
    planning_require(current_editorial_policy() == policy, "portfolio_editorial_policy_changed")
    result = dict(portfolio=portfolio, targets=targets, as_of=now,
        empty_episode_targets=empty,
        selected_requests=[prepared[key] for key in portfolio["selected_candidate_ids"]],
        editorial_policy_sha256=policy_sha, currentness="checked_at_preparation_only",
        eligibility_scope="source_currentness_story_audit_and_operator_judgments_only",
        fresh_dispatch_authority_required=True, operational_state_mutated=False,
        provider_transport="not_attempted", callback_enrollment="not_supported",
        publication_approved=False, production_authority=False)
    result["preparation_sha256"] = fingerprint(result)
    return result


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
