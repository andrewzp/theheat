"""Cheap drafting prerequisites, never a paid health probe or a factual pass."""

from __future__ import annotations

import os


def provider_preflight(
    *,
    writer_provider: str,
    anthropic_configured: bool,
    google_configured: bool,
    loaded_safety_configured: bool,
    critic_enabled: bool,
) -> dict:
    """Presence is necessary, but does not establish access, funding or capacity.

    Safety uses a key loaded at module import; writer/checker/critic read the
    environment per call. Keep those prerequisites distinct during key changes.
    """
    if any(
        type(value) is not bool
        for value in (
            anthropic_configured,
            google_configured,
            loaded_safety_configured,
            critic_enabled,
        )
    ):
        raise ValueError("Preflight requires explicit boolean availability")
    blocked = []
    if writer_provider not in {"anthropic", "google"}:
        blocked.append({"stage": "writer", "reason": "unsupported_provider"})
    elif not (anthropic_configured if writer_provider == "anthropic" else google_configured):
        blocked.append({"stage": "writer", "reason": "missing_credential"})
    if not loaded_safety_configured:
        blocked.append({"stage": "safety", "reason": "missing_loaded_credential"})
    if not google_configured:
        blocked.append({"stage": "fact_check", "reason": "missing_credential"})
        if critic_enabled:
            blocked.append({"stage": "critic", "reason": "missing_credential"})
    return {
        "status": "blocked" if blocked else "configured_unverified",
        "blocked_stages": blocked,
        "provider_access_verified": False,
        "funding_verified": False,
    }


def current_provider_preflight(*, critic_enabled: bool) -> dict:
    from src.two_bot import writer
    from src.voice import safety

    return provider_preflight(
        writer_provider=writer.WRITER_PROVIDER,
        anthropic_configured=bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        google_configured=bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        loaded_safety_configured=bool(safety.GEMINI_API_KEY.strip()),
        critic_enabled=critic_enabled,
    )
