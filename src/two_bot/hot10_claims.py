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
_TEMPERATURE = re.compile(
    r"(?<![\w.+\-−])([+\-−](?:\s*[+\-−])*\s*\d{1,3}(?:\.\d+)?|\d{1,3}(?:\.\d+)?)"
    r"\s*(?:°\s*|degrees?\s+|º\s*)?([CF])\b", re.I,
)
_CITY_COUNT = re.compile(r"(?<![\w.])(\d{1,4})\s+(?:(?:sampled|tracked|monitored|catalogue|qualified)\s+)?cities\b", re.I)
_WEEKDAY = re.compile(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.I)


def _temperature_key(value: float, unit: str, decimals: int) -> str:
    rounded = round(value, decimals)
    return f"{0.0 if rounded == 0 else rounded:.{decimals}f}{unit}"


def _supported_temperatures(rows: list[dict]) -> set[str]:
    allowed: set[str] = set()
    for row in rows:
        for key in ("temp_high_c", "normal_high_c"):
            celsius = row[key]
            for value, unit in ((celsius, "C"), (celsius * 9 / 5 + 32, "F")):
                allowed |= {_temperature_key(value, unit, 1), _temperature_key(value, unit, 0)}
        departure = row["anomaly_c"]
        for value, unit in ((departure, "C"), (departure * 9 / 5, "F")):
            for signed_or_magnitude in (value, abs(value)):
                allowed |= {_temperature_key(signed_or_magnitude, unit, 1),
                            _temperature_key(signed_or_magnitude, unit, 0)}
    return allowed


def claim_failures(tweet: str, bundle: Any) -> list[str]:
    from src.editorial.hot10_contract import local_weekday, validate_bundle

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
        text, unit = re.sub(r"\s+", "", match[1]).replace("−", "-"), match[2].upper()
        decimals = len(text.partition(".")[2])
        if not re.fullmatch(r"[+\-]?\d{1,3}(?:\.\d+)?", text) or decimals > 1 \
                or _temperature_key(float(text), unit, decimals) not in allowed:
            failures.append("hot10 evidence: temperature value is not a supplied forecast, normal or departure")
            break
    weekdays = {match[0].lower() for match in _WEEKDAY.finditer(tweet)}
    if weekdays:
        named = [row for row in raw["cities"] if re.search(r"(?<!\w)" + re.escape(row["city"]) + r"(?!\w)",
                                                         tweet, re.I)]
        if len(named) == 1 and weekdays != {local_weekday(named[0]["valid_date"]).lower()}:
            failures.append("hot10 evidence: weekday is not the named city's supplied provider-local date")
    counts = {raw["universe"]["sampled_cities"], raw["universe"]["qualified_cities"], len(raw["cities"])}
    if any(int(match[1]) not in counts for match in _CITY_COUNT.finditer(tweet)):
        failures.append("hot10 evidence: city count is not the supplied sampled, qualified or ranked count")
    return failures


__all__ = ["claim_failures"]
