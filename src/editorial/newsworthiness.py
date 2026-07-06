"""Bet A editorial consumers — matching sourced news events to detected signals.

Phase A1 (enrich): at the triage drain, match ``state["news_events"]`` (the
retrieval lane's structured/verified, cited world events) to the cycle's
candidate queue and attach ``human_impact`` facts to the matched StoryBundles
so the tweet can carry "3 firefighters killed, per NIFC" instead of only a
megawatt figure. Design: docs/superpowers/specs/2026-07-03-newsworthiness-bet-a-design.md §5.

Matching is deliberately conservative — **no match beats a wrong match**,
because a wrong match risks attaching a death toll to the wrong event, which
is worse than missing it (spec §3). Concretely:

- kind families are strict: fire news ↔ fire candidates, heat-mortality news
  ↔ hot-side temperature candidates (cold records never host a heat toll);
- country must agree; US events additionally require state agreement (a
  country-wide US match could pin a Texas toll on a Vermont record) — FIRMS
  hotspots resolve their state from lat/lon via the census bounding boxes;
- when BOTH sides carry an incident name and the names disagree, the match is
  blocked (a fatality figure must never ride a different fire's tweet);
- an event that matches several candidates attaches to the highest-scored one
  only, so the same impact fact is never duplicated across a cycle's drafts.

This module also owns the decision-4 citation detector used by ``save_draft``:
any draft whose text cites a ``human_impact`` fact is forced ``manual_only``
regardless of signal type — including the #352 autoship-eligible record types.
Detection is two-signal (the writer's ``cited_impact`` JSON field + a regex
sweep for the attached sources/values) and fails closed: either signal, or a
missing writer field, forces manual review.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from src.editorial._regions import lat_lon_to_state

# Candidate legacy_type families per news kind (spec §3: fire↔fire,
# heat_mortality↔heat classes). Hot-side only — attaching excess-mortality
# to a cold record would be a category error.
_FIRE_TYPES: frozenset[str] = frozenset({"fire", "fire_footprint"})
_HEAT_TYPES: frozenset[str] = frozenset({
    "record", "monthly_high", "all_time_high", "anomaly_hot",
    "absolute_extreme", "regional_anomaly", "wet_bulb_extreme",
})
_NEWS_KIND_TO_LEGACY_TYPES: dict[str, frozenset[str]] = {
    "fire": _FIRE_TYPES,
    "heat_mortality": _HEAT_TYPES,
}

# A news event spans [window_start, window_end]; a candidate is a point date
# (or its own window for regional anomalies). Allow a small slack so a fire
# detected the day before the feed row still matches — identity fields
# (country/state/kind/name) carry the precision, the window carries recency.
MATCH_WINDOW_SLACK_DAYS = 2

# Defensive ceiling on attached facts per bundle — the writer needs one good
# anecdote, not a dossier; an unbounded list only bloats the prompt.
MAX_IMPACT_FACTS_PER_BUNDLE = 4

# A2 (spec §4): the flat rescue at the fire score gate. Also the hard floor's
# width — news can rescue a NEAR-miss (Colorado at 62 < 64 clears), never
# resurrect a far-miss; the sensor still has to have nearly cleared the bar.
MAX_NEWS_BOOST = 8

# Values below this never count as a regex citation hit on their own: small
# integers collide with dates ("July 3") and temperatures. Source-name
# attribution is the load-bearing signal for small figures — the writer prompt
# REQUIRES attribution, so a real citation always carries the source name.
_MIN_REGEX_VALUE = 100

# Casualty/impact word stems. On an ENRICHED draft (impact facts were offered),
# any of these in the text forces manual review even when the value is small
# and the source name is absent — the deterministic net for "3 firefighters
# killed" written with a lying/mistaken cited_impact=false. Scoped to enriched
# drafts only, so ordinary fire/heat tweets are untouched; an enriched draft
# discussing impact without citing it properly is exactly what a human should
# see anyway (fail-closed is the safe direction for death tolls). Stems are
# word-boundary-anchored at the START (open-ended after, so fatalit→fatalities
# but "atoll" never reads as "toll"). Damage/cost stems cover rewritten money
# figures ("2 million dollars" for a "$2 million" entry — codex P1, round 3).
_IMPACT_WORD_RE = re.compile(
    r"\b(?:killed|dead|death|died|fatalit|casualt|injur|hospitaliz|missing|"
    r"evacuat|displaced|perished|toll|damag|destro)"
    r"|\b(?:loss(?:es)?|costs?)\b",  # bounded: "Costa Rica" must not read as "cost"
    re.IGNORECASE,
)

_US_COUNTRY_TOKENS: frozenset[str] = frozenset({
    "united states", "usa", "us", "u.s.", "u.s.a.", "united states of america",
})

# 2-letter USPS code -> full state name. Kept in sync by hand with
# src/data/ghcn.py _US_STATE_NAMES and the sentinel's copy — state names do
# not drift, and a local table keeps this module import-light.
_US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_US_STATE_NAMES_LOWER: frozenset[str] = frozenset(
    name.lower() for name in _US_STATE_NAMES.values()
)


def news_enrich_enabled() -> bool:
    """True only when BOTH the Bet A master flag and the enrich flag are "1".

    Requiring the master keeps the one-flip rollback property: turning
    ``THEHEAT_NEWSWORTHINESS_ENABLED`` off kills retrieval AND every consumer,
    so a stale 6-day-old ``news_events`` window can never keep enriching after
    the lane is shut down.
    """
    return (
        os.environ.get("THEHEAT_NEWSWORTHINESS_ENABLED", "") == "1"
        and os.environ.get("THEHEAT_NEWS_ENRICH_ENABLED", "") == "1"
    )


# ---------------------------------------------------------------------------
# candidate/event field extraction
# ---------------------------------------------------------------------------


def _fact_value(bundle: Any, label: str) -> Any:
    for fact in getattr(bundle, "current_facts", None) or []:
        if isinstance(fact, dict) and fact.get("label") == label:
            return fact.get("value")
    return None


def _normalize_country(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in _US_COUNTRY_TOKENS:
        return "united states"
    return text


def _candidate_country(bundle: Any) -> str:
    country = _normalize_country(getattr(bundle, "country", ""))
    if country:
        return country
    country = _normalize_country(_fact_value(bundle, "country"))
    if country:
        return country
    # Regional anomalies keep the region name only as a fact; when the region
    # IS a country ("France"), it is the honest country signal. Multi-country
    # regions ("Iberia") normalize to a token no news country equals — miss,
    # not wrong match.
    return _normalize_country(_fact_value(bundle, "region"))


def _normalize_us_state(raw: Any) -> str:
    """Canonicalize a state token (2-letter code or full name) to the full
    lowercase name; empty string when it is not a recognizable US state."""
    text = str(raw or "").strip()
    if not text:
        return ""
    full = _US_STATE_NAMES.get(text.upper())
    if full:
        return full.lower()
    lowered = text.lower()
    if lowered in _US_STATE_NAMES_LOWER:
        return lowered
    return ""


def _candidate_us_state(bundle: Any) -> str:
    """The candidate's SINGLE US state, canonical full name lowercase; "" when
    unresolvable.

    GHCN temperature bundles carry a full-name ``state`` fact; NIFC complexes
    carry a 2-letter ``region`` fact; FIRMS hotspots carry only lat/lon, which
    resolve through ``lat_lon_to_state`` — the repo's bbox + nearest-centroid
    resolver, single-valued by construction. A raw bbox-membership SET here let
    a nameless New York event match a Vermont-border hotspot whose point sat
    inside three overlapping boxes (codex P1, round 2); centroid tie-breaking
    picks exactly one state, so a wrong-state event can no longer ride the
    overlap.
    """
    explicit = _normalize_us_state(_fact_value(bundle, "state"))
    if explicit:
        return explicit
    region = _normalize_us_state(_fact_value(bundle, "region"))
    if region:
        return region
    lat = _fact_value(bundle, "lat")
    lon = _fact_value(bundle, "lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        resolved = lat_lon_to_state(float(lat), float(lon))
        if resolved:
            return resolved.lower()
    return ""


def _normalize_incident_name(raw: Any) -> str:
    """Lowercased incident name with fire/complex noise words stripped, so
    "Alpine Fire" and "Alpine" compare equal."""
    text = str(raw or "").strip().lower()
    text = re.sub(r"\b(fire|complex|incident)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _candidate_incident_name(bundle: Any) -> str:
    for label in ("complex_name", "incident_name", "name"):
        name = _normalize_incident_name(_fact_value(bundle, label))
        if name:
            return name
    return ""


def _parse_date(raw: Any) -> date | None:
    text = str(raw or "")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _candidate_window(bundle: Any) -> tuple[date, date] | None:
    """The candidate's date span: its window facts when present (regional
    anomalies), else the point date from ``when``."""
    start = _parse_date(_fact_value(bundle, "window_start"))
    end = _parse_date(_fact_value(bundle, "window_end"))
    if start and end and start <= end:
        return (start, end)
    point = _parse_date(getattr(bundle, "when", ""))
    if point:
        return (point, point)
    return None


def _event_window(ev: dict) -> tuple[date, date] | None:
    start = _parse_date(ev.get("window_start"))
    end = _parse_date(ev.get("window_end"))
    if start and end and start <= end:
        return (start, end)
    if start:
        return (start, start)
    if end:
        return (end, end)
    return None


def _windows_overlap(a: tuple[date, date], b: tuple[date, date], slack_days: int) -> bool:
    slack = timedelta(days=slack_days)
    return a[0] - slack <= b[1] and b[0] - slack <= a[1]


def _valid_impact_entry(entry: Any) -> bool:
    """The deterministic floor, re-applied at the consumer boundary: claim +
    value + source_name + url + as_of, or the entry does not exist here.
    (The retrieval lane already floors at parse time; this is the belt for
    state written by any other/older writer.)"""
    if not isinstance(entry, dict):
        return False
    return all(
        isinstance(entry.get(k), str) and entry.get(k)
        for k in ("claim", "source_name", "url", "as_of")
    ) and entry.get("value") not in (None, "")


def _usable_impact_entries(ev: dict) -> list[dict]:
    if ev.get("confidence") not in ("structured", "verified"):
        return []
    return [e for e in (ev.get("impact") or []) if _valid_impact_entry(e)]


def _score_total(candidate: Any) -> int:
    try:
        return int(getattr(getattr(candidate, "score", None), "total", 0) or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# matching (spec §3)
# ---------------------------------------------------------------------------


def _event_matches_candidate(ev: dict, candidate: Any) -> bool:
    bundle = getattr(candidate, "bundle", None)
    if bundle is None:
        return False

    families = _NEWS_KIND_TO_LEGACY_TYPES.get(str(ev.get("kind") or ""))
    if not families or getattr(candidate, "legacy_type", "") not in families:
        return False

    if getattr(candidate, "legacy_type", "") == "absolute_extreme":
        # The ONE direction-ambiguous legacy type: its bundles are
        # "absolute_extreme_hot" / "absolute_extreme_cold" with a matching
        # ``kind`` fact. Heat mortality must never land on a cold extreme
        # (codex P1, round 3 — probed and confirmed before this guard).
        kind_fact = str(_fact_value(bundle, "kind") or "").lower()
        signal_kind = str(getattr(bundle, "signal_kind", "") or "").lower()
        if kind_fact != "hot" and not signal_kind.endswith("_hot"):
            return False

    raw_place = ev.get("place")
    place: dict[str, Any] = raw_place if isinstance(raw_place, dict) else {}
    event_country = _normalize_country(place.get("country"))
    candidate_country = _candidate_country(bundle)
    if not event_country or not candidate_country or event_country != candidate_country:
        return False

    if event_country == "united states":
        # A country-wide US match is too coarse to pin an impact figure on one
        # station/hotspot — require state agreement on both sides.
        event_state = _normalize_us_state(place.get("admin1"))
        if not event_state or event_state != _candidate_us_state(bundle):
            return False

    event_name = _normalize_incident_name(place.get("name"))
    candidate_name = _candidate_incident_name(bundle)
    if event_name and str(ev.get("kind") or "") == "fire":
        # A NAMED fire event is incident-scoped: its impact belongs to THAT
        # fire and no other. Nameless FIRMS hotspots in the same state are not
        # it — requiring the same name on the candidate (NIFC complexes carry
        # one) is the only way a named death toll can never ride a different
        # fire's tweet (codex P0, round 1).
        if not candidate_name or event_name != candidate_name:
            return False
    elif event_name and candidate_name and event_name != candidate_name:
        return False

    ev_window = _event_window(ev)
    cand_window = _candidate_window(bundle)
    if ev_window is None or cand_window is None:
        return False
    return _windows_overlap(ev_window, cand_window, MATCH_WINDOW_SLACK_DAYS)


def match_news_to_candidates(
    news_events: list[dict] | None,
    candidates: list[Any],
) -> list[tuple[dict, Any]]:
    """Match each structured/verified news event to at most ONE candidate.

    Returns ``(event, candidate)`` pairs. The ambiguity rule (spec §3): an
    event matching several candidates attaches to the highest-scored one only,
    so the same impact fact never appears in two drafts of the same cycle.

    Fire tightening (codex P0, round 1): fire news is INCIDENT-scoped, so a
    nameless fire event that matches more than one candidate attaches to NONE
    — two same-state fires in-window cannot be told apart, and guessing by
    score is exactly the wrong-fire death-toll failure. Heat-mortality news is
    REGION-scoped (a country heatwave is one event), so the spec's
    highest-score rule stands there.
    """
    pairs: list[tuple[dict, Any]] = []
    for ev in news_events or []:
        if not isinstance(ev, dict) or not _usable_impact_entries(ev):
            continue
        hits = [c for c in candidates if _event_matches_candidate(ev, c)]
        if not hits:
            continue
        if len(hits) > 1 and str(ev.get("kind") or "") == "fire":
            raw_place = ev.get("place")
            place: dict[str, Any] = raw_place if isinstance(raw_place, dict) else {}
            if not _normalize_incident_name(place.get("name")):
                # Nameless fire event, several plausible hosts: ambiguous
                # identity — attach to none rather than guess.
                continue
        hits.sort(key=_score_total, reverse=True)
        pairs.append((ev, hits[0]))
    return pairs


def attach_human_impact(queue: list[Any], news_events: list[dict] | None) -> int:
    """Attach matched events' impact facts to their candidates' bundles, in
    place. Returns the number of candidates that gained facts. Dedup on
    (claim, url); total facts per bundle capped."""
    enriched: set[int] = set()
    for ev, candidate in match_news_to_candidates(news_events, queue):
        bundle = candidate.bundle
        existing = list(getattr(bundle, "human_impact", None) or [])
        seen = {(e.get("claim"), e.get("url")) for e in existing}
        for entry in _usable_impact_entries(ev):
            if len(existing) >= MAX_IMPACT_FACTS_PER_BUNDLE:
                break
            key = (entry.get("claim"), entry.get("url"))
            if key in seen:
                continue
            seen.add(key)
            existing.append(dict(entry))
        if existing:
            bundle.human_impact = existing
            enriched.add(id(candidate))
    return len(enriched)


# ---------------------------------------------------------------------------
# decision 4 — impact-citation detection (used by save_draft)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImpactCitation:
    """The two-signal verdict on whether a draft's text cites impact facts.

    ``forced`` fails closed: it is False only when the writer explicitly said
    cited_impact=false AND the regex sweep found no attached source/value in
    the text. A missing writer field (contract violation) forces manual.
    """

    forced: bool
    writer_flag: bool | None
    regex_hit: bool

    @property
    def disagreement(self) -> bool:
        if self.writer_flag is None:
            return True
        return self.writer_flag != self.regex_hit


def _int_value_pattern(number: int) -> str | None:
    """A digit-boundary regex for a large integer, tolerant of thousands
    separators ("1300" matches "1,300" and "1300")."""
    if number < _MIN_REGEX_VALUE:
        return None
    digits = str(number)
    with_commas = f"{number:,}"
    alternatives = {re.escape(digits), re.escape(with_commas)}
    return rf"(?<![\d,.])(?:{'|'.join(sorted(alternatives))})(?![\d])"


def _value_patterns(value: Any) -> list[str]:
    """Regex patterns that detect this impact value in tweet text.

    Ints/floats get the digit-boundary pattern. STRING values — the A1
    contract allows "1,450" or "$2 million" (codex P1, round 2) — get (a) a
    literal-echo pattern when the string is substantial (≥3 chars, contains a
    digit), and (b) the digit-boundary pattern for their extracted integer, so
    "1,450" in the text is caught however the entry spelled it.
    """
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return []
        pattern = _int_value_pattern(int(value))
        return [pattern] if pattern else []
    if isinstance(value, str):
        patterns: list[str] = []
        trimmed = value.strip()
        if len(trimmed) >= 3 and any(ch.isdigit() for ch in trimmed):
            patterns.append(rf"(?<!\w){re.escape(trimmed)}(?!\w)")
        # "$2 million" rewritten as "2 million dollars": pair the leading
        # digit-run with its magnitude word, in either spelling order's reach.
        magnitude = re.search(
            r"([\d][\d,.]*)\s*(thousand|million|billion|trillion)",
            trimmed, re.IGNORECASE,
        )
        if magnitude:
            number = re.escape(magnitude.group(1).rstrip(",."))
            word = magnitude.group(2)
            patterns.append(rf"(?<![\d,.]){number}\s*{word}")
        digits = re.sub(r"\D", "", trimmed)
        if digits:
            int_pattern = _int_value_pattern(int(digits))
            if int_pattern:
                patterns.append(int_pattern)
        return patterns
    return []


def _impact_regex_hit(text: str, entries: list[dict]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source_name") or "").strip()
        if source and re.search(
            rf"(?<!\w){re.escape(source)}(?!\w)", text, re.IGNORECASE
        ):
            return True
        for pattern in _value_patterns(entry.get("value")):
            if re.search(pattern, text):
                return True
    return bool(_IMPACT_WORD_RE.search(text or ""))


def detect_impact_citation(text: str, review_context: dict | None) -> ImpactCitation:
    """Decide whether this draft cites a human_impact fact (decision 4).

    Reads the pipeline's ``review_context["two_bot"]`` — ``human_impact``
    (the facts the writer was offered) and ``cited_impact`` (the writer's
    self-report). A draft whose bundle carried no impact facts can never be
    forced by this rule; impact-sounding text there is fact-check's problem.
    """
    two_bot = (review_context or {}).get("two_bot")
    two_bot = two_bot if isinstance(two_bot, dict) else {}
    entries = [e for e in (two_bot.get("human_impact") or []) if isinstance(e, dict)]
    if not entries:
        return ImpactCitation(forced=False, writer_flag=None, regex_hit=False)

    raw_flag = two_bot.get("cited_impact")
    writer_flag = raw_flag if isinstance(raw_flag, bool) else None
    regex_hit = _impact_regex_hit(text or "", entries)
    forced = writer_flag is not False or regex_hit
    return ImpactCitation(forced=forced, writer_flag=writer_flag, regex_hit=regex_hit)


# ---------------------------------------------------------------------------
# A2 — boost (rescue, capped, fire-first; spec §4)
# ---------------------------------------------------------------------------


def news_boost_enabled() -> bool:
    """True only when BOTH the Bet A master flag and the boost flag are "1".
    Same one-flip-rollback property as :func:`news_enrich_enabled`."""
    return (
        os.environ.get("THEHEAT_NEWSWORTHINESS_ENABLED", "") == "1"
        and os.environ.get("THEHEAT_NEWS_BOOST_ENABLED", "") == "1"
    )


def _fire_event_matches_identity(
    ev: dict,
    *,
    country: str,
    when: str,
    lat: float | None,
    lon: float | None,
    us_state: str | None,
    incident_name: str | None,
) -> bool:
    """The enrich matcher's identity rules, evaluated at the RUNNER (before a
    candidate exists) against one fire's raw fields. Boost attaches NO claim
    to any tweet — a wrong boost drafts a borderline fire that still faces the
    writer/critic gates — but the identity discipline is kept identical to
    enrich so the two consumers never disagree about what "a match" means."""
    if str(ev.get("kind") or "") != "fire":
        return False
    raw_place = ev.get("place")
    place: dict[str, Any] = raw_place if isinstance(raw_place, dict) else {}

    event_country = _normalize_country(place.get("country"))
    if not event_country or event_country != _normalize_country(country):
        return False

    if event_country == "united states":
        event_state = _normalize_us_state(place.get("admin1"))
        candidate_state = _normalize_us_state(us_state)
        if not candidate_state and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            resolved = lat_lon_to_state(float(lat), float(lon))
            candidate_state = resolved.lower() if resolved else ""
        if not event_state or event_state != candidate_state:
            return False

    event_name = _normalize_incident_name(place.get("name"))
    fire_name = _normalize_incident_name(incident_name)
    if event_name and event_name != fire_name:
        # Named news is incident-scoped; a nameless fire (FIRMS hotspot) or a
        # differently-named complex is not it.
        return False

    ev_window = _event_window(ev)
    fire_date = _parse_date(when)
    if ev_window is None or fire_date is None:
        return False
    return _windows_overlap(ev_window, (fire_date, fire_date), MATCH_WINDOW_SLACK_DAYS)


def plan_fire_boosts(
    news_events: list[dict] | None,
    fires: list[dict],
) -> dict[str, dict]:
    """Plan which fire gets which news event's rescue — BATCH-scoped, so the
    ambiguity discipline matches A1's enrich matcher exactly (codex P1, A2 r1).

    ``fires``: one dict per detected fire in this runner pass —
    ``{"id", "country", "when", "lat"?, "lon"?, "us_state"?, "incident_name"?}``.

    Rules:
    - a NAMELESS fire event matching more than one fire in the batch plans
      NONE (two same-state fires cannot be told apart; rescuing both would
      let one news report promote N different fires);
    - a NAMED event only ever matches same-named fires (identity check);
      several same-named hits are the same incident reported twice — the
      first takes the plan;
    - one fire takes at most ONE event (no boost stacking: +8 is the cap).
    """
    plan: dict[str, dict] = {}
    for ev in news_events or []:
        if not isinstance(ev, dict) or not _usable_impact_entries(ev):
            continue
        hits = [
            f for f in fires
            if _fire_event_matches_identity(
                ev,
                country=str(f.get("country") or ""),
                when=str(f.get("when") or ""),
                lat=f.get("lat"),
                lon=f.get("lon"),
                us_state=f.get("us_state"),
                incident_name=f.get("incident_name"),
            )
        ]
        if not hits:
            continue
        raw_place = ev.get("place")
        place: dict[str, Any] = raw_place if isinstance(raw_place, dict) else {}
        if len(hits) > 1 and not _normalize_incident_name(place.get("name")):
            # Nameless event, several plausible fires: ambiguous identity —
            # rescue none rather than guess (A1 parity).
            continue
        fire_id = str(hits[0].get("id") or "")
        if fire_id and fire_id not in plan:
            plan[fire_id] = ev
    return plan


def apply_newsworthiness_boost(score: Any, matched_event: dict) -> Any:
    """Rescue a NEAR-miss fire score with its planned newsworthiness match.

    Decision 3 made concrete (spec §4): flat +MAX_NEWS_BOOST, applied only
    when the score currently FAILS and sits within MAX_NEWS_BOOST of its
    threshold (the hard floor), only when the matched event carries ≥1
    structured/verified impact entry (source-required — re-checked here as
    the belt to :func:`plan_fire_boosts`' suspenders). A passing score is
    returned untouched — boost is a rescue, not a ranking inflator. The
    provenance rides ``score.reasons`` into the suppression ledger, dashboard,
    and triage, so an operator can always see why a signal cleared.
    """
    if score.passes:
        return score
    if score.total < score.threshold - MAX_NEWS_BOOST:
        return score
    entries = _usable_impact_entries(matched_event) if isinstance(matched_event, dict) else []
    if not entries:
        return score
    source_name = str(entries[0].get("source_name") or "")
    url = str(entries[0].get("url") or "")
    return replace(
        score,
        total=score.total + MAX_NEWS_BOOST,
        reasons=[
            *score.reasons,
            f"news_boost=+{MAX_NEWS_BOOST} per {source_name} ({url})",
        ],
    )


__all__ = [
    "MATCH_WINDOW_SLACK_DAYS",
    "MAX_IMPACT_FACTS_PER_BUNDLE",
    "MAX_NEWS_BOOST",
    "ImpactCitation",
    "apply_newsworthiness_boost",
    "attach_human_impact",
    "detect_impact_citation",
    "match_news_to_candidates",
    "news_boost_enabled",
    "news_enrich_enabled",
    "plan_fire_boosts",
]
