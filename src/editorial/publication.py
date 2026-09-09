"""Fail-closed automatic publication policy and durable epoch retirement.

Epochs are release authorizations, not timestamps or locks. Rotate the epoch on
EVERY pause and release, and let a serialized bot invocation observe a pause
before releasing. Configuration cannot recall an already-running old process.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import os
import re
from typing import Any

from src.state_schema import BotState

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,95}")


def valid_epoch(value: Any) -> bool:
    return isinstance(value, str) and _EPOCH.fullmatch(value) is not None


def merge_publication_control(current: Any, incoming: Any) -> dict:
    """Retired epochs are never forgotten by a stale writer or normal pruning."""
    retired: set[str] = set()
    rows = []
    invalid = False
    for value in (current, incoming):
        if value is None:
            continue
        if not isinstance(value, dict):
            invalid = True
            continue
        epochs = value.get("retired_epochs", [])
        if not isinstance(epochs, list) or any(not valid_epoch(epoch) for epoch in epochs):
            invalid = True
        else:
            retired.update(epochs)
        invalid = invalid or value.get("invalid_control") is True
        if value.get("observed_at"):
            rows.append(value)
    latest = max(rows, key=lambda row: str(row.get("observed_at", "")), default={})
    result = {key: latest[key] for key in ("observed_at", "epoch", "enabled", "reason") if key in latest}
    result["retired_epochs"] = sorted(retired)
    if invalid:
        result["invalid_control"] = True
    return result


def automatic_publication_policy(bot_state: Mapping[str, Any] | None = None) -> dict:
    requested = os.environ.get("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0") == "1"
    raw_epoch = os.environ.get("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "")
    epoch = raw_epoch if valid_epoch(raw_epoch) else None
    control = merge_publication_control((bot_state or {}).get("publication_control"), None)
    if not requested:
        reason = "Automatic publication is paused. Ingestion and review remain available."
    elif epoch is None:
        reason = "Automatic publication needs a valid, new release epoch."
    elif control.get("invalid_control"):
        reason = "Publication control is invalid; repair it before releasing automation."
    elif epoch in control["retired_epochs"]:
        reason = "This release epoch was retired. Revalidate drafts under a new release epoch."
    else:
        reason = "Automatic publication enabled for the current release epoch."
        return {"enabled": True, "epoch": epoch, "reason": reason}
    return {"enabled": False, "epoch": epoch, "reason": reason}


def observe_publication_policy(bot_state: BotState | dict) -> dict:
    """Record policy and disarm obsolete auto decisions without erasing attempts."""
    from src.editorial.revisions import revoke_approval

    control = merge_publication_control(bot_state.get("publication_control"), None)
    policy = automatic_publication_policy(bot_state)
    retired = set(control["retired_epochs"])
    previous = control.get("epoch")
    if valid_epoch(previous) and (not policy["enabled"] or previous != policy["epoch"]):
        retired.add(previous)
    if not policy["enabled"] and valid_epoch(policy["epoch"]):
        retired.add(policy["epoch"])
    for draft in bot_state.get("drafts", []):
        if not isinstance(draft, dict) or draft.get("status") not in ("pending", "approved"):
            continue
        binding = draft.get("approval_binding") or {}
        auto = binding.get("mode") == "auto" or draft.get("approval_mode") in ("auto", "policy_auto") or bool(draft.get("auto_approve_at"))
        if not auto:
            continue
        bound_epoch = binding.get("publication_epoch")
        if not policy["enabled"] or bound_epoch != policy["epoch"] or bound_epoch in retired:
            if valid_epoch(bound_epoch):
                retired.add(bound_epoch)
            # revoke_approval retains publish_outcome, timestamps and ledger data.
            revoke_approval(draft)
            draft["post_error"] = "Automatic approval revoked: publication paused or release epoch changed. Review this draft again."
    control.update(policy, retired_epochs=sorted(retired), observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    bot_state["publication_control"] = control
    return automatic_publication_policy(bot_state)


def automatic_approval_allowed(draft: dict, bot_state: Mapping[str, Any]) -> bool:
    policy = automatic_publication_policy(bot_state)
    return policy["enabled"] and (draft.get("approval_binding") or {}).get("publication_epoch") == policy["epoch"]
