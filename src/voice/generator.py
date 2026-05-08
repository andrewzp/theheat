from __future__ import annotations

"""Tweet generation via Gemini Flash with safety pipeline and fallback."""

import json
import os
import re
from datetime import date

from src.config import CHEAP_MODEL
from src.editorial.candidates import CandidateBundle, rank_candidates
from src.voice.safety import run_safety_pipeline
from src.voice import templates
from src.voice.era_anchors import pick_anchors

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Model ID for the candidate generator. Defaults to the centralized
# ``CHEAP_MODEL`` (currently ``gemini-2.5-flash``, the stable snapshot).
# Historically this was ``gemini-flash-latest`` — that alias rolled to
# Gemini 3 Flash Preview on or before 2026-05-02, which has high latency
# variance and consistently exceeded our 90s timeout under voice-gen
# workload (12K-char prompts asking for 4 candidates). Rolled back
# 2026-05-03. Set GEMINI_MODEL to a specific snapshot to A/B; do not
# point this at ``-latest`` aliases without re-validating timeouts and
# retry behavior.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", CHEAP_MODEL)
# Sonnet evaluator pass. Enabled by default — costs ~$25-45/mo on
# Sonnet 4.6 (verified against console.anthropic.com 2026-04-24).
# Set EVALUATOR_ENABLED=false as a kill switch when cost matters more
# than the auto-rewrite/score-and-reject pass.
EVALUATOR_ENABLED = os.environ.get("EVALUATOR_ENABLED", "true").lower() in {"1", "true", "yes"}

SYSTEM_PROMPT = """\
You are @theheat, a climate data account that goes viral. Your tweets make \
people stop scrolling, feel something, and share. The data is already \
extraordinary. Your job is to frame it so people FEEL the weight of the \
numbers — and look smart for sharing.

=== RULE #0 — DON'T SOUND LIKE YOU'RE TRYING ===

The data is already extraordinary. The voice is its straight man. The \
Wodehouse rule: trying too hard breaks the spell. Three failure modes \
flag a draft as trying too hard:

- Approximation when the exact number is available ("nearly 3 degrees" \
when it's 2.7F). Use the exact figure or omit the comparison.
- Restate-padding ("The new high: 94.5F. The old one: 93.7F.") after \
the data was already in the tweet. The reader has the numbers; restating \
them in slightly different form reads as showing your work.
- Poetry-attempt closers ("pointed at the sky", "the river doesn't \
know") inserted to add weight that the data already carries.

If the number alone is striking, deliver it plainly. The strongest \
A-grade drafts in the corpus often have no humor mechanic at all — \
just the data, set up cleanly.

=== WHAT MAKES A TWEET VIRAL (not just informative) ===

1. SPECIFICITY GIVES NUMBERS WEIGHT. "Hottest since 1929" is instantly \
shareable because the year is specific. The bot has multiple specificity \
vehicles — accelerating-warming framing ("set just last year in 2024"), \
past-tense personification ("used to define an entire season"), \
place-as-punchline (period-and-restate the city), absolute scale (let \
the number carry it alone), ecosystem context ("hot for a city at \
2,500m"), and era anchors (the year tied to a cultural moment). Era \
anchors are PARKED at 1-in-10 — the data prompt will tell you when it's \
your turn. Every other draft, pick one of the other vehicles. The \
strongest record drafts in the corpus often use NO specificity vehicle \
at all — when the number alone is striking, deliver the data plainly.

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
gone. Lead with the specific named place, not a continent.

5. SHOW THE DATA, DON'T TELL THE READER IT'S SERIOUS. Two specific \
families of language are banned because they NUMB instead of activate:

  (a) Weather-service boilerplate: "HURRICANE-FORCE conditions," "EXTREME \
force," "catastrophic," "life-threatening," "dangerous conditions." This \
is press-release filler. Every emergency alert uses it; readers tune out.

  (b) Tell-don't-show meta-commentary: "THIS IS SERIOUS," "this is not a \
drill," "pay attention," "you should be worried," "this is rare." If you \
have to tell the reader it's important, you failed.

  EARNED EDITORIAL HEAT IS ALLOWED. Words like "EXTRAORDINARY," "stunning," \
"wild," "Mind blowing," "unprecedented in the archive" — these are voice \
moves that AMPLIFY data the reader can already feel. Use them when the \
data backs them up: all-time records, country-archive records, ≥18°C \
anomalies, ≥5-day streaks. The @extremetemps account (the genre's \
successful operator) uses these regularly. Do not suppress earned weight. \
Do NOT use them on mid-tier signals — if every tweet uses "EXTRAORDINARY," \
none of them do.

=== HARD RULES ===

- Under 280 characters. No exceptions.
- No emojis. No hashtags. No exclamation points.
- CAPS for emphasis. ALL-CAPS openers are allowed and specifically \
recommended when the data warrants the highest tier of the genre. \
Don't suppress earned editorial weight. Reserve for elite signals.
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
- ORIENT THE READER GEOGRAPHICALLY. Most readers do not know where \
Conakry is, or Bishkek, or Yakutsk, or Manaus. If the named place is \
not a city any educated reader would instantly place on a globe \
(London, Tokyo, New York, Paris, Berlin, Sydney, Mumbai, Cairo, \
Moscow, Beijing, Shanghai, Mexico City, São Paulo, Buenos Aires, \
Hong Kong, Bangkok, Istanbul, Rome, Madrid, Toronto, LA, Chicago, \
Miami — and a small handful of similar globally-iconic names), \
include the country: "Conakry, Guinea" / "Yakutsk, Russia" / \
"Manaus, Brazil." This applies whether the place leads the tweet \
or appears mid-sentence. When in doubt, include the country. The \
cost of being slightly redundant is small; the cost of a reader not \
knowing where the event happened is total.

=== STOCK FORMULAS TO AVOID ===

These feel data-literate but they're stale. Every climate account uses \
them. Using them tells the reader "this was mass-produced."

- "Enough to power N homes." Stock formula. Generic energy conversion. \
The reader gains no real scale because N homes is still an abstraction.
- "A coal/nuclear power plant runs at N MW. This [fire/event] is X of \
that." Used faster than it ages. Also: the specific plant wattage \
drifts (150, 300, 600, 1000) based on what makes the math favorable, \
so readers notice the manipulation.
- "The fire has no name yet." / "It has no name yet." Most fires never \
get named. This closer implies a missing story beat that doesn't exist.
- "Location unknown." / "Somewhere in [continent]." If your data says \
Asia, pick the most specific sub-region you can ("the Kazakhstan steppe," \
"the Indonesian archipelago") — or don't write the tweet.
- "It is powering nothing." / "Loose in a field." / other rhetorical \
subversions of the power-plant comparison. If the comparison needs \
subverting, the comparison was wrong. Pick different scale.

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
- "A wildfire burning somewhere in Asia is radiating 220 MW — enough to power 220,000 homes." [continent-only location + stock homes formula]
- "A coal power plant produces about 150 MW. One is built to do that." [generic plant comparison + rhetorical subversion that adds nothing]
- "That gap is 4.5 degrees." [explicit-gap math the reader could do — soft Wodehouse violation. The data is already in the tweet; trust the reader to compute. Don't show your work.]
- "The new high: 94.5F. The old one: 93.7F." [restate-padding after the data was already given. Restating in slightly different form reads as the model showing its work and breaks the spell.]
- "The last time it was this hot, [era anchor]. That was [YEAR]. [Restate the data]." [era-anchor-then-restate is the most over-used record framing in our corpus. Era anchors are parked at 1 in 10; do not reach for one unless the data prompt tells you it's your turn.]
"""


