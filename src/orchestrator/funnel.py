"""Per-cycle funnel telemetry (Phase A — Throughput Initiative).

Pure observability. Flag-gated default-OFF via ``THEHEAT_FUNNEL_TELEMETRY``.
When ON, ``run_alerts`` stashes a transient ``funnel_sink`` on
``bot_state["_funnel_sink"]`` for the whole cycle. Every kill path (which already
records a suppression) ALSO bumps ``funnel_sink["kills"]`` LIVE via
:func:`record_kill` — so the per-run kill counts are immune to the global
100-row suppressions cap (codex must-fix: "the fix is a durable rolling counter,
not new kill-recording"). The drain accumulates writer/fact_check/critic passes
and the shadow slate. :func:`finalize_funnel` (after the cycle-cap prune) freezes
a complete ``funnel`` object + ``shadow_slate`` onto ``current_run``, which rides
into ``run_history`` (the run dict is serialized whole — ``sqlite_store``
``payload_json`` + gist JSON), so the dashboard computes the 7-day rollup FROM
run_history (not source_health, whose rows are written ``drafted=0`` early).

The sink is transient: it is popped at finalize and never persisted. Its
contents are plain dicts/ints (the increment lock is module-level, not in the
sink) so even a crash that leaks it to gist serializes harmlessly.

Codex outside-review must-fixes addressed:
* #1 exact denominators — per stage ``attempts = passes + kills``; passes are
  per-candidate-terminal (pipeline overwrites a stage's outcome on REVISE
  re-runs); ``writer_attempted`` = survivor sent, not LLM-sample count.
* #2 7-day rollup from run_history (frozen per-run funnels), not source_health.
* #3 shadow slate captured before the queue drains.
* the 100-cap blindness — kills counted live into the sink, never read back from
  the truncated global ledger.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable
from typing import cast

from src.state_schema import BotState

# Stages that have a meaningful editorial pass-rate. ``critic`` is the headline
# metric. safety / honesty_gate / evidence_contract are kill-only gates.
PASS_STAGES: tuple[str, ...] = ("writer", "fact_check", "critic")

SHADOW_SLATE_SIZE = 10

_VOLUME_KEYS: tuple[str, ...] = (
    "observed",
    "promoted",
    "triaged_in",
    "triaged_out",
    "billing_aborted",
    "writer_attempted",
    "drafted",
)

# Source runners record kills concurrently (each worker shares bot_state). The
# live kill counter is a read-modify-write, so guard it. Cheap — kills are rare.
_KILL_LOCK = threading.Lock()

_SINK_KEY = "_funnel_sink"


def funnel_telemetry_enabled() -> bool:
    """True only when ``THEHEAT_FUNNEL_TELEMETRY`` is explicitly truthy.

    Default OFF (the Throughput Initiative ships every phase dark).
    """
    raw = os.environ.get("THEHEAT_FUNNEL_TELEMETRY", "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def new_funnel() -> dict:
    """A fresh per-run funnel sink."""
    return {
        "passes": {stage: 0 for stage in PASS_STAGES},
        "kills": {},
        "_slate_skeleton": [],
        "_slate_ids": set(),
        "_slate_terminal": {},
    }


def attach_sink(bot_state: BotState | None, funnel_sink: dict | None) -> None:
    """Stash the sink on bot_state so kill paths can find it (transient)."""
    if bot_state is None or funnel_sink is None:
        return
    # _funnel_sink is a transient key (like _triage_queue), not in the BotState
    # TypedDict and never persisted — access via a plain-dict cast.
    cast(dict, bot_state)[_SINK_KEY] = funnel_sink


def record_kill(bot_state: BotState | None, stage: str) -> None:
    """Bump the live kill counter for ``stage`` if telemetry is active.

    Called from every suppression-recording path so the per-run kill counts are
    accurate even when a cycle records more than ``MAX_SUPPRESSIONS`` rows
    (the global ledger truncates; this counter does not).
    """
    if bot_state is None:
        return
    sink = cast(dict, bot_state).get(_SINK_KEY)
    if not isinstance(sink, dict):
        return
    with _KILL_LOCK:
        kills = sink["kills"]
        kills[stage] = kills.get(stage, 0) + 1


def record_candidate_passes(funnel_sink: dict | None, stage_outcomes: dict | None) -> None:
    """Credit a pass for each pass-stage the candidate cleared this attempt."""
    if funnel_sink is None or not stage_outcomes:
        return
    passes = funnel_sink["passes"]
    for stage in PASS_STAGES:
        if stage_outcomes.get(stage) == "pass":
            passes[stage] = passes.get(stage, 0) + 1


def _score_total(candidate) -> int:
    score = getattr(candidate, "score", None)
    raw = getattr(score, "total", None)
    if raw is None and isinstance(score, dict):
        raw = score.get("total")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def capture_slate(funnel_sink: dict | None, queue: Iterable) -> None:
    """Snapshot the top-:data:`SHADOW_SLATE_SIZE` distinct candidates by score.

    MUST run before the queue drains (codex must-fix #3). Records identity +
    score + summary; terminal stage is resolved at finalize.
    """
    if funnel_sink is None:
        return
    candidates = list(queue or [])
    ordered = sorted(candidates, key=_score_total, reverse=True)
    seen: set[str] = set()
    skeleton: list[dict] = []
    for candidate in ordered:
        event_id = getattr(candidate, "event_id", "") or ""
        if event_id in seen:
            continue
        seen.add(event_id)
        bundle = getattr(candidate, "bundle", None)
        summary = getattr(bundle, "where", None) or getattr(candidate, "city", None) or None
        skeleton.append({
            "event_id": event_id,
            "type": getattr(candidate, "legacy_type", None)
            or getattr(bundle, "signal_kind", None)
            or "unknown",
            "score_total": _score_total(candidate),
            "summary": summary,
        })
        if len(skeleton) >= SHADOW_SLATE_SIZE:
            break
    funnel_sink["_slate_skeleton"] = skeleton
    funnel_sink["_slate_ids"] = {s["event_id"] for s in skeleton}


def record_slate_terminal(funnel_sink: dict | None, event_id: str, stage: str) -> None:
    """Record a slate candidate's terminal stage (drain-observed, not from the
    truncatable suppression ledger). Ignored for non-slate events."""
    if funnel_sink is None or not event_id:
        return
    if event_id in funnel_sink.get("_slate_ids", set()):
        funnel_sink.setdefault("_slate_terminal", {})[event_id] = stage


def finalize_funnel(
    funnel_sink: dict,
    current_run: dict,
    bot_state: BotState,
    pruned_event_ids: set | None = None,
) -> dict:
    """Freeze the per-run funnel + resolved shadow slate onto current_run.

    Called AFTER the cycle-cap prune. Pops the transient sink off bot_state.
    """
    sources = current_run.get("sources") or []
    funnel: dict = {key: 0 for key in _VOLUME_KEYS}
    for source in sources:
        for key in _VOLUME_KEYS:
            try:
                funnel[key] += int(source.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
    funnel["passes"] = dict(funnel_sink.get("passes") or {stage: 0 for stage in PASS_STAGES})
    funnel["kills"] = dict(funnel_sink.get("kills") or {})

    # Resolve slate terminal stages. Precedence: cycle_cap (pruned after the
    # drain) > drain-observed terminal > live draft > unknown.
    drafted_ids = {
        d.get("event_id")
        for d in bot_state.get("drafts", []) or []
        if d.get("event_id")
    }
    slate_terminal = funnel_sink.get("_slate_terminal") or {}
    pruned = pruned_event_ids or set()
    slate: list[dict] = []
    for skel in funnel_sink.get("_slate_skeleton") or []:
        event_id = skel.get("event_id")
        if event_id in pruned:
            terminal = "cycle_cap"
        elif event_id in slate_terminal:
            terminal = slate_terminal[event_id]
        elif event_id in drafted_ids:
            terminal = "drafted"
        else:
            terminal = "unknown"
        slate.append({
            "event_id": skel.get("event_id"),
            "type": skel.get("type"),
            "score_total": skel.get("score_total"),
            "summary": skel.get("summary"),
            "terminal_stage": terminal,
        })

    current_run["funnel"] = funnel
    current_run["shadow_slate"] = slate

    # Pop the transient sink so it never persists.
    if bot_state is not None:
        cast(dict, bot_state).pop(_SINK_KEY, None)
    return funnel


def _rate(passes: int, kills: int) -> float | None:
    attempts = passes + kills
    if attempts == 0:
        return None
    return passes / attempts


def funnel_rates(funnel: dict) -> dict:
    """Derive pass/kill rates. Single source of truth for the denominators
    (mirrored in ``dashboard/app/api/funnel/route.js`` — keep in sync)."""
    passes = funnel.get("passes") or {}
    kills = funnel.get("kills") or {}
    stages: dict[str, dict] = {}
    for stage in PASS_STAGES:
        p = int(passes.get(stage, 0) or 0)
        k = int(kills.get(stage, 0) or 0)
        stages[stage] = {
            "passes": p,
            "kills": k,
            "attempts": p + k,
            "pass_rate": _rate(p, k),
            "kill_rate": (None if (p + k) == 0 else k / (p + k)),
        }

    triaged_in = int(funnel.get("triaged_in", 0) or 0)
    triaged_out = int(funnel.get("triaged_out", 0) or 0)
    # Billing-aborted candidates were skipped by the circuit breaker, not cut
    # by triage — excluding them keeps a billing outage from reading as an
    # editorial cap on the dashboard (codex r3 P2).
    billing_aborted = int(funnel.get("billing_aborted", 0) or 0)
    triage_cut = max(triaged_in - triaged_out - billing_aborted, 0)
    writer_attempted = int(funnel.get("writer_attempted", 0) or 0)
    drafted = int(funnel.get("drafted", 0) or 0)

    return {
        "critic_pass_rate": stages["critic"]["pass_rate"],
        "writer_pass_rate": stages["writer"]["pass_rate"],
        "fact_check_pass_rate": stages["fact_check"]["pass_rate"],
        "stages": stages,
        "triage_cut": triage_cut,
        "triage_cap_rate": (None if triaged_in == 0 else triage_cut / triaged_in),
        "billing_aborted": billing_aborted,
        "draft_yield": (None if writer_attempted == 0 else drafted / writer_attempted),
    }


def rollup_funnels(run_history: Iterable[dict]) -> dict:
    """Sum frozen per-run funnels across ``run_history`` into one rollup."""
    rollup: dict = {key: 0 for key in _VOLUME_KEYS}
    rollup["passes"] = {stage: 0 for stage in PASS_STAGES}
    rollup["kills"] = {}
    for run in run_history or []:
        funnel = run.get("funnel") if isinstance(run, dict) else None
        if not isinstance(funnel, dict):
            continue
        for key in _VOLUME_KEYS:
            try:
                rollup[key] += int(funnel.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
        for stage, count in (funnel.get("passes") or {}).items():
            if stage in rollup["passes"]:
                rollup["passes"][stage] += int(count or 0)
        for stage, count in (funnel.get("kills") or {}).items():
            rollup["kills"][stage] = rollup["kills"].get(stage, 0) + int(count or 0)
    return rollup


__all__ = [
    "PASS_STAGES",
    "SHADOW_SLATE_SIZE",
    "attach_sink",
    "capture_slate",
    "finalize_funnel",
    "funnel_rates",
    "funnel_telemetry_enabled",
    "new_funnel",
    "record_candidate_passes",
    "record_kill",
    "record_slate_terminal",
    "rollup_funnels",
]
