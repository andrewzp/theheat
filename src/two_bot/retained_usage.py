"""Passive usage from detached provider bytes. No verdict, price or persistence."""
from __future__ import annotations

import json

from src.two_bot.usage_observations import CONTRACT, observe_response

PARSER_VERSION = "retained_usage_v1"
_GOOGLE = {
    "promptTokenCount": "prompt_token_count", "candidatesTokenCount": "candidates_token_count",
    "cachedContentTokenCount": "cached_content_token_count", "thoughtsTokenCount": "thoughts_token_count",
    "toolUsePromptTokenCount": "tool_use_prompt_token_count", "totalTokenCount": "total_token_count",
    "trafficType": "traffic_type", "promptTokensDetails": "prompt_tokens_details",
    "candidatesTokensDetails": "candidates_tokens_details", "cacheTokensDetails": "cache_tokens_details",
    "toolUsePromptTokensDetails": "tool_use_prompt_tokens_details",
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def decode(raw):
    def nonfinite(_):
        raise ValueError("nonfinite")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=nonfinite)


def empty(provider, reason, *, status="unavailable", observed_at=None, complete=None):
    kind = provider if provider in CONTRACT["counts"] else "unknown"
    return dict(parser_version=PARSER_VERSION, status=status, reason=reason, observed_at=observed_at, complete_response=complete,
                resolved_model=None, counts={k: None for k in CONTRACT["counts"][kind]},
                labels={k: None for k in CONTRACT["labels"][kind]},
                breakdowns={k: None for k in CONTRACT["breakdowns"][kind]},
                invalid_fields=[], unsupported_fields=False)


def _provider_fields(provider, metadata):
    """One raw/terminal mapping; retain field presence separately from nulls."""
    if metadata is None:
        return None, set()
    if type(metadata) is not dict:
        raise ValueError("invalid_usage")
    if provider == "google":
        mapped = {_GOOGLE[k]: v for k, v in metadata.items() if k in _GOOGLE}
        present = set(mapped)
        if any(k not in _GOOGLE for k in metadata):
            mapped["unsupported"] = True
        for key in CONTRACT["breakdowns"]["google"]:
            items = mapped.get(key)
            if isinstance(items, list):
                mapped[key] = [dict(modality=i.get("modality"), token_count=i.get("tokenCount"),
                    **({"unsupported": True} if set(i)-{"modality", "tokenCount"} else {}))
                    if type(i) is dict else i for i in items]
        return mapped, present
    present = set()
    for key in sum((CONTRACT[part][provider] for part in ("counts", "labels", "breakdowns")), []):
        current = metadata
        for part in key.split("."):
            if type(current) is not dict or part not in current:
                break
            current = current[part]
        else:
            present.add(key)
    return metadata, present


def _normalized(provider, metadata, stage, model, resolved_model=None):
    mapped, present = _provider_fields(provider, metadata)
    envelope = dict(usage_metadata=mapped, model_version=resolved_model) if provider == "google" else dict(usage=mapped, model=resolved_model)
    return observe_response(stage, envelope, model, provider), present


def _terminal(provider, value, stage, model):
    # Existing synchronous writer receipts retain normalized counts. Google
    # check receipts retain the original camelCase usageMetadata object.
    if provider == "anthropic" and "counts" in value:
        counts = value["counts"]
        if type(counts) is not dict:
            raise ValueError("invalid_terminal_usage")
        metadata: dict = {}
        for key in CONTRACT["counts"][provider]:
            if key not in counts:
                continue
            parts = key.split(".")
            current = metadata
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = counts[key]
        value = metadata
    return _normalized(provider, value, stage, model)


def extract(raw, *, provider, stage, model, observed_at, complete, terminal_usage=None):
    """Extract only usage, even when the retained editorial answer was rejected."""
    result = empty(provider, "response_incomplete", observed_at=observed_at, complete=complete)
    if not complete:
        return result
    try:
        envelope = decode(raw)
        if type(envelope) is not dict or provider not in {"anthropic", "google"}:
            raise ValueError("invalid_envelope")
        metadata = envelope.get("usage" if provider == "anthropic" else "usageMetadata")
        value, present = _normalized(provider, metadata, stage, model,
            envelope.get("model" if provider == "anthropic" else "modelVersion"))
        result.update(status=value["usage_status"], reason=None,
            **{k: value[k] for k in ("resolved_model", "counts", "labels", "breakdowns", "invalid_fields", "unsupported_fields")})
        if result["invalid_fields"]:
            result.update(status="invalid", reason="invalid_envelope")
        if terminal_usage is not None:
            if type(terminal_usage) is not dict:
                raise ValueError("invalid_terminal_usage")
            terminal, reported = _terminal(provider, terminal_usage, stage, model)
            common = present & reported
            if set(terminal["invalid_fields"]) & common or any(
                result[part][key] != terminal[part][key]
                for part in ("counts", "labels", "breakdowns") for key in common if key in result[part]
            ):
                raise ValueError("conflicting_terminal_usage")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        result = empty(provider, "invalid_envelope", status="invalid", observed_at=observed_at, complete=complete)
    return result
