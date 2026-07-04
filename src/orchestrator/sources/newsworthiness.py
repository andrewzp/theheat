"""Source runner for the newsworthiness retrieval lane (Bet A phase 0).

Flag-gated by ``THEHEAT_NEWSWORTHINESS_ENABLED`` (default OFF → a skipped
source-health row, exactly like reganom shipped). When ON it retrieves cited
world events (NIFC feed + grounded search, verification ladder inside
``src.data.newsworthiness``) and records them to ``state["news_events"]``.

Phase 0 has ZERO editorial surface — nothing here touches scoring, triage, or
drafting. A retrieval failure records a degraded/failed source row and the
cycle proceeds without news; silent failure is structurally impossible because
this IS a source row the sentinel watches like any other.
"""

from __future__ import annotations

import os
import time

from src import state
from src.data.newsworthiness import fetch_news_events
from src.orchestrator.common import _record_source_run
from src.state_schema import BotState

SOURCE_KEY = "newsworthiness"


def _enabled() -> bool:
    return os.environ.get("THEHEAT_NEWSWORTHINESS_ENABLED", "") == "1"


def run_newsworthiness(bot_state: BotState, current_run: dict | None) -> None:
    source_start = time.perf_counter()
    if not _enabled():
        _record_source_run(
            current_run, bot_state, SOURCE_KEY, source_start,
            status="skipped", note="THEHEAT_NEWSWORTHINESS_ENABLED is not 1",
        )
        return

    print("[alerts] Retrieving newsworthiness events (NIFC + grounded search)...")
    try:
        result = fetch_news_events()
    except Exception as exc:  # noqa: BLE001 — the lane must never block the cycle
        _record_source_run(
            current_run, bot_state, SOURCE_KEY, source_start,
            status="failed", observed=0, error=f"newsworthiness fetch failed: {exc}",
        )
        return

    state.record_news_events(bot_state, result.events)
    observed = len(result.events)
    note_bits = [
        f"events={observed}",
        f"dropped_unwarranted={result.dropped_unwarranted}",
        f"dropped_unverified={result.dropped_unverified}",
    ]
    if result.notes:
        note_bits.append("; ".join(result.notes[:3]))
    # A leg failure (notes present) still yielded the other leg's events —
    # that is degraded, not success; both legs clean is success even at 0
    # events (a quiet news day is a real answer).
    status = "degraded" if any("leg failed" in n for n in result.notes) else "success"
    _record_source_run(
        current_run, bot_state, SOURCE_KEY, source_start,
        status=status, observed=observed, note=" | ".join(note_bits),
    )
