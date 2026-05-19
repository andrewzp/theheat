"""Prompt evidence checks for two-bot story bundles."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Number
from typing import Any, Literal

from src.two_bot.types import StoryBundle

EvidenceSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class EvidenceIssue:
    severity: EvidenceSeverity
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class EvidenceAudit:
    signal_kind: str
    event_id: str
    prompt_ready: bool
    issues: tuple[EvidenceIssue, ...]


class EvidenceContractError(ValueError):
    """Raised when a bundle is missing evidence required before generation."""


_SOURCE_LIKE_TOKENS = (
    "source",
    "sender",
    "url",
    "station",
    "gauge",
    "activation",
    "region_id",
    "event_id",
    "storm_id",
)

_UNIT_LABEL_SUFFIXES = (
    "_c",
    "_f",
    "_ft",
    "_gt",
    "_kt",
    "_m",
    "_mb",
    "_mm",
    "_mw",
    "_pct",
    "_ppm",
    "_ppb",
    "_km2",
    "_hectares",
    "_days",
)


def audit_story_bundle(bundle: StoryBundle) -> EvidenceAudit:
    """Return prompt-readiness issues for a StoryBundle.

    Errors mean the writer would receive an unusable evidence packet. Warnings
    surface weak context while allowing generation to continue.
    """

    issues: list[EvidenceIssue] = []

    _require_text(issues, bundle.signal_kind, "signal_kind", "missing_signal_kind")
    _require_text(issues, bundle.where, "where", "missing_where")
    _require_text(issues, bundle.when, "when", "missing_when")
    _require_text(issues, bundle.event_id, "event_id", "missing_event_id")

    headline_metric = bundle.headline_metric
    if not isinstance(headline_metric, dict) or not headline_metric:
        issues.append(
            _issue(
                "error",
                "missing_headline_metric",
                "headline_metric",
                "headline_metric must be a non-empty object",
            )
        )
    else:
        _require_metric_key(issues, headline_metric, "label")
        _require_metric_key(issues, headline_metric, "value")
        if _numeric_without_unit_signal(headline_metric):
            issues.append(
                _issue(
                    "warning",
                    "numeric_headline_without_unit",
                    "headline_metric",
                    "numeric headline_metric has no unit or unit-bearing label",
                )
            )

    current_facts = bundle.current_facts
    if not isinstance(current_facts, list) or not current_facts:
        issues.append(
            _issue(
                "error",
                "missing_current_facts",
                "current_facts",
                "current_facts must be a non-empty list",
            )
        )
    else:
        _check_fact_list(issues, current_facts, "current_facts")

    historical_context = bundle.historical_context
    if not historical_context:
        issues.append(
            _issue(
                "warning",
                "empty_historical_context",
                "historical_context",
                "historical_context is empty",
            )
        )
    elif isinstance(historical_context, dict):
        _check_nested_fact_dicts(issues, historical_context, "historical_context")
    else:
        issues.append(
            _issue(
                "warning",
                "unexpected_historical_context_shape",
                "historical_context",
                "historical_context should be an object",
            )
        )

    raw_signal_dump = bundle.raw_signal_dump
    if not isinstance(raw_signal_dump, dict) or not raw_signal_dump:
        issues.append(
            _issue(
                "error",
                "missing_raw_signal_dump",
                "raw_signal_dump",
                "raw_signal_dump must be a non-empty object",
            )
        )
    else:
        if len(raw_signal_dump) < 2:
            issues.append(
                _issue(
                    "warning",
                    "sparse_raw_signal_dump",
                    "raw_signal_dump",
                    "raw_signal_dump has fewer than two keys",
                )
            )
        if not _has_source_like_anchor(raw_signal_dump, current_facts):
            issues.append(
                _issue(
                    "warning",
                    "missing_source_anchor",
                    "raw_signal_dump",
                    "no source-like key found in raw_signal_dump or current_facts",
                )
            )

    has_errors = any(issue.severity == "error" for issue in issues)
    return EvidenceAudit(
        signal_kind=bundle.signal_kind,
        event_id=bundle.event_id,
        prompt_ready=not has_errors,
        issues=tuple(issues),
    )


def assert_prompt_ready(bundle: StoryBundle) -> None:
    audit = audit_story_bundle(bundle)
    if audit.prompt_ready:
        return

    codes = ", ".join(issue.code for issue in audit.issues if issue.severity == "error")
    raise EvidenceContractError(f"bundle is not prompt-ready: {codes}")


def _issue(
    severity: EvidenceSeverity,
    code: str,
    field: str,
    message: str,
) -> EvidenceIssue:
    return EvidenceIssue(
        severity=severity,
        code=code,
        field=field,
        message=message,
    )


def _require_text(
    issues: list[EvidenceIssue],
    value: Any,
    field: str,
    code: str,
) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            _issue("error", code, field, f"{field} must be a non-empty string")
        )


def _require_metric_key(
    issues: list[EvidenceIssue],
    headline_metric: dict[str, Any],
    key: str,
) -> None:
    if key not in headline_metric or headline_metric[key] in (None, ""):
        issues.append(
            _issue(
                "error",
                f"missing_headline_metric_{key}",
                f"headline_metric.{key}",
                f"headline_metric.{key} is required",
            )
        )


def _check_fact_list(
    issues: list[EvidenceIssue],
    facts: list[Any],
    field: str,
) -> None:
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            issues.append(
                _issue(
                    "warning",
                    "fact_not_object",
                    f"{field}[{index}]",
                    f"{field}[{index}] should be an object",
                )
            )
            continue
        if "label" not in fact or fact["label"] in (None, ""):
            issues.append(
                _issue(
                    "warning",
                    "fact_missing_label",
                    f"{field}[{index}].label",
                    f"{field}[{index}].label is missing",
                )
            )
        if "value" not in fact:
            issues.append(
                _issue(
                    "warning",
                    "fact_missing_value",
                    f"{field}[{index}].value",
                    f"{field}[{index}].value is missing",
                )
            )


def _check_nested_fact_dicts(
    issues: list[EvidenceIssue],
    values: dict[str, Any],
    field: str,
) -> None:
    for key, value in values.items():
        if not isinstance(value, dict):
            continue
        if "label" not in value or value["label"] in (None, ""):
            issues.append(
                _issue(
                    "warning",
                    "fact_missing_label",
                    f"{field}.{key}.label",
                    f"{field}.{key}.label is missing",
                )
            )
        if "value" not in value:
            issues.append(
                _issue(
                    "warning",
                    "fact_missing_value",
                    f"{field}.{key}.value",
                    f"{field}.{key}.value is missing",
                )
            )


def _numeric_without_unit_signal(headline_metric: dict[str, Any]) -> bool:
    value = headline_metric.get("value")
    if not isinstance(value, Number) or isinstance(value, bool):
        return False
    if headline_metric.get("unit"):
        return False
    label = str(headline_metric.get("label", "")).lower()
    return not label.endswith(_UNIT_LABEL_SUFFIXES)


def _has_source_like_anchor(
    raw_signal_dump: dict[str, Any],
    current_facts: Any,
) -> bool:
    keys = {str(key).lower() for key in raw_signal_dump}
    if isinstance(current_facts, list):
        for fact in current_facts:
            if isinstance(fact, dict):
                label = fact.get("label")
                if label is not None:
                    keys.add(str(label).lower())

    return any(
        token in key
        for key in keys
        for token in _SOURCE_LIKE_TOKENS
    )
