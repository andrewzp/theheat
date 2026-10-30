"""Supplied platform metric responses into append-only samples (W15.4).

The operator supplies a saved X API v2 tweet-lookup response and the time it
was captured. Each requested post must be one of ours (a retained delivery
receipt or posted draft); its counts go through the existing
``metric_history.append_sample`` path, so earlier snapshots are never
overwritten and post age comes only from the platform's ``created_at``. A
missing count is null (not zero), an access refusal or missing post records no
sample, and nothing here contacts the platform or changes the metrics flag.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from src.data.metric_history import PUBLIC_FIELDS, append_sample, parse_public_metrics

SCHEMA = "theheat.metric-intake/v1"
MAX_IDS = 100
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REFUSED = {"https://api.twitter.com/2/problems/not-authorized-for-resource": "access_refused",
            "https://api.twitter.com/2/problems/resource-not-found": "not_found"}


class MetricIntakeError(ValueError):
    pass


def _ours(state: dict) -> set[str]:
    ids: set[str] = set()
    ledger = state.get("publish_ledger") if isinstance(state.get("publish_ledger"), dict) else {}
    for row in ledger.values():
        if isinstance(row, dict) and row.get("tweet_id") and row.get("phase") == "confirmed":
            ids.add(str(row["tweet_id"]))
    for draft in state.get("drafts", []) if isinstance(state.get("drafts"), list) else []:
        if isinstance(draft, dict) and draft.get("status") == "posted" and draft.get("tweet_id"):
            ids.add(str(draft["tweet_id"]))
    return ids


def ingest(state: dict, raw_response: bytes, *, captured_at: datetime, requested_ids: list[str],
           now: datetime | None = None) -> tuple[dict, dict]:
    """(updated tweet_metrics, report); the supplied state is not mutated."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise MetricIntakeError("captured_at_timezone_required")
    captured = captured_at.astimezone(UTC)
    if captured > (now or datetime.now(UTC)):
        raise MetricIntakeError("captured_at_in_future")
    if len(raw_response) > MAX_RESPONSE_BYTES:
        raise MetricIntakeError("response_too_large")
    try:
        response = json.loads(raw_response)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricIntakeError("response_not_json") from exc
    if not isinstance(response, dict):
        raise MetricIntakeError("response_shape")
    ids = list(dict.fromkeys(str(i).strip() for i in requested_ids if str(i).strip()))
    if not 0 < len(ids) <= MAX_IDS or not all(i.isdigit() and len(i) <= 30 for i in ids):
        raise MetricIntakeError("requested_ids")
    data = {str(row.get("id")): row for row in response.get("data", []) or [] if isinstance(row, dict)}
    errors: dict[str, str] = {}
    for row in response.get("errors", []) or []:
        if isinstance(row, dict):
            key = str(row.get("resource_id") or row.get("value") or "")
            errors[key] = _REFUSED.get(str(row.get("type")), "platform_error")
    ours = _ours(state)
    metrics = deepcopy(state.get("tweet_metrics")) if isinstance(state.get("tweet_metrics"), dict) else {}
    posts = []
    for tweet_id in ids:
        if tweet_id not in ours:
            posts.append({"tweet_id": tweet_id, "status": "not_a_retained_post"})
            continue
        row = data.get(tweet_id)
        public = row.get("public_metrics") if isinstance(row, dict) else None
        if not isinstance(public, dict):
            posts.append({"tweet_id": tweet_id, "status": errors.get(tweet_id, "absent_from_response")})
            continue
        counts = {**parse_public_metrics(public), "created_at": row.get("created_at")}
        metrics[tweet_id] = append_sample(metrics.get(tweet_id), tweet_id=tweet_id, counts=counts,
                                          sampled_at=captured, state=state)
        stamp = captured.isoformat().replace("+00:00", "Z")
        latest = next((s for s in metrics[tweet_id].get("samples", {}).values()
                       if s.get("sampled_at") == stamp and s.get("counts") == {k: counts[k] for k in PUBLIC_FIELDS}), {})
        posts.append({"tweet_id": tweet_id, "status": "sample_appended",
                      "unavailable_dimensions": sorted(k for k in PUBLIC_FIELDS if counts.get(k) is None),
                      "post_age_seconds": latest.get("post_age_seconds"),
                      "post_time_status": latest.get("post_time_status")})
    report = {"schema": SCHEMA, "captured_at": captured.isoformat().replace("+00:00", "Z"),
              "response_sha256": hashlib.sha256(raw_response).hexdigest(), "posts": posts,
              "appended": sum(p["status"] == "sample_appended" for p in posts),
              "note": "Unavailable counts are null, not zero; refused or missing posts record no sample. "
                      "Background metrics collection is unchanged."}
    return metrics, report


__all__ = ["MetricIntakeError", "SCHEMA", "ingest"]
