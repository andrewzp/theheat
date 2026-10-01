"""Bounded, content-free provider usage observations; never billing authority.

The recent window supplements the legacy cumulative ledger. It cannot recover
missing responses, prove billed cost, settle reservations or enforce an allowance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import uuid

CONTRACT: dict = {
    "schema_version": 1, "limit": 32, "record_bytes": 4096, "input_limit": 1024,
    "count_limit": 10**12, "modality_limit": 8,
    "identifier_pattern": r"^[A-Za-z0-9_.:/@-]{1,160}$",
    "modalities": ["MODALITY_UNSPECIFIED", "TEXT", "IMAGE", "VIDEO", "AUDIO", "DOCUMENT"],
    "counts": {
        "google": ["prompt_token_count", "candidates_token_count", "cached_content_token_count",
                   "thoughts_token_count", "tool_use_prompt_token_count", "total_token_count"],
        "anthropic": ["input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                      "cache_creation.ephemeral_5m_input_tokens", "cache_creation.ephemeral_1h_input_tokens",
                      "output_tokens_details.thinking_tokens", "server_tool_use.web_search_requests",
                      "server_tool_use.web_fetch_requests"],
        "unknown": [],
    },
    "labels": {"google": ["traffic_type"], "anthropic": ["service_tier", "inference_geo"], "unknown": []},
    "breakdowns": {"google": ["prompt_tokens_details", "candidates_tokens_details", "cache_tokens_details",
                              "tool_use_prompt_tokens_details"], "anthropic": [], "unknown": []},
}
_IDENTIFIER = re.compile(CONTRACT["identifier_pattern"])
_RECORD_KEYS = {"schema_version", "id", "observed_at", "stage", "provider", "requested_model",
                "resolved_model", "response_id", "usage_status", "counts", "labels", "breakdowns",
                "invalid_fields", "unsupported_fields"}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _identifier(value) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _count(value) -> bool:
    return type(value) in (int, float) and 0 <= value <= CONTRACT["count_limit"] and value == int(value)


def _paths(provider):
    return {"provider", "stage", "requested_model", "resolved_model", "response_id", "usage", "capture",
            *CONTRACT["counts"][provider], *CONTRACT["labels"][provider], *CONTRACT["breakdowns"][provider]}


def _timestamp(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        return datetime.fromisoformat(value).isoformat(timespec="milliseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def valid_record(raw) -> bool:
    """Strict bounded persisted schema, paired with the dashboard validator."""
    if not isinstance(raw, dict) or len(raw) != len(_RECORD_KEYS) or set(raw) != _RECORD_KEYS:
        return False
    if type(raw["schema_version"]) not in (int, float) or raw["schema_version"] != 1:
        return False
    if not isinstance(raw["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", raw["id"]) or not _timestamp(raw["observed_at"]):
        return False
    provider = raw["provider"]
    if provider not in ("google", "anthropic", "unknown") or raw["usage_status"] not in ("present", "absent", "invalid"):
        return False
    if any(raw[k] is not None and not _identifier(raw[k]) for k in ("stage", "requested_model", "resolved_model", "response_id")):
        return False
    if type(raw["unsupported_fields"]) is not bool:
        return False
    errors = raw["invalid_fields"]
    if not isinstance(errors, list) or not all(isinstance(x, str) and x in _paths(provider) for x in errors):
        return False
    if errors != sorted(set(errors)):
        return False
    for section in ("counts", "labels", "breakdowns"):
        fields = raw[section]
        if (not isinstance(fields, dict) or len(fields) != len(CONTRACT[section][provider])
                or set(fields) != set(CONTRACT[section][provider])):
            return False
        for value in fields.values():
            if value is None:
                continue
            if section == "counts" and not _count(value):
                return False
            if section == "labels" and not _identifier(value):
                return False
            if section == "breakdowns":
                if not isinstance(value, list) or len(value) > CONTRACT["modality_limit"]:
                    return False
                seen = set()
                for item in value:
                    if not isinstance(item, dict) or set(item) != {"modality", "token_count"}:
                        return False
                    mode, count = item["modality"], item["token_count"]
                    if not isinstance(mode, str) or mode not in CONTRACT["modalities"] or mode in seen:
                        return False
                    if not _count(count):
                        return False
                    seen.add(mode)
                if value != sorted(value, key=lambda x: x["modality"]):
                    return False
    return len(canonical(raw).encode()) <= CONTRACT["record_bytes"]


def observe_response(stage, response, model, provider) -> dict:
    """Read only allowlisted SDK fields; absent values differ from explicit zero.

    No content/text accessor, serialization of the response, or provider request.
    A field access failure is recorded without changing the successful response.
    """
    errors: set[str] = set()
    if provider not in ("google", "anthropic"):
        provider = "unknown"
        errors.add("provider")

    def identifier(value, name):
        if value is not None and not _identifier(value):
            errors.add(name)
            return None
        return value

    def get(obj, path, error_field=None):
        try:
            for part in path.split("."):
                if obj is None:
                    return None
                obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part, None)
            return obj
        except Exception:
            errors.add(error_field or (path if path in _paths(provider) else "usage"))
            return None

    usage = get(response, "usage" if provider == "anthropic" else "usage_metadata") if provider != "unknown" else None
    status = "invalid" if "usage" in errors else "absent" if usage is None else "present"
    counts = {}
    for path in CONTRACT["counts"][provider]:
        value = get(usage, path)
        if value is not None and (type(value) is not int or not _count(value)):
            errors.add(path)
            value = None
        counts[path] = value
    labels = {path: identifier(get(usage, path), path) for path in CONTRACT["labels"][provider]}
    breakdowns = {}
    for path in CONTRACT["breakdowns"][provider]:
        raw = get(usage, path)
        value = None
        if raw is not None:
            if not isinstance(raw, list) or len(raw) > CONTRACT["modality_limit"]:
                errors.add(path)
            else:
                value, seen = [], set()
                for item in raw:
                    mode, count = get(item, "modality"), get(item, "token_count")
                    if (not isinstance(mode, str) or mode not in CONTRACT["modalities"] or mode in seen
                            or type(count) is not int or not _count(count)):
                        errors.add(path)
                        value = None
                        break
                    seen.add(mode)
                    value.append({"modality": mode, "token_count": count})
                if value is not None:
                    value.sort(key=lambda x: x["modality"])
        breakdowns[path] = value

    # Do not retain unknown field names/values, which could include content.
    def extras(obj, allowed):
        if obj is None:
            return False
        try:
            instance = obj if isinstance(obj, dict) else vars(obj)
            declared = {} if isinstance(obj, dict) else getattr(type(obj), "model_fields", {})
            if len(instance) > 64 or len(declared) > 64:
                return True
            fields = set(instance) | set(declared)
            extra = {} if isinstance(obj, dict) else getattr(obj, "model_extra", None)
            return any(k not in allowed and not k.startswith("_") for k in fields) or bool(extra)
        except Exception:
            errors.add("usage")
            return True

    all_paths = CONTRACT["counts"][provider] + CONTRACT["labels"][provider] + CONTRACT["breakdowns"][provider]
    unsupported = extras(usage, {p.split(".")[0] for p in all_paths})
    for parent in sorted({p.split(".")[0] for p in all_paths if "." in p}):
        unsupported |= extras(get(usage, parent), {p.split(".")[1] for p in all_paths if p.startswith(parent+".")})
    for path in CONTRACT["breakdowns"][provider]:
        items = get(usage, path)
        if isinstance(items, list):
            for item in items[:CONTRACT["modality_limit"]]:
                unsupported |= extras(item, {"modality", "token_count"})
    raw = {
        "schema_version": 1, "id": uuid.uuid4().hex,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "stage": identifier(stage, "stage"), "provider": provider,
        "requested_model": identifier(model, "requested_model"),
        "resolved_model": identifier(get(response, "model" if provider == "anthropic" else "model_version", "resolved_model"), "resolved_model"),
        "response_id": identifier(get(response, "id" if provider == "anthropic" else "response_id", "response_id"), "response_id"),
        "usage_status": status, "counts": counts, "labels": labels, "breakdowns": breakdowns,
        "unsupported_fields": unsupported, "invalid_fields": [],
    }
    raw["invalid_fields"] = sorted(errors)
    if not valid_record(raw):
        # Oversize is explicit, not a silent partial observation or retry.
        raw.update(counts={p: None for p in CONTRACT["counts"][provider]},
                   labels={p: None for p in CONTRACT["labels"][provider]},
                   breakdowns={p: None for p in CONTRACT["breakdowns"][provider]},
                   usage_status="invalid", invalid_fields=["capture"], unsupported_fields=True)
    return raw


def merge_observations(*values) -> dict:
    """Union exact observations, then retain latest32. No counters are summed.

    Same-ID competing payloads remain separate until the explicit retention cap.
    This window is not a complete history, even before it first truncates.
    """
    result = {"schema_version": 1, "observations": [], "truncated": False, "invalid": False}
    rows: dict[str, dict] = {}
    for raw in values:
        if raw is None or raw == {}:
            continue
        if (not isinstance(raw, dict) or len(raw) != len(result) or set(raw) != set(result)
                or type(raw.get("schema_version")) not in (int, float) or raw["schema_version"] != 1
                or type(raw.get("truncated")) is not bool or type(raw.get("invalid")) is not bool
                or not isinstance(raw.get("observations"), list)):
            result["invalid"] = True
            continue
        result["truncated"] |= raw["truncated"] or len(raw["observations"]) > CONTRACT["input_limit"]
        result["invalid"] |= raw["invalid"]
        for row in raw["observations"][:CONTRACT["input_limit"]]:
            try:
                if not valid_record(row):
                    result["invalid"] = True
                    continue
                # Canonical numeric normalization gives Python/JS JSON parity.
                normalized = deepcopy(row)
                normalized["schema_version"] = 1
                normalized["counts"] = {k: None if v is None else int(v) for k, v in row["counts"].items()}
                for value in normalized["breakdowns"].values():
                    for item in value or []:
                        item["token_count"] = int(item["token_count"])
                rows[canonical(normalized)] = normalized
            except (TypeError, ValueError, OverflowError, RecursionError):
                result["invalid"] = True
    ordered = sorted(rows, key=lambda k: (rows[k]["observed_at"], rows[k]["id"], k), reverse=True)
    result["truncated"] |= len(ordered) > CONTRACT["limit"]
    result["observations"] = [rows[k] for k in ordered[:CONTRACT["limit"]]]
    return result


def summarize_observations(value) -> dict:
    window = merge_observations(value)
    ids = [r["id"] for r in window["observations"]]
    return {**window, "retained_conflicting_ids": sorted({i for i in ids if ids.count(i) > 1}),
            "accounting_complete": False, "scope": "Recent provider-reported usage only; not an invoice or complete call history."}