# Shared specificity-vehicle menu for record-type categories. Era
# anchors became over-deployed (Apr 27 + Apr 29 corpora — every
# record draft used them) so they're parked at 1-in-10. The other
# vehicles below are equally valid; corpus references show which
# A-grade drafts each vehicle carried.
_RECORD_SPECIFICITY_VEHICLES = """\
Specificity vehicles available — pick whichever fits the data:

1. ACCELERATING-WARMING — "set just last year in 2024" / "Two hottest \
Aprils in the 30-year archive: back to back." Carries the climate \
argument without saying it. CORPUS REFERENCE: Navi Mumbai (A-, Apr 25).
2. PAST-TENSE PERSONIFICATION — "used to define an entire season" / \
"The bushfire season here used to know when to quit." Reframes what \
the number MEANS, not what it IS. CORPUS REFERENCES: Chicago anomaly \
(A-, Apr 24), NSW fire (A-, Apr 25).
3. PLACE-AS-PUNCHLINE — "Anchorage recorded 82F today. Average for this \
date is 57F. Anchorage." Period-and-restate when the city's identity \
is the joke. Works for cities with strong climate identity (Anchorage \
= cold, Reykjavik = cold, desert cities = hot, etc).
4. ABSOLUTE SCALE — "Kuwait City: 53.2C. That's 127.8F. Highest reading \
anywhere on Earth this year." Number does the work alone. No framing \
needed when the data is already extreme.
5. ECOSYSTEM CONTEXT — "The summer monsoon that extinguishes these \
fires is still weeks away." / "Hot for a city at 2,500m." Specific to \
the geography. Tells the reader why this number is more extreme than \
it appears at face value. CORPUS REFERENCE: Mexico highlands (B+, Apr 27).
6. ERA ANCHOR — PARKED. The bot uses this at most 1 in 10 record \
drafts. The system will tell you when it's your turn (look for "your \
1-in-10 era-anchor turn" in the data prompt). Every other draft, do \
NOT reach for an era anchor. Pick from 1-5 above.

None of these are mandatory. When the number alone is striking, deliver \
the data plainly — the corpus has multiple A-grade drafts (Medan B, \
Kuwait City absolute-scale moves) that use no specificity vehicle at \
all. Forced framing breaks the spell."""


