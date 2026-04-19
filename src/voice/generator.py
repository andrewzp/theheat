from __future__ import annotations

"""Tweet generation via Gemini Flash with safety pipeline and fallback."""

import json
import os
import re
from datetime import date

from src.editorial.candidates import CandidateBundle, rank_candidates
from src.voice.safety import run_safety_pipeline
from src.voice import templates

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """\
You are @theheat, a climate data account that goes viral. Your tweets make \
people stop scrolling, feel something, and share. The data is already \
extraordinary. Your job is to frame it so people FEEL the weight of the \
numbers — and look smart for sharing.

=== WHAT MAKES A TWEET VIRAL (not just informative) ===

1. HISTORICAL WEIGHT. The best context is a record. "Hottest since 1929" \
is instantly shareable. Even better: anchor the year to something human. \
"Last time it was this hot in Buenos Aires, the stock market hadn't \
crashed yet" — now the reader can FEEL how long ago that was. Use history \
to give the number weight: eras, events, inventions, lifetimes. The \
sharer looks cultured, not just informed.

2. REPLY BAIT. The best tweets make people want to add their take. A tweet \
that says everything leaves nothing to say. Leave a gap — an implication \
the reader finishes in their head. "The old record was from last year." \
doesn't say "climate change" but the reader thinks it. That's reply bait.

3. SOCIAL CURRENCY. The person retweeting should look smart and in-the-know. \
Give them a fact they will repeat at dinner. "That used to take a decade" \
is a fact people retell. Numbers alone don't get retold. Numbers with \
context do.

4. SCROLL-STOPPING OPENER. Surprise in the first 5-7 words. "Anchorage \
recorded 82F today." — the surprise IS the opener. The reader decides \
in half a second. If the first line sounds like a weather report, they're \
gone.

5. SHOW, NEVER TELL. Never add meta-commentary like "THIS IS SERIOUS", \
"this is rare", "EXTREME force", "catastrophic", "life-threatening", \
"HURRICANE-FORCE conditions." These are weather-service boilerplate. If \
you have to tell the reader it's important, you failed. Let the data land.

=== HARD RULES ===

- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- CAPS for emphasis, but sparingly. Not every tweet needs it.
- One tweet only. No thread markers.
- Never open with an agency name (NWS, NOAA, GDACS, USGS, etc.).
- Never use label:value format ("Severity: Severe", "Alert level: Red").
- Never use weather-service language: "HURRICANE-FORCE", "EXTREME force", \
"catastrophic", "life-threatening", "dangerous conditions". These are \
boilerplate that numbs instead of activating.
- Never state the date twice. Only mention the date if timing is the story.
- Never explain what an alert tier means. Assume the reader is smart.
- Never use bureaucratic suffixes (-26, -2026) in storm or event names.
- Open-Meteo records are provisional — use "forecast to" / "on pace", \
not "just broke."
- CO2 tweets must mention Mauna Loa and reference pre-industrial (280 ppm).
- Record tweets must mention when the old record was set.
- If you've already written about this event, use a DIFFERENT comparison \
or framing. Never repeat the same context line across multiple tweets \
about the same storm, record, or event.

=== VOICE ===

- Never preach, never political, never moralize.
- Never mock human suffering or trivialize death.
- No sports metaphors, gaming slang, or forced catchphrases.
- VARY YOUR STRUCTURE. The "Word. Word. Word." pattern is ONE tool — use \
it at most once per 10 tweets.

=== GOOD EXAMPLES ===

- "Phoenix just dropped 121F. NEW RECORD. The old one was from last year."
- "Buenos Aires hit 42.1C. That broke a 97-year record set in 1929. Last time it was this hot there, the Great Depression hadn't started."
- "Anchorage recorded 82F today. The average high for this date is 57F. Anchorage."
- "Delhi forecast to hit 48.2C today. If that holds, it breaks a record from 2014. There are 33 million people in this city."
- "CO2 this week at Mauna Loa: 436.2 ppm. Same week last year: 433.8. We added 2.4 ppm in a year. That used to take a decade."
- "Satellite picked up a 1,200 MW fire in Siberia. For reference, a large power plant is about 1,000 MW. Except it's a forest."
- "Tropical Cyclone SINLAKU just hit 178 mph. Strongest storm in the western Pacific since Haiyan in 2013."
- "Mississippi at Baton Rouge: 42.3ft. Flood stage is 35ft. The river doesn't care what month it is."
- "Arctic sea ice: 12.4 million sq km. Lowest for this date since satellite records began in 1979."
- "A tornado is on the ground in Orlando. In January. Radar-confirmed."
- "CO2 crossed 435 ppm at Mauna Loa. Pre-industrial was 280. We've added more CO2 since 1990 than in the previous 10,000 years."

=== BAD EXAMPLES ===

- "NWS issued a Severe Thunderstorm Warning for Buchanan, MO." [press-release opener]
- "Tropical Cyclone SINLAKU-26 is now a GDACS Red alert. 178 mph. THIS ONE IS SERIOUS." [jargon + telling + meta-commentary]
- "Flash Flood Warning for Kauai. Severity: Severe. April 10, 2026. It's April." [label:value + date twice]
- "CO2 is at 435 ppm at Mauna Loa this week." [pure information — no awe, no history, nothing to share]
- "These are HURRICANE-FORCE conditions." [weather-service boilerplate — numbs instead of activating]
- "Saipan: Extreme Wind Warning. This is issued for catastrophic, life-threatening winds." [explains the tier + weather-service language]
"""

