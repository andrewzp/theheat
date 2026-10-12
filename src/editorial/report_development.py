"""Read-only report review context beside the actual physical story consumer.

No report claim is placed in writer facts, impact, memory or generation input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from src.storage import postgres_projection as p
from src.storage.retained_reports import (RetainedReportSession, fixed,
    frozen, require, sha)
from src.storage.physical_events import PhysicalEpisodeSession


@dataclass(frozen=True)
class ReportContext:
    """Resolved reference context, bound to one current physical episode head."""
    encoded: bytes

    def annotations(self, physical_binding):
        value = p._decode(self.encoded)
        expected = value["episode_reference"]
        require(physical_binding["episode_id"] == expected["episode_id"]
                and physical_binding["revision_sha256"] == expected["revision_sha256"], "report_episode_context_changed")
        return frozen(value["reports_for_evidence_review"])


def review_projection(receipt, document):
    """Explicit whitelist; no private paths, original binaries or raw HTML."""
    claims = []
    holds = {"report_claims_not_promoted"}
    if document["legacy_metadata"] is not None:
        holds.add("original_report_evidence_missing")
    for claim in document["claims"]:
        claim_holds = set(claim["holds"])
        if claim["source_review"]["status"] != "human_reviewed":
            claim_holds.add("source_review_pending")
        if claim["translation"]["status"] == "unreviewed":
            claim_holds.add("translation_review_pending")
        if any(claim["times"][key] is None or claim["times"][key]["precision"] == "unknown" for key in ("event_start", "event_end")):
            claim_holds.add("event_window_unresolved")
        holds.update(claim_holds)
        claims.append(dict(claim_id=claim["claim_id"], kind=claim["kind"], summary=claim["summary"],
            original_language=claim["original_language"], excerpts=[dict(text=anchor["text"], artifact_id=anchor["artifact_id"],
                content_sha256=anchor["content_sha256"], start=anchor["start"], end=anchor["end"]) for anchor in claim["anchors"]],
            translation=frozen(claim["translation"]), attribution=claim["attribution"], times=frozen(claim["times"]),
            quantity=frozen(claim["quantity"]), geography=frozen(claim["geography"]), holds=sorted(claim_holds)))
    return dict(lineage_id=document["lineage_id"], report_sha256=receipt.canonical_sha256,
        source_label=document["publisher"], source_url=document["source_url"], original_language=document["original_language"],
        claims=claims, upstream_lineage_refs=list(document["upstream_lineage_refs"]), limits=list(document["limits"]),
        holds=sorted(holds), reference_review=frozen(document["reference_review"]), development_status="not_opened",
        related_story=None, generation_available=False, publication_enabled=False)


def _window(claim):
    values = [claim["times"][key] for key in ("event_start", "event_end")]
    if any(value is None or value["precision"] == "unknown" for value in values):
        return None
    if values[0]["precision"] != values[1]["precision"]:
        return None
    from src.commands.schema import utc_datetime
    if values[0]["precision"] == "instant":
        start, end = (utc_datetime(value["utc"]) for value in values)
        return (start, end, "explicit_utc_interval") if start <= end else None
    start_date, end_date = (date.fromisoformat(value["date"]) for value in values)
    return (start_date, end_date, "source_calendar_compatibility_only") if start_date <= end_date else None


def resolve_story_context(session, lineage_id, report_sha256, episode_reference):
    """No name/nearby/date-only match; exact source mention remains review-only."""
    require(type(session) is RetainedReportSession, "explicit_report_session_required")
    receipt, document = session.read_current(lineage_id, sha(report_sha256))
    projection = review_projection(receipt, document)
    fixed(episode_reference, "episode_id revision_sha256 claim_id")
    sha(episode_reference["revision_sha256"])
    claims = [claim for claim in document["claims"] if claim["claim_id"] == episode_reference["claim_id"]]
    require(len(claims) == 1, "report_claim_unavailable")
    claim = claims[0]
    identity = claim["identity_reference"]
    require(document["legacy_metadata"] is None and identity is not None, "report_episode_reference_unresolved")
    require(identity["authority"] == "nhc" and re.fullmatch(r"(?:AL|EP)(?:0[1-9]|[1-4][0-9])[0-9]{4}", identity["source_id"])
            and int(identity["source_id"][-4:]) > 0, "report_episode_reference_unresolved")
    require(episode_reference["episode_id"] == "ep1:cyclone:nhc:"+identity["source_id"], "report_episode_reference_changed")
    require(claim["original_language"] == "en" or claim["translation"]["status"] == "human_reviewed", "report_translation_unreviewed")
    require(claim["geography"]["role"] != "meeting_location" and not any(
        code in claim["holds"] for code in ("identity_unresolved", "event_window_unresolved", "geography_inconsistent")), "report_association_held")
    window = _window(claim)
    require(window is not None, "report_event_window_unresolved")
    episodes = PhysicalEpisodeSession(session.repository)
    _, revision = episodes.prepare_story_context(episode_reference["episode_id"], episode_reference["revision_sha256"])
    from src.storage.cyclone_supply import instant
    observations = [instant(item["advisory"]["issued_at"]) for item, status in episodes._records(revision["members"])
                    if status == "success"]
    start, end, compatibility = window
    if compatibility == "source_calendar_compatibility_only":
        observations = [value.date() for value in observations]
    require(start <= max(observations) and min(observations) <= end, "report_episode_window_changed")
    session.read_current(lineage_id, report_sha256)
    episodes.read_current(episode_reference["episode_id"], expected_head=episode_reference["revision_sha256"])
    projection["related_story"] = dict(episode_id=episode_reference["episode_id"], episode_head=episode_reference["revision_sha256"],
        association_status="source_identity_reference_only", time_compatibility=compatibility)
    context = ReportContext(p._canonical(dict(episode_reference=frozen(episode_reference), reports_for_evidence_review=[projection])))
    return context, projection


def prepare_report_development(session, lineage_id, report_sha256, *, episode_reference, snapshot, now):
    """Actual story preparation when explicitly linked; otherwise held intake."""
    receipt, document = session.read_current(lineage_id, report_sha256)
    projection = review_projection(receipt, document)
    prepared = []
    if episode_reference is not None:
        context, projection = resolve_story_context(session, lineage_id, report_sha256, episode_reference)
        from src.orchestrator.cyclone_episodes import prepare_episode_requests
        prepared = prepare_episode_requests(PhysicalEpisodeSession(session.repository), episode_reference["episode_id"],
            episode_reference["revision_sha256"], snapshot, now=now)
        # Before the shared hook is integrated, keep this annotation outside
        # every prepared bundle, memory and request. It cannot change the hash
        # of factual generation inputs or create a new provider permission.
        for row in prepared:
            row["reports_for_evidence_review"] = context.annotations(row["bundle"]["raw_signal_dump"]["physical_episode"])
    session.read_current(lineage_id, report_sha256)
    projection["development_status"] = "evidence_review_required"
    return dict(report=projection, prepared_stories=prepared, generation_available=False, publication_enabled=False)
