"""Owner-access health for the credentialed GPM/Earthdata lane, from retained state only.

Three things the Sources view and the owner need, none of which sends a request:

- the credential's state, from the existing ``credential_expiry`` projection
  (an expiry date, never a value);
- the age of the last good GPM data: the newest data date retained by the
  primary path's own tracking (``precip_recent_by_city`` is updated only when
  GPM itself served, never from the model witness), so a run that "succeeds"
  with no product, or is served by the witness, does not refresh it;
- a bounded backoff after the provider REFUSED a credential (HTTP 401/403):
  the same credential (identified by its expiry claim, not its value) is tried
  again only after 6 h, then 24 h, then every 72 h; a renewed credential
  (different expiry) is tried at the next scheduled run. An expired credential
  is already stopped locally with no request.

Mirrored by ``dashboard/lib/source-access.js`` (shared fixture parity).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.data import source_incidents

SCHEMA = "theheat.source-access/v1"
REFUSAL_BACKOFF_HOURS = (6, 24, 72)
GPM_SOURCE = "gpm_imerg"
GPM_CREDENTIAL = "EARTHDATA_TOKEN"
CURRENT_DATA_DAYS = 2


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def credential_identity(expires_at: datetime | None, *, configured: bool) -> dict[str, Any]:
    """Non-secret identity of the configured credential: its expiry claim only."""
    return {"configured": configured, "expires_at": _iso(expires_at) if expires_at else None,
            "kind": None if not configured else ("jwt" if expires_at else "opaque")}


def _source_rows_newest_first(run_history: Any, source: str) -> list[tuple[str, Mapping[str, Any]]]:
    runs = [run for run in (run_history if isinstance(run_history, list) else []) if isinstance(run, Mapping)]
    rows = []
    for run in runs:
        for entry in run.get("sources") or []:
            if isinstance(entry, Mapping) and entry.get("source") == source:
                rows.append((str(run.get("started_at") or ""), entry))
    return sorted(rows, key=lambda row: row[0], reverse=True)


def _primary_qualified(entry: Mapping[str, Any]) -> bool:
    details = entry.get("details") if isinstance(entry.get("details"), Mapping) else {}
    incident = details.get("incident") if isinstance(details, Mapping) else None
    return isinstance(incident, Mapping) and incident.get("product_state") == "primary_qualified"


def refusal_backoff(run_history: Any, *, credential_expires_at: str | None, now: datetime,
                    source: str = GPM_SOURCE) -> dict[str, Any] | None:
    """The active backoff for this exact credential, or None when an attempt is allowed."""
    refusals, latest = 0, None
    for _at, entry in _source_rows_newest_first(run_history, source):
        if _primary_qualified(entry):
            break
        details = entry.get("details") if isinstance(entry.get("details"), Mapping) else {}
        access = details.get("earthdata_access") if isinstance(details, Mapping) else None
        if not isinstance(access, Mapping) or access.get("schema") != SCHEMA:
            continue
        if not access.get("refused"):
            continue  # a backoff skip sends nothing and is not a new refusal
        if access.get("credential_expires_at") != credential_expires_at:
            break  # an older credential's refusals never hold a renewed one
        refusals += 1
        if latest is None:
            latest = _parse(access.get("refused_at"))
    if not refusals or latest is None:
        return None
    hours = REFUSAL_BACKOFF_HOURS[min(refusals, len(REFUSAL_BACKOFF_HOURS)) - 1]
    after = latest + timedelta(hours=hours)
    if now >= after:
        return None
    return {"refused_at": _iso(latest), "consecutive_refusals": refusals, "next_attempt_after": _iso(after),
            "credential_expires_at": credential_expires_at, "requests_sent": 0}


def run_record(*, credential_expires_at: str | None, attempts: Sequence[Mapping[str, Any]],
               backoff: Mapping[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """The retained ``details.earthdata_access`` row, present only when a refusal or backoff occurred."""
    refused = any(item.get("outcome") == "access_refused" for item in attempts)
    if not refused and backoff is None:
        return None
    return {"schema": SCHEMA, "credential_expires_at": credential_expires_at, "refused": refused,
            "refused_at": _iso(now) if refused else None, "backoff": dict(backoff) if backoff else None}


def gpm_last_good(state: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Newest data date the primary GPM path retained, and its age in days."""
    newest: date | None = None
    cities = 0
    recent = state.get("precip_recent_by_city")
    for rows in (recent.values() if isinstance(recent, Mapping) else []):
        for row in rows if isinstance(rows, list) else []:
            text = row.get("date") if isinstance(row, Mapping) else None
            try:
                day = date.fromisoformat(text) if type(text) is str else None
            except ValueError:
                day = None
            if day is not None and (newest is None or day > newest):
                newest = day
        cities += 1
    if newest is None:
        return {"data_date": None, "age_days": None, "basis": "no_retained_primary_gpm_data", "cities": 0}
    return {"data_date": newest.isoformat(), "age_days": (now.date() - newest).days,
            "basis": "precip_recent_by_city (primary GPM only)", "cities": cities}