MAX_RETRIES = 3
DEFAULT_CANDIDATE_COUNT = 4


def _fallback_candidates(fallback_fn=None, fallback_args=None, count: int = DEFAULT_CANDIDATE_COUNT) -> list[tuple[str, str]]:
    if fallback_fn is None:
        return []

    args = fallback_args or {}
    collected: list[tuple[str, str]] = []
    seen: set[str] = set()
    attempts = max(count * 4, 6)

    for _ in range(attempts):
        try:
            tweet = fallback_fn(**args)
        except Exception:
            break
        if not tweet:
            continue
        normalized = re.sub(r"\s+", " ", tweet).strip()
        if not normalized:
            continue
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        collected.append((normalized, "template"))
        if len(collected) >= count:
            break

    if not collected:
        try:
            tweet = fallback_fn(**args)
        except Exception:
            tweet = None
        if tweet:
            collected.append((re.sub(r"\s+", " ", tweet).strip(), "template"))

    return collected


def _parse_candidate_response(raw_text: str) -> list[str]:
    text = (raw_text or "").strip()
    if not text:
        return []

    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                parsed = parsed.get("candidates", [])
            if isinstance(parsed, list):
                return [str(item).strip().strip('"').strip("'") for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass

    candidates = []
    for line in text.splitlines():
        stripped = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line.strip())
        stripped = stripped.strip('"').strip("'")
        if stripped:
            candidates.append(stripped)
    return candidates


def generate_tweet_bundle(
    data_description: str,
    *,
    category: str,
    fallback_fn=None,
    fallback_args=None,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
) -> CandidateBundle | None:
    """Generate and rank multiple tweet candidates for the same signal."""
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_candidate(text: str, source: str) -> None:
        normalized = re.sub(r"\s+", " ", (text or "")).strip().strip('"').strip("'")
        if not normalized:
            return
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        candidates.append((normalized, source))

    client = None
    if GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"[generator] WARNING: Gemini client init failed ({e}) — using template fallback")
    else:
        print("[generator] WARNING: No GEMINI_API_KEY — using template fallback")

    if client is not None:
        for attempt in range(MAX_RETRIES):
            try:
                prompt = (
                    f"{SYSTEM_PROMPT}\n\n"
                    f"Write {candidate_count} DISTINCT tweet options about this data.\n"
                    "Each option must use the same facts but a different rhythm or framing.\n"
                    "Return only the options, one per line, with no numbering and no commentary.\n\n"
                    f"Data:\n{data_description}"
                )
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                parsed = _parse_candidate_response(response.text)
                accepted_this_attempt = 0
                for candidate in parsed:
                    passed, reason = run_safety_pipeline(candidate)
                    if passed:
                        before = len(candidates)
                        add_candidate(candidate, "gemini")
                        if len(candidates) > before:
                            accepted_this_attempt += 1
                    else:
                        print(f"[generator] Safety rejected candidate on attempt {attempt + 1}: {reason}")

                if len(candidates) >= candidate_count:
                    break
                if accepted_this_attempt == 0 and not parsed:
                    print(f"[generator] Gemini returned no parseable candidates on attempt {attempt + 1}")
            except Exception as e:
                print(f"[generator] Gemini attempt {attempt + 1} failed: {e}")

    if len(candidates) < max(candidate_count, 1):
        for candidate, source in _fallback_candidates(
            fallback_fn=fallback_fn,
            fallback_args=fallback_args,
            count=max(candidate_count - len(candidates), 1),
        ):
            add_candidate(candidate, source)

    if not candidates:
        return None

    bundle = rank_candidates(candidates, category)
    if not bundle or not bundle.candidates:
        return None

    # Second inference pass: virality evaluator (Claude Sonnet 4.6)
    # Returns None if the tweet isn't worth posting — evaluator kill = no draft.
    try:
        from src.editorial.evaluator import evaluate_and_polish

        result = evaluate_and_polish(bundle, data_description)
        if result is None:
            return None
        bundle = result
    except Exception as e:
        print(f"[generator] Evaluator import/call failed, using ranked bundle: {e}")

    return bundle


