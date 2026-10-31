"""P16 staged source execution: a private view per deadline-bearing worker.

A Python thread cannot be killed, and a response already in flight at the
deadline still returns into its source function. So a deadline-bearing source
worker never touches the live ``bot_state``/``current_run``: it runs against a
private staged copy, and only the main thread may promote that copy's delta
into the live objects, and only while the exact authority is still current:

* owner   - the same scheduler invocation (``Owner``), not yet closed;
* token   - the worker's ``CancelToken`` was never cancelled;
* deadline- the worker's own completion stamp ``completed_at <= deadline``
            (the deadline instant is inside the budget; ``>`` is late);
* base    - the stage was copied from the batch base the promotion expects.

Merge rules (main thread, deterministic, all-or-nothing per worker):

* paths the worker did not change are never written;
* a changed path whose live value still equals the base takes the worker's
  value (dicts are merged key by key in place, lists replaced in place);
* if live also changed the same path since the base:
  - dicts recurse key by key;
  - log-shaped lists (worker and live each keep base rows in order, minus
    any removed, then append a tail: appends, capped/windowed head drops,
    remove-then-append dedup) merge as the base rows neither side removed,
    then live's tail, then the worker's tail. A count-capped log may then
    exceed its cap by the other appenders' rows until its next capped write
    (bounded; nothing is lost). A side that removed every base row replaced
    the list: conflict;
  - anything else, including a scalar set to an equal value (two increments
    from one base look equal), is a conflict: nothing of that worker is
    applied and the scheduler records the conflict (fail closed).
* transient objects are never shared aliases: the worker gets its own triage
  queue list (rows from the live queue plus its own) and its own funnel sink;
  promotion appends its new queue rows in order, rebinding their state-bound
  callbacks to the live state, and adds its kill/pass counters to the live
  sink;
* side effects outside the state (the world threshold cache Gist write) are
  deferred with ``defer_or_run`` and performed on the main thread only after
  the worker's state delta is promoted.

An expired worker's staged state, queue rows, sink counters and deferred
effects are discarded. It may only add an explicitly late diagnostic row to
the scheduler-owned late-evidence buffer, which the main thread attaches to
``current_run["late_source_evidence"]`` at defined points.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
import dataclasses
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.two_bot.call_inventory import CancelToken

QUEUE_KEY = "_triage_queue"
SINK_KEY = "_funnel_sink"
TRANSIENT_KEYS = (QUEUE_KEY, SINK_KEY)
LATE_EVIDENCE_KEY = "late_source_evidence"
MAX_LATE_EVIDENCE = 32
DEADLINE_REASON = "runner_budget_exceeded"

# Monotonic clock for budgets/deadlines/completion stamps; tests may replace it.
clock: Callable[[], float] = time.perf_counter

_MISSING = object()
_ACTIVE: ContextVar["WorkerStage | None"] = ContextVar("theheat_worker_stage", default=None)
_LATE_LOCK = threading.Lock()
_LATE: list[dict] = []


def now() -> float:
    return clock()


class StagingConflict(Exception):
    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


@dataclass(eq=False)
class Owner:
    """One scheduler invocation over one live state/run pair."""

    live_state: dict
    live_run: dict | None
    token: str = field(default_factory=lambda: secrets.token_hex(8))
    generation: int = 0
    closed: bool = False
    stages: list["WorkerStage"] = field(default_factory=list)
    _batch: "Batch | None" = None

    @property
    def run_id(self) -> str | None:
        return (self.live_run or {}).get("id")

    def open_batch(self) -> "Batch":
        if self.closed or self._batch is not None:
            raise RuntimeError("staging_batch_not_open")
        self._batch = Batch(self, self.generation, *_snapshot(self.live_state, self.live_run))
        return self._batch

    def close_batch(self, batch: "Batch") -> None:
        if self._batch is not batch:
            raise RuntimeError("staging_batch_mismatch")
        self._batch = None
        if batch.promoted:
            self.generation += 1

    def close(self) -> None:
        self.closed = True
        self._batch = None


@dataclass(eq=False)
class Batch:
    owner: Owner
    base_generation: int
    base_state: dict
    base_run: dict | None
    promoted: int = 0

    def stage(self, source: str, budget_seconds: float) -> "WorkerStage":
        live = self.owner.live_state
        state = deepcopy(self.base_state)
        queue = live.get(QUEUE_KEY)
        base_queue = tuple(queue) if isinstance(queue, list) else None
        if base_queue is not None:
            state[QUEUE_KEY] = list(base_queue)  # Same queued rows, a private list.
        if isinstance(live.get(SINK_KEY), dict):
            from src.orchestrator import funnel

            state[SINK_KEY] = funnel.new_funnel()  # Private counters, added on promotion.
        started_at = now()
        deadline = started_at + budget_seconds
        stage = WorkerStage(
            owner=self.owner, batch=self, source=source, started_at=started_at, deadline=deadline,
            cancel=CancelToken(source, deadline=deadline, clock=now, deadline_reason=DEADLINE_REASON),
            base_generation=self.base_generation, base_queue=base_queue,
            state=state, run=deepcopy(self.base_run),
        )
        self.owner.stages.append(stage)
        return stage


@dataclass(eq=False)
class WorkerStage:
    owner: Owner
    batch: Batch
    source: str
    started_at: float
    deadline: float
    cancel: CancelToken
    base_generation: int
    base_queue: tuple | None
    state: dict
    run: dict | None
    deferred: list[tuple[str, Callable[..., Any], tuple]] = field(default_factory=list)
    completed_at: float | None = None
    outcome: str | None = None
    error_class: str | None = None
    disposition: str | None = None

    @property
    def on_time(self) -> bool:
        return self.completed_at is not None and self.completed_at <= self.deadline


def _snapshot(live_state: dict, live_run: dict | None) -> tuple[dict, dict | None]:
    state = {k: v for k, v in live_state.items() if k not in TRANSIENT_KEYS}
    return deepcopy(state), deepcopy(live_run)


def active_stage() -> WorkerStage | None:
    return _ACTIVE.get()


def authority_current() -> bool:
    """False only inside a staged worker whose deadline/cancellation has passed."""
    stage = _ACTIVE.get()
    return stage is None or not stage.cancel.cancelled


def defer_or_run(name: str, fn: Callable[..., Any], *args: Any) -> None:
    """Outside a staged worker: call ``fn`` now (unchanged serial behaviour).

    Inside one: record it; the main thread runs it after promoting this
    worker's state, and drops it if the worker is discarded.
    """
    stage = _ACTIVE.get()
    if stage is None:
        fn(*args)
        return
    # Exactly the arguments at deferral time, whatever the worker does later.
    stage.deferred.append((name, fn, deepcopy(args)))


def execute(stage: WorkerStage, run: Callable[[dict, dict | None], None]) -> WorkerStage:
    """Worker-thread body: run against the private view, stamp completion."""
    marker = _ACTIVE.set(stage)
    try:
        run(stage.state, stage.run)
        stage.outcome = "returned"
    except BaseException as exc:
        stage.outcome = "raised"
        stage.error_class = type(exc).__name__
        raise
    finally:
        stage.completed_at = now()
        _ACTIVE.reset(marker)
        # Decided by the completion stamp and an already-recorded cancellation
        # only; re-reading the clock here could disagree with the stamp.
        if stage.cancel.reason is not None or not stage.on_time:
            _note_late(stage)
    return stage


# ---------------------------------------------------------------------------
# Late evidence: written by expired workers, read by the main thread only.
# ---------------------------------------------------------------------------

def _note_late(stage: WorkerStage) -> None:
    try:
        changed = sorted(_changed_top_level(stage))
    except Exception:  # noqa: BLE001 - diagnostics never fail a late worker
        changed = ["<unavailable>"]
    row = {
        "owner": stage.owner.token,
        "run_id": stage.owner.run_id,
        "source": stage.source,
        "late": True,
        "outcome": stage.outcome,
        "error_class": stage.error_class,
        "late_by_ms": max(int(((stage.completed_at or stage.deadline) - stage.deadline) * 1000), 0),
        "refused_calls": stage.cancel.refused,
        "late_responses": dict(sorted(stage.cancel.late_responses.items())),
        "discarded_changes": changed,
        "dropped_effects": [name for name, _, _ in stage.deferred],
    }
    with _LATE_LOCK:
        _LATE.append(row)
        del _LATE[:-MAX_LATE_EVIDENCE]


def _changed_top_level(stage: WorkerStage) -> set[str]:
    out = {k for k in set(stage.state) | set(stage.batch.base_state)
           if k not in TRANSIENT_KEYS and not _same(stage.state.get(k, _MISSING), stage.batch.base_state.get(k, _MISSING))}
    queue = stage.state.get(QUEUE_KEY)
    if isinstance(queue, list) and len(queue) > len(stage.base_queue or ()):
        out.add(QUEUE_KEY)
    sink = stage.state.get(SINK_KEY)
    if isinstance(sink, dict) and (sink.get("kills") or any((sink.get("passes") or {}).values())):
        out.add(SINK_KEY)
    if stage.run is not None and stage.batch.base_run is not None:
        out |= {f"current_run.{k}" for k in set(stage.run) | set(stage.batch.base_run)
                if not _same(stage.run.get(k, _MISSING), stage.batch.base_run.get(k, _MISSING))}
    return out


def take_late_evidence(owner: Owner) -> list[dict]:
    with _LATE_LOCK:
        mine = [row for row in _LATE if row["owner"] == owner.token]
        _LATE[:] = [row for row in _LATE if row["owner"] != owner.token]
    return mine


def attach_late_evidence(current_run: dict | None, owner: Owner | None) -> int:
    """Main thread: move this owner's late rows onto ``current_run`` (bounded)."""
    if owner is None:
        return 0
    rows = take_late_evidence(owner)
    if rows and current_run is not None:
        retained = current_run.setdefault(LATE_EVIDENCE_KEY, [])
        retained.extend(rows)
        del retained[:-MAX_LATE_EVIDENCE]
    return len(rows)


