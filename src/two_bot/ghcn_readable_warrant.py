"""Lossless, readable GHCN layout; representation grants no source or send authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Any, cast

from src.two_bot.ghcn_claim_contract import (
    BASELINE_FIELDS,
    EVIDENCE_FIELDS,
    TABLE_FIELDS,
    VARIABLE_SCALARS,
)
from src.two_bot.json_utils import json_default

FORMAT = "ghcn-complete-readable-table-v1"
SCHEMA = "theheat-ghcn-complete-readable-table-v1"
PROFILE = {
    "format": FORMAT,
    "original_schema_version": 2,
    "all_null_group": "absent_calendar_key_not_zero",
}
BASELINE_PATH = "raw_signal_dump.evidence.baseline"
MAX_WIRE_BYTES = 32_768
MAX_FULL_BYTES = 262_144
MAX_DEPTH = 32
MAX_NODES = 65_536
MAX_INTEGER = 9_007_199_254_740_991
VARIABLES = ("temperature_2m_max", "temperature_2m_min")
COLS = ("accepted_years", "accepted_samples", "previous_date", "previous_c")
SIGNALS = frozenset(
    (
        "open_meteo_archive_high",
        "open_meteo_archive_low",
        "monthly_high",
        "monthly_low",
        "calendar_record",
        "calendar_record_low",
    )
)
REQUIRED = frozenset(
    "signal_kind where when event_id headline_metric current_facts historical_context raw_signal_dump".split()
)
OPTIONAL = frozenset(("country", "related_signals", "human_impact"))


class WarrantError(ValueError):
    """Fixed operational code, without retained values or external responses."""


def _require(condition: Any, code: str = "ghcn_readable_shape_invalid") -> None:
    if not condition:
        raise WarrantError(code)


def _walk(value: Any, *, native: bool = False) -> int:
    """Bound work before JSON/default conversion can allocate a detached tree."""
    count = 0
    ancestors: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "ghcn_readable_work_bound")
        kind = type(item)
        if item is None or kind is bool:
            return
        if kind is int:
            _require(abs(item) <= MAX_INTEGER, "ghcn_readable_scalar_invalid")
        elif kind is float:
            _require(math.isfinite(item), "ghcn_readable_scalar_invalid")
        elif kind is str:
            _require(len(item) <= MAX_FULL_BYTES, "ghcn_readable_byte_bound")
            try:
                item.encode("utf-8")
            except UnicodeError:
                raise WarrantError("ghcn_readable_scalar_invalid") from None
        elif kind is dict or kind is list or native and kind in (tuple, set, frozenset):
            _require(id(item) not in ancestors, "ghcn_readable_cycle")
            ancestors.add(id(item))
            if kind is dict:
                for key, child in item.items():
                    _require(type(key) is str)
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            ancestors.remove(id(item))
        elif native and isinstance(item, (date, datetime, Decimal)):
            normalized = json_default(item)
            _require(type(normalized) in (str, float), "ghcn_readable_scalar_invalid")
            visit(normalized, depth)
        elif native and is_dataclass(item) and not isinstance(item, type):
            _require(id(item) not in ancestors, "ghcn_readable_cycle")
            ancestors.add(id(item))
            for field in fields(item):
                visit(field.name, depth + 1)
                visit(getattr(item, field.name), depth + 1)
            ancestors.remove(id(item))
        else:
            raise WarrantError("ghcn_readable_scalar_invalid")

    visit(value, 0)
    return count


def _bytes(value: Any, limit: int, *, native: bool = False, capture: bool = False) -> bytes:
    _walk(value, native=native)
    encoder = json.JSONEncoder(
        sort_keys=True,
        ensure_ascii=capture,
        allow_nan=False,
        separators=None if capture else (",", ":"),
        default=json_default if native else None,
    )
    chunks: list[str] = []
    size = 0
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode("utf-8"))
            _require(size <= limit, "ghcn_readable_byte_bound")
            chunks.append(chunk)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, WarrantError):
            raise
        raise WarrantError("ghcn_readable_scalar_invalid") from None
    return "".join(chunks).encode("utf-8")


def _normal(value: Any, limit: int, *, native: bool = False, capture: bool = False) -> dict:
    result = json.loads(_bytes(value, limit, native=native, capture=capture))
    _require(type(result) is dict)
    _walk(result)
    return result


def _date(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _require(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value))
    try:
        _require(date.fromisoformat(value).isoformat() == value)
    except ValueError:
        raise WarrantError("ghcn_readable_date_invalid") from None


def _day(value: Any) -> None:
    _require(type(value) is str and re.fullmatch(r"[0-9]{2}-[0-9]{2}", value))
    _date("2000-" + value)


def _count(value: Any, *, positive: bool = False) -> None:
    _require(type(value) is int and (1 if positive else 0) <= value <= MAX_INTEGER)


def _number(value: Any, *, nullable: bool = False) -> None:
    _require(nullable and value is None or type(value) in (int, float) and math.isfinite(value))


def _columns(names: list[str]) -> list[str]:
    return ["calendar_day", *[f"{name}:{field}" for name in names for field in COLS]]


def has_readable_marker(value: Any) -> bool:
    if type(value) is not dict:
        return False
    raw, history = value.get("raw_signal_dump"), value.get("historical_context")
    evidence = raw.get("evidence") if type(raw) is dict else None
    baseline = evidence.get("baseline") if type(evidence) is dict else None
    alias = history.get("baseline") if type(history) is dict else None
    return bool(
        type(baseline) is dict
        and (
            "wire_profile" in baseline
            or "calendar_table" in baseline
            or type(baseline.get("schema_version")) is str
            and baseline["schema_version"].startswith("theheat-ghcn-")
        )
        or type(alias) is dict
        and ("same_document_baseline" in alias or "full_baseline_sha256" in alias)
    )


def _parts(tree: dict, *, wire: bool) -> tuple[dict, dict, dict, list[str]]:
    _require(
        REQUIRED <= tree.keys() <= REQUIRED | OPTIONAL
        and type(tree["signal_kind"]) is str
        and tree["signal_kind"] in SIGNALS
    )
    raw, history = tree["raw_signal_dump"], tree["historical_context"]
    _require(type(raw) is dict and type(history) is dict and "ghcn_claim_view" not in raw)
    evidence = raw.get("evidence")
    _require(
        type(evidence) is dict
        and evidence.get("source_product") == "noaa-ghcn-daily-v2"
        and evidence.get("evidence_type") == "observed"
    )
    _require(evidence.keys() == EVIDENCE_FIELDS)
    baseline = evidence.get("baseline")
    expected = BASELINE_FIELDS | ({"wire_profile", "calendar_table"} if wire else set())
    _require(type(baseline) is dict and baseline.keys() == expected)
    _require(
        type(baseline["schema_version"]) is (str if wire else int)
        and baseline["schema_version"] == (SCHEMA if wire else 2)
    )
    _require(
        baseline["source_product"] == "noaa-ghcn-daily-v2"
        and baseline["evidence_type"] == "observed"
    )
    _require(
        type(baseline["station_id"]) is str
        and re.fullmatch(r"[A-Z0-9]{11}", baseline["station_id"])
        and baseline["station_id"] == evidence["station_id"]
        and baseline["comparison_scope"] == "available_source_accepted_station_samples"
        and type(baseline["reconciled"]) is bool
    )
    _date(evidence["valid_date"])
    for key in ("comparison_before", "cutoff", "requested_comparison_cutoff"):
        _date(baseline[key], nullable=True)
    for key in ("source_payload_sha256", "revision_id"):
        _require(
            baseline[key] is None
            or type(baseline[key]) is str
            and re.fullmatch(r"[a-f0-9]{64}", baseline[key])
        )
    retrieved = baseline["retrieved_at"]
    if retrieved is not None:
        _require(
            type(retrieved) is str
            and re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)",
                retrieved,
            )
        )
        try:
            datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
        except ValueError:
            raise WarrantError("ghcn_readable_date_invalid") from None
    scopes = baseline["variables"]
    _require(type(scopes) is dict and bool(scopes) and scopes.keys() <= set(VARIABLES))
    names = [name for name in VARIABLES if name in scopes]
    for scope in scopes.values():
        _require(type(scope) is dict)
        table_fields = TABLE_FIELDS - ({"calendar_years", "calendar_samples"} if wire else set())
        keys = VARIABLE_SCALARS | table_fields
        _require(keys <= scope.keys() <= keys | {"candidate_accepted"})
        for key in ("complete", "source_coverage_complete", "candidate_accepted"):
            if key in scope:
                _require(type(scope[key]) is bool)
        for key in VARIABLE_SCALARS:
            if key.endswith("_count") or key in ("years_with_samples",):
                _count(scope[key])
        for key in ("coverage_fraction", "source_coverage_fraction"):
            _number(scope[key])
            _require(0 <= scope[key] <= 1)
        _number(scope["previous_value_c"], nullable=True)
        for key in (
            "start",
            "cutoff",
            "previous_date",
            "requested_comparison_cutoff",
            "source_latest_cell",
            "verified_source_cutoff",
        ):
            _date(scope[key], nullable=True)
        _require(type(scope["conflicting_dates"]) is list)
        for value in scope["conflicting_dates"]:
            _date(value)
        for key in table_fields:
            _require(type(scope[key]) is dict)
        for key in ("monthly_years", "monthly_samples"):
            for month, number in scope[key].items():
                _require(month in {f"{n:02d}" for n in range(1, 13)})
                _count(number, positive=key == "monthly_years")
        for key in ("record_dates", "record_values_c"):
            _require(
                scope[key].keys()
                == ({"all_time", "monthly"} if wire else {"all_time", "monthly", "calendar"})
            )
            _require(type(scope[key]["monthly"]) is dict)
        _date(scope["record_dates"]["all_time"], nullable=True)
        _number(scope["record_values_c"]["all_time"], nullable=True)
        months = scope["record_dates"]["monthly"]
        _require(
            months.keys()
            == scope["record_values_c"]["monthly"].keys()
            == scope["monthly_years"].keys()
        )
        for month, previous in months.items():
            _date(previous)
            _require(previous[5:7] == month)
            _number(scope["record_values_c"]["monthly"][month])
        if not wire:
            maps = (
                scope["calendar_years"],
                scope["calendar_samples"],
                scope["record_dates"]["calendar"],
                scope["record_values_c"]["calendar"],
            )
            _require(
                all(type(mapping) is dict and mapping.keys() == maps[0].keys() for mapping in maps)
            )
            for day in maps[0]:
                _require(_group(day, [mapping[day] for mapping in maps]))
    return raw, history, baseline, names


def _group(day: Any, group: Any) -> bool:
    _day(day)
    _require(type(group) is list and len(group) == 4)
    if all(value is None for value in group):
        return False
    _require(all(value is not None for value in group))
    years, samples, previous, value = group
    _count(years, positive=True)
    _count(samples, positive=True)
    _require(samples >= years)
    _date(previous)
    _require(previous[5:] == day)
    _number(value)
    return True


def _decode(wire: dict) -> dict:
    _raw, history, baseline, names = _parts(wire, wire=True)
    _require(_bytes(baseline["wire_profile"], MAX_WIRE_BYTES) == _bytes(PROFILE, MAX_WIRE_BYTES))
    alias = history.get("baseline")
    _require(
        type(alias) is dict
        and alias.keys() == {"same_document_baseline", "full_baseline_sha256"}
        and alias["same_document_baseline"] == BASELINE_PATH
        and type(alias["full_baseline_sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", alias["full_baseline_sha256"])
    )
    table = baseline["calendar_table"]
    _require(type(table) is dict and table.keys() == {"variables", "columns", "rows"})
    _require(table["variables"] == names and table["columns"] == _columns(names))
    rows = table["rows"]
    _require(type(rows) is list and len(rows) <= 366)
    previous = ""
    counts = {name: 0 for name in names}
    for row in rows:
        _require(type(row) is list and len(row) == 1 + 4 * len(names))
        _day(row[0])
        _require(row[0] > previous)
        previous = row[0]
        present = False
        for index, name in enumerate(names):
            exists = _group(row[0], row[1 + 4 * index : 5 + 4 * index])
            counts[name] += int(exists)
            present |= exists
        _require(present)
    # Pre-account the exact JSON expansion before allocating its calendar maps
    # and duplicated baseline. Removing profile/table changes no other fields.
    core = {
        key: value
        for key, value in baseline.items()
        if key not in ("wire_profile", "calendar_table")
    }
    core["schema_version"] = 2
    core_size = len(_bytes(core, MAX_FULL_BYTES))
    core_nodes = _walk(core)
    for index, name in enumerate(names):
        for column, field in enumerate(
            ("calendar_years", "calendar_samples", "calendar", "calendar")
        ):
            entries = [
                (row[0], row[1 + 4 * index + column])
                for row in rows
                if row[1 + 4 * index] is not None
            ]
            map_size = (
                2
                + max(0, len(entries) - 1)
                + sum(
                    len(_bytes(day, MAX_FULL_BYTES)) + 1 + len(_bytes(value, MAX_FULL_BYTES))
                    for day, value in entries
                )
            )
            core_size += 1 + len(_bytes(field, MAX_FULL_BYTES)) + 1 + map_size
            core_nodes += 2 + 2 * counts[name]
    expanded_size = (
        len(_bytes(wire, MAX_FULL_BYTES))
        - len(_bytes(baseline, MAX_FULL_BYTES))
        - len(_bytes(alias, MAX_FULL_BYTES))
        + 2 * core_size
    )
    expanded_nodes = _walk(wire) - _walk(baseline) - _walk(alias) + 2 * core_nodes
    _require(
        expanded_size <= MAX_FULL_BYTES and expanded_nodes <= MAX_NODES,
        "ghcn_readable_expansion_bound",
    )
    full = deepcopy(wire)
    restored = full["raw_signal_dump"]["evidence"]["baseline"]
    del restored["wire_profile"], restored["calendar_table"]
    restored["schema_version"] = 2
    for index, name in enumerate(names):
        scope = restored["variables"][name]
        maps: list[dict] = [{}, {}, {}, {}]
        for row in rows:
            group = row[1 + 4 * index : 5 + 4 * index]
            if group[0] is not None:
                for mapping, value in zip(maps, group, strict=True):
                    mapping[row[0]] = value
        scope["calendar_years"], scope["calendar_samples"] = maps[:2]
        scope["record_dates"]["calendar"], scope["record_values_c"]["calendar"] = maps[2:]
    full["historical_context"]["baseline"] = deepcopy(restored)
    actual = _bytes(full, MAX_FULL_BYTES)
    _require(len(actual) == expanded_size and _walk(full) == expanded_nodes)
    _require(
        hashlib.sha256(_bytes(restored, MAX_FULL_BYTES)).hexdigest()
        == cast(dict, alias)["full_baseline_sha256"],
        "ghcn_readable_alias_changed",
    )
    _parts(full, wire=False)
    return full


def _encode(full: dict) -> dict:
    _raw, history, baseline, names = _parts(full, wire=False)
    _require(
        _bytes(history.get("baseline"), MAX_FULL_BYTES) == _bytes(baseline, MAX_FULL_BYTES),
        "ghcn_readable_baseline_changed",
    )
    wire = deepcopy(full)
    converted = wire["raw_signal_dump"]["evidence"]["baseline"]
    wire["historical_context"]["baseline"] = {
        "same_document_baseline": BASELINE_PATH,
        "full_baseline_sha256": hashlib.sha256(_bytes(baseline, MAX_FULL_BYTES)).hexdigest(),
    }
    converted["schema_version"], converted["wire_profile"] = SCHEMA, deepcopy(PROFILE)
    values = []
    for name in names:
        scope = converted["variables"][name]
        values.append(
            [
                scope.pop("calendar_years"),
                scope.pop("calendar_samples"),
                scope["record_dates"].pop("calendar"),
                scope["record_values_c"].pop("calendar"),
            ]
        )
    days = sorted(set().union(*(maps[0] for maps in values)))
    converted["calendar_table"] = {
        "variables": names,
        "columns": _columns(names),
        "rows": [[day, *[mapping.get(day) for maps in values for mapping in maps]] for day in days],
    }
    return wire


def encode_full(value: Any) -> dict:
    """Normalize with the existing codec and encode the entire source warrant."""
    full = _normal(value, MAX_FULL_BYTES, native=True)
    wire = _normal(_encode(full), MAX_WIRE_BYTES, capture=True)
    _require(
        _bytes(_decode(wire), MAX_FULL_BYTES) == _bytes(full, MAX_FULL_BYTES),
        "ghcn_readable_roundtrip_changed",
    )
    return wire


def decode_wire(value: Any) -> dict:
    """Return detached full science; keep the caller's wire as approval identity."""
    wire = _normal(value, MAX_WIRE_BYTES, capture=True)
    full = _decode(wire)
    _require(
        _bytes(_encode(full), MAX_WIRE_BYTES, capture=True)
        == _bytes(wire, MAX_WIRE_BYTES, capture=True),
        "ghcn_readable_wire_changed",
    )
    return full


