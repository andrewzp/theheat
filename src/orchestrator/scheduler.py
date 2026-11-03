"""Optional concurrent source scheduler for alerts mode."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import cast

from src.orchestrator import staging
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.telemetry import _record_source_run
from src.two_bot.call_inventory import run_cancellable, submit_in_context
from src.state_schema import BotState

MAX_WORKERS = 6
RUNNER_BUDGET_SECONDS = 120
BREAKER_N = 3
BREAKER_ERROR = "circuit breaker (cooldown 1 cycle)"


@dataclass(frozen=True)
class SourceRunner:
    """A source and the callable that runs it against the state/run it is handed.

    ``run(bot_state, current_run)`` receives its objects explicitly: under the
    scheduler they are the worker's private staged view, never the live ones.
    """

    source: str
    run: Callable[[BotState, dict | None], None]
    health_sources: tuple[str, ...] = ()


def _health_sources(runner: SourceRunner) -> tuple[str, ...]:
    return runner.health_sources or (runner.source,)


def concurrent_sources_enabled() -> bool:
    return os.environ.get("THEHEAT_CONCURRENT_SOURCES", "0") == "1"


def _budget_text(budget_seconds: float) -> str:
    return f"{int(budget_seconds)}s" if float(budget_seconds).is_integer() else f"{budget_seconds:g}s"


def _breaker_open(bot_state: BotState, source: str) -> bool:
    health = (bot_state.get("source_health") or {}).get(source) or {}
    runs = list(health.get("runs") or [])
    if len(runs) < BREAKER_N:
        return False
    recent = runs[-BREAKER_N:]
    return all(run.get("error_class") == "timeout" for run in recent)


def _runner_breaker_open(bot_state: BotState, runner: SourceRunner) -> bool:
    return all(_breaker_open(bot_state, source) for source in _health_sources(runner))


def _record_breaker_skip(bot_state: BotState, current_run: dict | None, runner: SourceRunner) -> None:
    print(f"[{runner.source}] {BREAKER_ERROR}")
    for source in _health_sources(runner):
        _record_source_run(
            current_run,
            bot_state,
            source,
            time.perf_counter(),
            status="skipped",
            error=BREAKER_ERROR,
            breaker=True,
        )


def _record_budget_timeout(
    bot_state: BotState,
    current_run: dict | None,
    runner: SourceRunner,
    budget_seconds: float,
    started_at: float,
) -> None:
    error = f"budget exceeded ({_budget_text(budget_seconds)})"
    print(f"[{runner.source}] {error}")
    for source in _health_sources(runner):
        _record_source_run(
            current_run,
            bot_state,
            source,
            started_at,
            status="failed",
            error=error,
            error_class="timeout",
        )


def _record_unhandled_failure(
    bot_state: BotState,
    current_run: dict | None,
    runner: SourceRunner,
    started_at: float,
    exc: Exception,
) -> None:
    print(f"[{runner.source}] unhandled source error: {exc}")
    for source in _health_sources(runner):
        _record_source_run(
            current_run,
            bot_state,
            source,
            started_at,
            status="failed",
            error=str(exc),
        )


def _record_staging_conflict(
    bot_state: BotState,
    current_run: dict | None,
    runner: SourceRunner,
    started_at: float,
    disposition: str,
) -> None:
    error = f"staged result not promoted ({disposition})"
    print(f"[{runner.source}] {error}")
    for source in _health_sources(runner):
        _record_source_run(current_run, bot_state, source, started_at, status="failed", error=error)


def _live(owner: staging.Owner) -> BotState:
    return cast(BotState, owner.live_state)


def _await_with_budget(future: Future, started_at: float, budget_seconds: float) -> None:
    remaining = budget_seconds - (staging.now() - started_at)
    if remaining <= 0 and not future.done():
        raise TimeoutError()
    future.result(timeout=max(remaining, 0))


def _run_with_context(bot_state: BotState, current_run: dict | None, runner: SourceRunner) -> None:
    """Run ``runner`` against exactly the state/run it is given (live or staged)."""
    with _suppression_context(
        bot_state,
        source=runner.source,
        run_id=(current_run or {}).get("id"),
    ):
        runner.run(bot_state, current_run)


def _staged_body(runner: SourceRunner) -> Callable[[dict, dict | None], None]:
    def body(state: dict, run: dict | None) -> None:
        _run_with_context(cast(BotState, state), run, runner)
    return body


def _dispatch(executor: ThreadPoolExecutor, batch: staging.Batch, runner: SourceRunner,
              budget_seconds: float) -> tuple[staging.WorkerStage, Future]:
    stage = batch.stage(runner.source, budget_seconds)
    # A copy of this context per runner: operation/attempt joins and a finite
    # trial follow the work; a closed join is never revived (call_inventory).
    future = submit_in_context(executor, run_cancellable, stage.cancel, staging.execute, stage, _staged_body(runner))
    return stage, future


def _await_stage(stage: staging.WorkerStage, future: Future, budget_seconds: float) -> str:
    """Main thread: 'timeout', 'raised' or 'completed' (on time, in the worker's own stamp)."""
    try:
        _await_with_budget(future, stage.started_at, budget_seconds)
    except TimeoutError:
        return "timeout"
    except Exception:
        return "raised" if stage.on_time else "timeout"
    return "completed" if stage.on_time else "timeout"


def _settle_timeout(owner: staging.Owner, stage: staging.WorkerStage, runner: SourceRunner,
                    budget_seconds: float, future: Future) -> None:
    # A queued runner that never started never starts. A running thread cannot
    # be killed; it buys no further call after its deadline and its staged
    # state is never promoted (late evidence only).
    future.cancel()
    stage.cancel.cancel(staging.DEADLINE_REASON)
    staging.discard(stage, "timeout")
    _record_budget_timeout(_live(owner), owner.live_run, runner, budget_seconds, stage.started_at)


def _settle(owner: staging.Owner, batch: staging.Batch, stage: staging.WorkerStage, runner: SourceRunner,
            future: Future, observed: str, budget_seconds: float) -> None:
    """Main thread: promote an on-time stage, then report exactly as before."""
    if observed == "timeout":
        _settle_timeout(owner, stage, runner, budget_seconds, future)
        return
    disposition = staging.promote(owner, stage, batch)
    if disposition != "promoted":
        _record_staging_conflict(_live(owner), owner.live_run, runner, stage.started_at, disposition)
    if observed == "raised":
        exc = future.exception()
        _record_unhandled_failure(_live(owner), owner.live_run, runner, stage.started_at,
                                  exc if isinstance(exc, Exception) else RuntimeError(str(exc)))


def _run_one_with_budget(
    owner: staging.Owner,
    runner: SourceRunner,
    *,
    budget_seconds: float,
) -> None:
    if _runner_breaker_open(_live(owner), runner):
        _record_breaker_skip(_live(owner), owner.live_run, runner)
        return

    executor = ThreadPoolExecutor(max_workers=1)
    batch = owner.open_batch()
    try:
        stage, future = _dispatch(executor, batch, runner, budget_seconds)
        _settle(owner, batch, stage, runner, future, _await_stage(stage, future, budget_seconds), budget_seconds)
    finally:
        owner.close_batch(batch)
        # Timed-out Python threads cannot be killed safely. We leave them to
        # self-complete against their private stage; the GitHub job's
        # 20-minute cap is the outer guard.
        executor.shutdown(wait=False, cancel_futures=False)


def run_stage1_sources(
    bot_state: BotState,
    current_run: dict | None,
    *,
    serial_runners: list[SourceRunner],
    concurrent_runners: list[SourceRunner],
    budget_seconds: float = RUNNER_BUDGET_SECONDS,
    max_workers: int = MAX_WORKERS,
) -> staging.Owner:
    """Run Stage 1 source runners, each against a private staged view.

    Synthesis-component writers run in a serial sub-batch first; each is
    promoted (main thread) before the next starts. Other sources dispatch
    concurrently from one shared base and are promoted after the batch in
    declaration order, never completion order. A runner that misses its
    deadline is recorded as a timeout and its staged result is discarded; its
    worker thread cannot be killed, but every later physical call it attempts
    is refused before egress (call_inventory.CancelToken) and it can never
    reach the live state, queue, sink or deferred Gist write (staging.py).
    """
    owner = staging.Owner(cast(dict, bot_state), current_run)
    try:
        for runner in serial_runners:
            _run_one_with_budget(owner, runner, budget_seconds=budget_seconds)

        runnable: list[SourceRunner] = []
        for runner in concurrent_runners:
            if _runner_breaker_open(bot_state, runner):
                _record_breaker_skip(bot_state, current_run, runner)
                continue
            runnable.append(runner)
        if not runnable:
            return owner

        executor = ThreadPoolExecutor(max_workers=max_workers)
        batch = owner.open_batch()
        try:
            dispatch = [(runner, *_dispatch(executor, batch, runner, budget_seconds)) for runner in runnable]
            observed = []
            for runner, stage, future in dispatch:
                outcome = _await_stage(stage, future, budget_seconds)
                if outcome == "timeout":
                    _settle_timeout(owner, stage, runner, budget_seconds, future)
                observed.append(outcome)
            # Declaration order, after the whole batch: completion order never matters.
            for (runner, stage, future), outcome in zip(dispatch, observed):
                if outcome != "timeout":
                    _settle(owner, batch, stage, runner, future, outcome, budget_seconds)
        finally:
            owner.close_batch(batch)
            executor.shutdown(wait=False, cancel_futures=False)
    finally:
        owner.close()
        staging.attach_late_evidence(current_run, owner)
    return owner


def run_stage1_then_synthesis(
    bot_state: BotState,
    current_run: dict | None,
    *,
    serial_runners: list[SourceRunner],
    concurrent_runners: list[SourceRunner],
    synthesis_runner: SourceRunner,
    budget_seconds: float = RUNNER_BUDGET_SECONDS,
    max_workers: int = MAX_WORKERS,
) -> staging.Owner:
    owner = run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=serial_runners,
        concurrent_runners=concurrent_runners,
        budget_seconds=budget_seconds,
        max_workers=max_workers,
    )
    # Main thread, live objects, after every promotion: synthesis sees exactly
    # the promoted Stage 1 results and nothing an expired worker staged.
    _run_with_context(bot_state, current_run, synthesis_runner)
    staging.attach_late_evidence(current_run, owner)
    return owner


__all__ = [
    "BREAKER_N",
    "MAX_WORKERS",
    "RUNNER_BUDGET_SECONDS",
    "SourceRunner",
    "concurrent_sources_enabled",
    "run_stage1_sources",
    "run_stage1_then_synthesis",
]
