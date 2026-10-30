"""Product-level source incidents projected from retained collector rows.

One incident identity is the exact product leg (``source_product_contracts``),
requested window, region and parser contract. A collector attaches its leg
attempts to the existing run-history ``details.incident`` payload; first/last
occurrence and recovery are projected from those retained rows only. There is no
second incident service, store or probe here.

Rules this module keeps:

- A provider HTTP success is not a qualified product: an empty, stale or
  malformed answer stays "reachable, unqualified".
- One broken leg names that leg; it never labels the whole source or every hazard
  unavailable.
- An HTTP 404/410 is a missing or retired endpoint, never "no events".
- A sibling product, alternate host or model witness of one adapter is one
  corroboration group (``corroboration_groups``): it can serve, never corroborate.
- Recovery is a later *qualified* attempt for the same identity. A different
  window, region or parser contract cannot close an older incident.
- Public text is fixed vocabulary: no URL, key, token or raw provider error.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any

import requests

from src.data.source_product_contracts import corroboration_groups, legs_by_id

SCHEMA = "theheat.source-incident/v1"

OUTCOMES: dict[str, str] = {
    "qualified": "Product rows parsed under the parser contract.",
    "empty_success": "Provider answered with a valid header and zero data rows.",
    "stale_product": "Rows parsed, but none is current for the requested window.",
    "malformed": "Provider answered, but the body is not the expected product.",
    "endpoint_missing": "HTTP 404/410: endpoint or product file missing or retired; not 'no events'.",
    "access_refused": "Provider refused access (HTTP 401/403 or a credential refusal body).",
    "access_expired": "Local credential expiry gate; no provider request was sent.",
    "access_not_configured": "No credential configured; no provider request was sent.",
    "rate_limited": "HTTP 429 from the provider.",
    "provider_error": "HTTP 5xx from the provider.",
    "transport_failure": "Timeout, DNS or connection failure before a provider answer.",
    "granule_missing": "No product file was published inside the bounded walkback window.",
    "not_attempted": "The leg was not reached in this run.",
}
QUALIFIED = frozenset({"qualified"})
REACHABLE_UNQUALIFIED = frozenset({"empty_success", "stale_product", "malformed"})
ACCESS_HOLDS = frozenset({"access_refused", "access_expired", "access_not_configured"})
FAILURES = frozenset(OUTCOMES) - QUALIFIED - {"not_attempted"}

NEXT_ACTIONS: dict[str, str] = {
    "endpoint_missing": ("Supply an operator endpoint confirmation for this exact product "
                         "(scripts/source_incident_plan.py validate-input); the code never guesses a replacement URL."),
    "access_refused": "Owner: confirm the account/key for this provider; no credential search is performed.",
    "access_expired": "Owner: renew the expired credential in the production secret store.",
    "access_not_configured": "Owner: configure the credential if this source should run; skipped otherwise.",
    "malformed": "Inspect the retained parser contract; a provider answer that is not the product is not recovery.",
    "empty_success": "Reachable but no product rows: wait for a qualified run; this is not recovery or 'no events'.",
    "stale_product": "Reachable but stale: wait for a current product day.",
    "rate_limited": "Wait for the provider window; the next scheduled run retries within existing limits.",
    "provider_error": "Provider-side failure; the next scheduled run retries within existing limits.",
    "transport_failure": "Transport failure; the next scheduled run retries within existing limits.",
    "granule_missing": "No product file inside the walkback window; wait for publication.",
}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:/=-]{0,95}\Z")
_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_ACCESS_BODY = re.compile(r"invalid (?:map_key|api[ _]?key|token)|unauthori[sz]ed|access denied|expired token",
                          re.IGNORECASE)


def _token(value: Any, field: str) -> str:
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise ValueError(f"source_incident_{field}")
    return value


def incident_key(product_id: str, *, window: str, region: str, parser_contract: str) -> str:
    """Stable identity: product leg + requested window + region + parser contract."""
    return "|".join((_token(product_id, "product"), _token(window, "window"), _token(region, "region"),
                     _token(parser_contract, "parser_contract")))


def classify_status(status: int) -> str | None:
    """HTTP status → outcome; ``None`` means a 2xx whose body still needs parsing."""
    if type(status) is not int or not 100 <= status <= 599:
        return "malformed"
    if status in {404, 410}:
        return "endpoint_missing"
    if status in {401, 403}:
        return "access_refused"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "provider_error"
    if 200 <= status < 300:
        return None
    return "malformed"


def classify_body(text: Any, *, required_header: Iterable[str]) -> tuple[str, int]:
    """A 2xx CSV body → (outcome, data row count). HTML or refusal text is not a product."""
    if type(text) is not str:
        return "malformed", 0
    stripped = text.lstrip("﻿ \t\r\n")
    if _ACCESS_BODY.search(stripped[:512]):
        return "access_refused", 0
    if not stripped or stripped.startswith("<"):
        return "malformed", 0
    lines = [line for line in stripped.splitlines() if line.strip()]
    header = [cell.strip() for cell in lines[0].split(",")]
    if not set(required_header).issubset(header) or len(header) != len(set(header)):
        return "malformed", 0
    rows = len(lines) - 1
    return ("qualified" if rows else "empty_success"), rows


def classify_exception(exc: BaseException) -> str:
    """Exception → outcome, from type and status only (never its message text)."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return classify_status(exc.response.status_code) or "malformed"
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return "transport_failure"
    if isinstance(exc, requests.RequestException):
        return "transport_failure"
    text = str(exc).lower()
    if "freshness check failed" in text:
        return "stale_product"
    if "schema drift" in text or "malformed" in text or "header" in text or "valid source rows" in text:
        return "malformed"
    return "malformed"


