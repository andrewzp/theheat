"""@theheat bot CLI and legacy compatibility facade."""

from __future__ import annotations

import importlib
from typing import Any

# ruff: noqa: F403,F405
from src.orchestrator.common import *
_cli = importlib.import_module("src.orchestrator.cli")
_common = importlib.import_module("src.orchestrator.common")
_finalize = importlib.import_module("src.orchestrator.finalize")
_hot10 = importlib.import_module("src.orchestrator.hot10")
_posting = importlib.import_module("src.orchestrator.posting")
_alerts = importlib.import_module("src.orchestrator.run_alerts")

_SOURCE_MODULES = (
    "open_meteo", "firms", "nifc", "co2", "methane", "nws_alerts",
    "gdacs", "copernicus_ems", "sea_ice", "drought", "enso", "marine",
    "climate_indices", "ocean_sst", "ocean_sst_anomaly", "coral_dhw", "co_ops", "river_gauges",
    "ice_mass", "gpm_imerg", "nsidc_snow", "ozone_hole", "reanalysis_anomaly", "synthesis",
)


_SYNC_MODULES = (
    _common,
    _finalize,
    _hot10,
    _posting,
    _alerts,
    *(importlib.import_module(f"src.orchestrator.sources.{name}") for name in _SOURCE_MODULES),
)
_PUBLIC_WRAPPERS: dict[str, Any] = {}


def _sync_compat_globals() -> None:
    current = globals()
    for module in _SYNC_MODULES:
        for name, value in current.items():
            if name.startswith("__") or name in {"_SYNC_MODULES", "_sync_compat_globals"}:
                continue
            if _PUBLIC_WRAPPERS.get(name) is value:
                continue
            if hasattr(module, name):
                setattr(module, name, value)


def run_alerts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    _sync_compat_globals()
    return _alerts.run_alerts(bot_state, current_run=current_run)


def run_leaderboard(bot_state: BotState, current_run: dict | None = None) -> BotState:
    _sync_compat_globals()
    return _hot10.run_leaderboard(bot_state, current_run=current_run)


def run_manual_tweet(bot_state: BotState, current_run: dict | None = None) -> BotState:
    _sync_compat_globals()
    return _posting.run_manual_tweet(bot_state, current_run=current_run)


def process_due_drafts(bot_state: BotState, current_run: dict | None = None) -> BotState:
    _sync_compat_globals()
    return _posting.process_due_drafts(bot_state, current_run=current_run)


def post_approved(tweet_text: str, bot_state: BotState) -> str:
    _sync_compat_globals()
    return _posting.post_approved(tweet_text, bot_state)


_PUBLIC_WRAPPERS.update({
    "run_alerts": run_alerts,
    "run_leaderboard": run_leaderboard,
    "run_manual_tweet": run_manual_tweet,
    "process_due_drafts": process_due_drafts,
    "post_approved": post_approved,
})


MAX_DRAFTS_PER_CYCLE = _finalize.MAX_DRAFTS_PER_CYCLE
_prune_weakest_cycle_drafts = _finalize._prune_weakest_cycle_drafts


def main() -> None:
    _sync_compat_globals()
    _cli.main({
        "alerts": run_alerts,
        "leaderboard": run_leaderboard,
        "manual_tweet": run_manual_tweet,
        "auto_publish_due": process_due_drafts,
    })


if __name__ == "__main__":
    main()