# ---------------------------------------------------------------------------
# Promotion (main thread only)
# ---------------------------------------------------------------------------

def refusal(owner: Owner, stage: WorkerStage, batch: Batch) -> str | None:
    """Why ``stage`` may not be promoted into ``owner`` now, or None."""
    if stage.owner is not owner or owner.closed:
        return "stale_owner"
    if stage.batch is not batch or owner._batch is not batch or stage.base_generation != owner.generation:
        return "base_changed"
    if stage.disposition is not None:
        return "already_settled"
    if stage.cancel.reason is not None:  # Main-thread timeout or a worker-observed expiry.
        return "cancelled"
    if stage.completed_at is None:
        return "incomplete"
    if not stage.on_time:
        return "late"
    return None


def promote(owner: Owner, stage: WorkerStage, batch: Batch) -> str:
    """Apply ``stage`` to the live objects if its authority is current.

    Returns the disposition: ``promoted``, ``refused:<reason>`` or
    ``conflict:<path>``. Nothing is applied unless it is ``promoted``.
    """
    reason = refusal(owner, stage, batch)
    if reason is not None:
        if stage.disposition is None:
            stage.disposition = f"refused:{reason}"
        return f"refused:{reason}"
    try:
        ops: list = []
        _plan_dict(batch.base_state, _without_transient(stage.state), owner.live_state, "", ops)
        if stage.run is not None and owner.live_run is not None:
            _plan_dict(batch.base_run or {}, stage.run, owner.live_run, "current_run.", ops)
        new_rows = _queue_delta(stage)
        sink = _sink_delta(stage)
    except StagingConflict as exc:
        stage.disposition = f"conflict:{exc.path}"
        return stage.disposition
    for op in ops:
        op()
    _append_queue(owner, stage, new_rows)
    _add_sink(owner.live_state, sink)
    stage.disposition = "promoted"
    batch.promoted += 1
    for name, fn, args in stage.deferred:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - the same never-raise contract the worker had
            print(f"[scheduler] deferred {name} for {stage.source} failed: {exc}")
    return "promoted"


