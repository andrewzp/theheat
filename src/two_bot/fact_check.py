"""Stage 4: deterministic reuse checks plus strict Gemini fact-checking."""

from __future__ import annotations

import json
import os

from src.config import CHEAP_MODEL
from src.state_schema import BotState
from src.two_bot import memory
from src.two_bot.prompts.fact_check_prompt import (
    FACT_CHECK_SYSTEM_PROMPT,
    FACT_CHECK_USER_PROMPT_TEMPLATE,
)
from src.two_bot.retry import call_with_retries
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.strict_contract import CLAIM_KINDS, bundle_schema_issues, material_span_failures, review_snapshot
from src.two_bot.types import ExtractedClaim, FactCheckResult, StoryBundle
from src.two_bot.json_utils import json_default as _json_default, loads_model_json, model_response_diagnostic, ModelOutputContractError

FACT_CHECKER_MODEL = os.environ.get("THEHEAT_FACT_CHECK_MODEL", CHEAP_MODEL)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# JSON-parse retry budget — mirrors the writer's same-named constant. If the
# Gemini fact-checker returns empty / non-JSON / mid-truncation output, retry
# once with a stronger contract reminder before bubbling up as a structured
# failure. Production failures this prevents: 2026-05-15 Somalia coral_bleaching
# alerts run hit "ValueError: invalid JSON: Expecting ',' delimiter line 7 col
# 384" — single attempt, no retry, surfaced as pipeline_error. Stochastic
# refusal usually unblocks on a second sampling.
JSON_PARSE_RETRY_BUDGET = 1
_VALID_CLAIM_KINDS = CLAIM_KINDS

FACT_CHECK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "extracted_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "kind": {"type": "string", "enum": sorted(CLAIM_KINDS)}},
                "required": ["text", "kind"],
                "additionalProperties": False,
            },
        },
        "failures": {
            "type": "array",
            "items": {"anyOf": [
                {"type": "string"},
                {"type": "object", "properties": {key: {"type": "string"} for key in ("claim", "category", "reason")},
                 "required": ["claim", "category", "reason"], "additionalProperties": False},
            ]},
        },
    },
    "required": ["passed", "extracted_claims", "failures"],
    "additionalProperties": False,
}


