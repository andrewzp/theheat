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
    re.compile(r"\bdeadly\b", re.IGNORECASE),
    re.compile(r"\bkiller\b", re.IGNORECASE),
    re.compile(r"\bmonster storm\b", re.IGNORECASE),
    re.compile(r"historic devastation", re.IGNORECASE),
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
    single-digit F temperatures — those aren't credible record-heat values
    for this bot and have repeatedly meant the writer dropped a leading digit.
    Single-digit C can be valid for cold-record drafts, so Celsius is left for
    the bundle fact-checker instead of being killed by this text-only guard.
    """
    # Standalone 1-digit Fahrenheit near the start of the tweet, not preceded
    # by another digit (so "91F" passes, "1F" fails).
    if re.match(r"^\s*\dF\b", tweet):
        return False, "Tweet starts with a 1-digit temperature (likely truncated)"
    # Also catch "hit 2F" style mid-sentence after a common verb
    if re.search(r"\b(hit|forecast|forecast to hit|reached|at|record|dropped) \dF\b", tweet):
        return False, "Truncated temperature (single digit F) after a temperature verb"
    return True, None


_MONTHS_PATTERN = "|".join(MONTHS)

# Bureaucratic date-restatement patterns. The earlier blanket "count >= 2"
# rule false-positived on the now-standard monthly_low/high tweet shape
# ("hit X on May 4 — new May cold record in N years") where the month is
# load-bearing twice: once as a date, once as the record class.
_REDUNDANT_DATE_PATTERNS = [
    # "It's April." — standalone restatement after the date is already on screen.
    # The original failure mode that motivated this gate.
    #
    # Apostrophe is REQUIRED (straight or curly). Without it, the pattern
    # also matches the possessive "its May" — which is legitimate voice in
    # phrasings like "Phoenix broke its May record by 2°F" (Codex review of
    # PR #67 flagged this false positive).
    re.compile(rf"\bit[’']s ({_MONTHS_PATTERN})\b\.?", re.IGNORECASE),
    # "April 2026. April" — year-anchored restatement. Catches the variant
    # where the writer says the full date and then opens the next sentence
    # with the same month for no reason.
    #
    # The second occurrence is a BACKREFERENCE to the first month, so this
    # only fires when the same month repeats. "April 2026. May records..."
    # is a legitimate cross-month comparison and must pass (Codex review of
    # PR #67 flagged this false positive).
    re.compile(
        rf"\b({_MONTHS_PATTERN})\s+\d{{4}}\.\s+\1\b",
        re.IGNORECASE,
    ),
]


def check_month_repetition(tweet: str) -> tuple[bool, str | None]:
    """Flag tweets that bureaucratically restate the date.

    Targets the original failure mode where the writer prints a full date
    and then redundantly re-states the month as standalone padding:
      "NWS issued a Tropical Storm Warning. April 10, 2026. It's April."

    Does NOT fail on legitimate two-time mentions where the month appears
    once as a date and once as the record class — the now-standard shape
    for monthly_low / monthly_high signals:
      "Sissonville hit 28°F on May 4 — coldest May night in 16 years"

    Safety net: any single month appearing 4+ times is padding regardless
    of context.
    """
    for pattern in _REDUNDANT_DATE_PATTERNS:
        match = pattern.search(tweet)
        if match:
            return False, f"Redundant date restatement: {match.group()!r}"

    lowered = tweet.lower()
    for month in MONTHS:
        count = len(re.findall(rf"\b{month}\b", lowered))
        if count >= 4:
            return False, f"Month '{month}' mentioned {count} times — padding"
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