def discard(stage: WorkerStage, reason: str) -> None:
    if stage.disposition is None:
        stage.disposition = f"refused:{reason}"


def _without_transient(state: dict) -> dict:
    return {k: v for k, v in state.items() if k not in TRANSIENT_KEYS}


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if a is _MISSING or b is _MISSING or type(a) is not type(b):
        return False
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001 - incomparable values are treated as changed
        return False


def _plan_dict(base: dict, staged: dict, live: dict, path: str, ops: list) -> None:
    for key in list(staged) + [k for k in base if k not in staged]:
        b = base.get(key, _MISSING)
        s = staged.get(key, _MISSING)
        if _same(b, s):
            continue
        here = f"{path}{key}"
        current = live.get(key, _MISSING)
        if b is _MISSING and type(s) is type(current) and isinstance(s, (dict, list)):
            b = type(s)()  # Both sides created the same container since the base.
        if isinstance(b, dict) and isinstance(s, dict) and isinstance(current, dict):
            _plan_dict(b, s, current, here + ".", ops)
        elif isinstance(b, list) and isinstance(s, list) and isinstance(current, list):
            _plan_list(b, s, current, here, ops)
        elif _same(current, b):
            ops.append(_setter(live, key, s))
        else:
            # Changed by this worker AND by someone else since the base. Even an
            # equal value is refused: two increments from one base look equal.
            raise StagingConflict(here)


def _setter(container: dict, key: Any, value: Any) -> Callable[[], None]:
    if value is _MISSING:
        return lambda: container.pop(key, None)

    def apply() -> None:
        container[key] = value
    return apply


def _log_shape(base: list, other: list) -> tuple[list[int], list] | None:
    """(kept base positions, appended tail) when ``other`` keeps base rows in order, then appends.

    Covers appends, capped/windowed head drops and remove-then-append dedup
    (a re-observed row moves to the end). Removing every row of a non-empty
    base is a replacement, not a log edit: None.
    """
    kept: list[int] = []
    j = 0
    for i, row in enumerate(base):
        if j < len(other) and _same(other[j], row):
            kept.append(i)
            j += 1
    if base and not kept:
        return None
    return kept, other[j:]