def http_status_of(exc: BaseException) -> int | None:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status if type(status) is int and 100 <= status <= 599 else None
    return None


def attempt(product_id: str, outcome: str, *, window: str, region: str, parser_contract: str,
            http_status: int | None = None, rows: int | None = None, at: str | None = None,
            detail: Mapping[str, int] | None = None) -> dict[str, Any]:
    """One leg attempt with its product identity and corroboration role."""
    legs = legs_by_id()
    if product_id not in legs:
        raise ValueError("source_incident_product")
    if outcome not in OUTCOMES:
        raise ValueError("source_incident_outcome")
    if http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599):
        raise ValueError("source_incident_http_status")
    if rows is not None and (type(rows) is not int or rows < 0):
        raise ValueError("source_incident_rows")
    leg = legs[product_id]
    row: dict[str, Any] = {
        "key": incident_key(product_id, window=window, region=region, parser_contract=parser_contract),
        "product_id": product_id, "source_id": leg.source_id, "role": leg.role, "provider": leg.provider,
        "upstream": leg.upstream, "data_kind": leg.data_kind, "window": window, "region": region,
        "parser_contract": parser_contract, "outcome": outcome, "http_status": http_status, "rows": rows,
    }
    if at is not None:
        if type(at) is not str or not _AT.fullmatch(at):
            raise ValueError("source_incident_at")
        row["at"] = at
    if detail:
        row["detail"] = {_token(k, "detail"): min(int(v), 999_999) for k, v in sorted(detail.items())
                         if type(v) is int and v >= 0}
    return row