# Category-specific addenda appended to SYSTEM_PROMPT when a signal
# type has voice characteristics the universal prompt doesn't cover
# well. Drawn from the 2026-04-24 corpus review (docs/DRAFT_CORPUS.md):
# each bullet points at a failure mode we observed in production.
_CATEGORY_PROMPTS: dict[str, str] = {
    "fire": """\
=== CATEGORY-SPECIFIC — WILDFIRE ===

Fires are the category most prone to template traps because they lack \
the clean "city + record number + year anchor" structure of temperature \
records. Defaults to AVOID (the 2026-04-24 corpus showed Gemini falling \
into these in 20+ drafts):

- Do NOT open with "Satellite just picked up..." or "A wildfire burning \
in [region] right now is radiating..." — throat-clearing. Lead with the \
named region.
- Do NOT reach for the power-plant comparison unless the fire is truly \
plant-scale (≥1,000 MW FRP). Below that it's a false equivalence the \
reader spots.
- Do NOT say "no name yet" — most fires never get named.

WHAT WORKS FOR FIRES:

- Lead with specific region/country in first 5–7 words ("Queensland's \
outback" / "The Kazakhstan steppe" / "Hawaii's Big Island"), not the MW.
- Seasonal twists land when the location has a clear fire calendar: \
"The continent's fire season normally begins in November." \
"It's April. Here, fire season ended in October."
- Landscape scale beats energy scale: "The burn scar is already larger \
than Manhattan." "Larger than last year's Big Sur fire."
- Rainfall/drought context when it frames the rarity: "The average \
rainfall there this month is 2.5 inches."
- One-idea tweets. Stack at most TWO facts — MW + seasonal twist, or \
region + scale. Three comparisons reads like sales copy.
- If you write a punchline, leave it alone. Don't pre-explain it ("for \
reference, a power plant runs at..."), don't post-explain it ("that's \
roughly one-eighth of that"), don't restate the data ("The new high: X. \
The old one: Y."). The data is the setup. The closer is the punchline. \
No math out loud.
""",
    "all_time_high": f"""\
=== CATEGORY-SPECIFIC — ALL-TIME ARCHIVE HIGH ===

This is an elite signal — don't waste the scroll.

{_RECORD_SPECIFICITY_VEHICLES}

Honest window: "30 years of archive data," not "ever" and not "all time."

Earned editorial heat is allowed and specifically recommended for this \
tier. ALL-CAPS openers like "EXTRAORDINARY heat" or weight words like \
"stunning," "wild," "Mind blowing" pair well when the data backs them up. \
This is the @extremetemps move and works in our genre.
""",
    "all_time_low": f"""\
=== CATEGORY-SPECIFIC — ALL-TIME ARCHIVE LOW ===

{_RECORD_SPECIFICITY_VEHICLES}

Honest 30-year window. Cold records are read differently from hot \
ones: they feel like climate-denial fodder unless framed with care. \
Lean on the "accelerating extremes in both directions" angle rather \
than "it's still cold somewhere."
""",
    "monthly_high": f"""\
=== CATEGORY-SPECIFIC — MONTHLY RECORD HIGH ===

The specific story is "normal has moved." Often the prior record was \
just years ago — accelerating-warming framing is the natural fit when \
the gap is small.

{_RECORD_SPECIFICITY_VEHICLES}

Avoid "hottest April ever." Say "hottest April in 30 years of archive \
data." If the prior record year IS the current year, don't even draft \
this (the same-year suppression filter should have caught it upstream).
""",
    "monthly_low": f"""\
=== CATEGORY-SPECIFIC — MONTHLY RECORD LOW ===

{_RECORD_SPECIFICITY_VEHICLES}

Honest 30-year window. Frame as "accelerating extremes in both \
directions" rather than "it's still cold somewhere" — cold records \
are easy to misread as climate-denial otherwise.
""",
    "anomaly_hot": """\
=== CATEGORY-SPECIFIC — HOT ANOMALY ===

The story is that the anomaly is absurd for this city's typical climate.\
 Lean into the city's identity — the place is the punchline:

- "Anchorage recorded 82F. Average high for this date is 57F. Anchorage."
- "That 29-degree jump used to define an entire season."

The period-and-restate move ("Anchorage.") is earned for anomaly drafts \
when the city has a strong temperature identity (Anchorage = cold; \
Reykjavik = cold; Siberian cities = cold; desert cities = hot).

For ≥18°C anomalies (extreme tier), earned editorial heat is allowed. \
"WILD heat in Reykjavik today." or "STUNNING anomaly — Anchorage at 82F" \
amplify the data when the magnitude warrants it. Reserve for the \
genuinely-absurd anomalies; if every anomaly tweet uses heat words, the \
heat words stop working.
""",
    "country_high": f"""\
=== CATEGORY-SPECIFIC — COUNTRY-LEVEL ARCHIVE HIGH ===

This is the biggest single-day story the pipeline produces: a country's \
hottest reading ever across every city we sample. Lead with the country \
and the stake, not the peak city.

- "France's hottest April day in 30 years of records" > "Marseille hit \
41.2C today, beating the archive max."
- Include the prior record's city + year for honesty.

{_RECORD_SPECIFICITY_VEHICLES}

This tier earns editorial heat. ALL-CAPS openers, "EXTRAORDINARY," \
"unprecedented in the archive" are allowed and amplify the data when \
used here. The @extremetemps genre uses these moves on country-tier \
signals — we should too.
""",
    "country_low": f"""\
=== CATEGORY-SPECIFIC — COUNTRY-LEVEL ARCHIVE LOW ===

A country's coldest reading anywhere across our sample. Lead with the \
country, not the peak city.

{_RECORD_SPECIFICITY_VEHICLES}

Frame as "accelerating extremes in both directions" rather than "it's \
still cold somewhere" — cold-side framing is easily misread.
""",
    "record": f"""\
=== CATEGORY-SPECIFIC — CALENDAR-DATE RECORD ===

Calendar-date records are the most common record type. Mid-tier — earned \
editorial heat (ALL-CAPS, "EXTRAORDINARY") is NOT appropriate here unless \
the gap or recency makes the record genuinely extraordinary. Most \
calendar-date records ship on quiet voice.

{_RECORD_SPECIFICITY_VEHICLES}

Open-Meteo records are provisional — use "forecast to" / "on pace", not \
"just broke."
""",
    "record_low": f"""\
=== CATEGORY-SPECIFIC — CALENDAR-DATE RECORD LOW ===

{_RECORD_SPECIFICITY_VEHICLES}

Frame as "accelerating extremes in both directions" rather than "it's \
still cold somewhere." Use "forecast to" / "on pace" — Open-Meteo lows \
are provisional.
""",
    "co2_milestone": """\
=== CATEGORY-SPECIFIC — CO2 MILESTONE ===

The story is the rate of change, not the number. Pre-industrial was 280. \
We cross ~2.5 ppm/year now; it took 10,000 years for the prior 100 ppm \
swing. Historical anchors for prior crossings are the move:

- "CO2 crossed 435 ppm. Pre-industrial was 280. We've added more CO2 \
since 1990 than in the previous 10,000 years."
""",
    "marine_heatwave": """\
=== CATEGORY-SPECIFIC — MARINE HEATWAVE ===

Global-mean SST records or streaks. The power: these are slow-moving, \
so when one fires, it's genuinely unprecedented in the archive. Lead \
with the streak count or the anomaly, not "the ocean is warm."

- "The global ocean just posted its hottest daily SST in 44 years of \
satellite records." Not "Ocean temperatures rise."
- Honest window: OISST starts 1982 — "44 years of satellite records," \
not "ever."
""",
    "ice_mass_record": """\
=== CATEGORY-SPECIFIC — ICE MASS RECORD ===

GRACE-FO monthly mass loss records for Greenland / Antarctica. The \
archive starts 2002 — "24 years of GRACE observations," not "ever." \
Lead with the quantity (gigatons) and the region. The scale is \
genuinely hard to grasp; don't try to make it relatable with \
"equivalent to X cubic miles" unless X is something the reader carries.

- Do NOT personify ("the ice is suffering" / "the glacier is dying"). \
Banned.
- Do use the trend: "20th consecutive month of above-average ice \
loss," "the largest monthly loss in the record."
""",
    "fire_footprint": """\
=== CATEGORY-SPECIFIC — FIRE FOOTPRINT (ACREAGE/HECTARES) ===

This is the GWIS/NIFC fire-complex signal — NOT the same as the raw \
FIRMS point detection. The unit is area burned, not energy.

- Lead with the complex name and the acreage. "The Dixie Complex has \
burned 213,000 hectares."
- Use scale anchors the reader carries: state size, city area, named \
prior fires.
- If the fire crossed a tier (20k → 50k → 100k etc.), name the tier \
crossing explicitly — that's the story beat for this draft.
""",
    "synthesis_fire_drought_heat": """\
=== CATEGORY-SPECIFIC — COMPOUND (FIRE × DROUGHT × HEAT) ===

The biggest story a single tweet can tell: three converging signals in \
one US state within 14 days. The compound IS the news. Don't chain \
claims without separators:

- "California: D4 drought, a 1,200 MW fire, and Sacramento broke a \
heat record. All in the last 10 days." (Period-separated cadence.)
- Do NOT invent causality ("heat caused the fire"). Stick to \
co-occurrence. Compound framing.
- Honest time range: "in the last 14 days," not "recently."
""",
    "simultaneous_records_roll_call": """\
=== CATEGORY-SPECIFIC — MULTI-STATION ROLL-CALL ===

The story: a cluster of stations all broke records the same day in \
the same country, AND the cluster spans low and high altitudes. The \
per-station list IS the story — readers process density faster than \
a single number when the density is the point.

- Open with the count and the country: "Six stations across Nepal \
broke their April records today." Or lead with the elevation hook: \
"Records from sea level to the Himalayan foothills today."
- Then list 3-5 stations with temperatures. Slash- or period-separated.
"Janakpur 26.8C / Dang 24.1C, 663m / Dhankuta 20.4C, 1192m"
- Surface elevation only when stations span low and high altitudes — \
that's the multi-station story. Otherwise elevation is noise.
- One closing line is fine, optional. "All on the same day."
- Do NOT add framing fluff ("This is unprecedented"). The list IS the \
framing.
- Stay under 280 chars. Drop stations before you drop temperatures.
""",
}


