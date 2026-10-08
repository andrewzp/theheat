"""Qualified dated marine components, not a shared event or impact warrant.

Component IDs bind complete source receipts. They are separate from publication
IDs and do not make the existing Gist state transactional or an immutable archive.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
from datetime import UTC, date, datetime
import json
import re
from typing import Any, cast

from src.state_schema import BotState

from src.data import coral_evidence, coral_regional_contract, coral_source_contract, crw_contract
from src.data.source_status import SourceFetchError
from src.editorial.revisions import fingerprint

COMPONENT_BYTES = 8192
COMPONENT_LIMIT = 128
KINDS = {"coral": "corals", "sst_anomaly": "sst_anomalies"}
SIGNAL_KIND = "synthesis_marine_compound"
LIMITS = (
    "Two independently qualified, dated NOAA CRW measurements at configured associated locations. "
    "The association establishes no shared footprint, simultaneous event, cause, trend, marine "
    "heatwave classification, observed bleaching or mortality. DHW accumulates heat stress over "
    "12 weeks; SST anomaly is a daily strided regional sample mean. Neither is an exhaustive "
    "14-day maximum. Preserve each component's own valid date, source class and sampling scope."
)
_ERRORS = (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError, SourceFetchError)


class MarineEvidenceError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MarineEvidenceError(code)


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(value: Any) -> datetime:
    return crw_contract.product_time(value)


def _bounded(value: Any, limit: int = COMPONENT_BYTES) -> dict:
    # JSON roundtrip provides detached primitives; count the state encoding's
    # escaped bytes, not only the shorter display encoding.
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    _require(len(raw) <= limit, "component_too_large")
    return json.loads(raw)


def _reading(kind: str, raw: Any):
    from src.data.coral_dhw import CoralDHWReading
    from src.data.ocean_sst_anomaly import RegionalSSTReading, _detect_tier

    _require(kind in KINDS, "unknown_component_kind")
    cls: Any = CoralDHWReading if kind == "coral" else RegionalSSTReading
    _require(type(raw) is dict and set(raw) == {f.name for f in fields(cls)}, "reading_shape")
    reading = cls(**raw)
    _require(type(reading.date) is str and date.fromisoformat(reading.date).isoformat() == reading.date,
             "reading_date")
    if kind == "sst_anomaly":
        _require(crw_contract.qualified_provenance(reading), "sst_source_unqualified")
        _require(type(reading.tier) is int and reading.tier == (_detect_tier(reading.anomaly_c) or 0),
                 "sst_tier_binding")
    elif reading.source_leg == "crw_erddap":
        _require(coral_source_contract.qualified_provenance(reading), "coral_point_unqualified")
        _require(reading.stress_level == coral_evidence.DHW_ONLY_STRESS_LEVEL
                 and reading.baa_7day_max is None, "point_scope")
    else:
        _require(coral_regional_contract.qualified_provenance(reading), "coral_regional_unqualified")
    return reading


def _retrieval_times(value: Any) -> list[datetime]:
    if isinstance(value, dict):
        return [stamp for key, child in value.items()
                for stamp in ([_stamp(child)] if key == "retrieved_at" else _retrieval_times(child))]
    if isinstance(value, list):
        return [stamp for child in value for stamp in _retrieval_times(child)]
    return []


def validate_component(value: Any, kind: str, evaluation_at: str):
    from src.editorial.synthesis import CORAL_TO_SST_REGION, WINDOW_DAYS
    from src.editorial.synthesis import MARINE_DHW_MIN_C_WEEKS, MARINE_SST_ANOMALY_MIN_C

    row = _bounded(value)
    _require(type(row) is dict and set(row) == {"event_id", "at", "marine_source"}, "component_shape")
    source = row["marine_source"]
    _require(type(source) is dict and set(source) == {"schema_version", "kind", "reading"}
             and type(source["schema_version"]) is int and source["schema_version"] == 1
             and source["kind"] == kind, "component_schema")
    reading = _reading(kind, source["reading"])
    _require(row["event_id"] == f"marine_component_{kind}_v1_{fingerprint(source)}", "component_identity")
    _require(row["at"] == f"{reading.date}T00:00:00Z", "component_date_binding")
    as_of, now = _stamp(evaluation_at), _stamp(now_utc())
    _require(as_of <= now, "future_evaluation")
    day = date.fromisoformat(reading.date)
    _require(0 <= (as_of.date() - day).days <= WINDOW_DAYS
             and 0 <= (now.date() - day).days <= WINDOW_DAYS, "component_outside_window")
    times = _retrieval_times(reading.provenance)
    _require(bool(times) and max(times) <= as_of, "future_acquisition")
    if kind == "coral":
        _require(bool(CORAL_TO_SST_REGION.get(reading.region_id)), "unmapped_region")
        _require(reading.dhw_value >= MARINE_DHW_MIN_C_WEEKS, "below_marine_floor")
    else:
        _require(reading.region_slug in CORAL_TO_SST_REGION.values(), "unmapped_region")
        _require(reading.anomaly_c >= MARINE_SST_ANOMALY_MIN_C, "below_marine_floor")
    return reading


def component(kind: str, reading: Any, *, evaluation_at: str | None = None) -> dict:
    source = dict(schema_version=1, kind=kind, reading=asdict(reading))
    row = dict(event_id=f"marine_component_{kind}_v1_{fingerprint(source)}",
               at=f"{reading.date}T00:00:00Z", marine_source=source)
    validate_component(row, kind, evaluation_at or now_utc())
    return _bounded(row)


def record_reading(state: BotState, kind: str, reading: Any) -> str:
    """Record a detached source snapshot; never return a mutable stored row."""
    from src import state as state_module

    try:
        row = component(kind, reading)
        region = reading.region_id if kind == "coral" else reading.region_slug
        components: dict = cast(dict, state.get("synthesis_components") or {})
        bucket = (components.get(KINDS[kind]) or {}).get(region, [])
        _require(isinstance(bucket, list), "component_bucket_shape")
        if any(isinstance(old, dict) and old.get("event_id") == row["event_id"] for old in bucket):
            _require(all(old == row for old in bucket if isinstance(old, dict)
                         and old.get("event_id") == row["event_id"]), "component_identity_conflict")
            return "unchanged"
        _require(len(bucket) < COMPONENT_LIMIT, "component_capacity")
        state_module.record_synthesis_component(state, kind=kind, region=region,
            event_id=row["event_id"], timestamp=row["at"], metadata={"marine_source": deepcopy(row["marine_source"])})
        return "retained"
    except MarineEvidenceError as exc:
        return str(exc)  # Only fixed local codes, never source/exception bodies.
    except _ERRORS:
        return "component_unqualified"


def _note(diagnostics: dict | None, code: str) -> None:
    if diagnostics is not None:
        diagnostics[code] = diagnostics.get(code, 0) + 1


def select_component(state: BotState, kind: str, region: str, evaluation_at: str,
                     *, diagnostics: dict | None = None) -> dict | None:
    """Select a peak within one source family, withholding contradictory dates."""
    buckets: Any = state.get("synthesis_components")
    if not isinstance(buckets, dict) or not isinstance(buckets.get(KINDS[kind]), dict):
        return None
    rows = buckets[KINDS[kind]].get(region, [])
    if not isinstance(rows, list):
        _note(diagnostics, "component_bucket_shape")
        return None
    # At capacity, a rejected insertion may be missing from this pool. Refuse
    # even exactly-full pools until ordinary TTL pruning makes room.
    if len(rows) >= COMPONENT_LIMIT:
        _note(diagnostics, "component_capacity")
        return None
    groups: dict[tuple, list[tuple]] = {}
    for value in rows:
        try:
            row = _bounded(value)
            reading = validate_component(row, kind, evaluation_at)
            actual_region = reading.region_id if kind == "coral" else reading.region_slug
            _require(actual_region == region, "component_region_binding")
            values = asdict(reading)
            values.pop("provenance")  # Only contradiction detection, NEVER a source/cache identity.
            key = (reading.source_leg, reading.date)
            groups.setdefault(key, []).append((row, reading, fingerprint(values)))
        except _ERRORS:
            _note(diagnostics, "component_unqualified")
            continue
    for group in groups.values():
        if len({item[2] for item in group}) > 1:
            _note(diagnostics, "component_date_conflict")
    candidates = [item for values in groups.values() if len({item[2] for item in values}) == 1 for item in values]
    if not candidates:
        return None
    primary = [item for item in candidates if item[1].source_leg is None]
    candidates = primary or candidates
    def rank(item):
        row, reading, _ = item
        metric = reading.dhw_value if kind == "coral" else reading.anomaly_c
        return (metric, reading.date, max(_retrieval_times(reading.provenance)), row["event_id"])
    return deepcopy(max(candidates, key=rank)[0])


def make_payload(coral: dict, sst: dict, evaluation_at: str) -> dict:
    from src.editorial.synthesis import CORAL_TO_SST_REGION, WINDOW_DAYS, _iso_week

    c = validate_component(coral, "coral", evaluation_at)
    s = validate_component(sst, "sst_anomaly", evaluation_at)
    _require(CORAL_TO_SST_REGION.get(c.region_id) == s.region_slug, "unmapped_pair")
    return {
        "marine_schema_version": 1, "kind": "marine_compound",
        "source_name": "NOAA Coral Reef Watch",
        "event_id": f"synthesis_marine_compound_{c.region_id}_{_iso_week(_stamp(evaluation_at).date())}",
        "evaluation_at": evaluation_at, "window_days": WINDOW_DAYS,
        "coral_region_id": c.region_id, "sst_region_slug": s.region_slug,
        "components": {"coral": deepcopy(coral), "sst_anomaly": deepcopy(sst)},
    }


def _pair(payload: Any):
    _require(type(payload) is dict, "marine_payload_shape")
    components = payload["components"]
    _require(type(components) is dict and set(components) == set(KINDS), "marine_pair_shape")
    expected = make_payload(components["coral"], components["sst_anomaly"], payload["evaluation_at"])
    _require(fingerprint(payload) == fingerprint(expected), "marine_payload_binding")
    # Numeric schema versions must not inherit JSON's number equivalence.
    _require(type(payload["marine_schema_version"]) is int and type(payload["window_days"]) is int,
             "marine_payload_schema")
    return (validate_component(components["coral"], "coral", payload["evaluation_at"]),
            validate_component(components["sst_anomaly"], "sst_anomaly", payload["evaluation_at"]))


def build_bundle(payload: dict):
    from src.two_bot.types import StoryBundle
    from src.two_bot.bundle_capture import capture_bundle

    coral, sst = _pair(payload)
    point = coral.source_leg == "crw_erddap"
    coral_scope = coral_evidence.DHW_POINT_SCOPE if point else coral_evidence.REGIONAL_SCOPE
    coral_limit = coral_evidence.DHW_ONLY_LIMIT if point else coral_evidence.REGIONAL_LIMIT
    result = StoryBundle(
        signal_kind=SIGNAL_KIND, where=coral.region_full_name,
        when=payload["evaluation_at"][:10], event_id=payload["event_id"],
        headline_metric={"label": "coral_dhw", "value": coral.dhw_value, "unit": "°C-weeks"},
        current_facts=[
            {"label": "data_source", "value": "NOAA Coral Reef Watch; independently dated source products"},
            {"label": "evaluation_at", "value": payload["evaluation_at"]},
            {"label": "coral_region", "value": coral.region_full_name},
            {"label": "coral_valid_date", "value": coral.date},
            {"label": "dhw_value", "value": coral.dhw_value, "unit": "°C-weeks"},
            {"label": "coral_sample_scope", "value": coral_scope},
            {"label": "coral_claim_limit", "value": coral_limit},
            {"label": "sst_region", "value": sst.region_display_name},
            {"label": "sst_valid_date", "value": sst.date},
            {"label": "sst_anomaly_c", "value": sst.anomaly_c, "unit": "°C"},
            {"label": "sst_sample_scope", "value": crw_contract.METHOD},
            {"label": "sst_sampled_cells", "value": sst.cells_used},
            {"label": "composition_limits", "value": LIMITS},
        ],
        historical_context={
            "scope": "independent_dated_marine_measurements",
            "sst_reference_climatology": {"label": "sst_reference_climatology",
                                          "value": crw_contract.reference_climatology(sst)},
            "association": {"label": "regional_association",
                            "coral_region_id": coral.region_id, "sst_region_slug": sst.region_slug,
                            "value": "configured regional association, not a shared measurement footprint"},
        },
        raw_signal_dump=deepcopy(payload),
    )
    capture_bundle(result)  # Complete review evidence must fit its existing32KiB bound.
    return result


def is_marine(bundle: Any) -> bool:
    raw = getattr(bundle, "raw_signal_dump", None)
    return getattr(bundle, "signal_kind", None) == SIGNAL_KIND or (
        isinstance(raw, dict) and (raw.get("kind") == "marine_compound" or "marine_schema_version" in raw)
    )


def bundle_failures(bundle: Any) -> list[str]:
    if not is_marine(bundle):
        return []
    try:
        expected = build_bundle(bundle.raw_signal_dump)
        _require(fingerprint(bundle.to_dict()) == fingerprint(expected.to_dict()), "marine_story_projection")
    except _ERRORS:
        return ["Marine comparison requires complete qualified source components with bound dates, scopes and projections"]
    return []


def claim_failures(tweet: str, bundle: Any) -> list[str]:
    """Finite shared-event/impact guards; ordinary required checking still applies."""
    if not is_marine(bundle):
        return []
    from types import SimpleNamespace
    from src.two_bot.pipeline import _cross_signal_violation

    text = re.sub(r"[\s\-\u2010-\u2015\u2212]+", " ", tweet.lower())
    shared = _cross_signal_violation(tweet, bundle)
    if shared or re.search(
        r"\b(?:(?:same|shared|single) (?:footprint|reef|waters|patch|location)|"
        r"simultaneous(?:ly)?|at the same time|overlap\w*|marine heatwave|mass bleaching|"
        r"observed bleaching|bleaching (?:is|was|has been) observed|mortality|corals? (?:died|are dying|bleached))\b",
        text,
    ):
        return ["unwarranted_marine_relation: paired source products do not establish a shared event, footprint, cause or impact"]
    try:
        coral, sst = _pair(bundle.raw_signal_dump)
        if coral.date != sst.date and re.search(r"\b(?:same day|same date)\b", text):
            return ["unwarranted_marine_time: the selected products have different valid dates"]
        subject = SimpleNamespace(signal_kind="coral_bleaching", raw_signal_dump=asdict(coral), current_facts=[])
        if coral.source_leg == "crw_erddap" and coral_evidence._ALERT_LABEL.search(text):
            return ["unwarranted_coral_alert: the selected DHW point has no alert-class evidence"]
        return ["unwarranted_coral_alert: " + reason
                for reason in coral_evidence.regional_alert_failures(tweet, subject)]
    except _ERRORS:
        return []  # bundle_failures supplies the source refusal; never a check pass.
