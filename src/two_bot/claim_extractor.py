"""Stage 3.5: extract concrete claims from the writer's tweet text."""

from __future__ import annotations

import json
import os

from src.two_bot.prompts.claim_extract_prompt import (
    CLAIM_EXTRACT_SYSTEM_PROMPT,
    CLAIM_EXTRACT_USER_PROMPT_TEMPLATE,
)
from src.two_bot.types import ExtractedClaim

CLAIM_EXTRACT_MODEL = os.environ.get("THEHEAT_CLAIM_EXTRACT_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_VALID_KINDS = {
    "number",
    "date",
    "named_entity",
    "comparison",
    "era_anchor",
    "peer_comparison",
}


def _parse_claims_json(raw: str) -> list[ExtractedClaim]:
    try:
        parsed = json.loads(raw)
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
            raise ValueError(f"Unsupported extracted claim kind: {kind}")
        claims.append(ExtractedClaim(text=text, kind=kind))
    return claims


def _call_gemini(tweet: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for claim extraction")
    from google import genai

    client = genai.Client(api_key=api_key)
    user_prompt = CLAIM_EXTRACT_USER_PROMPT_TEMPLATE.format(tweet=tweet)
    response = client.models.generate_content(
        model=CLAIM_EXTRACT_MODEL,
        contents=f"{CLAIM_EXTRACT_SYSTEM_PROMPT}\n\n{user_prompt}",
    )
    return response.text


def extract_claims(tweet: str) -> list[ExtractedClaim]:
    """Extract concrete claims from tweet text via Gemini Flash."""

    return _parse_claims_json(_call_gemini(tweet))

