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


def extract(raw, *, provider, stage, model, observed_at, complete, terminal_usage=None):
    """Extract only usage, even when the retained editorial answer was rejected."""
    result = empty(provider, "response_incomplete", observed_at=observed_at, complete=complete)
    if not complete:
        return result
    try:
        envelope = decode(raw)
        if type(envelope) is not dict or provider not in {"anthropic", "google"}:
            raise ValueError("invalid_envelope")
        usage = envelope.get("usage" if provider == "anthropic" else "usageMetadata")
        if usage is not None and type(usage) is not dict:
            raise ValueError("invalid_usage")
        if provider == "google":
            mapped = None
            if usage is not None:
                mapped = {_GOOGLE[k]: v for k, v in usage.items() if k in _GOOGLE}
                if any(k not in _GOOGLE for k in usage):
                    mapped["unsupported"] = True
                for key in CONTRACT["breakdowns"]["google"]:
                    items = mapped.get(key)
                    if isinstance(items, list):
                        mapped[key] = [dict(modality=i.get("modality"), token_count=i.get("tokenCount"),
                            **({"unsupported": True} if set(i)-{"modality", "tokenCount"} else {}))
                            if type(i) is dict else i for i in items]
            envelope = dict(usage_metadata=mapped, model_version=envelope.get("modelVersion"))
        else:
            envelope = dict(usage=usage, model=envelope.get("model"))
        value = observe_response(stage, envelope, model, provider)
        result.update(status=value["usage_status"], reason=None,
            **{k: value[k] for k in ("resolved_model", "counts", "labels", "breakdowns", "invalid_fields", "unsupported_fields")})
        if result["invalid_fields"]:
            result.update(status="invalid", reason="invalid_envelope")
        if type(terminal_usage) is dict:
            comparison = terminal_usage.get("counts", terminal_usage)
            if type(comparison) is dict and any(k in comparison and comparison[k] != v for k, v in result["counts"].items()):
                result = empty(provider, "invalid_envelope", status="invalid", observed_at=observed_at, complete=complete)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        result = empty(provider, "invalid_envelope", status="invalid", observed_at=observed_at, complete=complete)
    return result
