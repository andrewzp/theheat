"""Declared spend/egress call stages, per-operation joins and ceiling semantics.

Every route that can create provider, data, platform or hosting spend has one
declaration here, and its real call site consumes that declaration immediately
before the physical call (``consume``). An undeclared stage is refused before
egress. Pricing is never zero: ``estimate_partial`` means a retained token
estimate exists for some dimensions while the charge stays unknown; ``unknown``
means no estimate exists at all.

``operation_scope`` joins every consumed call inside one operation (an alerts
run, Hot10, a manual or maintenance command) and the active candidate attempt
(``src.orchestrator.candidate_budget``) to request rows. A dispatched request
that never reports an outcome stays ``dispatched`` (interrupted, unknown) and a
timeout, malformed response or exception never becomes a free attempt. Only a
reservation proven unstarted may be released.

``OperationAllowance`` is a finite per-operation physical-call allowance with
reserve-before-egress semantics (used by news discovery). It is process-local:
nothing here is a cross-process lock, an invoice ceiling or a hard financial
cap. Gist state accounting is not transactional and is never labelled as one.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import os
import threading
from typing import Any, Iterator, Mapping

SPEND_CLASSES = ("discovery", "selection", "acquisition", "platform", "hosting", "maintenance", "evaluation")
PRICING = ("estimate_partial", "unknown")
PATHS = ("ordinary", "manual", "batch", "maintenance")
OUTCOMES = ("dispatched", "returned", "malformed", "unavailable", "unknown", "released_unstarted")
MAX_JOIN_ROWS = 64
MAX_OPERATION_ROWS = 8


class UndeclaredCallError(RuntimeError):
    """A physical call stage without a declaration; refused before egress."""


class BackgroundLaneDisabled(RuntimeError):
    """An opt-in background lane is not exactly enabled; refused before construction."""

    def __init__(self, lane: str):
        super().__init__(f"background_lane_disabled:{lane}")
        self.lane = lane


@dataclass(frozen=True)
class CallDeclaration:
    stage: str
    spend_class: str
    providers: tuple[str, ...]
    physical_call: str
    allowance: str
    pricing: str
    paths: tuple[str, ...]
    call_site: str
    unpriced_dimensions: tuple[str, ...] = ()
    background_lane: str | None = None

    def public(self) -> dict:
        return {"stage": self.stage, "spend_class": self.spend_class, "providers": list(self.providers),
                "physical_call": self.physical_call, "allowance": self.allowance, "pricing": self.pricing,
                "paths": list(self.paths), "call_site": self.call_site,
                "unpriced_dimensions": list(self.unpriced_dimensions), "background_lane": self.background_lane,
                "actual_cost_known": False}


def _d(stage, spend_class, providers, physical_call, allowance, pricing, paths, call_site, unpriced=(), lane=None):
    return CallDeclaration(stage, spend_class, tuple(providers), physical_call, allowance, pricing,
                           tuple(paths), call_site, tuple(unpriced), lane)


_CHARGE = ("actual_charge",)
DECLARATIONS: dict[str, CallDeclaration] = {d.stage: d for d in (
    _d("writer", "selection", ("anthropic", "google"), "sdk_generate", "candidate_attempt", "estimate_partial",
       ("ordinary", "manual"), "src.two_bot.trial_budget:provider_call", _CHARGE),
    _d("safety", "selection", ("google",), "sdk_generate", "candidate_attempt", "estimate_partial",
       ("ordinary", "manual"), "src.two_bot.trial_budget:provider_call", _CHARGE),
    _d("fact_check", "selection", ("google",), "sdk_generate", "candidate_attempt", "estimate_partial",
       ("ordinary", "manual"), "src.two_bot.trial_budget:provider_call", _CHARGE),
    _d("critic", "selection", ("google",), "sdk_generate", "candidate_attempt", "estimate_partial",
       ("ordinary", "manual"), "src.two_bot.trial_budget:provider_call", _CHARGE),
    _d("newsworthiness_search", "discovery", ("google",), "sdk_generate", "news_discovery", "estimate_partial",
       ("ordinary",), "src.data.newsworthiness:_call_grounded_search", _CHARGE + ("search_grounding_tool",)),
    _d("newsworthiness_verify", "discovery", ("google",), "sdk_generate", "news_discovery", "estimate_partial",
       ("ordinary",), "src.data.newsworthiness:_call_verify_flash", _CHARGE),
    _d("news_verification_page", "discovery", ("publisher",), "http_get", "news_discovery", "unknown",
       ("ordinary",), "src.data.newsworthiness:_verify_grounded", ("egress",)),
    _d("source_http_get", "acquisition", ("source",), "http_get", "source_runner", "unknown",
       ("ordinary", "manual", "maintenance"), "src.data._http:fetch_with_retry", ("egress", "source_plan")),
    _d("gist_state", "hosting", ("github",), "http_request", "state_io", "unknown",
       ("ordinary", "manual", "maintenance"), "src.state:_consume_gist_request", ("hosting_plan",)),
    _d("x_publish", "platform", ("x",), "sdk_request", "daily_publication_cap", "unknown",
       ("ordinary", "manual"), "src.posting.twitter:create_post", ("platform_plan",)),
    _d("bluesky_publish", "platform", ("bluesky",), "sdk_request", "daily_publication_cap", "unknown",
       ("ordinary", "manual"), "src.posting.bluesky:create_post", ("platform_plan",)),
    _d("x_metrics_read", "maintenance", ("x",), "sdk_request", "metrics_daily_gate", "unknown",
       ("maintenance",), "src.data.twitter_metrics:fetch_metrics", ("platform_plan",), "metrics"),
    _d("batch_writer", "selection", ("anthropic",), "sdk_batch_submit", "local_spend_journal", "estimate_partial",
       ("batch",), "src.two_bot.batch_transport:AnthropicBatchTransport.submit", _CHARGE + ("batch_discount",)),
    _d("synchronous_writer", "selection", ("anthropic",), "sdk_generate", "local_spend_journal", "estimate_partial",
       ("manual",), "src.two_bot.synchronous_writer:execute_writer_once", _CHARGE),
    _d("local_required_check", "selection", ("google",), "sdk_generate", "local_spend_journal", "estimate_partial",
       ("manual", "batch"), "src.two_bot.check_transport:GoogleCheckTransport.execute", _CHARGE),
    _d("paid_evaluation", "evaluation", ("anthropic", "google"), "sdk_generate", "workflow_job_gate", "unknown",
       ("maintenance",), "scripts.writer_dryrun:main", _CHARGE, "paid_evaluation"),
    # Replay/canary pytest runs: exact job gates in voice-regression.yml plus the
    # default ``-m 'not voice_replay'`` deselection; no step-level mirror by design.
    _d("paid_pr_replay", "evaluation", ("anthropic", "google"), "sdk_generate", "workflow_job_gate", "unknown",
       ("maintenance",), ".github/workflows/voice-regression.yml:THEHEAT_PAID_PR_REPLAY_ENABLED", _CHARGE,
       "paid_pr_replay"),
    _d("selfheal_repair", "maintenance", ("anthropic", "github"), "workflow_agent", "workflow_job_gate", "unknown",
       ("maintenance",), ".github/workflows/workflow-self-heal.yml:repair_preflight", _CHARGE, "selfheal_repair"),
    # Visibility bucket for a provider_call stage/provider missing from this table:
    # counted and shown as unpriced, never silently free. Source tests keep it empty.
    _d("undeclared_provider_call", "selection", ("anthropic", "google"), "sdk_generate", "none_declared", "unknown",
       PATHS, "src.two_bot.trial_budget:provider_call", ("actual_charge", "undeclared_route")),
        _d("threshold_acquisition", "acquisition", ("noaa",), "http_get", "production_pause_gate", "unknown",
       ("maintenance",), "scripts.update_thresholds_incremental:_consume_acquisition", ("egress", "runner_minutes")),
)}

# How each declared stage is (or is not) captured by the explicit private request
# archive (``request_archive``; default OFF). "uncaptured_model" stages are model
# requests the archive cannot record; while a capture scope is open they are
# refused before egress and the refusal is recorded in the scope manifest.
ARCHIVE_CAPTURE: dict[str, str] = {
    **{s: "provider_call_seam" for s in ("writer", "safety", "fact_check", "critic", "undeclared_provider_call")},
    "batch_writer": "route_family:batch_submit", "local_required_check": "route_family:command_check",
    "synchronous_writer": "engine_retained_observation",
    "newsworthiness_search": "uncaptured_model", "newsworthiness_verify": "uncaptured_model",
    "paid_evaluation": "provider_call_seam", "paid_pr_replay": "provider_call_seam",
    "selfheal_repair": "uncaptured_external_agent",
}


# Exact "1" opt-in flags at the real call boundary; anything else is disabled.
BACKGROUND_LANES: dict[str, str] = {
    "metrics": "THEHEAT_METRICS_ENABLED",
    "paid_evaluation": "THEHEAT_PAID_EVALUATION_ENABLED",
    "paid_pr_replay": "THEHEAT_PAID_PR_REPLAY_ENABLED",
    "selfheal_repair": "THEHEAT_SELFHEAL_REPAIR_ENABLED",
}
# A PR replay is a paid evaluation; both exact flags are required.
_LANE_REQUIRES = {"paid_pr_replay": ("paid_evaluation",)}

# Operation -> the stages it may call (shown before an action runs).
OPERATIONS: dict[str, tuple[str, ...]] = {
    "alerts": ("source_http_get", "newsworthiness_search", "newsworthiness_verify", "news_verification_page",
               "writer", "safety", "fact_check", "critic", "gist_state"),
    "leaderboard": ("source_http_get", "writer", "safety", "fact_check", "critic", "x_metrics_read", "gist_state"),
    "publish": ("x_publish", "bluesky_publish", "gist_state"),
    "manual_generation": ("synchronous_writer", "local_required_check"),
    "batch_generation": ("batch_writer", "local_required_check"),
    "threshold_refresh": ("threshold_acquisition",),
}

# Ceiling kinds are distinct; none of them is a monthly or invoice cap.
CEILING_KINDS: dict[str, dict] = {
    "candidate_attempts": {"unit": "writer_started_candidates", "financial_cap": False, "enforced": True,
                           "guarantee": "process_local_one_operation"},
    "provider_call_cap": {"unit": "physical_provider_calls", "financial_cap": False, "enforced": True,
                          "guarantee": "process_local_one_operation"},
    "estimated_token_cap": {"unit": "scenario_usd_estimate", "financial_cap": False, "enforced": True,
                            "guarantee": "finite_trial_journal_before_dispatch"},
    "local_spend_allowance": {"unit": "reserved_micro_usd", "financial_cap": False, "enforced": True,
                              "guarantee": "sqlite_transaction_local_authority"},
    "daily_publication_cap": {"unit": "posts_per_utc_day", "financial_cap": False, "enforced": True,
                              "guarantee": "gist_state_nontransactional"},
    "monthly_budget_watch": {"unit": "recorded_estimate_usd", "financial_cap": False, "enforced": False,
                             "guarantee": "alert_only_incomplete_coverage"},
    "invoice_ceiling": {"unit": "provider_invoice", "financial_cap": True, "enforced": False,
                        "guarantee": "not_implemented_no_invoice_access"},
}
PATH_CEILINGS: dict[str, tuple[str, ...]] = {
    "ordinary": ("candidate_attempts", "provider_call_cap", "daily_publication_cap", "monthly_budget_watch",
                 "invoice_ceiling"),
    "manual": ("estimated_token_cap", "provider_call_cap", "local_spend_allowance", "daily_publication_cap",
               "invoice_ceiling"),
    "batch": ("local_spend_allowance", "provider_call_cap", "invoice_ceiling"),
    "maintenance": ("provider_call_cap", "invoice_ceiling"),
}

_LOCK = threading.Lock()
_RUNTIME_COUNTS: dict[str, int] = {}


def declaration(stage: str) -> CallDeclaration:
    found = DECLARATIONS.get(stage) if isinstance(stage, str) else None
    if found is None:
        raise UndeclaredCallError("undeclared_call_stage")
    return found


def background_lane_enabled(lane: str, environ: Mapping[str, str] | None = None) -> bool:
    if lane not in BACKGROUND_LANES:
        raise UndeclaredCallError("undeclared_background_lane")
    env = os.environ if environ is None else environ
    return all(env.get(BACKGROUND_LANES[name]) == "1" for name in (*_LANE_REQUIRES.get(lane, ()), lane))


def require_background_lane(lane: str, environ: Mapping[str, str] | None = None) -> None:
    """Refuse before any client/provider construction unless exactly opted in."""
    if not background_lane_enabled(lane, environ):
        raise BackgroundLaneDisabled(lane)


@dataclass
class CallTicket:
    stage: str
    provider: str
    model: str | None
    ordinal: int
    outcome: str = "dispatched"
    _rows: tuple = ()

    def settle(self, outcome: str) -> None:
        """Record a terminal outcome once; a started call can never be released."""
        if outcome not in OUTCOMES[1:-1]:
            raise ValueError("invalid_call_outcome")
        with _LOCK:
            if self.outcome != "dispatched":
                return
            self.outcome = outcome
            for row in self._rows:
                row["outcome"] = outcome


@dataclass
class _Join:
    kind: str
    name: str
    path: str
    rows: list
    overflow: int = 0
    closed: bool = False

    def add(self, row: dict) -> dict | None:
        if self.closed:
            return None
        if len(self.rows) >= MAX_JOIN_ROWS:
            self.overflow += 1
            return None
        self.rows.append(row)
        return row

    def dispatched(self) -> int:
        return len(self.rows) + self.overflow

    def counts(self) -> dict:
        out = {name: 0 for name in OUTCOMES}
        for row in self.rows:
            out[row["outcome"]] += 1
        out["dispatched"] += self.overflow  # Unrecorded rows stay unknown, never free.
        return out


_OPERATION: ContextVar[_Join | None] = ContextVar("theheat_operation_join", default=None)
_ATTEMPT: ContextVar[_Join | None] = ContextVar("theheat_attempt_join", default=None)


def consume(stage: str, *, provider: str | None = None, model: str | None = None,
            join: bool = True) -> CallTicket:
    """The real call site's declaration consumption, immediately before egress.

    ``join=False`` counts the physical call without adding an operation or
    attempt request row (state I/O and per-attempt source fetches).
    """
    found = declaration(stage)
    chosen = provider if provider is not None else found.providers[0]
    if chosen not in found.providers:
        raise UndeclaredCallError("undeclared_call_provider")
    if ARCHIVE_CAPTURE.get(stage) == "uncaptured_model":
        _refuse_uncaptured_in_open_archive()
    with _LOCK:
        _RUNTIME_COUNTS[stage] = _RUNTIME_COUNTS.get(stage, 0) + 1
        ordinal = _RUNTIME_COUNTS[stage]
        rows = []
        for active in ((_OPERATION.get(), _ATTEMPT.get()) if join else ()):
            if active is not None:
                row = active.add({"stage": stage, "provider": chosen,
                                "model": model if isinstance(model, str) and len(model) <= 80 else None,
                                "spend_class": found.spend_class, "pricing": found.pricing,
                                "outcome": "dispatched"})
                if row is not None:
                    rows.append(row)
    return CallTicket(stage, chosen, model, ordinal, _rows=tuple(rows))


def _refuse_uncaptured_in_open_archive() -> None:
    """Missing capture is explicit: an open capture scope never silently misses a model call."""
    from src.two_bot import request_archive
    opened = request_archive._OPEN_SCOPE
    if opened is None:
        return
    opened._note_foreign_refusal()  # Existing closed record kind: a refused, uncaptured call.
    raise request_archive.RequestArchiveRefused("archive_route_uncaptured")


def archive_coverage() -> dict:
    """Per-stage archive capture mode; anything not listed is not a model request."""
    return {stage: ARCHIVE_CAPTURE.get(stage, "not_a_model_request") for stage in DECLARATIONS}


def consume_provider_stage(stage: str, provider: str, model: str | None) -> CallTicket:
    """provider_call's consumption: an unknown stage/provider is counted, not dropped."""
    found = DECLARATIONS.get(stage) if isinstance(stage, str) else None
    if found is None or provider not in found.providers or stage == "undeclared_provider_call":
        if provider not in ("anthropic", "google"):
            raise UndeclaredCallError("undeclared_call_provider")
        return consume("undeclared_provider_call", provider=provider, model=model)
    return consume(stage, provider=provider, model=model)


