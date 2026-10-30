"""One purchase per retained story, whichever supported engine it names.

A retained brief names exactly one engine (``urgent`` → synchronous, otherwise
batch); there is no fallback between engines. Two current briefs for the same
source revision and event are one purchase: whichever engine holds it (even
with an unknown batch submission), the other must not buy a second writer
call. This identity deliberately ignores the engine, timing window and bundle
wording, so toggling ``urgent`` or re-wording a brief cannot buy twice.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.editorial.revisions import fingerprint


def purchase_identity(value: Mapping[str, Any]) -> str:
    save = value.get("save") if isinstance(value, Mapping) else None
    bundle = value.get("bundle") if isinstance(value, Mapping) else None
    return fingerprint({"source_key": value.get("source_key"), "source_revision": value.get("source_revision"),
                        "event_id": save.get("event_id") if isinstance(save, Mapping) else None,
                        "signal_kind": bundle.get("signal_kind") if isinstance(bundle, Mapping) else None})


def duplicate_purchases(values: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Brief ids whose purchase identity another current brief shares (all of them are held)."""
    groups: dict[str, list[str]] = {}
    for brief_id, value in values.items():
        groups.setdefault(purchase_identity(value), []).append(brief_id)
    return {brief for briefs in groups.values() if len(briefs) > 1 for brief in briefs}


def engine_for(value: Mapping[str, Any]) -> str:
    """The named engine only; unavailability is a refusal, never a switch."""
    if type(value.get("urgent")) is not bool:
        raise ValueError("generation_input_invalid")
    return "synchronous" if value["urgent"] else "batch"


__all__ = ["duplicate_purchases", "engine_for", "purchase_identity"]
