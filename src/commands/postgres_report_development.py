"""Metadata-only report intake under the existing local command transaction."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.report_development import prepare_report_development, review_projection
from src.storage import postgres_projection as p
from src.storage.retained_reports import (RetainedReportSession, ReportError, digest, fixed,
    frozen, identifier, require, sha)

DEVELOPMENT = "report-development-v1"
MAX_ITEMS = 16


def private_configuration(path):
    path = Path(path)
    require(path.is_absolute(), "report_configuration_invalid")
    def load():
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
                    and stat.S_IMODE(metadata.st_mode) == 0o600 and metadata.st_size <= 16384, "report_configuration_invalid")
            from src.commands.preview_ingress import strict_json
            return strict_json(stream.read(16385))
    return load


def configuration(authority):
    load = getattr(authority, "report_configuration", None)
    require(authority.environment == "local" and callable(load), "report_development_unavailable")
    assert callable(load)
    value = frozen(load())
    fixed(value, "current_reports decision_refs")
    require(type(value["current_reports"]) is list and len(value["current_reports"]) <= MAX_ITEMS, "report_configuration_bound")
    require(type(value["decision_refs"]) is list and len(value["decision_refs"]) <= 32)
    seen = set()
    for row in value["current_reports"]:
        fixed(row, "lineage_id report_sha256 episode_reference")
        identifier(row["lineage_id"])
        sha(row["report_sha256"])
        require(row["lineage_id"] not in seen, "report_configuration_invalid")
        seen.add(row["lineage_id"])
        if row["episode_reference"] is not None:
            fixed(row["episode_reference"], "episode_id revision_sha256 claim_id")
            sha(row["episode_reference"]["revision_sha256"])
            identifier(row["episode_reference"]["claim_id"])
    for ref in value["decision_refs"]:
        fixed(ref, "namespace snapshot_id sha256")
        require(ref["namespace"] == "report-human-decision-v1", "report_review_unavailable")
        sha(ref["snapshot_id"])
        sha(ref["sha256"])
    return value


def configured_session(authority, config):
    return RetainedReportSession(authority.projections, tuple(config["decision_refs"]))


def _item_id(lineage_id):
    return "rd_"+digest(lineage_id)


def _latest(c, lineage_id):
    prefix = _item_id(lineage_id)+":"
    row = c.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id >= %s AND snapshot_id < %s ORDER BY snapshot_id DESC LIMIT 1", (DEVELOPMENT, prefix, prefix[:-1]+";")).fetchone()
    if row is None:
        return None
    receipt, value = p.PostgresProjectionRepository._read(c, DEVELOPMENT, row[0])
    fixed(value, "schema_version item_id sequence previous_sha256 report_sha256 episode_reference review prepared_story_refs opened_at")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    require(type(value["sequence"]) is int and 1 <= value["sequence"] <= 512)
    require(value["item_id"] == _item_id(lineage_id) and row[0] == prefix+f'{value["sequence"]:010d}')
    return receipt, value


def projection(authority, *, now):
    config = configuration(authority)
    session = configured_session(authority, config)
    rows = []
    for ref in config["current_reports"]:
        try:
            receipt, document = session.read_current(ref["lineage_id"], ref["report_sha256"])
            row = review_projection(receipt, document)
            row["episode_reference"] = frozen(ref["episode_reference"])
            row["expected_policy_sha256"] = digest(current_editorial_policy())
            with authority.projections._connection() as c:
                authority._validate(c)
                latest = _latest(c, ref["lineage_id"])
            if latest:
                value = latest[1]
                current = value["report_sha256"] == ref["report_sha256"] and value["episode_reference"] == ref["episode_reference"]
                row["development_status"] = "evidence_review_required" if current else "evidence_changed_refresh_required"
                row["development"] = dict(item_id=value["item_id"], item_sha256=latest[0].canonical_sha256,
                                          opened_at=value["opened_at"], current=current)
                # Stale associations are never displayed as current. Re-resolve
                # exact report/episode head and actual request only on opening.
                if current and value["episode_reference"] is not None:
                    from src.editorial.report_development import resolve_story_context
                    try:
                        _, checked = resolve_story_context(session, ref["lineage_id"], ref["report_sha256"], ref["episode_reference"])
                        row["related_story"] = checked["related_story"]
                    except (ValueError, TypeError):
                        row["development_status"] = "evidence_changed_refresh_required"
                        row["development"]["current"] = False
            rows.append(row)
        except (ReportError, p.ProjectionError, ValueError, TypeError):
            rows.append(dict(lineage_id=ref["lineage_id"], report_sha256=ref["report_sha256"],
                source_label="Report unavailable", claims=[], holds=["retained_evidence_unavailable"],
                development_status="unavailable", episode_reference=None, related_story=None,
                generation_available=False, publication_enabled=False))
    require(configuration(authority) == config, "report_configuration_changed")
    return dict(enabled=True, reports=rows, reviewed_at=utc_text(now), generation_available=False, publication_enabled=False)


@dataclass(frozen=True)
class ReportTransition:
    outcome: dict


def prepare(authority, c, state, command, actor, *, now, editorial_policy):
    """Called inside the command savepoint; no draft or provider reservation."""
    authorize(actor, command.action)
    require(command.action == "open_report_evidence" and actor.subject == command.actor_subject
            and actor.authentication_context == command.authentication_context, "report_actor_changed")
    require(now < utc_datetime(command.expires_at), "report_command_expired")
    payload = command.payload
    fixed(payload, "lineage_id report_sha256 expected_policy_sha256 episode_reference")
    require(payload["expected_policy_sha256"] == digest(editorial_policy), "report_policy_changed")
    config = configuration(authority)
    matches = [ref for ref in config["current_reports"] if ref["lineage_id"] == payload["lineage_id"]]
    require(len(matches) == 1 and matches[0]["report_sha256"] == payload["report_sha256"]
            and matches[0]["episode_reference"] == payload["episode_reference"], "report_not_currently_configured")
    lineage = payload["lineage_id"]
    # The command authority already serializes its own consumer. Also hold the
    # report/episode writers' existing deterministic locks through final commit.
    lock = int(digest(lineage)[:16], 16)
    c.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock-2**64,))
    episode = payload["episode_reference"]
    if episode is not None:
        lock = int(digest(episode["episode_id"])[:16], 16)
        c.execute("SELECT pg_advisory_xact_lock(%s)", (lock if lock < 2**63 else lock-2**64,))
    session = configured_session(authority, config)
    developed = prepare_report_development(session, lineage, payload["report_sha256"], episode_reference=episode, snapshot=state, now=utc_text(now))
    refs = [dict(opportunity_id=row["opportunity_id"], bundle_sha256=row["bundle_sha256"],
                 memory_sha256=row["memory_sha256"], policy_sha256=row["policy_sha256"],
                 writer_request_sha256=digest(row["writer_request"])) for row in developed["prepared_stories"]]
    latest = _latest(c, lineage)
    reused = bool(latest and latest[1]["report_sha256"] == payload["report_sha256"]
                  and latest[1]["episode_reference"] == episode and latest[1]["prepared_story_refs"] == refs)
    if reused:
        receipt = latest[0]
        value = latest[1]
    else:
        sequence = latest[1]["sequence"]+1 if latest else 1
        require(sequence <= 512, "report_development_bound")
        value = dict(schema_version=1, item_id=_item_id(lineage), sequence=sequence,
            previous_sha256=latest[0].canonical_sha256 if latest else None, report_sha256=payload["report_sha256"],
            episode_reference=frozen(episode), review=developed["report"], prepared_story_refs=refs, opened_at=utc_text(now))
        raw, fields = p._snapshot(value)
        receipt = p.PostgresProjectionRepository._record(c, DEVELOPMENT, value["item_id"]+f':{sequence:010d}', raw, fields)
    require(configuration(authority) == config and digest(current_editorial_policy()) == digest(editorial_policy), "report_context_changed")
    return ReportTransition(dict(item_id=value["item_id"], item_sha256=receipt.canonical_sha256,
        lineage_id=lineage, report_sha256=payload["report_sha256"], status="evidence_review_required", reused=reused,
        draft_mutated=False, provider_request_created=False, publication_enabled=False))


def expected_failure(exc):
    if isinstance(exc, ReportError):
        return CommandError(str(exc), "Retained report evidence changed or requires review. Refresh this report.")
    raise exc
