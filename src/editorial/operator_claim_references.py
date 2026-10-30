"""Strict operator-selected connections, never scientific support or approval.

Paired with dashboard/lib/operator-claim-references.js. Request items contain
only quotes and retained-fact pointers; durable digests are derived here.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

MAX_ITEMS = 32
MAX_FACTS = 64
MAX_LIST = 64
MAX_BYTES = 16_384
MAX_RECORD_FIELDS = 16
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}")
# A scalar fact is referenced whole; a list-valued fact only by one exact element.
# An element is a scalar or one flat record of scalars (e.g. one ranked Hot10 row);
# an empty list is retained but offers nothing to reference.
POINTER = re.compile(r"/current_facts/(0|[1-9][0-9]?)(?:/value/(0|[1-9][0-9]?))?")
_KIND_ALIASES = {
    "all_time_high": "open_meteo_archive_high",
    "all_time_low": "open_meteo_archive_low",
    "record": "calendar_record",
    "record_low": "calendar_record_low",
}


def _exact(value: Any, keys: set[str]) -> bool:
    return type(value) is dict and set(value) == keys


def _string(value: Any, limit: int) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value) is None


def operator_claim_kind_matches(draft_type: Any, bundle_kind: Any) -> bool:
    """Only the four saved legacy labels documented by two_bot_dispatch.

    Alias direction matters: the saved draft keeps the legacy label while the
    intern gives its retained bundle the more precise kind. No broad temperature
    family matching or normalization is permitted.
    """
    return (_string(draft_type, 80) and _string(bundle_kind, 80)
            and (draft_type == bundle_kind or _KIND_ALIASES.get(draft_type) == bundle_kind))


def _scalar(value: Any) -> bool:
    try:
        return (value is None or type(value) is bool or
                (type(value) in (int, float) and math.isfinite(value)) or _string(value, 2048))
    except OverflowError:
        return False


def _record(value: Any) -> bool:
    """One flat row of named scalars; never nested and never relabelled as a scalar fact."""
    return (type(value) is dict and 1 <= len(value) <= MAX_RECORD_FIELDS
            and all(isinstance(key, str) and _FIELD.fullmatch(key) for key in value)
            and all(_scalar(field) for field in value.values()))


def _fact(value: Any) -> bool:
    if type(value) is not dict or not _string(value.get("label"), 160) or "value" not in value:
        return False
    item = value["value"]
    valid = _scalar(item) or (type(item) is list and len(item) <= MAX_LIST
                              and all(_scalar(x) or _record(x) for x in item))
    return valid and (value.get("unit") in (None, "") or _string(value.get("unit"), 80))


def resolve_reference(facts: list[dict], pointer: Any) -> tuple[dict, Any]:
    """The exact referenced fact (or list element) and the value bound by its digest.

    An element keeps provenance: its digest binds the whole fact's fingerprint, the
    element index and the element value; it is never relabelled as a scalar fact.
    """
    from src.editorial.revisions import fingerprint
    match = POINTER.fullmatch(pointer) if isinstance(pointer, str) else None
    if match is None:
        raise ValueError("Select a saved source fact from this draft")
    index = int(match[1])
    if index >= len(facts):
        raise ValueError("A selected source fact is missing or repeated")
    fact = facts[index]
    listed = type(fact["value"]) is list
    if match[2] is None:
        if listed:
            raise ValueError("Select one exact element of a list-valued source fact")
        return {"label": fact["label"], "value": fact["value"], "unit": fact.get("unit")}, fact
    element = int(match[2])
    if not listed or element >= len(fact["value"]):
        raise ValueError("A selected source fact is missing or repeated")
    view = {"label": f"{fact['label']}[{element}]", "value": fact["value"][element], "unit": fact.get("unit")}
    return view, {"fact_sha256": fingerprint(fact), "element": element, "value": fact["value"][element]}


def _integer(value: Any) -> bool:
    # JSON 1.0 and 1 are the same number in JavaScript; booleans are distinct.
    return type(value) in (int, float) and abs(value) <= 9_007_199_254_740_991 and value == int(value)


def retained_claim_facts(bundle: Any) -> list[dict]:
    facts = bundle.get("current_facts") if type(bundle) is dict else None
    if type(facts) is not list or len(facts) > MAX_FACTS or not all(_fact(row) for row in facts):
        raise ValueError("Saved source facts are unavailable; refresh before linking a quote")
    return facts


def build_operator_claim_references(text: str, bundle: Any, items: Any) -> dict | None:
    """Validate the complete request before changing any draft state."""
    # Local import keeps revision integration free of an import cycle.
    from src.editorial.revisions import fingerprint, text_hash
    if not _string(text, 280):
        raise ValueError("The quote must belong to a valid current draft")
    if type(items) is not list or len(items) > MAX_ITEMS:
        raise ValueError("Use at most 32 operator-selected references")
    if not items:
        return None
    facts = retained_claim_facts(bundle)
    retained, spans, selected_count = [], set(), 0
    for item in items:
        if not _exact(item, {"claim", "sources"}):
            raise ValueError("Each reference needs an exact quote and selected source facts")
        claim, sources = item["claim"], item["sources"]
        if (not _exact(claim, {"start", "end", "text"}) or
                not _integer(claim["start"]) or not _integer(claim["end"]) or
                not 0 <= claim["start"] < claim["end"] <= len(text) or
                not _string(claim["text"], 280) or text[int(claim["start"]):int(claim["end"])] != claim["text"]):
            raise ValueError("The selected quote has changed; select it again")
        span = (claim["start"], claim["end"])
        if span in spans:
            raise ValueError("Combine the source facts for each selected quote")
        spans.add(span)
        if type(sources) is not list or not 1 <= len(sources) <= MAX_FACTS:
            raise ValueError("Select at least one saved source fact for each quote")
        selected_count += len(sources)
        if selected_count > MAX_FACTS:
            raise ValueError("Use at most 64 selected source facts in total")
        rows, pointers = [], set()
        for source in sources:
            pointer = source.get("pointer") if type(source) is dict else None
            if not _exact(source, {"pointer"}) or not isinstance(pointer, str):
                raise ValueError("Select a saved source fact from this draft")
            _, bound = resolve_reference(facts, pointer)
            if pointer in pointers:
                raise ValueError("A selected source fact is missing or repeated")
            pointers.add(pointer)
            rows.append({"pointer": pointer, "value_sha256": fingerprint(bound)})
        retained.append({"claim": {"start": int(claim["start"]), "end": int(claim["end"]), "text": claim["text"]}, "sources": rows})
    result = {"schema_version": 1, "origin": "operator_supplied", "text_sha256": text_hash(text),
              "bundle_sha256": fingerprint(bundle), "items": retained}
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")) > MAX_BYTES:
        raise ValueError("Selected references exceed the 16 KiB limit; remove some references")
    return result


def read_operator_claim_references(text: str, bundle: Any, value: Any) -> dict | None:
    """Recompute all digests; stale/malformed saved metadata is never current."""
    from src.editorial.revisions import fingerprint
    if not _exact(value, {"schema_version", "origin", "text_sha256", "bundle_sha256", "items"}):
        return None
    try:
        if not _integer(value["schema_version"]) or value["schema_version"] != 1 or value["origin"] != "operator_supplied":
            return None
        if type(value["items"]) is not list or not 1 <= len(value["items"]) <= MAX_ITEMS:
            return None
        items = []
        for item in value["items"]:
            if not _exact(item, {"claim", "sources"}) or type(item["sources"]) is not list:
                return None
            if any(not _exact(row, {"pointer", "value_sha256"}) for row in item["sources"]):
                return None
            items.append({"claim": item["claim"], "sources": [{"pointer": row["pointer"]} for row in item["sources"]]})
        expected = build_operator_claim_references(text, bundle, items)
        return expected if fingerprint(expected) == fingerprint(value) else None
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return None


def project_operator_claim_references(draft: dict) -> dict:
    from src.editorial.revisions import draft_identity
    identity = draft_identity(draft)
    review = draft.get("review_context")
    if not isinstance(review, dict) or "operator_claim_references" not in review:
        return {"status": "missing", "identity": identity, "items": []}
    two = review.get("two_bot")
    bundle = two.get("bundle") if isinstance(two, dict) else None
    text = draft.get("text")
    if not isinstance(bundle, dict) or not isinstance(text, str):
        return {"status": "unavailable", "identity": identity, "items": []}
    value = read_operator_claim_references(text, bundle, review["operator_claim_references"])
    if (value is None or draft.get("revision_conflicts") or bundle.get("event_id") != draft.get("event_id") or not operator_claim_kind_matches(draft.get("type"), bundle.get("signal_kind"))):
        return {"status": "unavailable", "identity": identity, "items": []}
    items = []
    for item in value["items"]:
        sources = []
        for source in item["sources"]:
            fact, _ = resolve_reference(bundle["current_facts"], source["pointer"])
            sources.append({"pointer": source["pointer"], "fact": fact})
        items.append({"claim": item["claim"], "sources": sources})
    def string(value, maximum):
        return value if _string(value, maximum) else None
    evidence = bundle.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    return {"status": "saved", "identity": identity, "items": items,
            "where": string(bundle.get("where"), 512), "when": string(bundle.get("when"), 128), "source_label": string(review.get("source"), 80),
            "source_type": string(evidence.get("evidence_type"), 80), "scope": string(evidence.get("spatial_scope"), 160),
            "issued_at": string(evidence.get("issued_at"), 128), "valid_start": string(evidence.get("valid_start"), 128), "valid_end": string(evidence.get("valid_end"), 128)}


def project_operator_claim_reference_history(draft: dict) -> list[dict]:
    from copy import deepcopy
    from src.editorial.revisions import draft_identity
    history = draft.get("revision_history")
    if not isinstance(history, list):
        return []
    result = []
    for row in history:
        review = row.get("review_context") if isinstance(row, dict) else None
        if not isinstance(review, dict) or "operator_claim_references" not in review:
            continue
        snapshot = {**deepcopy(row), "event_id": draft.get("event_id"), "type": draft.get("type")}
        try:
            result.append({**snapshot, "revision_identity": draft_identity(snapshot), "operator_claim_reference_view": project_operator_claim_references(snapshot)})
        except (ValueError, TypeError, UnicodeError, OverflowError):
            result.append({"content_revision": None, "operator_claim_reference_view": {"status": "unavailable", "items": []}})
    return result