def run_incident(source: str, attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The per-run ``details.incident`` payload: product-level, never source-wide."""
    rows = [dict(item) for item in attempts]
    if any(row.get("outcome") not in OUTCOMES for row in rows):
        raise ValueError("source_incident_outcome")
    served = [row for row in rows if row["outcome"] in QUALIFIED]
    primary = [row for row in rows if row.get("role") == "primary"]
    if served and any(row.get("role") == "primary" for row in served):
        state = "primary_qualified"
    elif served:
        state = "alternate_served"
    elif any(row["outcome"] in REACHABLE_UNQUALIFIED for row in rows):
        state = "reachable_unqualified"
    elif rows and all(row["outcome"] in ACCESS_HOLDS | {"not_attempted"} for row in rows):
        state = "access_hold"
    elif rows:
        state = "unavailable"
    else:
        state = "not_recorded"
    served_ids = sorted({row["product_id"] for row in served})
    groups = corroboration_groups(served_ids) if served_ids else []
    return {
        "schema": SCHEMA, "source": _token(source, "source"), "product_state": state, "attempts": rows,
        "served_product_ids": served_ids,
        # Legs of one adapter or upstream are one group: serving is not corroboration.
        "independent_source_upper_bound": len(groups),
        "primary_outcomes": sorted({row["outcome"] for row in primary}),
        "open_keys": sorted({row["key"] for row in rows if row["outcome"] in FAILURES}),
    }


def _runs_oldest_first(run_history: Any) -> list[Mapping[str, Any]]:
    runs = [run for run in (run_history if isinstance(run_history, list) else []) if isinstance(run, Mapping)]
    return sorted(runs, key=lambda run: str(run.get("started_at") or ""))


def project_incidents(run_history: Any, *, source: str | None = None) -> list[dict[str, Any]]:
    """First/last occurrence and recovery per identity from retained run rows only."""
    table: dict[str, dict[str, Any]] = {}
    for run in _runs_oldest_first(run_history):
        at = str(run.get("started_at") or "")
        for entry in run.get("sources") or []:
            if not isinstance(entry, Mapping) or (source is not None and entry.get("source") != source):
                continue
            details = entry.get("details")
            incident = details.get("incident") if isinstance(details, Mapping) else None
            if not isinstance(incident, Mapping) or incident.get("schema") != SCHEMA:
                continue
            for item in incident.get("attempts") or []:
                if not isinstance(item, Mapping) or item.get("outcome") not in OUTCOMES or item["outcome"] == "not_attempted":
                    continue
                key = str(item.get("key"))
                row = table.get(key)
                if row is None:
                    row = table[key] = {
                        "key": key, "source": entry.get("source"), "product_id": item.get("product_id"),
                        "role": item.get("role"), "provider": item.get("provider"), "window": item.get("window"), "region": item.get("region"),
                        "parser_contract": item.get("parser_contract"), "first_failure": None,
                        "last_failure": None, "failures": 0, "last_outcome": None, "last_at": None,
                        "recovered_at": None, "recovery_run": None, "failure_outcomes": [],
                    }
                outcome = item["outcome"]
                row["last_outcome"], row["last_at"] = outcome, at
                if outcome in QUALIFIED:
                    if row["failures"] and row["recovered_at"] is None:
                        row["recovered_at"], row["recovery_run"] = at, run.get("id")
                    continue
                if row["recovered_at"] is not None:
                    # A new failure after recovery reopens; earlier history is kept.
                    row["recovered_at"] = row["recovery_run"] = None
                row["failures"] += 1
                row["first_failure"] = row["first_failure"] or at
                row["last_failure"] = at
                if outcome not in row["failure_outcomes"]:
                    row["failure_outcomes"].append(outcome)
    result = []
    for row in table.values():
        last = row["last_outcome"]
        if last in QUALIFIED:
            state = "recovered" if row["failures"] else "qualified"
        elif last in REACHABLE_UNQUALIFIED:
            state = "reachable_unqualified"
        elif last in ACCESS_HOLDS:
            state = "access_hold"
        else:
            state = "open"
        row["state"] = state
        row["next_action"] = None if state in {"recovered", "qualified"} else NEXT_ACTIONS.get(last)
        row["retained_window"] = "retained_run_history_only"
        result.append(row)
    return sorted(result, key=lambda row: (str(row["source"]), row["key"]))


def recovery_summary(incidents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sources/Operations view: a cleared transport error alone is not recovery."""
    by_state: dict[str, list[str]] = {}
    for row in incidents:
        by_state.setdefault(str(row["state"]), []).append(str(row["product_id"]))
    return {"states": {state: sorted(ids) for state, ids in sorted(by_state.items())},
            "recovered_requires": "a later qualified attempt for the same product, window, region and parser contract"}



# --- GPM / Earthdata (owner-access boundary) --------------------------------------
_GPM_LEGS = {
    "imerg_late_grid_datapool": ("gpm_imerg.imerg_late_grid_datapool", "configured_watchlist", "gpm_imerg.grid_subset"),
    "imerg_late_grid_s3": ("gpm_imerg.imerg_late_grid_s3", "configured_watchlist", "gpm_imerg.grid_subset"),
    "imerg_late_opendap": ("gpm_imerg.imerg_late_opendap", "rotating_window", "gpm_imerg.ascii_subset"),
    "open_meteo_witness": ("gpm_imerg.open_meteo_witness", "rotating_window", "open_meteo.ensemble_agreement"),
}
_GPM_WINDOW = "imerg_late_daily_walkback"
_GRID_REASON = {"not_found": "granule_missing", "transient": "transport_failure", "parse_error": "malformed",
                "zero_readings": "empty_success"}


def _gpm_leg_outcome(leg: Mapping[str, Any]) -> tuple[str, int | None, dict[str, int]]:
    signatures = leg.get("failure_signatures") if isinstance(leg.get("failure_signatures"), Mapping) else {}
    codes = leg.get("dispositions") if type(leg.get("dispositions")) is str else ""
    detail = {"failed_members": codes.count("f"), "unreadable_members": codes.count("u") + codes.count("o"),
              "read_members": codes.count("r")}
    detail = {k: v for k, v in detail.items() if v}
    outcome = leg.get("outcome")
    statuses = {str(sig) for sig in signatures}
    if outcome == "served":
        return "qualified", leg.get("readings") if type(leg.get("readings")) is int else codes.count("r"), detail
    if outcome == "stale_data_date":
        return "stale_product", None, detail
    if statuses & {"HTTP 401", "HTTP 403"}:
        return "access_refused", None, detail
    if "HTTP 404" in statuses or "HTTP 410" in statuses:
        return "endpoint_missing", None, detail
    if outcome == "unavailable":
        return _GRID_REASON.get(str(leg.get("reason")), "malformed"), None, detail
    probes = leg.get("date_probes") if isinstance(leg.get("date_probes"), list) else []
    if probes and all(isinstance(p, Mapping) and p.get("outcome") == "not_found" for p in probes):
        return "granule_missing", None, detail
    if outcome == "no_readings":
        return ("transport_failure" if statuses else "empty_success"), 0, detail
    if any(isinstance(p, Mapping) and p.get("outcome") == "error_stopped_walkback" for p in probes):
        return "transport_failure", None, detail
    return ("transport_failure" if statuses else "not_attempted"), None, detail


def gpm_attempts(trace_export: Any) -> list[dict[str, Any]]:
    """Product-level attempts from the existing GPM rainfall trace export (no new capture)."""
    if not isinstance(trace_export, Mapping):
        return []
    gate = trace_export.get("primary_gate")
    product = trace_export.get("product") if type(trace_export.get("product")) is str else "late"
    window = f"{_GPM_WINDOW}_{product}" if _TOKEN.fullmatch(f"{_GPM_WINDOW}_{product}") else _GPM_WINDOW
    rows: list[dict[str, Any]] = []
    if gate in {"credential_expired", "credential_not_configured"}:
        product_id, region, parser = _GPM_LEGS["imerg_late_opendap"]
        outcome = "access_expired" if gate == "credential_expired" else "access_not_configured"
        rows.append(attempt(product_id, outcome, window=window, region=region, parser_contract=parser))
    for leg in trace_export.get("legs") or []:
        if not isinstance(leg, Mapping) or leg.get("leg") not in _GPM_LEGS:
            continue
        product_id, region, parser = _GPM_LEGS[str(leg["leg"])]
        outcome, count, detail = _gpm_leg_outcome(leg)
        rows.append(attempt(product_id, outcome, window=window, region=region, parser_contract=parser,
                            rows=count, detail=detail))
    return rows


EARTHDATA_PUBLIC_TEXT = {
    "access_expired": "Earthdata access expired: owner renewal required. No request was sent.",
    "access_not_configured": "Earthdata access is not configured. No request was sent.",
    "access_refused": "Earthdata refused access: owner account/key check required. Collection stopped at the first refusal.",
}
_ATTESTATION_KEYS = frozenset({"schema", "provider", "action", "attested_at", "attested_by", "evidence_reference"})
_SECRETISH = re.compile(r"token|secret|password|passwd|bearer|cookie|api[_-]?key|credential_value", re.IGNORECASE)
ATTESTATION_SCHEMA = "theheat.owner-access-attestation/v1"


def validate_access_attestation(document: Any) -> dict[str, Any]:
    """An owner statement that access was renewed. It never carries a credential value."""
    if not isinstance(document, Mapping) or set(document) != _ATTESTATION_KEYS:
        raise ValueError("owner_access_attestation_shape")
    if any(_SECRETISH.search(str(value)) for value in document.values() if isinstance(value, str)
           and len(value) > 40):
        raise ValueError("owner_access_attestation_contains_secret_like_value")
    if document["schema"] != ATTESTATION_SCHEMA or document["provider"] != "earthdata" \
            or document["action"] not in {"token_renewed", "account_access_confirmed"} \
            or document["attested_by"] != "owner":
        raise ValueError("owner_access_attestation_value")
    if type(document["attested_at"]) is not str or not _AT.fullmatch(document["attested_at"]):
        raise ValueError("owner_access_attestation_time")
    ref = document["evidence_reference"]
    if type(ref) is not str or not 1 <= len(ref) <= 200 or _SECRETISH.search(ref) and len(ref) > 40:
        raise ValueError("owner_access_attestation_reference")
    return dict(document)


def earthdata_access_hold(incidents: Sequence[Mapping[str, Any]], *,
                          attestation: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Named owner-action hold for GPM access; no login loop, search or replay.

    ``incidents`` are ``project_incidents`` rows. An attestation moves the hold to
    "awaiting a qualified run": it never qualifies earlier observations.
    """
    rows = [row for row in incidents if str(row.get("product_id", "")).startswith("gpm_imerg.")
            and row.get("role") in {"primary", "alternate_route"}]
    access = [row for row in rows if row.get("state") == "access_hold"]
    if not access:
        return None
    latest_refusal = max(str(row.get("last_failure") or "") for row in access)
    if any(row.get("state") in {"recovered", "qualified"} and str(row.get("last_at") or "") > latest_refusal
           for row in rows):
        # A later qualified GES DISC result establishes access; nothing earlier is requalified.
        return None
    stage = str(access[-1]["last_outcome"])
    hold: dict[str, Any] = {
        "hold": "earthdata_owner_access", "stage": stage,
        "public_text": EARTHDATA_PUBLIC_TEXT.get(stage, EARTHDATA_PUBLIC_TEXT["access_refused"]),
        "owner_action": ("Owner renews the Earthdata Login token in the production secret store and records "
                         "an owner-access attestation; the next scheduled run is the only new attempt."),
        "login_loop": False, "credential_search": "not_performed", "automatic_retry": "next_scheduled_run_only",
        "requalifies_prior_observations": False, "since": access[0].get("first_failure"),
        "products": sorted({str(row["product_id"]) for row in access}),
    }
    if attestation is not None:
        accepted = validate_access_attestation(attestation)
        later = [row for row in rows if row.get("state") in {"recovered", "qualified"}
                 and str(row.get("last_at") or "") > accepted["attested_at"]]
        hold["attestation"] = {"attested_at": accepted["attested_at"], "action": accepted["action"]}
        hold["stage"] = "recovered_after_attestation" if later else "renewal_attested_awaiting_qualified_run"
    return hold

__all__ = [
    "ACCESS_HOLDS", "ATTESTATION_SCHEMA", "EARTHDATA_PUBLIC_TEXT", "FAILURES", "NEXT_ACTIONS", "OUTCOMES", "QUALIFIED", "REACHABLE_UNQUALIFIED", "SCHEMA",
    "attempt", "classify_body", "earthdata_access_hold", "gpm_attempts", "validate_access_attestation", "classify_exception", "classify_status", "http_status_of", "incident_key",
    "project_incidents", "recovery_summary", "run_incident",
]