class ReadableBundle:
    """Mutable complete fields with freshly recomputed complete wire serialization."""

    _present: set[str]

    def __init__(self, full: dict):
        data = _normal(full, MAX_FULL_BYTES, native=True)
        _parts(data, wire=False)
        object.__setattr__(self, "_present", set(data))
        for key in REQUIRED:
            object.__setattr__(self, key, data[key])
        for key, default in (("country", ""), ("related_signals", []), ("human_impact", [])):
            object.__setattr__(self, key, data.get(key, default))

    def __setattr__(self, key: str, value: Any) -> None:
        if key in OPTIONAL:
            self._present.add(key)
        object.__setattr__(self, key, value)

    def full_tree(self) -> dict:
        data = {key: getattr(self, key) for key in REQUIRED}
        for key in OPTIONAL:
            value = getattr(self, key)
            if key in self._present or value:
                if key == "related_signals":
                    from src.two_bot.types import RelatedSignal

                    value = [
                        item.to_dict() if isinstance(item, RelatedSignal) else item
                        for item in value
                    ]
                data[key] = value
        return _normal(data, MAX_FULL_BYTES, native=True)

    def to_dict(self) -> dict:
        return encode_full(self.full_tree())


def retained_bundle(value: Any) -> ReadableBundle:
    full = decode_wire(value)
    result = ReadableBundle(full)
    _require(
        _bytes(result.to_dict(), MAX_WIRE_BYTES, capture=True)
        == _bytes(value, MAX_WIRE_BYTES, capture=True),
        "ghcn_readable_wire_changed",
    )
    return result


