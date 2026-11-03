"""Versioned source identities that survive ordinary Python/JavaScript JSON.

Measurements keep their numeric value across int/float representation changes.
Domain validators still enforce metadata types, provenance, units and meaning.
This authenticates no source and never rewrites evidence or existing identities.
"""
from __future__ import annotations

import math
from typing import Any

from src.editorial.revisions import fingerprint as semantic_fingerprint

MAX_SAFE_INTEGER = (1 << 53) - 1


def fingerprint(value: Any, *, profile: str) -> str:
    remaining = 100_000

    def supported(item: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 64:
            raise ValueError("evidence_identity_capacity")
        if item is None or type(item) in (str, bool):
            return
        if type(item) in (int, float):
            if abs(item) > MAX_SAFE_INTEGER or not math.isfinite(item):
                raise ValueError("evidence_number_not_interoperable")
            return
        if type(item) is list:
            for child in item:
                supported(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                supported(child, depth + 1)
            return
        raise ValueError("evidence_identity_requires_json")

    if type(profile) is not str or not 0 < len(profile) <= 128:
        raise ValueError("evidence_identity_profile")
    supported(value, 0)
    return semantic_fingerprint({"profile": profile, "value": value})