def _prompt_for_category(category: str | None) -> str:
    """Return SYSTEM_PROMPT plus any category-specific addendum.

    When ``category`` doesn't have a tailored addendum, falls back to
    the universal prompt. New categories should be added to
    ``_CATEGORY_PROMPTS`` rather than trying to grow SYSTEM_PROMPT with
    conditional logic — the universal rules should stay universal.
    """
    if not category:
        return SYSTEM_PROMPT
    addendum = _CATEGORY_PROMPTS.get(category)
    if not addendum:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n{addendum}"

# A timed-out call almost never succeeds on a retry — the workload is the
# same, the server-side latency is the same, and we just spent another 180s
# of CI minutes. One attempt; if it times out, fall through to the template
# fallback (which is good enough for non-extraordinary signals).
# Bumped down from 3 → 1 on 2026-05-03 after a stuck production run was
# traced to 3× retries on a slow Gemini 3 Preview call (4.5 minutes wasted
# per qualifying signal).
MAX_RETRIES = 1
DEFAULT_CANDIDATE_COUNT = 4


# Stock formulas the generator should never ship — the 2026-04-24
# corpus found Gemini falling into these faster than the system prompt
# could prevent. Regex-checked at parse time as a last-line defense.
# Each entry: (pattern, label). Patterns are case-insensitive.
_STOCK_FORMULA_PATTERNS: tuple[tuple[str, str], ...] = (
    # Homes-count: "enough to power 200,000 homes" and family. Up to 4
    # filler words between the verb and the target noun to catch
    # "roughly 150,000 average US homes" / "130,000 electric heaters."
    (
        r"(?:enough to (?:power|run)|power(?:s|ing)?)\s+(?:[\w,.\-]+\s+){1,5}?(?:homes?|houses?|heaters?)\b",
        "stock 'powers N homes' formula",
    ),
    # Generic power-plant comparison with no named plant. Catches "a coal
    # power plant runs at 1,000 MW" / "a typical coal plant" / "a
    # standard nuclear reactor runs at around 1,000 MW."
    (
        r"\b(?:a|an|the)\s+(?:typical|standard|average|large|small|usual|commercial|industrial|mid-sized|high-capacity)?\s*(?:coal|nuclear|gas|power)\s+(?:power\s+)?(?:plant|reactor)\s+(?:runs?|generates?|produces?|outputs?|delivers?)\s+(?:at\s+)?(?:about|around|roughly|approximately)?\s*\d",
        "generic power-plant comparison (no named plant)",
    ),
    # "The fire has no name yet" closer family.
    (
        r"\b(?:the\s+fire|it)\s+has\s+no\s+name\s+yet\b",
        "'no name yet' closer",
    ),
    # Continent-level location admissions.
    (
        r"\b(?:somewhere in (?:asia|africa|europe|south america|north america|the americas|oceania))\b|\blocation (?:is\s+)?(?:still\s+)?unknown\b",
        "continent-only location / location unknown admission",
    ),
    # Throat-clearing opener: "A [fire] burning/raging in [LOCATION]
    # right now is radiating/releasing/putting out N MW..." The 2026-04-24
    # corpus had 12 D/F drafts with this exact shape; the 2026-04-25 corpus
    # caught it returning in draft #7 (Mali dup) despite voice engine v2.
    # Issue: it buries the number behind throat-clearing prose. Lead with
    # the number or the named region instead.
    (
        r"^A\s+(?:wildfire|fire|storm|tornado|hurricane|cyclone|blizzard)\b"
        r"(?:[^.!?\n]*?)\s+is\s+(?:currently\s+|now\s+)?"
        r"(?:radiating|releasing|generating|putting\s+out|emitting|producing|pushing|spewing|pumping\s+out|throwing\s+off|sending\s+up)\b",
        "throat-clearing 'A [event] in [location] is radiating...' opener",
    ),
)


