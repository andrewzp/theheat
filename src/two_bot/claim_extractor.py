"""Stage 3.5: extract concrete claims from the writer's tweet text."""

from __future__ import annotations

import json
import os

from src.config import CHEAP_MODEL
from src.two_bot.json_utils import loads_model_json
from src.two_bot.prompts.claim_extract_prompt import (
    CLAIM_EXTRACT_SYSTEM_PROMPT,
    CLAIM_EXTRACT_USER_PROMPT_TEMPLATE,
)
from src.two_bot.retry import call_with_retries
from src.two_bot.types import ExtractedClaim

CLAIM_EXTRACT_MODEL = os.environ.get("THEHEAT_CLAIM_EXTRACT_MODEL", CHEAP_MODEL)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
JSON_PARSE_RETRY_BUDGET = 1
_VALID_KINDS = {
    "number",
    "date",
    "named_entity",
    "comparison",
    "era_anchor",
    "peer_comparison",
}


def _parse_claims_json(raw: str) -> list[ExtractedClaim]:
    """Parse the claim-extractor's JSON list.

    Unknown ``kind`` values are SKIPPED (with a warning), not raised. See
    fact_check._parse_extracted_claims for the rationale — the model
    sometimes invents a generic kind like "factual_assertion" not in the
    prompt's enumerated list, and dropping that single claim is the right
    failure mode rather than killing the whole response.
    """
    try:
        parsed = loads_model_json(raw, expected="array")
    except json.JSONDecodeError as exc:
        print(f"[two_bot.claim_extractor] Invalid JSON response: {raw}")
        raise ValueError("Claim extractor returned invalid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("Claim extractor response must be a JSON list")

    claims: list[ExtractedClaim] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Claim extractor item must be a JSON object")
        text = item.get("text")
        kind = item.get("kind")
        if not isinstance(text, str) or not isinstance(kind, str):
            raise ValueError("Claim extractor item must include text and kind strings")
        if kind not in _VALID_KINDS:
            print(
                f"[two_bot.claim_extractor] dropping claim with unsupported "
                f"kind={kind!r}; valid kinds: {sorted(_VALID_KINDS)}"
            )
            continue
        claims.append(ExtractedClaim(text=text, kind=kind))
    return claims


def _call_gemini(tweet: str, *, retry_suffix: str = "") -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for claim extraction")
    from google import genai
    from google.genai import types as genai_types

    # google-genai HttpOptions.timeout is in MILLISECONDS — see fact_check.py.
    # Without an explicit timeout, the SDK passes None through, which is
    # unbounded per-request and a real hang risk on a stuck Gemini call.
    # 90000 = 90 seconds, parity with fact_check.
    client = genai.Client(
        api_key=api_key,
        http_options=genai_types.HttpOptions(timeout=90000),
    )
    user_prompt = CLAIM_EXTRACT_USER_PROMPT_TEMPLATE.format(tweet=tweet)
    if retry_suffix:
        user_prompt = f"{user_prompt}{retry_suffix}"
    response = call_with_retries(
        "gemini claim extraction",
        lambda: client.models.generate_content(
            model=CLAIM_EXTRACT_MODEL,
            contents=f"{CLAIM_EXTRACT_SYSTEM_PROMPT}\n\n{user_prompt}",
        ),
    )
    # google-genai's response.text is Optional — empty when no candidates
    # come back. Empty string falls through to the JSON parser as a
    # parse error, which the caller handles consistently with other
    # API failure modes.
    return response.text or ""


def extract_claims(tweet: str) -> list[ExtractedClaim]:
    """Extract concrete claims from tweet text via Gemini Flash."""

    last_parse_error: str | None = None
    for parse_attempt in range(JSON_PARSE_RETRY_BUDGET + 1):
        retry_suffix = ""
        if parse_attempt > 0 and last_parse_error is not None:
            retry_suffix = (
                "\n\n[JSON-output retry: the previous attempt did not return "
                "valid JSON. Return ONLY the JSON array specified above — "
                "no prose before or after, no markdown fences, no chain-of-"
                "thought. Use [] only when the tweet contains no concrete claims.]"
            )
        raw = _call_gemini(tweet, retry_suffix=retry_suffix)
        try:
            return _parse_claims_json(raw)
        except ValueError as exc:
            last_parse_error = str(exc)

    raise ValueError(
        f"claim extractor returned invalid JSON across "
        f"{JSON_PARSE_RETRY_BUDGET + 1} attempts: {last_parse_error}"
    )