def runtime_counts() -> dict[str, int]:
    with _LOCK:
        return dict(_RUNTIME_COUNTS)


def inventory() -> dict:
    """The declared inventory joined to this process's consumed physical calls."""
    counts = runtime_counts()
    return {"schema_version": 1, "actual_cost_known": False, "invoice_reconciled": False,
            "declarations": [{**d.public(), "consumed_physical_calls": counts.get(d.stage, 0)}
                             for d in DECLARATIONS.values()],
            "archive_capture": archive_coverage(), "background_lanes": dict(BACKGROUND_LANES), "operations": {k: list(v) for k, v in OPERATIONS.items()},
            "ceilings": CEILING_KINDS, "path_ceilings": {k: list(v) for k, v in PATH_CEILINGS.items()}}


@contextmanager
def operation_scope(operation: str, path: str = "ordinary") -> Iterator[_Join]:
    if operation not in OPERATIONS or path not in PATHS:
        raise UndeclaredCallError("undeclared_operation")
    join = _Join("operation", operation, path, [])
    token = _OPERATION.set(join)
    try:
        yield join
    finally:
        join.closed = True
        _OPERATION.reset(token)


def open_attempt_join(key: str) -> tuple[_Join, Any]:
    """Join physical calls to one candidate attempt; the caller closes it.

    Attempts never nest: a join left open by an escaped exception is closed
    here, so its rows cannot absorb a later candidate's requests.
    """
    stale = _ATTEMPT.get()
    if stale is not None:
        stale.closed = True
    join = _Join("attempt", hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], "ordinary", [])
    return join, _ATTEMPT.set(join)


