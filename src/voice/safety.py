from __future__ import annotations

"""Two-layer safety pipeline for generated tweets."""

import os
import re

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Layer 1: Deterministic regex patterns
BANNED_PATTERNS = [
    re.compile(r"[\U0001F600-\U0001F64F]"),  # Emoticons
    re.compile(r"[\U0001F300-\U0001F5FF]"),  # Symbols & pictographs
    re.compile(r"[\U0001F680-\U0001F6FF]"),  # Transport & map
    re.compile(r"[\U0001F900-\U0001F9FF]"),  # Supplemental symbols
    re.compile(r"[\U00002702-\U000027B0]"),  # Dingbats
    re.compile(r"#\w+"),                       # Hashtags
    re.compile(r"^BREAKING:", re.IGNORECASE),  # BREAKING prefix
    re.compile(r"!"),                          # Exclamation marks
    re.compile(r"we need to", re.IGNORECASE),  # Policy opinions
    re.compile(r"we must", re.IGNORECASE),
    re.compile(r"governments? (must|should|need)", re.IGNORECASE),
    re.compile(r"take action", re.IGNORECASE),
    re.compile(r"climate (denier|denial)", re.IGNORECASE),
    re.compile(r"wake up", re.IGNORECASE),
]


def check_regex(tweet: str) -> tuple[bool, str | None]:
    """Layer 1: Deterministic regex check. Returns (passed, reason)."""
    if len(tweet) > 280:
        return False, f"Too long: {len(tweet)} chars (max 280)"

    for pattern in BANNED_PATTERNS:
        match = pattern.search(tweet)
        if match:
            return False, f"Banned pattern: {match.group()!r}"

    return True, None


def check_llm(tweet: str) -> tuple[bool, str | None]:
    """Layer 2: LLM safety check via Gemini Flash. Returns (passed, reason)."""
    if not GEMINI_API_KEY:
        return True, None  # Skip if no API key

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = (
            "You are a content safety reviewer for a climate data Twitter bot. "
            "The bot uses dark humor but must never mock human suffering, trivialize "
            "death or injury, or cross from dry wit into cruelty.\n\n"
            f"Tweet to review:\n\"{tweet}\"\n\n"
            "Does this tweet mock human suffering, trivialize death, or cross from "
            "dark humor into cruelty? Answer only YES or NO."
        )

        response = model.generate_content(prompt)
        answer = response.text.strip().upper()

        if answer.startswith("YES"):
            return False, "LLM flagged as potentially harmful"
        return True, None

    except Exception:
        # If LLM check fails, allow the tweet through (regex already passed)
        return True, None


def run_safety_pipeline(tweet: str) -> tuple[bool, str | None]:
    """Run both safety layers. Returns (passed, reason)."""
    # Layer 1: Deterministic
    passed, reason = check_regex(tweet)
    if not passed:
        return False, reason

    # Layer 2: LLM
    passed, reason = check_llm(tweet)
    if not passed:
        return False, reason

    return True, None
