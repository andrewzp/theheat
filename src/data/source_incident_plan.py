"""Offline diagnostic and repair plan for current source incidents (W03.6).

Inputs are a retained state snapshot plus optional owner/operator documents:
an endpoint confirmation (the exact product endpoint an operator verified) and an
owner-access attestation (that a credential was renewed, never its value). The
plan only reads those inputs: no probe, crawl, credential enumeration, account
repair, paid self-heal or background activation happens here.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlsplit

from src.data import firms, source_access, source_incidents
from src.data.source_product_contracts import legs_by_id

SCHEMA = "theheat.source-incident-plan/v1"
CONFIRMATION_SCHEMA = "theheat.endpoint-confirmation/v1"
_CONFIRMATION_KEYS = frozenset({"schema", "product_id", "endpoint_template", "confirmed_at", "confirmed_by",
                                "evidence_reference"})
_PLACEHOLDER = re.compile(r"\{[a-z_]{1,16}\}")
_KEYLIKE = re.compile(r"[A-Fa-f0-9]{24,}|[A-Za-z0-9_-]{40,}")

# The endpoints the current code actually requests, with credentials as placeholders.
CURRENT_ENDPOINTS: dict[str, str] = {
    **{f"firms.{product.lower()}": f"{firms.FIRMS_URL}/{{key}}/{product}/world/{{days}}"
       for product in ("VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")},
    "firms.noaa_hms": f"{firms.HMS_FIRE_URL}/{{yyyy}}/{{mm}}/hms_fire{{yyyymmdd}}.txt",
}
SELF_HEAL = {
    "repair_flag": "THEHEAT_SELFHEAL_REPAIR_ENABLED",
    "paid_repair": "not_invoked_by_this_plan",
    "background_activation": "not_performed",
    "rule": "Self-heal keeps its existing gate; this plan never starts a model agent or edits configuration.",
}


def validate_endpoint_confirmation(document: Any) -> dict[str, Any]:
    """An operator's verified endpoint for one product; credentials stay placeholders."""
    if not isinstance(document, Mapping) or set(document) != _CONFIRMATION_KEYS:
        raise ValueError("endpoint_confirmation_shape")
    if document["schema"] != CONFIRMATION_SCHEMA or document["confirmed_by"] not in {"owner", "operator"}:
        raise ValueError("endpoint_confirmation_value")
    if document["product_id"] not in legs_by_id():
        raise ValueError("endpoint_confirmation_product")
    template = document["endpoint_template"]
    if type(template) is not str or len(template) > 400:
        raise ValueError("endpoint_confirmation_template")
    parts = urlsplit(template)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment or "@" in parts.netloc:
        raise ValueError("endpoint_confirmation_template")
    if _KEYLIKE.search(_PLACEHOLDER.sub("", template)):
        raise ValueError("endpoint_confirmation_contains_credential_like_value")
    if type(document["confirmed_at"]) is not str or not source_incidents._AT.fullmatch(document["confirmed_at"]):
        raise ValueError("endpoint_confirmation_time")
    ref = document["evidence_reference"]
    if type(ref) is not str or not 1 <= len(ref) <= 200:
        raise ValueError("endpoint_confirmation_reference")
    return dict(document)


def _endpoint_action(row: Mapping[str, Any], confirmations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    product_id = str(row["product_id"])
    current = CURRENT_ENDPOINTS.get(product_id)
    confirmation = confirmations.get(product_id)
    if confirmation is None:
        return {
            "action": "operator_endpoint_confirmation_required", "owner": "operator",
            "input_schema": CONFIRMATION_SCHEMA, "product_id": product_id, "current_code_endpoint": current,
            "text": "Verify this exact product endpoint from provider documentation and supply a confirmation "
                    "document; a 404 is not 'no events' and no replacement URL is guessed.",
        }
    if current is not None and confirmation["endpoint_template"] == current:
        return {"action": "confirmed_endpoint_still_missing", "owner": "provider", "product_id": product_id,
                "text": "The confirmed endpoint is the one already requested; the product stays held until a "
                        "qualified run. Nothing in code changes."}
    return {"action": "code_change_review_required", "owner": "root", "product_id": product_id,
            "current_code_endpoint": current, "confirmed_endpoint": confirmation["endpoint_template"],
            "text": "The confirmed endpoint differs from the code; Root reviews a code change. This plan never "
                    "rewrites configuration or URLs."}


def build_plan(state: Mapping[str, Any], *, confirmations: Sequence[Mapping[str, Any]] = (),
               attestations: Sequence[Mapping[str, Any]] = (), now: datetime | None = None) -> dict[str, Any]:
    """Exact next action per open product incident, from retained inputs only."""
    confirmed = {doc["product_id"]: doc for doc in (validate_endpoint_confirmation(d) for d in confirmations)}
    attested = [source_incidents.validate_access_attestation(doc) for doc in attestations]
    incidents = source_incidents.project_incidents(state.get("run_history") if isinstance(state, Mapping) else None)
    actions: list[dict[str, Any]] = []
    for row in incidents:
        if row["state"] in {"qualified", "recovered"}:
            continue
        outcome = row["last_outcome"]
        if outcome == "endpoint_missing":
            action = _endpoint_action(row, confirmed)
        elif outcome in source_incidents.ACCESS_HOLDS:
            action = {"action": "owner_access_action", "owner": "owner", "product_id": row["product_id"],
                      "text": source_incidents.NEXT_ACTIONS[outcome]}
        elif outcome == "malformed":
            action = {"action": "local_parser_review", "owner": "code", "product_id": row["product_id"],
                      "parser_contract": row["parser_contract"],
                      "text": "Offline: replay the retained packet through the named parser contract; a provider "
                              "answer that is not the product never counts as recovery."}
        else:
            action = {"action": "wait_for_next_scheduled_run", "owner": "none", "product_id": row["product_id"],
                      "text": source_incidents.NEXT_ACTIONS.get(str(outcome), "Wait for a qualified run.")}
        actions.append({**action, "key": row["key"], "state": row["state"], "since": row["first_failure"],
                        "failures_in_retained_runs": row["failures"]})
    hold = source_incidents.earthdata_access_hold(incidents, attestation=attested[-1] if attested else None)
    return {
        "schema": SCHEMA, "network": "not_used", "credential_enumeration": "not_performed",
        "incidents": incidents, "recovery": source_incidents.recovery_summary(incidents),
        "actions": actions, "earthdata_hold": hold, "self_heal": SELF_HEAL,
        # Credential state, refusal backoff and last-good GPM data age (no request is sent).
        "gpm_access": source_access.gpm_access_health(state if isinstance(state, Mapping) else {},
                                                      now=now or datetime.now(timezone.utc)),
        "scope": "retained_run_history_only_not_current_availability",
    }


__all__ = ["CONFIRMATION_SCHEMA", "CURRENT_ENDPOINTS", "SCHEMA", "SELF_HEAL", "build_plan",
           "validate_endpoint_confirmation"]