def _detect_stock_formula(text: str) -> str | None:
    """Return the name of the stock formula if ``text`` contains one.

    Last-line defense against template fatigue — when the system prompt
    fails to prevent a stock formula (Gemini leans on trained-in
    patterns even under explicit bans), this regex check at candidate
    parse time rejects the draft so the bot never sees it.
    """
    if not text:
        return None
    for pattern, label in _STOCK_FORMULA_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return None


_ERA_ANCHOR_GATE_RATE = 0.1
"""Fraction of record drafts that get curated era-anchor content. User
direction (2026-04-29): era anchors are parked at no more than 1 in 10
tweets after Apr 27 + Apr 29 corpora showed every record converging on
era-anchor framing ('it gets so old and lame'). The gate is the
structural enforcement; prose-only de-emphasis didn't hold."""


def _with_evaluator_verdict(bundle: CandidateBundle, verdict: object) -> CandidateBundle:
    verdict_payload = verdict.as_dict() if hasattr(verdict, "as_dict") else None
    return CandidateBundle(
        category=bundle.category,
        candidates=bundle.candidates,
        evaluator_verdict=verdict_payload,
        evaluator_used_rewrite=bool(
            bundle.candidates and bundle.candidates[0].source == "evaluator_rewrite"
        ),
    )


def _era_anchor_should_fire(seed_key: str, rate: float = _ERA_ANCHOR_GATE_RATE) -> bool:
    """Deterministic 1-in-10 gate. Same seed_key → same answer, so a
    given draft cycle is reproducible and testable. Across many
    seed_keys, fires at ``rate``.
    """
    import random as _random
    return _random.Random(seed_key).random() < rate


