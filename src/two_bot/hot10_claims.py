"""Deterministic Hot10 copy limits, applied before any model check.

A qualified Hot10 bulletin supports one kind of statement: a forecast daily
high's departure from a point monthly normal, ranked among the disclosed
sampled cities. It never supports absolute heat, a global ranking, a record,
an observation or a human/infrastructure consequence. This is a bounded
lexical floor for those recognisable upgrades, not general entailment.
"""
from __future__ import annotations

import re
from typing import Any

_GLOBAL = re.compile(
    r"\b(?:hottest|warmest)\b"
    r"|\b(?:world|planet|earth|globe)['’]s\b"
    r"|\b(?:in|on|across|around)\s+(?:the\s+)?(?:world|planet|earth|globe)\b"
    r"|\b(?:globally|worldwide|anywhere)\b",
    re.I,
)
_RECORD = re.compile(r"\b(?:records?|all[- ]time|unprecedented|ever|historic)\b", re.I)
_CONSEQUENCE = re.compile(
    r"\b(?:deaths?|dead|died|deadly|kill(?:s|ed|ing)?|fatal\w*|hospital\w*|heat\s?stroke|illness\w*|"
    r"health|blackouts?|power\s+(?:cuts?|grids?)|outages?|wildfires?|fires?|drought|crops?|harvests?|"
    r"evacuat\w*|emergency|danger\w*|life[- ]threatening|suffer\w*|crisis|catastroph\w*|disaster\w*)\b",
    re.I,
)
_FORECAST = re.compile(r"\b(?:forecasts?|forecasted|projected|predicted|expected)\b", re.I)
_UNIVERSE = re.compile(
    r"\b(?:sampled|tracked|monitored)\b[^.;]{0,40}\bcit(?:y|ies)\b|\bcit(?:y|ies)\b[^.;]{0,24}\b(?:sampled|tracked|monitored)\b",
    re.I,
)
_TEMPERATURE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*(?:°\s*|degrees?\s+|º\s*)?([CF])\b", re.I)
_CITY_COUNT = re.compile(r"(?<![\w.])(\d{1,4})\s+(?:(?:sampled|tracked|monitored|catalogue|qualified)\s+)?cities\b", re.I)


def _supported_temperatures(rows: list[dict]) -> set[str]:
    allowed: set[str] = set()
    for row in rows:
        for key in ("temp_high_c", "normal_high_c"):
            celsius = row[key]
            for value, unit in ((celsius, "C"), (celsius * 9 / 5 + 32, "F")):
                allowed |= {f"{round(value, 1):.1f}{unit}", f"{round(value):.0f}{unit}"}
        departure = row["anomaly_c"]
        for value, unit in ((departure, "C"), (departure * 9 / 5, "F")):
            magnitude = abs(value)
            allowed |= {f"{round(magnitude, 1):.1f}{unit}", f"{round(magnitude):.0f}{unit}"}
    return allowed


def claim_failures(tweet: str, bundle: Any) -> list[str]:
    from src.editorial.hot10_contract import validate_bundle

    if bundle.signal_kind != "hot10" or not isinstance(tweet, str):
        return []
    contract = validate_bundle(bundle)
    if contract:
        return ["hot10 evidence: retained bulletin fails its source contract (" + ", ".join(contract) + ")"]
    failures = []
    if _GLOBAL.search(tweet):
        failures.append("hot10 evidence: ranks departures within sampled cities, not absolute heat or a global ranking")
    if _RECORD.search(tweet):
        failures.append("hot10 evidence: a departure from a monthly normal is not a record or historical extreme")
    if _CONSEQUENCE.search(tweet):
        failures.append("hot10 evidence: no human, health, fire or infrastructure consequence is supplied")
    if not _FORECAST.search(tweet):
        failures.append("hot10 evidence: copy must keep forecast status")
    if not _UNIVERSE.search(tweet):
        failures.append("hot10 evidence: copy must name the sampled city universe")
    raw = bundle.raw_signal_dump
    allowed = _supported_temperatures(raw["cities"])
    for match in _TEMPERATURE.finditer(tweet):
        text, unit = match[1], match[2].upper()
        decimals = len(text.partition(".")[2])
        key = f"{float(text):.{decimals}f}{unit}"
        if decimals > 1 or key not in allowed:
            failures.append("hot10 evidence: temperature value is not a supplied forecast, normal or departure")
            break
    counts = {raw["universe"]["sampled_cities"], raw["universe"]["qualified_cities"], len(raw["cities"])}
    if any(int(match[1]) not in counts for match in _CITY_COUNT.finditer(tweet)):
        failures.append("hot10 evidence: city count is not the supplied sampled, qualified or ranked count")
    return failures


__all__ = ["claim_failures"]
