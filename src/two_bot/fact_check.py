"""Stage 4: deterministic reuse checks plus strict Gemini fact-checking."""

from __future__ import annotations

import json
import os

from src.two_bot import memory
from src.two_bot.prompts.fact_check_prompt import (
    FACT_CHECK_SYSTEM_PROMPT,
    FACT_CHECK_USER_PROMPT_TEMPLATE,
)
from src.two_bot.types import ExtractedClaim, FactCheckResult, StoryBundle

FACT_CHECKER_MODEL = os.environ.get("THEHEAT_FACT_CHECK_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


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


def _parse_fact_check_json(raw: str) -> tuple[bool, list[str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[two_bot.fact_check] Invalid JSON response: {raw}")
        raise ValueError("Fact-checker returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Fact-checker response must be a JSON object")
    if not isinstance(parsed.get("passed"), bool):
        raise ValueError("Fact-checker response must include boolean passed")
    failures = parsed.get("failures", [])
    if not isinstance(failures, list):
        raise ValueError("Fact-checker failures must be a list")
    return parsed["passed"], [_format_failure(item) for item in failures]


def _call_gemini(tweet: str, bundle: StoryBundle) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for fact-checking")
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=90))
    user_prompt = FACT_CHECK_USER_PROMPT_TEMPLATE.format(
        tweet=tweet,
        bundle_json=json.dumps(bundle.to_dict(), sort_keys=True),
    )
    response = client.models.generate_content(
        model=FACT_CHECKER_MODEL,
        contents=f"{FACT_CHECK_SYSTEM_PROMPT}\n\n{user_prompt}",
    )
    return response.text


def fact_check(
    tweet: str,
    extracted: list[ExtractedClaim],
    bundle: StoryBundle,
    state: dict,
) -> FactCheckResult:
    """Run strict local reuse checks, then LLM verification."""

    failures: list[str] = []

    if memory.is_reuse(state, tweet, "tweet_text"):
        failures.append("reuse: tweet text duplicates shipped tweet")

    for claim in extracted:
        if claim.kind == "era_anchor" and memory.is_reuse(state, claim.text, "era_anchor"):
            failures.append(f"reuse: era anchor '{claim.text}' already used")
        if claim.kind == "peer_comparison" and memory.is_reuse(state, claim.text, "peer_comparison"):
            failures.append(f"reuse: peer comparison '{claim.text}' already used")

    if failures:
        return FactCheckResult(
            passed=False,
            failures=failures,
            raw_response="(local reuse checks)",
            extracted_claims=extracted,
        )

    raw = _call_gemini(tweet, bundle)
    passed, llm_failures = _parse_fact_check_json(raw)
    return FactCheckResult(
        passed=passed,
        failures=llm_failures,
        raw_response=raw,
        extracted_claims=extracted,
    )