def _plan_list(base: list, staged: list, live: list, path: str, ops: list) -> None:
    if _same(live, base):
        def replace() -> None:
            live[:] = staged
        ops.append(replace)
        return
    worker = _log_shape(base, staged)
    other = _log_shape(base, live)
    if worker is None or other is None:
        raise StagingConflict(path)
    # Rows either side removed stay removed; live's own row objects are kept;
    # then live's appended rows, then this worker's, in promotion order.
    worker_kept = set(worker[0])
    live_kept, live_tail = other
    survivors = [row for i, row in zip(live_kept, live) if i in worker_kept]
    merged = survivors + list(live_tail) + list(worker[1])

    def merge() -> None:
        live[:] = merged
    ops.append(merge)


def _queue_delta(stage: WorkerStage) -> list:
    queue = stage.state.get(QUEUE_KEY, _MISSING)
    base = stage.base_queue or ()
    if queue is _MISSING:
        if base:
            raise StagingConflict(QUEUE_KEY)
        return []
    if not isinstance(queue, list) or len(queue) < len(base) or any(a is not b for a, b in zip(queue, base)):
        raise StagingConflict(QUEUE_KEY)  # Only appends; removal/reorder stays main-thread work.
    return queue[len(base):]


def _sink_delta(stage: WorkerStage) -> dict | None:
    sink = stage.state.get(SINK_KEY)
    if not isinstance(sink, dict):
        return None
    for key in ("_slate_skeleton", "_slate_ids", "_slate_terminal"):
        if sink.get(key):
            raise StagingConflict(f"{SINK_KEY}.{key}")
    return sink


def _add_sink(live_state: dict, sink: dict | None) -> None:
    if sink is None:
        return
    target = live_state.get(SINK_KEY)
    if not isinstance(target, dict):
        return
    from src.orchestrator import funnel

    with funnel._KILL_LOCK:
        for group in ("kills", "passes"):
            counts = target.setdefault(group, {})
            for stage_name, n in (sink.get(group) or {}).items():
                if n:
                    counts[stage_name] = counts.get(stage_name, 0) + n


def _append_queue(owner: Owner, stage: WorkerStage, rows: list) -> None:
    if not rows:
        return
    from src.orchestrator import triage_queue

    rebound = [_rebind_row(row, stage, owner) for row in rows]
    with triage_queue._TRIAGE_QUEUE_LOCK:
        owner.live_state.setdefault(QUEUE_KEY, []).extend(rebound)


def _rebind_row(row: Any, stage: WorkerStage, owner: Owner) -> Any:
    """Callbacks a worker bound to its staged state now act on the live state."""
    callbacks = {name: getattr(row, name, None) for name in ("on_draft_success", "annual_cap_check")}
    if not any(callbacks.values()):
        return row
    replacement = dataclasses.replace(row, **{
        name: _forwarding(fn, stage, owner) for name, fn in callbacks.items() if fn is not None})
    _carry_intake_identity(row, replacement)
    return replacement


def _carry_intake_identity(old: Any, new: Any) -> None:
    import weakref

    from src.orchestrator import triage_queue

    with triage_queue._TRIAGE_QUEUE_LOCK:
        identity = triage_queue._GDACS_INTAKE.get(id(old))
        if identity is None:
            return
        triage_queue._GDACS_INTAKE[id(new)] = identity
    weakref.finalize(new, triage_queue._GDACS_INTAKE.pop, id(new), None)


def _forwarding(fn: Callable[..., Any], stage: WorkerStage, owner: Owner) -> Callable[..., Any]:
    """Run ``fn`` with its staged dicts mirroring the live ones, then write back.

    Mirroring is shallow, so nested mutations land on the live containers;
    top-level rebinding/removal is copied back afterwards. Main thread only.
    """
    pairs = [(stage.state, owner.live_state)]
    if stage.run is not None and owner.live_run is not None:
        pairs.append((stage.run, owner.live_run))

    def bound(*args: Any, **kwargs: Any) -> Any:
        for staged, live in pairs:
            staged.clear()
            staged.update(live)
        try:
            return fn(*args, **kwargs)
        finally:
            for staged, live in pairs:
                for key in [k for k in live if k not in staged]:
                    del live[key]
                for key, value in staged.items():
                    if live.get(key, _MISSING) is not value:
                        live[key] = value
    bound.__wrapped__ = fn  # type: ignore[attr-defined]
    return bound


__all__ = [
    "DEADLINE_REASON", "LATE_EVIDENCE_KEY", "Owner", "StagingConflict", "WorkerStage", "active_stage",
    "attach_late_evidence", "authority_current", "defer_or_run", "execute", "promote", "take_late_evidence",
]
