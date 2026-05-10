from __future__ import annotations

"""Two-layer safety pipeline for generated tweets."""

import os
import re

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Safety LLM model ID. Same env-driven config as the generator — can be
# pointed at a different variant if the safety check needs more or less
# capacity than the generator. Default matches the generator default.
GEMINI_SAFETY_MODEL = os.environ.get(
    "GEMINI_SAFETY_MODEL",
    os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
)

MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)

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
    # Old voice patterns — prevent Gemini from reverting
    re.compile(r"career high", re.IGNORECASE),
    re.compile(r"unguardable", re.IGNORECASE),
    re.compile(r"\bcooked\b", re.IGNORECASE),
    re.compile(r"\brekt\b", re.IGNORECASE),
    re.compile(r"speed.?running", re.IGNORECASE),
    re.compile(r"drug test", re.IGNORECASE),
    re.compile(r"retire the jersey", re.IGNORECASE),
    re.compile(r"\brookie", re.IGNORECASE),
    re.compile(r"debut performance", re.IGNORECASE),
    re.compile(r"congratulations to no one", re.IGNORECASE),
    re.compile(r"nobody asked", re.IGNORECASE),
    # Press-release openers — never start a tweet with agency name
    re.compile(r"^(NWS|NOAA|GDACS|USGS|NSIDC|NASA|FEMA)\b", re.IGNORECASE),
    re.compile(r"^A (NWS|NOAA|GDACS)\b", re.IGNORECASE),
    re.compile(r"^An? \w+ (issued|warning|alert) (by|from)", re.IGNORECASE),
    # Label:value phrasing — never press-release format
    re.compile(r"\bSeverity:\s*(Severe|Extreme|Moderate|Minor|Red|Orange|Green)\b", re.IGNORECASE),
    re.compile(r"\bAlert [Ll]evel:\s*(Red|Orange|Green)\b"),
    re.compile(r"\bConfidence:\s*(HIGH|MEDIUM|LOW|Nominal)\b"),
    # Redundant explainers that kill the punch
    re.compile(r"highest (severity )?level [A-Z]+ issues?", re.IGNORECASE),
    re.compile(r"the highest (possible )?(alert|severity|warning) (tier|level)", re.IGNORECASE),
    # Tell-don't-show meta-commentary — if you have to say it, you failed
    re.compile(r"THIS (ONE )?IS SERIOUS", re.IGNORECASE),
    re.compile(r"this is not a drill", re.IGNORECASE),
    re.compile(r"pay attention", re.IGNORECASE),
    re.compile(r"you should be (worried|concerned|scared)", re.IGNORECASE),
    re.compile(r"this is (extremely )?rare", re.IGNORECASE),
    re.compile(r"you (only|might) see \w+ of these", re.IGNORECASE),
    # Weather-service boilerplate — numbs instead of activating
    re.compile(r"HURRICANE.FORCE", re.IGNORECASE),
    re.compile(r"EXTREME force", re.IGNORECASE),
    re.compile(r"\bcatastrophic\b", re.IGNORECASE),
    re.compile(r"life.threatening", re.IGNORECASE),
    re.compile(r"dangerous conditions", re.IGNORECASE),
    re.compile(r"\bextreme wind warning\b", re.IGNORECASE),
    # Bureaucratic noise in event names
    re.compile(r"-\d{2,4}\b"),  # -26, -2026 suffixes
    # Fabricated temporal/seasonal/biological context — primary defense is the
    # writer prompt's HARD RULES bullet ("NO FABRICATED CONTEXT") in
    # src/two_bot/prompts/writer_prompt.py. These regexes are the fail-safe
    # if the writer disobeys (model swap, retraining, prompt drift). Each
    # phrase below is one of the verbatim examples called out in the prompt
    # and was a confirmed fact-check kill in production prior to PR #50.
    re.compile(r"three weeks into meteorological spring", re.IGNORECASE),
    re.compile(r"\bJanuary reading\b", re.IGNORECASE),
    re.compile(r"flowers are already up", re.IGNORECASE),
    re.compile(r"the ground froze", re.IGNORECASE),
    re.compile(r"fruit trees blooming early", re.IGNORECASE),
]


def check_truncated_temperature(tweet: str) -> tuple[bool, str | None]:
    """Flag tweets with suspiciously low temperature readings.

    Gemini sometimes drops the leading digit: "1F forecast for Singapore"
    when it should be "91F". A real weather record tweet will never have
    single-digit F or sub-10C temperatures — those aren't records, they're
    errors. Rejects tweets that start with or prominently feature a
    standalone 1-digit temperature.
    """
    # Standalone 1-digit Fahrenheit near the start of the tweet, not preceded
    # by another digit (so "91F" passes, "1F" fails).
    if re.match(r"^\s*\d(?:F\b|C\b)", tweet):
        return False, "Tweet starts with a 1-digit temperature (likely truncated)"
    # Also catch "hit 2F" style mid-sentence after a common verb
    if re.search(r"\b(hit|forecast|forecast to hit|reached|at|record|dropped) \dF\b", tweet):
        return False, "Truncated temperature (single digit F) after a temperature verb"
    if re.search(r"\b(hit|forecast|forecast to hit|reached|at|record|dropped) \dC\b", tweet):
        return False, "Truncated temperature (single digit C) after a temperature verb"
    return True, None


def check_month_repetition(tweet: str) -> tuple[bool, str | None]:
    """Flag tweets that mention the same month twice in close proximity.

    Catches failures like:
      "NWS issued a Tropical Storm Warning. April 10, 2026. It's April."
    """
    lowered = tweet.lower()
    for month in MONTHS:
        # Count occurrences of the month word, ignoring it appearing inside a longer word.
        count = len(re.findall(rf"\b{month}\b", lowered))
        if count >= 2:
            return False, f"Month '{month}' mentioned {count} times — redundant date"
    return True, None


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
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = (
            "You are a content safety reviewer for a climate data Twitter bot. "
            "The bot uses dark humor but must never mock human suffering, trivialize "
            "death or injury, or cross from dry wit into cruelty.\n\n"
            f"Tweet to review:\n\"{tweet}\"\n\n"
            "Does this tweet mock human suffering, trivialize death, or cross from "
            "dark humor into cruelty? Answer only YES or NO."
        )

        response = client.models.generate_content(
            model=GEMINI_SAFETY_MODEL,
            contents=prompt,
        )
        # response.text is Optional — empty answer routes to NO (allow through;
        # regex pipeline already did the deterministic gating).
        answer = (response.text or "").strip().upper()

        if answer.startswith("YES"):
            return False, "LLM flagged as potentially harmful"
        return True, None

    except Exception as e:
        # If LLM check fails, allow the tweet through (regex already passed)
        print(f"[safety] LLM safety check failed, falling back to regex only: {e}")
        return True, None


def run_safety_pipeline(tweet: str) -> tuple[bool, str | None]:
    """Run both safety layers. Returns (passed, reason)."""
    # Layer 1a: Regex — banned tokens, press-release openers, label:value
    passed, reason = check_regex(tweet)
    if not passed:
        return False, reason

    # Layer 1b: Structural — repeated dates, etc.
    passed, reason = check_month_repetition(tweet)
    if not passed:
        return False, reason

    # Layer 1c: Data integrity — truncated temperatures from Gemini
    passed, reason = check_truncated_temperature(tweet)
    if not passed:
        return False, reason

    # Layer 2: LLM
    passed, reason = check_llm(tweet)
    if not passed:
        return False, reason

    return True, None