def _format_failure(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        claim = item.get("claim", "")
        category = item.get("category", "")
        reason = item.get("reason", "")
        parts = [str(part) for part in (claim, category, reason) if part]
        return ": ".join(parts) if parts else json.dumps(item, sort_keys=True)
    return str(item)


def _parse_extracted_claims(value, *, required: bool) -> list[ExtractedClaim]:
    """Keep every supported claim; unsupported kinds are explicit failures."""
    if value is None:
        if required:
            raise ModelOutputContractError("Fact-checker response must include extracted_claims")
        return []
    if not isinstance(value, list):
        raise ModelOutputContractError("Fact-checker extracted_claims must be a list")
    claims: list[ExtractedClaim] = []
    for item in value:
        if not isinstance(item, dict):
            raise ModelOutputContractError("Fact-checker extracted_claims items must be objects")
        text = item.get("text")
        kind = item.get("kind")
        if not isinstance(text, str) or not text.strip() or not isinstance(kind, str):
            raise ModelOutputContractError("Fact-checker claims must include text and kind strings")
        if set(item) != {"text", "kind"}:
            raise ModelOutputContractError("Fact-checker claim fields do not match the extraction contract")
        if kind not in _VALID_CLAIM_KINDS:
            raise ModelOutputContractError(f"Unsupported extracted claim kind: {kind!r}; claim remains unresolved")
        claims.append(ExtractedClaim(text=text, kind=kind))
    return claims


def _parse_fact_check_json(
    raw: str,
    *,
    require_extracted_claims: bool = False,
) -> tuple[bool, list[str], list[ExtractedClaim]]:
    try:
        parsed = loads_model_json(raw, expected="object")
    except ValueError as exc:
        raise ValueError(f"Fact-checker returned invalid JSON ({model_response_diagnostic(raw)})") from exc
    if not isinstance(parsed, dict):
        raise ModelOutputContractError("Fact-checker response must be a JSON object")
    if not isinstance(parsed.get("passed"), bool):
        raise ModelOutputContractError("Fact-checker response must include boolean passed")
    allowed = {"passed", "failures", "extracted_claims"}
    if "failures" not in parsed or set(parsed) - allowed:
        raise ModelOutputContractError("Fact-checker response fields do not match the output contract")
    failures = parsed["failures"]
    if not isinstance(failures, list):
        raise ModelOutputContractError("Fact-checker failures must be a list")
    extracted_claims = _parse_extracted_claims(
        parsed.get("extracted_claims"),
        required=require_extracted_claims,
    )
    for failure in failures:
        if isinstance(failure, str) and failure.strip():
            continue
        if not isinstance(failure, dict) or set(failure) != {"claim", "category", "reason"} or not all(isinstance(failure[key], str) and failure[key].strip() for key in failure):
            raise ModelOutputContractError("Fact-checker failures require a nonempty reason and exact claim/category fields")
    if parsed["passed"] != (not failures):
        raise ModelOutputContractError("Fact-checker passed flag contradicts its failures")
    return (
        parsed["passed"],
        [_format_failure(item) for item in failures],
        extracted_claims,
    )


def _call_gemini(tweet: str, bundle: StoryBundle, *, retry_suffix: str = "") -> str:
    """One Gemini fact-check call. Network-level retries handled by
    call_with_retries; JSON-parse retries handled by the caller (fact_check)
    via the ``retry_suffix`` kwarg, which appends a contract-reinforcement
    message to the user prompt on the second attempt.
    """

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for fact-checking")
    from google import genai
    from google.genai import types as genai_types

    # NB: google-genai HttpOptions.timeout is MILLISECONDS, not seconds.
    # (Confirmed against googleapis/python-genai/google/genai/types.py 2026-05-08.)
    # Prior value of `timeout=90` meant 90ms — every fact-check call failed
    # with ReadTimeout in <300ms total across 3 retry attempts, silently
    # killing every draft from 2026-05-03 onward (4-day production outage).
    # 90000 = 90 seconds, the original intent.
    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=90000))
    user_prompt = FACT_CHECK_USER_PROMPT_TEMPLATE.format(
        tweet=tweet,
        bundle_json=json.dumps(bundle.to_dict(), sort_keys=True, default=_json_default, allow_nan=False),
    )
    if retry_suffix:
        user_prompt = f"{user_prompt}{retry_suffix}"
    response = call_with_retries(
        "gemini fact-check",
        lambda: client.models.generate_content(
            model=FACT_CHECKER_MODEL,
            contents=f"{FACT_CHECK_SYSTEM_PROMPT}\n\n{user_prompt}",
            config=genai_types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=FACT_CHECK_OUTPUT_SCHEMA),
        ),
    )
    # google-genai's response.text is Optional — empty when no candidates
    # come back. Empty string falls through to the JSON parser as a parse
    # error, which the caller handles consistently with other failure modes.
    return response.text or ""


