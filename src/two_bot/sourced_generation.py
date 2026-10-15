"""Shared retained-source preparation and explicit command client; no provider transport."""
from __future__ import annotations

from datetime import timedelta
from copy import deepcopy
import hashlib

from src.commands.schema import CommandError, canonical_json, utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.two_bot.batch_contract import prepare_batch_plan
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.memory import build_memory_slice
from src.two_bot.candidate_derivation import retained_bundle


def refuse(condition, code):
    if not condition:
        raise CommandError(code, "Sourced generation is unavailable; refresh the retained brief")


def source_bundle(value, *, resolved=None):
    try:
        bundle = retained_bundle(value, resolved=resolved)
        refuse(capture_bundle(bundle).payload() == value, "generation_bundle_changed")
        refuse(audit_story_bundle(resolved.full if resolved is not None else bundle).prompt_ready, "generation_evidence_not_ready")
        return bundle
    except (TypeError, ValueError, AttributeError):
        raise CommandError("generation_evidence_not_ready", "Retained source evidence requires repair") from None


def identity(value, state, policy, *, now, epoch, resolved=None):
    bundle = source_bundle(value["bundle"], resolved=resolved)
    memory = build_memory_slice(deepcopy(state), bundle, now=now)
    context = dict(bundle_sha256=fingerprint(value["bundle"]), memory_sha256=fingerprint(memory.to_dict()),
                   policy_sha256=fingerprint(policy), publication_epoch=epoch)
    key = fingerprint(dict(brief_id=hashlib.sha256(canonical_json(value).encode()).hexdigest(), **context))
    return bundle, memory, context, key


def prepare(value, state, policy, *, now, epoch):
    bundle, memory, context, key = identity(value, state, policy, now=now, epoch=epoch)
    raw = prepare_batch_plan(bundle, memory, bundle_sha256=context["bundle_sha256"],
        memory_sha256=context["memory_sha256"], policy=policy, job_id="gs_"+key,
        publication_epoch=epoch, created_at=utc_text(now),
        useful_until=utc_text(min(utc_datetime(value["useful_until"]), now+timedelta(days=7))),
        minimum_window_seconds=3600, urgent=value["urgent"], samples=1)
    return raw, memory.to_dict(), context, key


class SourcedGenerationClient:
    """Explicit automatic caller adapter for the same reference-only command."""
    def __init__(self, authority, principal, resolve, clock):
        self.authority, self.principal, self.resolve, self.clock = authority, principal, resolve, clock

    def submit(self, bundle, *, score, **save):
        from uuid import uuid4
        from src.commands import postgres_sourced_generation as domain
        from src.commands.schema import Command
        now = self.clock()
        expected_save = dict(legacy_type=save["legacy_type"], event_id=save["event_id"],
            score=score.as_dict() if score is not None else None, city=save.get("city", ""),
            tweet_date=save.get("tweet_date", ""), cooldown_exempt=save.get("cooldown_exempt", False),
            review_context=save["review_context"], evaluator_metadata=save.get("draft_metadata"))
        matches = []
        with self.authority.projections._connection() as c:
            self.authority._validate(c)
            version, _ = self.authority._state(c, lock=True)
            for identity in domain.configuration(self.authority)["current_inputs"]:
                value = domain.read(c, domain.INPUT, identity)
                if value["bundle"] == capture_bundle(bundle).payload() and value["save"] == expected_save:
                    matches.append(identity)
        refuse(len(matches) == 1, "generation_source_not_retained")
        from src.editorial.policy import current_editorial_policy
        body = dict(command_id=str(uuid4()), action="request_sourced_generation", requested_at=utc_text(now),
            expires_at=utc_text(now+timedelta(hours=1)), targets=[], payload=dict(brief_id=matches[0],
                brief_sha256=matches[0], expected_state_version=version,
                expected_policy_sha256=fingerprint(current_editorial_policy())))
        command = Command.from_request(body, self.principal, environment="local", now=now)
        self.authority.accept(command, self.principal, now=now)
        try:
            result = self.authority.consume(self.resolve, command_id=command.command_id, now=now)
        except CommandError as exc:
            if exc.code != "command_pending":
                raise
            return dict(generation_status="queued", command_id=command.command_id, job_id=None)
        refuse(result is not None and result["status"] == "applied", result.get("code", "generation_unavailable") if result else "generation_unavailable")
        return dict(result["generation"], command_id=command.command_id)