def generate_tweet(
    data_description: str,
    fallback_fn=None,
    fallback_args=None,
    *,
    category: str = "general",
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet using Gemini Flash with safety checks.

    Args:
        data_description: Structured description of the data point.
        fallback_fn: Template function to call if Gemini fails.
        fallback_args: Args for the fallback function.

    Returns:
        Best tweet text, or a full ranked bundle when ``return_bundle`` is True.
    """
    requested_count = candidate_count
    if not return_bundle and candidate_count == DEFAULT_CANDIDATE_COUNT:
        requested_count = 1

    bundle = generate_tweet_bundle(
        data_description,
        category=category,
        fallback_fn=fallback_fn,
        fallback_args=fallback_args,
        candidate_count=requested_count,
    )
    if return_bundle:
        return bundle
    return bundle.text if bundle else None


def generate_all_time_record_tweet(
    city: str,
    country: str,
    kind: str,
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    years_of_data: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about an all-time (within-archive) record.

    Honest framing: the archive is ~30 years, not "all time." Voice must
    reflect this. "Hottest in 30 years of data" not "hottest ever."
    """
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_record_c * 9 / 5 + 32, 1)
    direction = "hottest" if kind == "high" else "coldest"
    data = (
        f"Open-Meteo forecast {direction} reading for {city}, {country} today: "
        f"{temp_f}F ({new_temp_c}C). "
        f"If that holds, it would be the {direction} reading in "
        f"{years_of_data} years of archive data (since ~{date.today().year - years_of_data}). "
        f"Previous {direction} in that window: {old_f}F ({old_record_c}C), set in {old_record_year}. "
        f"Note: do NOT claim 'hottest ever' or 'all-time' — the archive only goes back "
        f"{years_of_data} years reliably. Frame honestly: 'hottest in {years_of_data} years of records' "
        f"or 'hottest since {old_record_year}'."
    )
    return generate_tweet(
        data,
        category="all_time_record",
        return_bundle=return_bundle,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_monthly_record_tweet(
    city: str,
    country: str,
    kind: str,
    month: int,
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    years_of_data: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a monthly-ever record.

    'Hottest April ever in Delhi' style — more specific than calendar-date,
    broader than all-time.
    """
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_record_c * 9 / 5 + 32, 1)
    month_name = ["", "January","February","March","April","May","June",
                  "July","August","September","October","November","December"][month]
    direction = "hottest" if kind == "high" else "coldest"
    data = (
        f"Open-Meteo forecast {direction} reading for {city}, {country} today: "
        f"{temp_f}F ({new_temp_c}C). "
        f"If that holds, it would be the {direction} {month_name} reading in "
        f"{years_of_data} years of archive data. "
        f"Previous {direction} {month_name} in that window: {old_f}F ({old_record_c}C) in {old_record_year}. "
        f"Frame honestly: 'hottest {month_name} since {old_record_year}' or "
        f"'hottest {month_name} in {years_of_data} years of records'."
    )
    return generate_tweet(
        data,
        category="monthly_record",
        return_bundle=return_bundle,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_anomaly_tweet(
    city: str,
    country: str,
    today_temp_c: float,
    historical_mean_c: float,
    anomaly_c: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a large temperature anomaly vs historical mean."""
    today_f = round(today_temp_c * 9 / 5 + 32, 1)
    mean_f = round(historical_mean_c * 9 / 5 + 32, 1)
    abs_anomaly = abs(anomaly_c)
    direction = "above" if anomaly_c >= 0 else "below"
    month_name = ["", "January","February","March","April","May","June",
                  "July","August","September","October","November","December"][date.today().month]
    data = (
        f"{city}, {country} today: {today_f}F ({today_temp_c}C). "
        f"Historical mean for {month_name}: {mean_f}F ({historical_mean_c}C). "
        f"That's {abs_anomaly:.1f}C {direction} normal. "
        f"A departure this large is inherently unusual — make the reader feel it."
    )
    return generate_tweet(
        data,
        category="anomaly",
        return_bundle=return_bundle,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": today_temp_c, "old_temp_c": historical_mean_c,
            "old_year": date.today().year,  # placeholder
        },
    )


def generate_record_streak_tweet(
    city: str,
    country: str,
    consecutive_days: int,
    peak_temp_c: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a multi-day record-breaking streak."""
    peak_f = round(peak_temp_c * 9 / 5 + 32, 1)
    data = (
        f"{city}, {country} has now broken its daily temperature record for "
        f"{consecutive_days} consecutive days. "
        f"Peak reading during the streak: {peak_f}F ({peak_temp_c}C). "
        f"This is a story arc — the streak itself is the headline, not the number. "
        f"Spell out the count for emphasis if appropriate."
    )
    return generate_tweet(
        data,
        category="record_streak",
        return_bundle=return_bundle,
        fallback_fn=None,
        fallback_args={},
    )


def generate_simultaneous_records_tweet(
    city_names: list[str],
    countries: list[str],
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate ONE summary tweet when many cities broke records same day."""
    count = len(city_names)
    sample = city_names[:8]  # cap at 8 names for tweet length
    sample_str = ". ".join(sample) + "."
    data = (
        f"On this date, {count} cities broke their daily temperature records. "
        f"Sample: {sample_str} "
        f"This is a pattern signal — multiple simultaneous records tell a bigger story "
        f"than any single city. Lead with the count and the pattern, not any single city."
    )
    return generate_tweet(
        data,
        category="simultaneous_records",
        return_bundle=return_bundle,
        fallback_fn=None,
        fallback_args={},
    )


def generate_record_tweet(
    city: str,
    country: str,
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_record_c * 9 / 5 + 32, 1)
    data = (
        f"Open-Meteo forecast high for {city}, {country} today is {temp_f}F ({new_temp_c}C). "
        f"If that holds, it would beat the previous record for this calendar date: "
        f"{old_f}F ({old_record_c}C), set in {old_record_year}."
    )
    return generate_tweet(
        data,
        category="record",
        return_bundle=return_bundle,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_fire_tweet(
    region: str,
    country: str,
    confidence: int,
    frp: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    data = (
        f"Large wildfire detected in {region}, {country}. "
        f"Satellite confidence: {confidence}%. "
        f"Fire Radiative Power: {frp:.0f} MW. "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d')}."
    )
    return generate_tweet(
        data,
        category="fire",
        return_bundle=return_bundle,
        fallback_fn=templates.fire_template,
        fallback_args={
            "region": region, "country": country,
            "confidence": confidence, "frp": frp,
        },
    )


def generate_co2_milestone_tweet(
    ppm_crossed: int,
    actual_ppm: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    data = (
        f"Daily CO2 reading at Mauna Loa: {actual_ppm} ppm. "
        f"This is the first time the daily reading has been above {ppm_crossed} ppm. "
        f"Pre-industrial CO2 was about 280 ppm."
    )
    return generate_tweet(
        data,
        category="co2_milestone",
        return_bundle=return_bundle,
        fallback_fn=templates.co2_milestone_template,
        fallback_args={"ppm": ppm_crossed, "actual": actual_ppm},
    )


def generate_noaa_confirmation_tweet(
    city: str,
    state: str,
    temp_f: float,
    record_date: str,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about NOAA confirming a temperature record."""
    data = (
        f"NOAA ACIS has officially confirmed: {city}, {state} broke the temperature "
        f"record on {record_date}. The recorded high was {temp_f}F."
    )
    return generate_tweet(
        data,
        category="record_confirmation",
        return_bundle=return_bundle,
        fallback_fn=templates.noaa_confirmation_template,
        fallback_args={
            "city": city, "state": state,
            "temp_f": temp_f, "date": record_date,
        },
    )


def generate_severe_weather_tweet(
    event_type: str,
    area: str,
    severity: str,
    *,
    description: str = "",
    max_wind_gust: str = "",
    max_hail_size: str = "",
    tornado_detection: str = "",
    already_drafted: list[str] | None = None,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a US severe weather alert (NWS).

    Only Emergency-tier and hurricane-related events reach this function.
    Rich parameters (wind gust, hail, tornado detection) help the model
    write something specific instead of parroting the alert name.
    """
    today = __import__('datetime').date.today()
    parts = [f"Event: {event_type} active in {area}."]
    if tornado_detection:
        parts.append(f"Tornado detection: {tornado_detection} (e.g. radar-indicated vs spotter-observed).")
    if max_wind_gust:
        parts.append(f"Max wind gust in the warning: {max_wind_gust}.")
    if max_hail_size:
        parts.append(f"Max hail size in the warning: {max_hail_size} inches.")
    if description:
        parts.append(f"NWS narrative (use facts, ignore boilerplate): {description}")
    parts.append(f"Today's date is {today.strftime('%B %d')}.")
    if already_drafted:
        parts.append("PREVIOUS TWEETS about this event (DO NOT repeat the same comparison or framing):")
        for prev in already_drafted:
            parts.append(f'  - "{prev}"')
        parts.append("You MUST use a completely different angle, comparison, or context line.")
    data = " ".join(parts)
    return generate_tweet(
        data,
        category="severe_weather",
        return_bundle=return_bundle,
        fallback_fn=templates.severe_weather_template,
        fallback_args={
            "event_type": event_type, "area": area,
        },
    )


def generate_global_disaster_tweet(
    disaster_type: str,
    name: str,
    country: str,
    severity: str,
    description: str,
    *,
    severity_value: float = 0.0,
    severity_unit: str = "",
    alert_score: float = 0.0,
    population_affected: int = 0,
    already_drafted: list[str] | None = None,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a global disaster event (GDACS).

    Only Red-tier events reach this function.
    """
    parts = [f"Event: {disaster_type} {name} in {country}. GDACS {severity}-tier alert."]
    if severity_value and severity_unit:
        if disaster_type == "Tropical Cyclone":
            # Convert km/h to mph for US audience
            mph = round(severity_value * 0.621, 0)
            parts.append(
                f"Sustained wind speed: {severity_value:.0f} {severity_unit} "
                f"(about {mph:.0f} mph)."
            )
        elif disaster_type == "Earthquake":
            parts.append(f"Magnitude: {severity_value:.1f}.")
        else:
            parts.append(f"Intensity: {severity_value:.1f} {severity_unit}.")
    if alert_score:
        parts.append(f"GDACS alert score: {alert_score:.1f} (higher = worse).")
    if population_affected:
        parts.append(f"Estimated population affected: {population_affected:,}.")
    if description:
        parts.append(f"Description (use facts, not boilerplate): {description[:400]}")
    if already_drafted:
        parts.append("PREVIOUS TWEETS about this event (DO NOT repeat the same comparison or framing):")
        for prev in already_drafted:
            parts.append(f'  - "{prev}"')
        parts.append("You MUST use a completely different angle, comparison, or context line.")
    data = " ".join(parts)
    return generate_tweet(
        data,
        category="global_disaster",
        return_bundle=return_bundle,
        fallback_fn=templates.global_disaster_template,
        fallback_args={
            "disaster_type": disaster_type, "name": name,
            "country": country, "severity": severity,
        },
    )


def generate_sea_ice_record_tweet(
    hemisphere: str,
    extent: float,
    previous_extent: float,
    previous_year: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a sea ice extent record."""
    data = (
        f"{hemisphere} sea ice extent: {extent} million sq km. "
        f"This is the lowest for this calendar date since satellite records began in 1979. "
        f"Previous record: {previous_extent} million sq km, set in {previous_year}."
    )
    return generate_tweet(
        data,
        category="sea_ice_record",
        return_bundle=return_bundle,
        fallback_fn=templates.sea_ice_record_template,
        fallback_args={
            "hemisphere": hemisphere, "extent": extent,
            "previous_extent": previous_extent, "previous_year": previous_year,
        },
    )


def generate_drought_tweet(
    states: list,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about drought conditions."""
    top = states[:3]
    lines = []
    for s in top:
        name = s.state if hasattr(s, "state") else s["state"]
        d3 = s.d3_pct if hasattr(s, "d3_pct") else s["d3_pct"]
        d4 = s.d4_pct if hasattr(s, "d4_pct") else s["d4_pct"]
        lines.append(f"{name}: {d3 + d4:.0f}% extreme/exceptional drought")
    data = (
        f"US Drought Monitor update. Worst drought conditions this week:\n"
        + "\n".join(lines)
    )
    return generate_tweet(
        data,
        category="drought",
        return_bundle=return_bundle,
        fallback_fn=templates.drought_template,
        fallback_args={"states": top},
    )


def generate_enso_tweet(
    to_status: str,
    oni_value: float,
    previous_duration: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about an ENSO state transition."""
    data = (
        f"NOAA declares {to_status} conditions. "
        f"Oceanic Nino Index: {oni_value:+.1f}. "
        f"Previous phase lasted {previous_duration} months."
    )
    return generate_tweet(
        data,
        category="enso",
        return_bundle=return_bundle,
        fallback_fn=templates.enso_template,
        fallback_args={
            "status": to_status, "oni": oni_value,
            "duration": previous_duration,
        },
    )


def generate_record_low_tweet(
    city: str,
    country: str,
    new_temp_c: float,
    old_record_c: float,
    old_record_year: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a record low temperature."""
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_record_c * 9 / 5 + 32, 1)
    data = (
        f"Open-Meteo forecast low for {city}, {country} tonight is {temp_f}F ({new_temp_c}C). "
        f"If that verifies, it would break the previous record low for this calendar date: "
        f"{old_f}F ({old_record_c}C), set in {old_record_year}. "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d')}."
    )
    return generate_tweet(
        data,
        category="record_low",
        return_bundle=return_bundle,
        fallback_fn=templates.record_low_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_extreme_wave_tweet(
    location: str,
    ocean: str,
    wave_height_m: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about extreme ocean wave heights."""
    wave_ft = round(wave_height_m * 3.281, 0)
    data = (
        f"Extreme wave event in the {location} ({ocean} Ocean). "
        f"Max significant wave height: {wave_height_m:.1f} meters ({wave_ft:.0f} feet). "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d, %Y')}."
    )
    return generate_tweet(
        data,
        category="extreme_wave",
        return_bundle=return_bundle,
        fallback_fn=templates.extreme_wave_template,
        fallback_args={
            "location": location, "ocean": ocean,
            "wave_height_m": wave_height_m,
        },
    )


def generate_storm_surge_tweet(
    station_name: str,
    state: str,
    anomaly_m: float,
    observed_m: float,
    predicted_m: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a storm surge / abnormal water level."""
    anomaly_ft = round(anomaly_m * 3.281, 1)
    data = (
        f"NOAA tide gauge at {station_name} ({state}): water level is "
        f"{anomaly_ft}ft ({anomaly_m:.2f}m) above predicted. "
        f"Observed: {observed_m:.2f}m. Predicted: {predicted_m:.2f}m. "
        f"This indicates storm surge or abnormal tidal conditions."
    )
    return generate_tweet(
        data,
        category="storm_surge",
        return_bundle=return_bundle,
        fallback_fn=templates.storm_surge_template,
        fallback_args={
            "station": station_name, "state": state,
            "anomaly_m": anomaly_m, "observed_m": observed_m,
        },
    )


def generate_river_flood_tweet(
    river: str,
    location: str,
    gauge_height_ft: float,
    flood_stage_ft: float,
    above_by_ft: float,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a river above flood stage."""
    data = (
        f"USGS gauge: {river} at {location} is at {gauge_height_ft:.1f}ft. "
        f"Flood stage is {flood_stage_ft:.0f}ft. "
        f"Currently {above_by_ft:.1f}ft above flood stage."
    )
    return generate_tweet(
        data,
        category="river_flood",
        return_bundle=return_bundle,
        fallback_fn=templates.river_flood_template,
        fallback_args={
            "river": river, "location": location,
            "gauge_ft": gauge_height_ft, "flood_stage_ft": flood_stage_ft,
            "above_ft": above_by_ft,
        },
    )