def close_attempt_join(join: _Join, token: Any = None) -> None:
    """Close without restoring an earlier (stale) attempt as the active one."""
    join.closed = True
    if _ATTEMPT.get() is join:
        _ATTEMPT.set(None)


def current_attempt_join() -> _Join | None:
    return _ATTEMPT.get()


class OperationAllowance:
    """Finite physical-call slots for one operation; reserve strictly before egress.

    ``reserve`` returns False when the stage has no slot left, so the caller
    stops before another paid call. Every reserved slot stays consumed unless
    ``release_unstarted`` proves no physical attempt happened. Outcomes are kept
    separately; unknown and malformed results remain spent.
    """

    def __init__(self, operation: str, limits: Mapping[str, int]):
        for stage, limit in limits.items():
            declaration(stage)
            if type(limit) is not int or limit < 0:
                raise ValueError("invalid_allowance_limit")
        self.operation = operation
        self.limits = dict(limits)
        self.reserved = {stage: 0 for stage in limits}
        self.physical_attempts = {stage: 0 for stage in limits}
        self.refused = {stage: 0 for stage in limits}
        self.outcomes = {stage: {name: 0 for name in OUTCOMES[1:]} for stage in limits}
        self._lock = threading.Lock()

    def remaining(self, stage: str) -> int:
        return max(self.limits[stage] - self.reserved[stage], 0)

    def can_cover(self, required: Mapping[str, int]) -> bool:
        return all(stage in self.limits and self.remaining(stage) >= count for stage, count in required.items())

    def reserve(self, stage: str) -> bool:
        with self._lock:
            if self.remaining(stage) < 1:
                self.refused[stage] += 1
                return False
            self.reserved[stage] += 1
            return True

    def attempt(self, stage: str) -> None:
        with self._lock:
            if self.reserved[stage] < 1:
                raise ValueError("unreserved_physical_attempt")
            self.physical_attempts[stage] += 1

    def settle(self, stage: str, outcome: str) -> None:
        if outcome not in OUTCOMES[1:-1]:
            raise ValueError("invalid_call_outcome")
        with self._lock:
            self.outcomes[stage][outcome] += 1

    def release_unstarted(self, stage: str, *, physical_attempts_before: int) -> None:
        with self._lock:
            if self.physical_attempts[stage] != physical_attempts_before or self.reserved[stage] < 1:
                raise ValueError("started_reservation_not_releasable")
            self.reserved[stage] -= 1
            self.outcomes[stage]["released_unstarted"] += 1

    def summary(self) -> dict:
        with self._lock:
            stages = {}
            for stage, limit in self.limits.items():
                found = DECLARATIONS[stage]
                stages[stage] = {"spend_class": found.spend_class, "pricing": found.pricing, "limit": limit,
                                 "reserved": self.reserved[stage], "remaining": self.remaining(stage),
                                 "refused_before_egress": self.refused[stage],
                                 "physical_attempts": self.physical_attempts[stage],
                                 "outcomes": dict(self.outcomes[stage])}
            return {"operation": self.operation, "scope": "one_operation_process_local",
                    "financial_cap": False, "actual_cost_known": False, "stages": stages}


