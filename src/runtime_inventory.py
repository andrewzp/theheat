"""Allowlisted observations of the bot process, captured without external calls.

This is configuration evidence from an actual invocation, not a provider health
check. Credential presence cannot establish validity, permission, or credits.
The dashboard must display the capture time and treat missing snapshots as
unknown rather than substituting its own deployment's environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
import os
from pathlib import Path
import re


_VERSION_PATH = Path(__file__).resolve().parents[1] / "VERSION"
_VERSION_SHAPE = re.compile(r"\d+(?:\.\d+){2,3}(?:[-+][A-Za-z0-9.-]+)?")
_SHA_SHAPE = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?")


def _version() -> str | None:
    try:
        value = _VERSION_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return value if _VERSION_SHAPE.fullmatch(value) else None


def collect_runtime_inventory(mode: str, *, now: datetime | None = None, bot_state: Mapping[str, Any] | None = None) -> dict:
    """Return only named, non-secret configuration effective in this process.

    Model modules cache configuration at import time; report their actual
    constants instead of re-reading environment overrides that may disagree.
    Existing flag resolvers preserve each caller's real parsing and defaults.
    Imports are local to avoid a CLI/common-module import cycle.
    """
    from src import state
    from src.data import firms, gpm_imerg, twitter_metrics
    from src.editorial import approval, newsworthiness
    from src.editorial.publication import automatic_publication_policy
    from src.orchestrator import caps, funnel, hot10, scheduler, triage_queue
    from src.orchestrator.sources import air_quality, open_meteo
    from src.orchestrator.sources import newsworthiness as news_source
    from src.posting import bluesky
    from src.two_bot import critic, fact_check, pipeline, writer
    from src.voice import safety

    captured_at = now or datetime.now(UTC)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    raw_sha = os.environ.get("GITHUB_SHA", "")
    raw_run_id = os.environ.get("GITHUB_RUN_ID", "")
    signals_provider = os.environ.get("THEHEAT_SIGNALS_PROVIDER", "open_meteo").lower()

    from src.editorial.policy import current_editorial_policy
    publication_policy = automatic_publication_policy(bot_state)
    return {
        "schema_version": 1,
        "editorial_policy": current_editorial_policy(),
        "captured_at": captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "git_sha": raw_sha.lower() if _SHA_SHAPE.fullmatch(raw_sha) else None,
        "version": _version(),
        "github_run_id": raw_run_id if raw_run_id.isascii() and raw_run_id.isdigit() else None,
        "state_backend": state._configured_backend(),
        "models": {
            "writer": writer.WRITER_MODEL,
            "writer_provider": writer.WRITER_PROVIDER,
            "fact_check": fact_check.FACT_CHECKER_MODEL,
            "critic": critic.CRITIC_MODEL,
            "safety": safety.GEMINI_SAFETY_MODEL,
            "claim_extract": None,
        },
        "flags": {
            "automatic_publication_enabled": publication_policy["enabled"],
            "automatic_publication_epoch": publication_policy["epoch"],
            "automatic_publication_reason": publication_policy["reason"],
            "autoship_on_critic_pass": approval.autoship_on_critic_pass_enabled(),
            "autoship_max_age_hours": approval.autoship_max_age_hours(),
            "critic_enabled": pipeline._critic_enabled(),
            "critic_revise_enabled": pipeline._critic_revise_enabled(),
            "writer_samples": pipeline._writer_samples(),
            "triage_enabled": triage_queue._triage_enabled(),
            "refill_enabled": caps.refill_enabled(),
            "funnel_telemetry": funnel.funnel_telemetry_enabled(),
            "concurrent_sources": scheduler.concurrent_sources_enabled(),
            "metrics_enabled": hot10._metrics_enabled(),
            "reganom_enabled": os.environ.get("THEHEAT_REGANOM_ENABLED", "0") == "1",
            "records_cluster_enabled": open_meteo._records_cluster_enabled(),
            "newsworthiness_enabled": news_source._enabled(),
            "news_enrich_enabled": newsworthiness.news_enrich_enabled(),
            "news_boost_enabled": newsworthiness.news_boost_enabled(),
            "engagement_window_enabled": os.environ.get("THEHEAT_ENGAGEMENT_WINDOW_ENABLED", "0") == "1",
            "shadow_ab_enabled": os.environ.get("THEHEAT_SHADOW_AB_ENABLED") == "1",
            "signals_provider": signals_provider if signals_provider in {"open_meteo", "ghcn", "both"} else None,
            "gpm_source": gpm_imerg._gpm_source(),
            "aq_pm25_enabled": air_quality._enabled("THEHEAT_AQ_PM25_ENABLED"),
            "aq_dust_enabled": air_quality._enabled("THEHEAT_AQ_DUST_ENABLED"),
            "wetbulb_enabled": os.environ.get("THEHEAT_WETBULB_ENABLED", "1") == "1",
        },
        "credentials_present": {
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "safety_gemini": bool(safety.GEMINI_API_KEY),
            "twitter": twitter_metrics.credentials_available(),
            "bluesky": bool(bluesky.BLUESKY_HANDLE and bluesky.BLUESKY_APP_PASSWORD),
            "nasa_firms": bool(firms.FIRMS_API_KEY),
            "earthdata": bool(os.environ.get("EARTHDATA_TOKEN")),
            "github_state": bool(state.GITHUB_TOKEN and state.GIST_ID),
        },
        "capabilities": {
            "claim_extraction": "inactive",
            "legacy_voice_generation": "inactive",
            "safety_llm": "configured" if safety.GEMINI_API_KEY else "inactive",
        },
    }