def gpm_access_health(state: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """One projection for Sources/Operations/CLI: credential, refusal backoff, hold and last-good age."""
    expiry_rows = state.get("credential_expiry") if isinstance(state.get("credential_expiry"), Mapping) else {}
    credential_row = expiry_rows.get(GPM_CREDENTIAL) if isinstance(expiry_rows, Mapping) else None
    expires = _parse(credential_row.get("expires_at")) if isinstance(credential_row, Mapping) else None
    credential: dict[str, Any] = {"tracked": expires is not None, "expires_at": _iso(expires) if expires else None,
                  "expired": bool(expires and expires <= now),
                  "days_since_expiry": (now - expires).days if expires and expires <= now else None}
    last_good = gpm_last_good(state, now=now)
    run_history = state.get("run_history")
    latest_access = None
    for _at, entry in _source_rows_newest_first(run_history, GPM_SOURCE):
        details = entry.get("details") if isinstance(entry.get("details"), Mapping) else {}
        access = details.get("earthdata_access") if isinstance(details, Mapping) else None
        if isinstance(access, Mapping) and access.get("schema") == SCHEMA:
            latest_access = access
        break
    backoff = refusal_backoff(run_history, credential_expires_at=credential["expires_at"], now=now)
    hold = source_incidents.earthdata_access_hold(source_incidents.project_incidents(run_history, source=GPM_SOURCE))
    if credential["expired"]:
        stage = "access_expired"
    elif backoff is not None:
        stage = "refused_backoff"
    elif hold is not None:
        stage = str(hold["stage"])
    elif last_good["age_days"] is not None and last_good["age_days"] <= CURRENT_DATA_DAYS:
        stage = "current"
    else:
        stage = "no_current_data"
    age = last_good["age_days"]
    last_text = (f"Last good GPM data {last_good['data_date']} ({age} day{'s' if age != 1 else ''} old)."
                 if age is not None else "No good GPM data is retained.")
    text = {
        "access_expired": (f"Earthdata access expired {credential['expires_at'][:10] if credential['expires_at'] else ''}; "
                           "owner renewal required. No request is sent until then. "),
        "refused_backoff": ("Earthdata refused this credential; the same credential is retried only after "
                            f"{backoff['next_attempt_after'] if backoff else ''} unless renewed. "),
        "current": "",
        "no_current_data": "No qualified GPM run is retained for the current window. ",
    }.get(stage, f"Earthdata owner-access hold ({stage}); a renewed credential is tried at the next scheduled run. ")
    return {"schema": SCHEMA, "source": GPM_SOURCE, "as_of": _iso(now), "stage": stage, "credential": credential,
            "last_good": last_good, "backoff": backoff, "latest_access_record": dict(latest_access) if latest_access else None,
            "hold": hold, "requests_sent_by_projection": 0, "public_text": (text + last_text).strip(),
            "empty_feed_is_not_coverage": True}


__all__ = ["REFUSAL_BACKOFF_HOURS", "SCHEMA", "credential_identity", "gpm_access_health", "gpm_last_good",
           "refusal_backoff", "run_record"]
