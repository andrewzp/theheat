"""Operation-local candidate-attempt budget for one generation operation.

A candidate attempt is one distinct queued story handed to the writer path. With
triage enabled and a valid positive ``THEHEAT_MAX_DRAFTS_PER_CYCLE`` N, one alerts
operation (one ``run_alerts`` call, every drain inside it, including optional
refill) starts the writer for at most N distinct candidates. The leaderboard
operation (Hot10) writes at most its single daily candidate. A rejected attempt
keeps its slot; only an explicit pipeline report that the writer never started
(cache hit or deterministic refusal) returns it. Repeated copies of one event in
the same operation never buy a second attempt.

This is a candidate ceiling, not a provider-call, retry, response or invoice
ceiling: one attempt still runs every required check, and provider retries,
unknown billing and posting limits keep their own rules. Each operation creates
its own budget; nothing here is module-global, persisted or shared between
threads or operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from typing import Any

MAX_ENV = "THEHEAT_MAX_DRAFTS_PER_CYCLE"
TRIAGE_ENV = "THEHEAT_TRIAGE_ENABLED"
DEFAULT_MAX_CANDIDATES = 3  # The bot workflow default and historical cycle cap.
LEADERBOARD_MAX_CANDIDATES = 1  # Hot10 is one daily candidate, never ten posts.
_INTEGER = re.compile(r"\+?[0-9]{1,6}")


class CandidateBudgetConfigError(ValueError):
    """A configured maximum that cannot safely bound an operation; fixed code only."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def configured_max_candidates(environ: Any = None) -> int:
    """The validated N. Unset or empty keeps the historical default of 3.

    A configured value must be a plain positive integer no larger than the
    retained draft store (``caps.MAX_DRAFTS``). Anything else is refused, never
    silently replaced by the default or clamped.
    """
    from src.orchestrator.caps import MAX_DRAFTS
    env = os.environ if environ is None else environ
    raw = env.get(MAX_ENV)
    if raw is None or raw == "":
        return DEFAULT_MAX_CANDIDATES
    text = str(raw).strip()
    if _INTEGER.fullmatch(text) is None:
        raise CandidateBudgetConfigError("max_drafts_per_cycle_not_integer")
    value = int(text)
    if value < 1:
        raise CandidateBudgetConfigError("max_drafts_per_cycle_not_positive")
    if value > MAX_DRAFTS:
        raise CandidateBudgetConfigError("max_drafts_per_cycle_above_bound")
    return value


def triage_enabled(environ: Any = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(TRIAGE_ENV, "0") == "1"


@dataclass
class CandidateBudget:
    """Attempt slots for one operation. ``limit=None`` means no operation limit."""

    operation: str
    limit: int | None
    refusal: str | None = None  # A configuration refusal holds the whole operation.
    attempts: int = 0  # Consumed slots: writer started, or a handoff not proven pre-writer.
    refused_before_writer: int = 0
    held: int = 0
    joined_requests: int = 0  # Physical model requests joined to settled attempts.
    _keys: dict[str, str] = field(default_factory=dict)
    _joins: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_operation(cls, operation: str, environ: Any = None) -> "CandidateBudget":
        """Read configuration once at the start of one operation."""
        enabled = triage_enabled(environ)
        limit: int | None = None
        if enabled:
            try:
                limit = configured_max_candidates(environ)
            except CandidateBudgetConfigError as exc:
                return cls(operation, 0, refusal=exc.code)
        if operation == "leaderboard":
            limit = LEADERBOARD_MAX_CANDIDATES if limit is None else min(limit, LEADERBOARD_MAX_CANDIDATES)
        return cls(operation, limit)

    @staticmethod
    def key_for(candidate: Any) -> str:
        event_id = getattr(candidate, "event_id", "") or ""
        if event_id:
            return "event:" + event_id
        try:  # Sources always set event_id; an exact bundle is the fallback identity.
            payload = json.dumps(candidate.bundle.to_dict(), sort_keys=True, default=str, allow_nan=False)
            return "bundle:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except Exception:
            return f"object:{id(candidate)}"

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(self.limit - self.attempts, 0)

    def exhausted(self) -> bool:
        return self.limit is not None and self.attempts >= self.limit

    def seen(self, key: str) -> bool:
        return key in self._keys

    def reserve(self, key: str) -> bool:
        """Claim one slot before the paid boundary; False if seen or exhausted."""
        if self.seen(key) or self.exhausted():
            return False
        self._keys[key] = "reserved"
        self.attempts += 1
        # Join every physical model request until settle (call_inventory).
        from src.two_bot.call_inventory import open_attempt_join
        self._joins[key] = open_attempt_join(key)
        return True

    def settle(self, key: str, *, writer_started: bool) -> None:
        """A started (or unproven) attempt keeps its slot; a proven pre-writer refusal returns it."""
        if self._keys.get(key) != "reserved":
            raise ValueError("candidate_budget_unreserved")
        joined = self._joins.pop(key, None)
        if joined is not None:
            from src.two_bot.call_inventory import close_attempt_join
            close_attempt_join(*joined)
            dispatched = joined[0].dispatched()
            self.joined_requests += dispatched
            # A dispatched request (returned, malformed, timed out or unknown)
            # can never be refunded, whatever the pipeline report says.
            writer_started = writer_started or dispatched > 0
        if writer_started:
            self._keys[key] = "attempted"
            return
        self._keys[key] = "refused_before_writer"
        self.attempts -= 1
        self.refused_before_writer += 1

    def hold(self, count: int = 1) -> None:
        self.held += count

    def summary(self) -> dict:
        return {"operation": self.operation, "limit": self.limit, "attempts": self.attempts,
                "refused_before_writer": self.refused_before_writer, "held": self.held,
                "refusal": self.refusal, "joined_requests": self.joined_requests}


def writer_started(drafted: bool, result: dict) -> bool:
    """Only an explicit pipeline ``writer_started is False`` proves no writer call.

    A saved draft, a queued/reused asynchronous generation, a missing report or
    anything else counts as a started attempt and keeps its slot.
    """
    if drafted or result.get("generation_status") in {"queued", "reused"}:
        return True
    return result.get("writer_started") is not False


__all__ = ["CandidateBudget", "CandidateBudgetConfigError", "DEFAULT_MAX_CANDIDATES",
           "LEADERBOARD_MAX_CANDIDATES", "configured_max_candidates", "triage_enabled", "writer_started"]