def _generation_context(full: dict) -> None:
    """Skip contexts the existing complete publication replay cannot reconstruct.

    A discarded original candidate is not retained. Its False flag therefore
    cannot be recreated from the accepted observation set. Encoding preserves
    such evidence for inspection, but fresh generation must not buy a draft
    that the current source guard will necessarily refuse.
    """
    evidence = full["raw_signal_dump"]["evidence"]
    observations = evidence["variables"]
    scopes = evidence["baseline"]["variables"]
    _require(
        type(observations) is dict
        and bool(observations)
        and observations.keys() <= {"TMAX", "TMIN"}
        and scopes.keys() == set(VARIABLES),
        "ghcn_readable_context_incomplete",
    )
    for variable, element in zip(VARIABLES, ("TMAX", "TMIN"), strict=True):
        scope = scopes[variable]
        if element in observations:
            _require(scope.get("candidate_accepted") is True, "ghcn_readable_context_incomplete")
        else:
            _require("candidate_accepted" not in scope, "ghcn_readable_context_incomplete")


def prepare_bundle(bundle: Any) -> Any:
    """Idempotent preparation BEFORE capture/cache/request identities, no authority."""
    if isinstance(bundle, ReadableBundle):
        _generation_context(bundle.full_tree())
        return bundle
    # Unrelated families retain their original serialization/refusal ordering.
    # Inspect only their ordinary fields; never add an eager to_dict call.
    raw = getattr(bundle, "raw_signal_dump", None)
    history = getattr(bundle, "historical_context", None)
    marker = has_readable_marker({"raw_signal_dump": raw, "historical_context": history})
    evidence = raw.get("evidence") if type(raw) is dict else None
    signal = getattr(bundle, "signal_kind", None)
    fresh = (
        type(raw) is dict
        and "ghcn_claim_view" not in raw
        and type(signal) is str
        and signal in SIGNALS
        and type(evidence) is dict
        and evidence.get("source_product") == "noaa-ghcn-daily-v2"
    )
    if not marker and not fresh:
        return bundle
    tree = bundle.to_dict()
    if has_readable_marker(tree):
        result = retained_bundle(tree)
        _generation_context(result.full_tree())
        return result
    raw = tree.get("raw_signal_dump") if type(tree) is dict else None
    evidence = raw.get("evidence") if type(raw) is dict else None
    if (
        type(tree) is dict
        and type(tree.get("signal_kind")) is str
        and tree["signal_kind"] in SIGNALS
        and type(raw) is dict
        and type(evidence) is dict
        and evidence.get("source_product") == "noaa-ghcn-daily-v2"
        and "ghcn_claim_view" not in raw
    ):
        result = ReadableBundle(_normal(tree, MAX_FULL_BYTES, native=True))
        _generation_context(result.full_tree())
        return result
    return bundle


class _ScientificBundle:
    """Detached full calculation input; never a replacement for saved wire identity."""

    def __init__(self, tree: dict):
        self._tree = deepcopy(tree)

    def __getattr__(self, name: str) -> Any:
        if name in REQUIRED | OPTIONAL:
            tree = object.__getattribute__(self, "_tree")
            if name in tree:
                return tree[name]
            if name == "country":
                return ""
            if name in ("related_signals", "human_impact"):
                return []
        raise AttributeError(name)

    def to_dict(self) -> dict:
        return deepcopy(self._tree)


def scientific_bundle(bundle: Any) -> Any:
    """Validate an exact prepared adapter, then expose its complete calculation view.

    Generic/legacy objects are not hydrated or repaired here. Retained readers
    must explicitly validate the original wire through retained_bundle first.
    """
    if isinstance(bundle, ReadableBundle):
        return _ScientificBundle(decode_wire(bundle.to_dict()))
    return bundle


def materialize_tree(value: dict) -> dict:
    """Explicit saved-wire calculation boundary; old full trees keep their content."""
    return decode_wire(value) if has_readable_marker(value) else deepcopy(value)
