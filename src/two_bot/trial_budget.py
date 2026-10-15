"""Opt-in finite trial envelope; never a monthly cap or factual authorization."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable, Iterator, NoReturn


MAX_CANDIDATES = 2
MAX_CALLS = 8
MAX_REQUEST_BYTES = 128 * 1024
MAX_ESTIMATED_USD = Decimal("2")
OUTPUT_LIMITS = {"writer": 1024, "safety": 2048, "fact_check": 8192, "critic": 8192}
MODELS = {
    "writer": ("anthropic", "claude-sonnet-4-6"),
    "safety": ("google", "gemini-2.5-flash"),
    "fact_check": ("google", "gemini-2.5-flash"),
    "critic": ("google", "gemini-2.5-pro"),
}
# USD/million tokens; dated standard first-party text scenario, not invoice prices.
# Sonnet includes worst-case five-minute cache-write pricing for every input token.
RATES = {"writer": ("3.75", "15"), "safety": ("0.30", "2.50"),
         "fact_check": ("0.30", "2.50"), "critic": ("1.25", "10")}
_ACTIVE: ContextVar[TrialBudget | None] = ContextVar("theheat_trial_budget", default=None)


class TrialStopped(RuntimeError):
    """A refused or uncertain purchase must not buy a retry or replacement."""


def current_trial() -> TrialBudget | None:
    return _ACTIVE.get()


class TrialBudget:
    def __init__(self, journal: Callable[[dict], None], stop_file: Path):
        self.journal = journal
        self.stop_file = stop_file
        self.candidates: set[str] = set()
        self.candidate: str | None = None
        self.calls: list[dict] = []
        self.estimated_reserved = Decimal(0)
        self.stopped: str | None = None
        self._lock = threading.Lock()

    def stop(self, reason: str) -> NoReturn:
        self.stopped = reason
        raise TrialStopped(reason)

    def begin_candidate(self, event_id: str) -> None:
        if self.stopped:
            raise TrialStopped(self.stopped)
        if not event_id or event_id in self.candidates or len(self.candidates) >= MAX_CANDIDATES:
            self.stop("trial_candidate_limit")
        self.candidates.add(event_id)
        self.candidate = event_id

    def reserve(self, stage: str, provider: str, request: dict) -> dict:
        with self._lock:
            if self.stopped:
                raise TrialStopped(self.stopped)
            if self.stop_file.exists():
                self.stop("trial_stop_requested")
            if not self.candidate or stage not in MODELS:
                self.stop("trial_unassigned_stage")
            if (provider, request.get("model")) != MODELS[stage]:
                self.stop("trial_unpriced_model")
            if len(self.calls) >= MAX_CALLS or any(
                r["candidate"] == self.candidate and r["stage"] == stage for r in self.calls
            ):
                self.stop("trial_retry_or_call_limit")
            bounded = deepcopy(request)
            if provider == "anthropic":
                if set(bounded) - {"model", "system", "messages", "max_tokens", "output_config"}:
                    self.stop("trial_unsupported_request")
                bounded["max_tokens"] = OUTPUT_LIMITS[stage]
            else:
                if set(bounded) - {"model", "contents", "config"}:
                    self.stop("trial_unsupported_request")
                config = bounded.get("config") or {}
                if not isinstance(config, dict):
                    config = config.model_dump(exclude_none=True)
                if set(config) - {"response_mime_type", "response_json_schema"}:
                    self.stop("trial_unsupported_config")
                bounded["config"] = {**config, "max_output_tokens": OUTPUT_LIMITS[stage]}
            try:
                raw = json.dumps(bounded, ensure_ascii=False, allow_nan=False).encode()
            except (TypeError, ValueError, UnicodeError):
                self.stop("trial_invalid_request")
            if len(raw) > MAX_REQUEST_BYTES:
                self.stop("trial_request_size_limit")
            # Deliberately conservative scenario: one UTF-8 request byte per input
            # token, including schema/envelope. This is NOT an exact token counter
            # or a hard provider-invoice ceiling. Hard bytes/calls/output caps are
            # independent; no discounts/free tier/unknown charge refunds assumed.
            incoming, outgoing = (Decimal(v) for v in RATES[stage])
            reserve = (len(raw) * incoming + OUTPUT_LIMITS[stage] * outgoing) / 1_000_000
            if self.estimated_reserved + reserve > MAX_ESTIMATED_USD:
                self.stop("trial_estimated_allowance_exhausted")
            row = {"ordinal": len(self.calls) + 1, "candidate": self.candidate,
                   "stage": stage, "provider": provider, "model": bounded["model"],
                   "request_sha256": hashlib.sha256(raw).hexdigest(), "request_bytes": len(raw),
                   "output_token_limit": OUTPUT_LIMITS[stage],
                   "reserved_estimate_usd": str(reserve), "actual_cost_known": False,
                   "outcome": "reserved_before_dispatch"}
            # The caller must durably fsync this BEFORE the provider can run.
            try:
                self.journal(row)
            except Exception:
                self.stopped = "trial_journal_failed"
                raise
            self.calls.append(row)
            self.estimated_reserved += reserve
            return bounded


@contextmanager
def trial_scope(budget: TrialBudget) -> Iterator[None]:
    if current_trial() is not None:
        raise TrialStopped("trial_already_active")
    token = _ACTIVE.set(budget)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def google_trial_options() -> dict:
    if current_trial() is None:
        return {}
    from google.genai import types
    return {"retry_options": types.HttpRetryOptions(attempts=1)}


def provider_call(stage: str, provider: str, request: dict, send: Callable):
    budget = current_trial()
    if budget is None:
        return send(**request)
    bounded = budget.reserve(stage, provider, request)
    try:
        response = send(**bounded)
    except BaseException:
        budget.stopped = "trial_provider_outcome_unknown"
        raise
    # Returned responses are not bill reconciliation. Never refund a reservation.
    try:
        budget.journal({"ordinal": len(budget.calls), "stage": stage,
                        "outcome": "response_returned", "actual_cost_known": False})
    except Exception:
        budget.stopped = "trial_journal_failed_after_dispatch"
        raise
    return response
