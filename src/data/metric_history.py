"""Append-only public metric observations inside each retained tweet metric row.

No API calls here. Public metrics combine organic/promoted exposure; impressions
are not unique readers. The existing collector's cadence is not a fixed-age SLA.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, cast

from src.state_schema import TweetMetric


PUBLIC_FIELDS = {
    "likes": "like_count", "retweets": "retweet_count", "replies": "reply_count",
    "quotes": "quote_count", "impressions": "impression_count", "bookmarks": "bookmark_count",
}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _time(value) -> datetime | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value,
    ):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _count(value) -> int | None:
    # bools, strings, fractional/negative/nonfinite numbers are not observations.
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def parse_public_metrics(payload: dict) -> dict[str, int | None]:
    return {name: _count(payload.get(native)) for name, native in PUBLIC_FIELDS.items()}


def publication_reference(state: Mapping[str, Any], tweet_id: str, sampled_at: datetime,
                          platform_created_at: str | None = None) -> dict:
    """Only the platform's created_at establishes post age.

    Confirmation and legacy receipt timestamps are explicitly proxies. Modern
    intent.at precedes the network call and is excluded even as a receipt proxy.
    Conflicting proxy times stay unknown. Only a retained receipt fingerprint
    can establish the published revision.
    """
    candidates = []
    fingerprints = set()

    def receipt(row, source):
        if not isinstance(row, dict):
            return
        if str(row.get("tweet_id") or "") == tweet_id:
            key = "confirmed_at" if row.get("confirmed_at") else "at" if not row.get("phase") else None
            at = _time(row.get(key))
            if at is not None and at <= sampled_at:
                candidates.append((0 if key == "confirmed_at" else 2, at, f"{source}.{key}"))
            text_hash = row.get("text_sha256")
            if isinstance(text_hash, str) and re.fullmatch(r"[a-f0-9]{64}", text_hash):
                fingerprints.add(text_hash)
        for conflict in row.get("attempt_conflicts", []) if isinstance(row.get("attempt_conflicts"), list) else []:
            receipt(conflict, f"{source}.attempt_conflicts")

    ledger = state.get("publish_ledger")
    for row in ledger.values() if isinstance(ledger, dict) else []:
        receipt(row, "publish_ledger")
    for draft in state.get("drafts", []):
        if not isinstance(draft, dict):
            continue
        if str(draft.get("tweet_id") or "") == tweet_id:
            at = _time(draft.get("posted_at"))
            if at is not None and at <= sampled_at:
                candidates.append((1, at, "draft.posted_at"))
        receipt(draft.get("published_revision"), "draft.published_revision")
    best = min((rank for rank, _, _ in candidates), default=None)
    selected = {(at, source) for rank, at, source in candidates if rank == best}
    times = {at for at, _ in selected}
    receipt_time = next(iter(times)) if len(times) == 1 else None
    post_time = _time(platform_created_at)
    if post_time and post_time > sampled_at:
        post_time = None
    return {
        "posted_at": post_time.isoformat().replace("+00:00", "Z") if post_time else None,
        "post_time_basis": "x_api.created_at" if post_time else None,
        "post_time_status": "recorded" if post_time else "unknown",
        "post_age_seconds": (sampled_at - post_time).total_seconds() if post_time else None,
        "receipt_at": receipt_time.isoformat().replace("+00:00", "Z") if receipt_time else None,
        "receipt_time_basis": sorted({source for _, source in selected}),
        "receipt_time_status": "proxy" if receipt_time else "conflict" if times else "unknown",
        "receipt_age_seconds": (sampled_at - receipt_time).total_seconds() if receipt_time else None,
        "published_text_sha256": next(iter(fingerprints)) if len(fingerprints) == 1 else None,
        "published_revision_status": "recorded" if len(fingerprints) == 1 else "conflict" if fingerprints else "unknown",
    }


def append_sample(previous: Mapping[str, Any] | None, *, tweet_id: str, counts: dict,
                  sampled_at: datetime, state: Mapping[str, Any]) -> TweetMetric:
    if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
        raise ValueError("Metric sample time must have a timezone")
    sample_time = sampled_at.astimezone(UTC)
    at = sample_time.isoformat().replace("+00:00", "Z")
    metrics = {name: _count(counts.get(name)) for name in PUBLIC_FIELDS}
    observation = {
        "schema_version": 1, "tweet_id": tweet_id, "sampled_at": at,
        "source": "x_api.public_metrics", "counts": metrics,
        **publication_reference(state, tweet_id, sample_time, counts.get("created_at")),
    }
    sample_id = hashlib.sha256(_canonical(observation).encode()).hexdigest()
    latest = {"at": at, **metrics, "samples": {sample_id: observation}}
    return cast(TweetMetric, merge_metric_rows(previous, latest))


def merge_metric_rows(current, incoming) -> dict:
    """Retain all distinct payloads, including conflicting same-time samples.

    A normal stale-state merge never removes an observation. This is not a
    transaction or protection from simultaneous unconditional Gist overwrites.
    Existing flat rows stay readable and are not invented as historical samples.
    """
    rows = [row for row in (current, incoming) if isinstance(row, dict)]
    if not rows:
        return {}
    newest = max(rows, key=lambda row: (_time(row.get("at")) or datetime.min.replace(tzinfo=UTC),
                                       _canonical({key: value for key, value in row.items()
                                                   if key not in {"samples", "legacy_rows", "latest_sample_conflict"}})))
    result = deepcopy(newest)
    samples = {}
    legacy = {}
    for row in rows:
        historical = row.get("legacy_rows")
        if isinstance(historical, dict):
            for original in historical.values():
                if isinstance(original, dict):
                    legacy[hashlib.sha256(_canonical(original).encode()).hexdigest()] = deepcopy(original)
        history = row.get("samples")
        if not isinstance(history, dict):
            # Preserve an actual retained flat row when the first new sample is
            # added. Label it as legacy rather than inventing receipt/time data.
            if not isinstance(historical, dict):
                original = {key: value for key, value in row.items()
                            if key not in {"samples", "legacy_rows", "latest_sample_conflict"}}
                legacy[hashlib.sha256(_canonical(original).encode()).hexdigest()] = deepcopy(original)
            continue
        for sample in history.values():
            if not isinstance(sample, dict):
                continue
            # Derive identity from the complete payload, so a conflicting value
            # under an existing key cannot erase the earlier observation.
            key = hashlib.sha256(_canonical(sample).encode()).hexdigest()
            samples[key] = deepcopy(sample)
    if len(legacy) > 1 or (samples and legacy) or any(row.get("legacy_rows") for row in rows):
        result["legacy_rows"] = dict(sorted(legacy.items()))
    if samples:
        result["samples"] = dict(sorted(samples.items()))
    if samples or result.get("legacy_rows"):
        latest_at = _time(result.get("at"))
        same_time_counts = {_canonical(sample.get("counts")) for sample in samples.values()
                            if latest_at is not None and _time(sample.get("sampled_at")) == latest_at}
        same_time_counts.update(_canonical({name: _count(row.get(name)) for name in PUBLIC_FIELDS})
                                for row in legacy.values()
                                if latest_at is not None and _time(row.get("at")) == latest_at)
        result["latest_sample_conflict"] = len(same_time_counts) > 1
    return result