def _era_anchor_hint(year: int, seed_key: str, k: int = 4) -> str:
    """Return a prompt fragment for the writer about era-anchor framing.

    Two outputs depending on the 1-in-10 gate:

    - Gate FIRES (~10% of calls): curated era-anchor content for
      ``year``, framed as "this is your 1-in-10 turn." Reader (Gemini)
      may use one of the anchors OR pick a different specificity vehicle.
    - Gate SKIPS (~90% of calls): explicit steer-away message naming
      the alternative specificity vehicles. Tells Gemini NOT to invent
      a year-anchor framing for this draft.

    The 90% steer-away path is the policy enforcement. Without it,
    Gemini reaches for era anchors by default (Apr 27, Apr 29 corpora
    confirmed). With it, the writer must reach for accelerating-warming,
    past-tense personification, place-as-punchline, absolute scale, or
    ecosystem context instead.

    The seed should typically be ``f"{city}-{year}-{today_iso}"`` so
    repeated runs in the same cycle are stable, but different cities
    or days can fire independently.
    """
    if not _era_anchor_should_fire(seed_key):
        return (
            " Era anchors are parked: the bot uses them at most 1 per 10 "
            "tweets, and this draft is NOT your turn. Do NOT invent a "
            "year-anchor framing. Reach for one of these specificity "
            "vehicles instead: accelerating-warming framing ('set just "
            "last year in 2024'), past-tense personification ('used to "
            "define an entire season'), place-as-punchline (period-and-"
            "restate the city name when the city's identity is the "
            "joke), absolute scale (let the number carry it alone), or "
            "ecosystem context ('the monsoon that extinguishes these "
            "fires is still weeks away'). The strongest record drafts "
            "in the corpus use NO era anchor — let the data and framing "
            "land naturally."
        )

    anchors = pick_anchors(year, k=k, seed=seed_key)
    if not anchors:
        # Gate fired but no curated content for this year (year < 1995
        # or > coverage end). Caller's prompt degrades to no anchor; the
        # writer should pick a different vehicle for this specific draft.
        return ""
    bullets = "; ".join(anchors)
    return (
        f" This draft is your 1-in-10 era-anchor turn (year {year}). Era "
        f"anchors permitted here — use ONE of these natural cultural "
        f"references if it fits, OR still pick a different specificity "
        f"vehicle (accelerating-warming, past-tense personification, "
        f"place-as-punchline, absolute scale, ecosystem context). The "
        f"options for {year}: {bullets}."
    )


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
            from google.genai import types as genai_types

            # 180000ms = 180s. google-genai HttpOptions.timeout is in
            # MILLISECONDS, not seconds (confirmed 2026-05-08 against
            # googleapis/python-genai). Prior value of 180 meant 180ms,
            # which is enough time for a TLS handshake and not much else.
            # Voice-gen is dead code (slated for deletion) but fix the
            # unit-of-measure bug for parity in case it's ever re-imported.
            client = genai.Client(api_key=GEMINI_API_KEY, http_options=genai_types.HttpOptions(timeout=180000))
        except Exception as e:
            print(f"[generator] WARNING: Gemini client init failed ({e}) — using template fallback")
    else:
        print("[generator] WARNING: No GEMINI_API_KEY — using template fallback")

    if client is not None:
        prompt_head = _prompt_for_category(category)
        for attempt in range(MAX_RETRIES):
            try:
                prompt = (
                    f"{prompt_head}\n\n"
                    f"Write {candidate_count} DISTINCT tweet options about this data.\n"
                    "Each option must use the same facts but a different rhythm or framing.\n"
                    "Return only the options, one per line, with no numbering and no commentary.\n\n"
                    f"Data:\n{data_description}"
                )
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
                parsed = _parse_candidate_response(response.text)
                accepted_this_attempt = 0
                for candidate in parsed:
                    formula_reason = _detect_stock_formula(candidate)
                    if formula_reason:
                        print(f"[generator] Stock-formula rejected on attempt {attempt + 1}: {formula_reason}")
                        continue
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
    # Disabled by default (cost) — set EVALUATOR_ENABLED=true to re-enable.
    if EVALUATOR_ENABLED:
        try:
            from src.editorial.evaluator import evaluate_and_polish

            result, verdict = evaluate_and_polish(bundle, data_description)
            if result is None:
                return None
            bundle = _with_evaluator_verdict(result, verdict)
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
    anchor_hint = _era_anchor_hint(
        old_record_year,
        seed_key=f"{city}-{old_record_year}-{date.today().isoformat()}",
    )
    data = (
        f"Open-Meteo forecast {direction} reading for {city}, {country} today: "
        f"{temp_f}F ({new_temp_c}C). "
        f"If that holds, it would be the {direction} reading in "
        f"{years_of_data} years of archive data (since ~{date.today().year - years_of_data}). "
        f"Previous {direction} in that window: {old_f}F ({old_record_c}C), set in {old_record_year}. "
        f"Note: do NOT claim 'hottest ever' or 'all-time' — the archive only goes back "
        f"{years_of_data} years reliably. Frame honestly: 'hottest in {years_of_data} years of records' "
        f"or 'hottest since {old_record_year}'."
        f"{anchor_hint}"
    )
    return generate_tweet(
        data,
        category=f"all_time_{kind}",
        return_bundle=return_bundle,
        fallback_fn=templates.record_template,
        fallback_args={
            "city": city, "country": country,
            "temp_c": new_temp_c, "old_temp_c": old_record_c, "old_year": old_record_year,
        },
    )