def fact_check(
    tweet: str,
    extracted: list[ExtractedClaim],
    bundle: StoryBundle,
    state: BotState,
) -> FactCheckResult:
    """Run strict local reuse checks, then LLM verification."""

    failures: list[str] = [f"{code}: {field}: {message}" for code, field, message in bundle_schema_issues(bundle)]
    if not failures:
        from src.data.temperature_evidence import temperature_claim_failures
        failures.extend(scientific_claim_failures(tweet, bundle))
        if isinstance(tweet, str):
            failures.extend(temperature_claim_failures(tweet, bundle))
    if not isinstance(tweet, str) or not tweet.strip() or len(tweet) > 280:
        failures.append("invalid_tweet: fact checking requires nonempty tweet text within 280 characters")
    elif isinstance(tweet, str):
        try:
            tweet.encode("utf-8")
        except UnicodeError:
            failures.append("invalid_tweet: malformed Unicode")
    if not isinstance(extracted, list) or any(not isinstance(claim, ExtractedClaim) or not isinstance(claim.kind, str) or claim.kind not in CLAIM_KINDS or not isinstance(claim.text, str) or not claim.text.strip() for claim in extracted):
        return FactCheckResult(
            passed=False, failures=[*failures, "invalid_claim_inventory: supplied claims must have nonempty text and a supported kind"],
            raw_response=json.dumps(review_snapshot(extracted), allow_nan=False), extracted_claims=[],
        )
    extracted = list(extracted)

    if isinstance(tweet, str) and memory.is_reuse(state, tweet, "tweet_text"):
        failures.append("reuse: tweet text duplicates shipped tweet")

    def _claim_reuse_failures(claims: list[ExtractedClaim]) -> list[str]:
        reuse_failures: list[str] = []
        for claim in claims:
            if claim.kind == "era_anchor" and memory.is_reuse(state, claim.text, "era_anchor"):
                reuse_failures.append(f"reuse: era anchor '{claim.text}' already used")
            if claim.kind == "peer_comparison" and memory.is_reuse(state, claim.text, "peer_comparison"):
                reuse_failures.append(f"reuse: peer comparison '{claim.text}' already used")
        return reuse_failures

    failures.extend(_claim_reuse_failures(extracted))

    if failures:
        return FactCheckResult(
            passed=False,
            failures=failures,
            raw_response="(local deterministic checks)",
            extracted_claims=extracted,
        )

    # JSON-parse retry loop. The Gemini fact-checker occasionally returns
    # empty / mid-truncated / non-JSON output (stochastic refusal class).
    # call_with_retries handles network-level errors INSIDE _call_gemini,
    # but the JSON parse happens AFTER that returns — so without this
    # outer retry a malformed response surfaces as pipeline_error. Mirror
    # the writer's pattern: retry once with an explicit contract reminder,
    # then return a structured fact_check FAIL instead of letting
    # ValueError bubble up. Fail-closed is the right disposition for a
    # gate — better to block a draft than ship an unchecked one.
    last_parse_error: str | None = None
    raw = ""
    for parse_attempt in range(JSON_PARSE_RETRY_BUDGET + 1):
        retry_suffix = ""
        if parse_attempt > 0 and last_parse_error is not None:
            retry_suffix = (
                "\n\n[JSON-output retry: the previous attempt did not return "
                "valid JSON. Return ONLY the JSON object specified above — "
                "no prose before or after, no markdown fences, no chain-of-"
                "thought. Include every material claim as an exact tweet substring "
                "with a supported kind, even when every claim passes. Never "
                "replace extraction with an empty pass response.]"
            )
        raw = _call_gemini(tweet, bundle, retry_suffix=retry_suffix)
        try:
            passed, llm_failures, llm_extracted = _parse_fact_check_json(
                raw,
                require_extracted_claims=True,
            )
            # A prior extractor is context, not permission for this checker to
            # omit its inventory. Each completed factual check owns its claims.
            canonical_claims = llm_extracted
            all_failures = list(llm_failures)
            all_failures.extend(material_span_failures(tweet, canonical_claims))
            all_failures.extend(_claim_reuse_failures(canonical_claims))
            return FactCheckResult(
                passed=passed and not all_failures,
                failures=all_failures,
                raw_response=raw,
                extracted_claims=canonical_claims,
            )
        except ModelOutputContractError as exc:
            return FactCheckResult(
                passed=False, failures=[f"Fact-check output contract rejected: {exc}"],
                raw_response=raw, extracted_claims=extracted,
            )
        except ValueError as exc:
            last_parse_error = str(exc)

    # Retry budget exhausted — fail-closed with a clear failures entry so
    # the suppression dashboard categorizes it as a fact_check stage kill
    # (not pipeline_error). The draft is blocked; the human-approval queue
    # never sees something the fact-checker couldn't read.
    return FactCheckResult(
        passed=False,
        failures=[
            f"fact-checker returned invalid JSON across "
            f"{JSON_PARSE_RETRY_BUDGET + 1} attempts: {last_parse_error}"
        ],
        raw_response=raw,
        extracted_claims=extracted,
    )
