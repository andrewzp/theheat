"""Conservative local checks for hazardous upgrades of source evidence.

These checks deliberately do not classify a thermal pixel, certify an archive,
or infer landfall from a storm name. Passing a typed warrant is only a schema
requirement; source adapters and independent checking still own its truth.
"""
from __future__ import annotations

import math
import re
from typing import Any, TypeGuard

from src.two_bot.strict_contract import valid_date, valid_url


def _source_warrant(value: Any, bundle) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(value, dict)
        and all(isinstance(value.get(key), str) and value[key].strip() for key in ("source_product", "revision_id"))
        and valid_url(value.get("source_url"))
        and valid_date(value.get("valid_date"))
        and value["valid_date"][:10] == str(bundle.when)[:10]
        and value.get("target_event_id") == bundle.event_id
    )


def _finite_number(value: Any) -> TypeGuard[int | float]:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _moisture_diagnostic(value: Any, bundle, text: str) -> bool:
    if not _source_warrant(value, bundle):
        return False
    diagnostic = "wet_bulb_temperature" if re.search(r"wet[- ]bulb", text) else ("humidex" if "humidex" in text else "heat_index")
    if value.get("diagnostic") != diagnostic or not _finite_number(value.get("value")) or value.get("unit") not in ("C", "°C", "F", "°F"):
        return False
    if value.get("evidence_type") == "observed_diagnostic":
        return True
    inputs = value.get("inputs")
    if value.get("evidence_type") != "calculated_diagnostic" or not isinstance(value.get("method"), str) or not value["method"].strip() or not isinstance(inputs, dict):
        return False
    humidity = inputs.get("relative_humidity_pct")
    moisture_available = (_finite_number(humidity) and 0 <= humidity <= 100) or _finite_number(inputs.get("dewpoint_c"))
    return _finite_number(inputs.get("temperature_c")) and moisture_available


def scientific_claim_failures(tweet: str, bundle) -> list[str]:
    """Reject recognizable unsupported claims before asking a model.

    Lexical coverage is bounded; this is not a general entailment proof or a
    replacement for the temperature domain contract and historical-case audit.
    """
    if not isinstance(tweet, str):
        return []  # The output schema supplies the actionable text-type error.
    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    evidence = raw.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    facts = {
        fact.get("label"): fact.get("value")
        for fact in bundle.current_facts if isinstance(fact, dict) and isinstance(fact.get("label"), str)
    } if isinstance(bundle.current_facts, list) else {}
    failures = []
    signal = bundle.signal_kind
    text = tweet.lower()

    if signal.startswith("precipitation") and re.search(r"\b(?:record(?:[- ]breaking)?|wettest|all[- ]time)\b", text):
        # In particular, a `previous_record_mm` field copied from a threshold
        # does not qualify. Require the archived comparison's own provenance.
        comparison = evidence.get("record_comparison")
        if not (_source_warrant(comparison, bundle) and comparison.get("evidence_type") == "archive_comparison"
                and all(isinstance(comparison.get(key), str) and comparison[key].strip() for key in ("comparison_scope", "metric", "unit"))
                and valid_date(comparison.get("cutoff")) and comparison["cutoff"][:10] < str(bundle.when)[:10]
                and _finite_number(comparison.get("value")) and comparison.get("unit") == bundle.headline_metric.get("unit")):
            failures.append("unwarranted_record: rainfall record language requires a sourced, scoped archive comparison; an alert threshold is not a record")

    if signal == "fire":
        # FRP is the satellite product's physical metric, not an incident
        # classification. Other fire assertions (including a satellite-
        # confirmed "fire") require an independently attributed incident.
        classification_text = re.sub(r"\bfire[- ]radiative[- ]power\b", "", text)
        if re.search(r"\b(?:fires?|wildfires?|burning forests?|burning vegetation)\b", classification_text):
            incident = evidence.get("incident")
            if not (_source_warrant(incident, bundle) and incident.get("evidence_type") == "verified_incident"
                    and incident.get("classification") == "vegetation_fire"):
                failures.append("unverified_incident: thermal detection confidence does not establish vegetation-fire identity")
        if re.search(r"\b(?:convective lid|atmospheric cap|pyrocumul\w*|fire[- ]generated thunderstorm)\b", text):
            failures.append("unwarranted_fire_cause: event-specific atmospheric explanation requires a reviewed diagnostic; thermal power alone is insufficient")

    if signal.startswith("cyclone") or "cyclone" in str(raw.get("event_type", "")).lower():
        for match in re.finditer(r"\blandfall\b", text):
            before = text[max(0, match.start() - 70):match.start()]
            after = text[match.end():match.end() + 30]
            # Qualifiers must govern this occurrence directly. A "forecast"
            # or "no" in a different clause cannot excuse completed landfall.
            qualified = re.search(r"\b(?:forecast|expected|possible|potential|could|may|might|will|not|no|never|risk of)\s+(?:(?:a|to|make|made|making|is|of|for|any)\s+){0,4}$", before)
            qualified = qualified or re.match(r"\s+(?:risk|forecast|uncertainty|remains possible|is expected)\b", after)
            if not qualified:
                landfall = evidence.get("landfall")
                if not (_source_warrant(landfall, bundle) and landfall.get("status") == "confirmed"
                        and valid_date(landfall.get("confirmed_at")) and landfall["confirmed_at"][:10] <= str(bundle.when)[:10]):
                    failures.append("unconfirmed_landfall: completed landfall requires dated source confirmation, not a forecast or event label")
                    break

    # P06 supplies the more precise temperature source/valid-time rule. This
    # also covers explicitly modelled non-temperature fallback products.
    forecast = evidence.get("evidence_type") == "forecast" or facts.get("evidence_grade") in {"modelled", "model_fallback", "forecast"}
    if forecast and re.search(r"\b(?:recorded|measured|observed|has broken|broke the record|set a (?:new )?record)\b", text):
        failures.append("forecast_as_observation: a forecast cannot establish an already observed measurement or record")
    if re.search(r"\b(?:wet[- ]bulb|heat index|humidex)\b", text):
        moisture = evidence.get("moisture_diagnostic")
        if not _moisture_diagnostic(moisture, bundle, text):
            failures.append("missing_moisture_evidence: an event-specific moisture diagnostic requires sourced inputs and a method or attributed diagnostic")
    return failures
