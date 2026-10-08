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
    return []
