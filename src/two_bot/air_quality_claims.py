"""Bounded causal-language refusals; co-reported forecasts are not causal evidence.

This is a cheap rejection rule, never an entailment proof or a passing check.
Normalize a temporary scan only: exact candidate text and source packets remain
bound to the ordinary mandatory check, revision and rejection-cache identities.
"""
from __future__ import annotations

import re
import unicodedata

from src.data.air_quality_evidence import is_air_quality


_AQ = r"(?:dust|pm\s*(?:2\s*\.\s*5|25|10)|particulate(?: matter| pollution)?|air pollution|pollution|aqi|air quality)"
_EFFECT = rf"(?:{_AQ}|visibility|health|breathing|lungs?|asthma|respiratory(?: symptoms| illness)?|hospitali[sz]ations?|deaths?|illness)"
_AQ_TERM = re.compile(rf"\b{_AQ}\b")
_EFFECT_TERM = re.compile(rf"\b{_EFFECT}\b")
_FORWARD = re.compile(
    r"\b(?:push(?:es|ed|ing)?|driv(?:e[sn]?|ing)|drove|rais(?:e[sd]?|ing)|"
    r"lift(?:s|ed|ing)?|boost(?:s|ed|ing)?|fuel(?:s|led|ed|ling|ing)?|"
    r"worsen(?:s|ed|ing)?|caus(?:e[sd]?|ing)|trigger(?:s|ed|ing)?|"
    r"increas(?:e[sd]?|ing)|reduc(?:e[sd]?|ing)|cut(?:s|ting)?|"
    r"impair(?:s|ed|ing)?|degrad(?:e[sd]?|ing)|lower(?:s|ed|ing)?|"
    r"suppress(?:es|ed|ing)?|obscur(?:e[sd]?|ing)|threaten(?:s|ed|ing)?|"
    r"contribut(?:e[sd]?|ing) to|(?:lead(?:s|ing)?|led) to|result(?:s|ed|ing)? in)\b"
)
_REVERSE = re.compile(r"\b(?:because of|due to|owing to|as a result of|caused by|driven by)\b")
_NEGATED = re.compile(
    r"\b(?:(?:does|do|did|is|are|was|were|will|would|could|can|has|have|had) (?:not|never)|cannot)"
    r" (?:be |been |have |directly |necessarily )*$"
)
_BACKGROUND = re.compile(
    r"in general,? dust (?:can|may) (?:raise|increase) "
    r"(?:pm10|pm2\.5|particulate) (?:levels|concentrations)"
)
_CONTRACTIONS = re.compile(r"\b(does|do|did|is|are|was|were|would|could|has|have|had)n't\b")


def _normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'").replace("‘", "'")
    text = _CONTRACTIONS.sub(r"\1 not", text)
    text = re.sub(r"\bcan't\b", "cannot", text)
    text = re.sub(r"\bwon't\b", "will not", text)
    return re.sub(r"[\s\-\u2010-\u2015\u2212]+", " ", text)


_DUST = re.compile(r"\bdust\b")
_PERIOD_COMPARISON = re.compile(
    r"\b(?:who|guidelines?|limits?|standards?)\b|\b\d+(?:\.\d+)?\s*(?:x|times)\b|\b(?:twice|triple|double)\b"
    r"|\b(?:24 hour|daily|day long) (?:mean|average)\b"
)
_NEGATED_PERIOD = re.compile(r"\b(?:not|no|never|without) (?:a |an |any )?(?:24 hour |daily |day long )?(?:mean|average)\b")
_PM10_COMPARISON_SPAN = re.compile(
    r"\bpm\s*10(?:'s)?\s+(?:"
    r"(?:(?:is\s+)?(?:also\s+)?forecast\s+(?:to\s+)?|(?:is\s+)?)"
    r"(?:averag(?:e|ing)|(?:24 hour|daily)\s+(?:mean|average))\s+(?:(?:of|is)\s+)?"
    r"\d[\d,.]*\s*(?:μg|ug)/m3"
    r"(?:\s*,?\s*(?:about\s+)?(?:\d+(?:\.\d+)?\s*(?:times|x)|twice|double|triple)\s+"
    r"(?:the\s+)?who\s+(?:24 hour\s+)?(?:guideline|limit|standard)s?\b)?"
    r"|cross(?:es|ed)?\s+(?:the\s+)?(?:who\s+(?:24 hour\s+)?)?(?:guideline|limit|standard)s?\b)"
)


def dust_comparison_failures(tweet: str, bundle) -> list[str]:
    """A dust story's peak is never a 24-hour mean or a WHO-period comparison.

Only an explicit PM10 comparison span may carry the existing co-reported PM10
anchor; incidental mentions do not exempt the rest of a dust clause. Ambiguous
mixed comparisons hold. An explicit negation ("a peak, not a daily mean") is not a comparison.
"""
    if getattr(bundle, "signal_kind", None) != "dust_event" or not isinstance(tweet, str):
        return []
    for clause in re.split(r"[!?;。]|\.(?!\d)|(?<!\d)\.", _normalized(tweet)):
        if not _DUST.search(clause):
            continue
        scan = _NEGATED_PERIOD.sub(" ", clause)
        # Remove only the recognized PM10 metric/comparison, never its trailing
        # clause or a dust comparison before/after a parenthetical PM10 mention.
        scan = _PM10_COMPARISON_SPAN.sub(" ", scan)
        if _PERIOD_COMPARISON.search(scan):
            return ["dust_peak_comparison: a forecast dust peak cannot be compared with a 24-hour mean, "
                    "WHO period or multiple; only supplied PM10 carries the PM10 anchor"]
    return []


def causal_claim_failures(tweet: str, bundle) -> list[str]:
    """Hold named positive AQ causal links, including quoted/forecast assertions.

Immediate negation only scopes its own predicate. A complete, narrowly recognized
background sentence can reach the normal checkers. Neither exception establishes
truth, and existing cross-signal rules can independently reject the same text.
Other paraphrases and pronoun-only links still require model review.
"""
    related = getattr(bundle, "related_signals", None)
    if not (is_air_quality(bundle) or (
        isinstance(related, list) and any(is_air_quality(signal) for signal in related)
    )):
        return []
    # Keep decimal points (PM2.5 and numeric values); do not join independent
    # sentences. Commas, quotes, line breaks and Unicode dashes cannot hide a link.
    clauses = re.split(r"[!?;。]|\.(?!\d)|(?<!\d)\.", _normalized(tweet))
    for clause in clauses:
        if _BACKGROUND.fullmatch(clause.strip()):
            continue
        for pattern, left_term, right_term in (
            (_FORWARD, _AQ_TERM, _EFFECT_TERM),
            (_REVERSE, _EFFECT_TERM, _AQ_TERM),
        ):
            for match in pattern.finditer(clause):
                before, after = clause[:match.start()], clause[match.end():]
                if _NEGATED.search(before):
                    continue
                if match.group() == "due to" and re.match(r" be\b", after):
                    continue  # Scheduled infinitive, not a causal explanation.
                if left_term.search(before) and right_term.search(after):
                    return [
                        "unsupported_air_quality_causation: co-reported air-quality forecasts do not "
                        "establish an event-specific cause or visibility/health impact"
                    ]
    # Preserve the existing causal refusal when a PM10 comparison is itself
    # caused by dust; otherwise apply the independent dust-peak comparison hold.
    return dust_comparison_failures(tweet, bundle)