def operation_cost_row(operation: str, path: str = "ordinary", *, join: _Join | None = None,
                       candidate_budget: Any = None, allowances: tuple = (), spend_class: str = "selection",
                       source: str | None = None) -> dict:
    """A bounded, secret-free decision-point projection for Operations.

    Shows what the operation may call, what it reserved, what was observed,
    what stays unpriced and whether another attempt is allowed. Request rows
    carry stage/provider/outcome codes only: no prompt, header or exception.
    """
    if operation not in OPERATIONS or path not in PATHS or spend_class not in SPEND_CLASSES:
        raise UndeclaredCallError("undeclared_operation")
    rows = join.rows if join is not None else []
    overflow = join.overflow if join is not None else 0
    counts = join.counts() if join is not None else {name: 0 for name in OUTCOMES}
    stages: dict[str, dict] = {}
    for row in rows:
        stage = stages.setdefault(row["stage"], {"requests": 0, "unsettled": 0, "unknown_or_malformed": 0,
                                                 "spend_class": row["spend_class"], "pricing": row["pricing"]})
        stage["requests"] += 1
        stage["unsettled"] += row["outcome"] == "dispatched"
        stage["unknown_or_malformed"] += row["outcome"] in ("unknown", "malformed")
    budget = candidate_budget.summary() if candidate_budget is not None else None
    another: dict[str, bool] = {}
    if budget is not None:
        another["candidate_attempt"] = budget["refusal"] is None and (
            budget["limit"] is None or budget["attempts"] < budget["limit"])
    summaries = [a.summary() for a in allowances][:4]
    for summary in summaries:
        for name, stage_row in summary["stages"].items():
            another[name] = stage_row["remaining"] > 0
    return {
        "schema_version": 1, "operation": operation, "path": path, "spend_class": spend_class, "source": source,
        "may_call": [{"stage": s, "spend_class": DECLARATIONS[s].spend_class, "pricing": DECLARATIONS[s].pricing}
                     for s in OPERATIONS[operation]],
        "ceilings": list(PATH_CEILINGS[path]),
        "candidate_attempts": None if budget is None else {
            "limit": budget["limit"], "used": budget["attempts"], "returned_unstarted": budget["refused_before_writer"],
            "held": budget["held"], "refusal": budget["refusal"], "joined_requests": budget.get("joined_requests", 0)},
        "allowances": summaries,
        "requests": {"total": len(rows) + overflow, "by_outcome": counts, "by_stage": stages,
                     "interrupted": counts["dispatched"], "truncated": overflow > 0},
        "unpriced_requests": sum(1 for row in rows if row["pricing"] == "unknown") + overflow,
        "estimate_only_requests": sum(1 for row in rows if row["pricing"] == "estimate_partial"),
        "another_attempt_allowed": another,
        "actual_cost_known": False, "financial_cap": False,
    }


def record_operation_cost(current_run: dict | None, row: dict) -> None:
    """Append to the run row persisted with run history (newest last, bounded)."""
    if not isinstance(current_run, dict):
        return
    rows = current_run.setdefault("operation_costs", [])
    if isinstance(rows, list):
        rows.append(row)
        del rows[:-MAX_OPERATION_ROWS]


__all__ = ["BACKGROUND_LANES", "BackgroundLaneDisabled", "CEILING_KINDS", "CallDeclaration", "CallTicket",
           "DECLARATIONS", "consume_provider_stage", "OPERATIONS", "OperationAllowance", "PATH_CEILINGS", "UndeclaredCallError",
           "background_lane_enabled", "close_attempt_join", "consume", "current_attempt_join", "declaration",
           "inventory", "open_attempt_join", "operation_cost_row", "operation_scope", "record_operation_cost",
           "require_background_lane", "runtime_counts"]