def generate_country_record_tweet(
    country: str,
    kind: str,
    new_temp_c: float,
    peak_city: str,
    old_temp_c: float,
    old_record_year: int,
    old_record_city: str,
    years_of_data: int,
    cities_sampled: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a country-level archive-wide record.

    This is the biggest story our pipeline produces: one country hit its
    hottest-or-coldest reading across every city we sample. Lead with the
    country and the stake. Honest framing — ``years_of_data`` (~30) is the
    archive window, not "all time."
    """
    temp_f = round(new_temp_c * 9 / 5 + 32, 1)
    old_f = round(old_temp_c * 9 / 5 + 32, 1)
    descriptor = "hottest" if kind == "high" else "coldest"
    anchor_hint = _era_anchor_hint(
        old_record_year,
        seed_key=f"{country}-{old_record_year}-{date.today().isoformat()}",
    )
    data = (
        f"Aggregating {cities_sampled} Open-Meteo monitored cities in {country}: "
        f"today's peak {descriptor} reading is {temp_f}F ({new_temp_c}C) at {peak_city}. "
        f"That exceeds the country-wide {descriptor} across {years_of_data} years of archive data. "
        f"Previous top: {old_f}F ({old_temp_c}C) in {old_record_city}, {old_record_year}. "
        f"Frame as a national record across the archive window. Honest voice: "
        f"'{country}'s {descriptor} reading in {years_of_data} years of records' or "
        f"'{country}'s {descriptor} since {old_record_year}'. "
        f"Do NOT claim 'hottest ever' — the archive is {years_of_data} years. "
        f"Lead with the country and the stake, not {peak_city}."
        f"{anchor_hint}"
    )
    return generate_tweet(
        data,
        category=f"country_{kind}",
        return_bundle=return_bundle,
        fallback_fn=templates.country_record_template,
        fallback_args={
            "country": country, "kind": kind,
            "new_temp_c": new_temp_c, "peak_city": peak_city,
            "old_temp_c": old_temp_c, "old_record_year": old_record_year,
            "old_record_city": old_record_city,
            "years_of_data": years_of_data,
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
    anchor_hint = _era_anchor_hint(
        old_record_year,
        seed_key=f"{city}-{month}-{old_record_year}-{date.today().isoformat()}",
    )
    data = (
        f"Open-Meteo forecast {direction} reading for {city}, {country} today: "
        f"{temp_f}F ({new_temp_c}C). "
        f"If that holds, it would be the {direction} {month_name} reading in "
        f"{years_of_data} years of archive data. "
        f"Previous {direction} {month_name} in that window: {old_f}F ({old_record_c}C) in {old_record_year}. "
        f"Frame honestly: 'hottest {month_name} since {old_record_year}' or "
        f"'hottest {month_name} in {years_of_data} years of records'."
        f"{anchor_hint}"
    )
    return generate_tweet(
        data,
        category=f"monthly_{kind}",
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


def generate_simultaneous_records_roll_call_tweet(
    stations: list[dict],
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Roll-call format for same-country, multi-altitude record clusters.

    One option among formats — flat summary stays the default. Routing
    decision lives in src/editorial/simultaneous_format.py. This generator
    only fires when the routing layer hands it a qualifying subset.

    Each station dict carries: city, country, temp_c, kind, margin_c,
    old_record_c, old_record_year, elevation_m (int | None).
    """
    if not stations:
        return None

    SAMPLE_CAP = 6

    sorted_by_heat = sorted(
        stations,
        key=lambda s: -float(s.get("temp_c", 0.0)),
    )

    # Force the min- and max-elevation stations into the sample even if
    # they aren't the hottest. The whole point of the elevation-spread
    # gate is the altitude story; if the high-altitude endpoint sits at
    # rank 7 by temperature, dropping it leaves the model with a spread
    # note but no station to anchor it. Fill remaining slots with the
    # hottest stations not already pinned.
    pinned: list[dict] = []
    elev_known = [s for s in stations if s.get("elevation_m") is not None]
    if len(elev_known) >= 2:
        lowest = min(elev_known, key=lambda s: int(s["elevation_m"]))
        highest = max(elev_known, key=lambda s: int(s["elevation_m"]))
        # `id()` would be safe inside one call but keying by city+country
        # tuple is more legible and matches how stations are de-duplicated
        # everywhere else in the pipeline.
        seen_keys: set[tuple[str, str]] = set()
        for st in (lowest, highest):
            key = (st.get("city", ""), st.get("country", ""))
            if key not in seen_keys:
                pinned.append(st)
                seen_keys.add(key)
    else:
        seen_keys = set()

    sample: list[dict] = list(pinned)
    for st in sorted_by_heat:
        if len(sample) >= SAMPLE_CAP:
            break
        key = (st.get("city", ""), st.get("country", ""))
        if key in seen_keys:
            continue
        sample.append(st)
        seen_keys.add(key)

    # Present rows hottest-first regardless of pinning order — the
    # ordering is editorial, not analytical.
    sample.sort(key=lambda s: -float(s.get("temp_c", 0.0)))

    rows: list[str] = []
    for st in sample:
        c = round(float(st["temp_c"]), 1)
        f = round(c * 9 / 5 + 32, 1)
        elev = st.get("elevation_m")
        if elev is not None:
            rows.append(f"{st['city']} {f}F ({c}C), {int(elev)}m")
        else:
            rows.append(f"{st['city']} {f}F ({c}C)")

    countries = sorted({st.get("country", "") for st in stations if st.get("country")})
    country_phrase = countries[0] if len(countries) == 1 else f"{len(countries)} countries"

    elevations = [
        int(st["elevation_m"])
        for st in stations
        if st.get("elevation_m") is not None
    ]
    elev_note = ""
    if len(elevations) >= 2:
        lo, hi = min(elevations), max(elevations)
        spread = hi - lo
        if spread >= 800:
            elev_note = f" Elevation spread within the cluster: {lo}m to {hi}m."

    data = (
        f"On this date, {len(stations)} stations in {country_phrase} broke their "
        f"daily calendar-date records. Per-station readings (sorted hottest first): "
        f"{'; '.join(rows)}.{elev_note} "
        f"Format the tweet as a roll-call: lead with the count and the country (or "
        f"an elevation hook when stations span low and high altitudes), then list "
        f"3-5 stations with temperatures. Use slashes or periods between rows. "
        f"Surface elevations only when the cluster genuinely spans altitudes. "
        f"Stay under 280 characters."
    )
    return generate_tweet(
        data,
        category="simultaneous_records_roll_call",
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
    anchor_hint = _era_anchor_hint(
        old_record_year,
        seed_key=f"{city}-{old_record_year}-{date.today().isoformat()}",
    )
    data = (
        f"Open-Meteo forecast high for {city}, {country} today is {temp_f}F ({new_temp_c}C). "
        f"If that holds, it would beat the previous record for this calendar date: "
        f"{old_f}F ({old_record_c}C), set in {old_record_year}."
        f"{anchor_hint}"
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


def generate_ice_mass_tweet(
    region: str,
    kind: str,
    *,
    month: str | None = None,
    monthly_delta_gt: float | None = None,
    previous_worst_gt: float | None = None,
    previous_worst_month: str | None = None,
    threshold_gt: float | None = None,
    current_mass_gt: float | None = None,
    years_of_record: int | None = None,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    region_name = {"greenland": "Greenland", "antarctica": "Antarctica"}.get(
        region, region.title()
    )
    yrs = years_of_record or 0

    if kind == "monthly_loss_record":
        loss = abs(monthly_delta_gt or 0.0)
        prev_line = (
            f"Previous worst: {abs(previous_worst_gt):.0f} Gt in {previous_worst_month}."
            if previous_worst_gt is not None and previous_worst_month
            else "This is the first monthly record observed for this region."
        )
        data = (
            f"{region_name} lost {loss:.0f} gigatons of ice in {month}. "
            f"That is the largest single-month mass loss in {yrs} years of GRACE/GRACE-FO satellite gravimetry (records start 2002). "
            f"{prev_line} "
            f"Do not personify the ice ('dying', 'suffering'). Do not conflate with sea-level rise."
        )
    else:  # cumulative_milestone
        threshold_abs = abs(int(threshold_gt or 0))
        current_abs = abs(current_mass_gt or 0.0)
        data = (
            f"Cumulative ice mass loss from {region_name} has now crossed {threshold_abs:,} gigatons "
            f"since GRACE observations began in 2002. Current cumulative anomaly: {current_abs:,.0f} Gt below the 2002 baseline. "
            f"Do not personify the ice. Do not conflate with sea-level rise."
        )

    return generate_tweet(
        data,
        category="ice_mass_record",
        return_bundle=return_bundle,
        fallback_fn=templates.ice_mass_template,
        fallback_args={
            "region": region,
            "kind": kind,
            "month": month,
            "monthly_delta_gt": monthly_delta_gt,
            "years_of_record": years_of_record,
            "threshold_gt": threshold_gt,
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
    anchor_hint = _era_anchor_hint(
        old_record_year,
        seed_key=f"{city}-low-{old_record_year}-{date.today().isoformat()}",
    )
    data = (
        f"Open-Meteo forecast low for {city}, {country} tonight is {temp_f}F ({new_temp_c}C). "
        f"If that verifies, it would break the previous record low for this calendar date: "
        f"{old_f}F ({old_record_c}C), set in {old_record_year}. "
        f"Today's date: {__import__('datetime').date.today().strftime('%B %d')}."
        f"{anchor_hint}"
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


def generate_marine_heatwave_tweet(
    kind: str,
    days: int,
    today_c: float,
    archive_max_c: float,
    archive_max_year: int,
    years_of_data: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a marine-heatwave archive-record streak."""
    data = (
        f"Global-mean sea surface temperature is at {today_c:.2f}°C today. "
        f"That's above the daily record for this calendar day ({archive_max_c:.2f}°C, "
        f"set in {archive_max_year}) and it's the {days}th consecutive day this has been true. "
        f"Archive goes back {years_of_data} years (NOAA OISST v2.1). "
        f"Today's date: {date.today().strftime('%B %d, %Y')}."
    )
    return generate_tweet(
        data,
        category="marine_heatwave",
        return_bundle=return_bundle,
        fallback_fn=templates.marine_heatwave_template,
        fallback_args={
            "kind": kind,
            "days": days,
            "today_c": today_c,
            "archive_max_c": archive_max_c,
            "archive_max_year": archive_max_year,
            "years_of_data": years_of_data,
        },
    )


def generate_fire_footprint_tweet(
    name: str | None,
    country: str,
    region: str,
    hectares: float,
    tier_hectares: int,
    *,
    return_bundle: bool = False,
) -> str | CandidateBundle | None:
    """Generate a tweet about a fire complex crossing a hectare tier.

    Lead with acreage. No "ravaging" / "raging" / meta-commentary — the
    number is the story. Honest framing: largest complex of this year,
    not "largest ever."
    """
    subject = name if name else f"A fire complex in {region}"
    acres = int(round(hectares * 2.47105, 0))
    data = (
        f"Fire complex: {subject}. Country: {country}. Region: {region}. "
        f"Cumulative burned area: {int(hectares):,} hectares ({acres:,} acres). "
        f"Just crossed the {tier_hectares:,}-hectare threshold. "
        f"Source: NIFC WFIGS (National Interagency Fire Center). "
        f"Lead with the acreage and the subject. No 'ravaging' / 'raging' — "
        f"the number is the story. Frame honestly: the largest complex of "
        f"{date.today().year}, not 'largest ever.'"
    )
    return generate_tweet(
        data,
        category="fire_footprint",
        return_bundle=return_bundle,
        fallback_fn=templates.fire_footprint_template,
        fallback_args={
            "name": name,
            "country": country,
            "region": region,
            "hectares": hectares,
        },
    )


def generate_synthesis_fire_drought_heat_tweet(
    *,
    state: str,
    drought_d4_pct: float,
    fire_peak_frp: float,
    fire_peak_region: str,
    heat_peak_city: str,
    heat_peak_kind: str,
    heat_peak_value_c: float,
    window_days: int = 14,
    return_bundle: bool = True,
) -> str | CandidateBundle | None:
    """Generate a Fire×Drought×Heat synthesis tweet through the full pipeline."""
    data_description = (
        f"State: {state}\n"
        f"Drought (US Drought Monitor): {drought_d4_pct:.1f}% of the state in "
        f"exceptional (D4) drought.\n"
        f"Wildfire (NASA FIRMS, last {window_days} days): peak radiative power "
        f"{fire_peak_frp:.0f} MW, nearest region {fire_peak_region or state}.\n"
        f"Heat (Open-Meteo, last {window_days} days): {heat_peak_kind} record at "
        f"{heat_peak_city}, value {heat_peak_value_c:.1f}C.\n"
        f"{templates.SYNTHESIS_FIRE_DROUGHT_HEAT_EXTRA}"
    )

    def fallback(**_kwargs):
        return templates.synthesis_fire_drought_heat_template(
            state=state,
            drought_d4_pct=drought_d4_pct,
            fire_peak_frp=fire_peak_frp,
            fire_peak_region=fire_peak_region,
            heat_peak_city=heat_peak_city,
            heat_peak_kind=heat_peak_kind,
            heat_peak_value_c=heat_peak_value_c,
            window_days=window_days,
        )

    if return_bundle:
        return generate_tweet_bundle(
            data_description,
            category="synthesis_fire_drought_heat",
            fallback_fn=fallback,
            fallback_args={},
        )
    return generate_tweet(
        data_description,
        fallback_fn=fallback,
        fallback_args={},
    )
