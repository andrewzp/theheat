"""Optional concurrent source scheduler for alerts mode."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass

from src.orchestrator.suppression import _suppression_context
from src.orchestrator.telemetry import _record_source_run
from src.state_schema import BotState

MAX_WORKERS = 6
RUNNER_BUDGET_SECONDS = 120
BREAKER_N = 3
BREAKER_ERROR = "circuit breaker (cooldown 1 cycle)"


@dataclass(frozen=True)
class SourceRunner:
    source: str
    run: Callable[[], None]
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


def _await_with_budget(future: Future[None], started_at: float, budget_seconds: float) -> None:
    remaining = budget_seconds - (time.perf_counter() - started_at)
    if remaining <= 0 and not future.done():
        raise TimeoutError()
    future.result(timeout=max(remaining, 0))


def _run_with_context(bot_state: BotState, current_run: dict | None, runner: SourceRunner) -> None:
    with _suppression_context(
        bot_state,
        source=runner.source,
        run_id=(current_run or {}).get("id"),
    ):
        runner.run()


def _run_one_with_budget(
    bot_state: BotState,
    current_run: dict | None,
    runner: SourceRunner,
    *,
    budget_seconds: float,
) -> None:
    if _runner_breaker_open(bot_state, runner):
        _record_breaker_skip(bot_state, current_run, runner)
        return

    executor = ThreadPoolExecutor(max_workers=1)
    started_at = time.perf_counter()
    future = executor.submit(_run_with_context, bot_state, current_run, runner)
    try:
        _await_with_budget(future, started_at, budget_seconds)
    except TimeoutError:
        _record_budget_timeout(bot_state, current_run, runner, budget_seconds, started_at)
    except Exception as exc:
        _record_unhandled_failure(bot_state, current_run, runner, started_at, exc)
    finally:
        # Timed-out Python threads cannot be killed safely. We leave them to
        # self-complete; the GitHub job's 20-minute cap is the outer guard.
        executor.shutdown(wait=False, cancel_futures=False)


def run_stage1_sources(
    bot_state: BotState,
    current_run: dict | None,
    *,
    serial_runners: list[SourceRunner],
    concurrent_runners: list[SourceRunner],
    budget_seconds: float = RUNNER_BUDGET_SECONDS,
    max_workers: int = MAX_WORKERS,
) -> None:
    """Run Stage 1 source runners.

    Synthesis-component writers run in a serial sub-batch first. Other sources
    dispatch concurrently. A timed-out runner is recorded as failed but its
    worker thread is not cancelled.
    """
    for runner in serial_runners:
        _run_one_with_budget(
            bot_state,
            current_run,
            runner,
            budget_seconds=budget_seconds,
        )

    dispatch: list[tuple[SourceRunner, Future[None], float]] = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for runner in concurrent_runners:
            if _runner_breaker_open(bot_state, runner):
                _record_breaker_skip(bot_state, current_run, runner)
                continue
            started_at = time.perf_counter()
            future = executor.submit(_run_with_context, bot_state, current_run, runner)
            dispatch.append((runner, future, started_at))

        for runner, future, started_at in dispatch:
            try:
                _await_with_budget(future, started_at, budget_seconds)
            except TimeoutError:
                _record_budget_timeout(bot_state, current_run, runner, budget_seconds, started_at)
            except Exception as exc:
                _record_unhandled_failure(bot_state, current_run, runner, started_at, exc)
    finally:
        executor.shutdown(wait=False, cancel_futures=False)


def run_stage1_then_synthesis(
    bot_state: BotState,
    current_run: dict | None,
    *,
    serial_runners: list[SourceRunner],
    concurrent_runners: list[SourceRunner],
    synthesis_runner: SourceRunner,
    budget_seconds: float = RUNNER_BUDGET_SECONDS,
    max_workers: int = MAX_WORKERS,
) -> None:
    run_stage1_sources(
        bot_state,
        current_run,
        serial_runners=serial_runners,
        concurrent_runners=concurrent_runners,
        budget_seconds=budget_seconds,
        max_workers=max_workers,
    )
    _run_with_context(bot_state, current_run, synthesis_runner)


__all__ = [
    "BREAKER_N",
    "MAX_WORKERS",
    "RUNNER_BUDGET_SECONDS",
    "SourceRunner",
    "concurrent_sources_enabled",
    "run_stage1_sources",
    "run_stage1_then_synthesis",
]
