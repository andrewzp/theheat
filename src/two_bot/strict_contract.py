"""Deterministic validation at the evidence and model-output boundaries.

Schema validity is necessary, not proof of scientific truth. This module never
retrieves sources or upgrades a forecast, threshold or detection into a record.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any
from urllib.parse import urlparse

from src.two_bot.json_utils import json_default

CONTRACT_VERSION = 1
CLAIM_KINDS = frozenset({"number", "date", "named_entity", "comparison", "era_anchor", "peer_comparison"})
_SOURCE_KEYS = frozenset({"source", "data_source", "source_name", "source_product", "source_url", "url"})
_DATE_KEYS = frozenset({"date", "valid_date", "as_of", "issued_at", "retrieved_at", "signal_date", "start_date", "end_date", "valid_start", "valid_end", "cutoff", "verified_source_cutoff", "requested_cutoff", "comparison_before"})
_OPENERS = frozenset({"A", "An", "The", "This", "That", "These", "Those", "Some", "Last", "First", "No", "Not", "It", "Its", "In", "At", "On", "For", "Over", "Under", "From", "By", "With", "Without", "But", "And", "Or", "If", "As"})


def valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return True
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        pass
    return False


def valid_url(value: Any) -> bool:
    if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlparse(value)
        _ = parsed.port  # Access validates malformed/out-of-range ports.
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _source_fields(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        key in _SOURCE_KEYS and isinstance(item, str) and bool(item.strip())
        and ("url" not in key or valid_url(item))
        for key, item in value.items()
    )


def _has_primary_source(raw: Any, facts: Any) -> bool:
    # Only named primary-evidence locations qualify. A source URL in unrelated
    # news, historical context, or a nested related event is not measurement
    # provenance for this candidate. This is a minimum identity check, not a
    # complete source record, retrieval revision, or scientific warrant.
    if isinstance(raw, dict) and any(_source_fields(value) for value in (
        raw, raw.get("evidence"), raw.get("source"), raw.get("provenance"),
    )):
        return True
    return isinstance(facts, list) and any(
        isinstance(fact, dict) and isinstance(fact.get("label"), str)
        and fact["label"] in _SOURCE_KEYS
        and _source_fields({fact["label"]: fact.get("value")})
        for fact in facts
    )


def _evidence_default(value: Any) -> Any:
    if isinstance(value, bytes):
        raise TypeError("Evidence bytes require explicit decoding by the source adapter")
    return json_default(value)


def bundle_schema_issues(bundle) -> list[tuple[str, str, str]]:
    """Return stable (code, field, explanation) issues without repairing input."""
    issues = []
    try:
        # Existing documented date/Decimal/dataclass serialization is retained;
        # NaN/infinity/unknown objects cannot become source evidence strings.
        payload = bundle.to_dict()
        encoded = json.dumps(payload, default=_evidence_default, allow_nan=False, ensure_ascii=False)
        encoded.encode("utf-8")
        payload = json.loads(encoded)
    except (ValueError, TypeError, UnicodeError, OverflowError, AttributeError, RecursionError) as exc:
        return [("invalid_evidence_json", "bundle", f"Evidence must be finite serializable data: {exc}")]
    for key in ("signal_kind", "where", "event_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            issues.append((f"missing_{key}", key, "Supply a nonempty identity string"))
    if not isinstance(bundle.when, str) or not valid_date(payload.get("when")):
        issues.append(("invalid_valid_time", "when", "Supply a real ISO calendar date or timezone-qualified timestamp"))
    headline = payload.get("headline_metric")
    if not isinstance(headline, dict) or not isinstance(headline.get("label"), str) or not headline["label"].strip():
        issues.append(("invalid_headline_metric", "headline_metric", "Supply a metric label and value"))
    if isinstance(headline, dict) and (headline.get("value") is None or isinstance(headline["value"], (dict, list, bool)) or (isinstance(headline["value"], str) and not headline["value"].strip())):
        issues.append(("invalid_headline_value", "headline_metric.value", "Headline value must be a finite number or nonempty text"))
    facts = payload.get("current_facts")
    if not isinstance(facts, list) or not facts or any(not isinstance(fact, dict) or not isinstance(fact.get("label"), str) or not fact["label"].strip() or "value" not in fact for fact in facts):
        issues.append(("invalid_current_facts", "current_facts", "Facts require nonempty labels and explicit values"))
    if not _has_primary_source(payload.get("raw_signal_dump"), payload.get("current_facts")):
        issues.append(("missing_provenance", "raw_signal_dump", "An event ID or place name is not a source or source-record identity"))

    for field in ("raw_signal_dump", "historical_context"):
        if not isinstance(payload.get(field), dict):
            issues.append(("invalid_evidence_structure", field, "Supply an evidence object; preserve malformed input for repair"))

    def temperature_structure(evidence: Any, path: str) -> None:
        if evidence is None:
            return  # Unknown evidence does not become an asserted observation.
        if not isinstance(evidence, dict):
            issues.append(("invalid_evidence_structure", path, "Source evidence must be an object"))
            return
        baseline = evidence.get("baseline")
        if baseline is None:
            return
        if not isinstance(baseline, dict):
            issues.append(("invalid_evidence_structure", f"{path}.baseline", "Baseline must be an object"))
            return
        if baseline.get("variable") is not None and not isinstance(baseline["variable"], str):
            issues.append(("invalid_evidence_structure", f"{path}.baseline.variable", "Selected baseline variable must be a name"))
        variables = baseline.get("variables", {})
        if not isinstance(variables, dict) or any(not isinstance(row, dict) for row in variables.values()):
            issues.append(("invalid_evidence_structure", f"{path}.baseline.variables", "Each named baseline variable requires an object"))
        members = baseline.get("members", [])
        if not isinstance(members, list) or any(not isinstance(member, dict) for member in members):
            issues.append(("invalid_evidence_structure", f"{path}.baseline.members", "Baseline members must be evidence objects"))
            return
        for index, member in enumerate(members):
            temperature_structure(member.get("evidence"), f"{path}.baseline.members[{index}].evidence")

    raw = payload.get("raw_signal_dump")
    if isinstance(raw, dict):
        temperature_structure(raw.get("evidence"), "raw_signal_dump.evidence")

    def dates(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if set(value) & {"__nonfinite_number__", "__invalid_unicode__", "__invalid_cycle__", "__invalid_mapping__", "__unsupported_type__", "__depth_limit__"}:
                issues.append(("diagnostic_snapshot_not_evidence", path, "Rejected-evidence diagnostic tags must be repaired from the original source"))
            if isinstance(value.get("label"), str) and value["label"] in _DATE_KEYS and value.get("value") not in (None, "") and not valid_date(value["value"]):
                issues.append(("invalid_evidence_date", f"{path}.value", "Source date is malformed or lacks required timezone"))
            for key, item in value.items():
                if key in _DATE_KEYS and item not in (None, "") and not valid_date(item):
                    issues.append(("invalid_evidence_date", f"{path}.{key}", "Source date is malformed or lacks required timezone"))
                dates(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                dates(item, f"{path}[{index}]")
    for field in ("raw_signal_dump", "current_facts", "historical_context", "related_signals"):
        dates(payload.get(field), field)
    impacts = payload.get("human_impact", [])
    if not isinstance(impacts, list):
        issues.append(("invalid_impact_provenance", "human_impact", "Human impacts must be a list of sourced facts"))
        impacts = []
    for index, impact in enumerate(impacts):
        if isinstance(impact, dict) and (not valid_date(impact.get("as_of")) or not valid_url(impact.get("url"))):
            issues.append(("invalid_impact_provenance", f"human_impact[{index}]", "Impact requires a valid source URL and real as-of date"))
    return issues


def material_span_failures(tweet: str, claims: list) -> list[str]:
    """Require literal coverage of detectable numbers, dates and entity spans.

    This bounded independent check cannot prove coverage of every implication.
    Semantic entailment and source-specific typed warrants remain required.
    """
    if not isinstance(tweet, str) or not tweet.strip() or len(tweet) > 280:
        return ["invalid_tweet: fact checking requires nonempty tweet text within 280 characters"]
    try:
        tweet.encode("utf-8")
    except UnicodeError:
        return ["invalid_tweet: malformed Unicode"]
    failures = []
    if not claims:
        failures.append("incomplete_claim_extraction: every factual tweet requires a nonempty claim inventory")
    spans = []
    for claim in claims:
        if not isinstance(getattr(claim, "text", None), str) or not claim.text.strip() or claim.text not in tweet:
            failures.append("invalid_claim_span: extracted claim must be an exact nonempty tweet substring")
            continue
        start = 0
        while (start := tweet.find(claim.text, start)) >= 0:
            spans.append((start, start + len(claim.text)))
            start += len(claim.text)
    visible = re.sub(r"https?://\S+", lambda match: " " * len(match.group()), tweet)
    material = [(match.start(), match.end(), match.group()) for match in re.finditer(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?", visible)]
    for match in re.finditer(r"\b[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*)*", visible):
        token = match.group().rstrip(".,")
        if token not in _OPENERS:
            material.append((match.start(), match.start() + len(token), token))
    for start, end, value in material:
        if not any(left <= start and right >= end for left, right in spans):
            failures.append(f"incomplete_claim_extraction: uncovered material span {value!r}")
    for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", visible):
        if not valid_date(match.group()):
            failures.append(f"invalid_claim_date: {match.group()}")
    return list(dict.fromkeys(failures))


def review_snapshot(value: Any, _active: frozenset[int] = frozenset()) -> Any:
    """Encode rejected evidence for review; diagnostic tags are never evidence.

    Ordinary JSON values are retained verbatim. Nonfinite values and unsupported
    objects cannot be written to the state JSON, so preserve their error type
    explicitly instead of substituting a scientifically usable value.
    """
    import math

    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return value
        except UnicodeError:
            return {"__invalid_unicode__": ascii(value)}
    if isinstance(value, float):
        return value if math.isfinite(value) else {"__nonfinite_number__": str(value)}
    if id(value) in _active:
        return {"__invalid_cycle__": type(value).__name__}
    if len(_active) >= 64:
        return {"__depth_limit__": type(value).__name__}
    active = _active | {id(value)}
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            return {key: review_snapshot(item, active) for key, item in value.items()}
        return {"__invalid_mapping__": [[review_snapshot(key, active), review_snapshot(item, active)] for key, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [review_snapshot(item, active) for item in value]
    try:
        return review_snapshot(json_default(value), active)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return {"__unsupported_type__": f"{type(value).__module__}.{type(value).__qualname__}"}


def model_failure_snapshot(stage: str, raw: Any) -> dict:
    """Retain failed model output privately without unbounded state growth."""
    from src.two_bot.json_utils import model_response_diagnostic

    limit = 65536
    truncated = isinstance(raw, str) and len(raw) > limit
    return {
        "stage": stage,
        "diagnostic": model_response_diagnostic(raw),
        "raw_response": review_snapshot(raw[:limit] if truncated else raw),
        "truncated": truncated,
    }
