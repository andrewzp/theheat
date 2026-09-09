"""Temperature time and evidence contracts. No provider calls or host-date fallback."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ARCHIVE_MODEL = "era5"
ARCHIVE_PRODUCT = "openmeteo-era5-daily-v2"
FORECAST_PRODUCT = "openmeteo-best-match-forecast-daily-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def daily_time(payload: dict, *, index=0, retrieved_at=None) -> dict:
    """Bind the provider's daily value to its local calendar day and UTC interval.

    Issue/model-run time is not returned by this endpoint and stays unknown.
    A retrieval timestamp must never substitute for a missing valid date.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid provider daily payload")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ValueError("Missing provider daily payload")
    try:
        valid = date.fromisoformat(daily["time"][index])
        zone_name = payload["timezone"]
        zone = ZoneInfo(zone_name)
        offset = payload["utc_offset_seconds"]
        if not isinstance(offset, int) or isinstance(offset, bool) or not -43200 <= offset <= 50400:
            raise ValueError("Invalid provider UTC offset")
    except (KeyError, IndexError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Missing or invalid provider valid date/timezone") from exc
    start = datetime.combine(valid, time.min, zone)
    end = datetime.combine(valid + timedelta(days=1), time.min, zone)
    return {
        "valid_date": valid.isoformat(),
        "timezone": zone_name,
        "utc_offset_seconds": offset,
        "valid_start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "valid_end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "retrieved_at": retrieved_at or utc_now(),
        "issued_at": None,
        "model_run": None,
    }


def forecast_day(payload: dict, *, retrieved_at=None) -> dict:
    timing = daily_time(payload, retrieved_at=retrieved_at)
    daily = payload["daily"]
    values = {}
    for target, source in (
        ("max_c", "temperature_2m_max"),
        ("min_c", "temperature_2m_min"),
        ("tw_max_c", "wet_bulb_temperature_2m_max"),
    ):
        row = daily.get(source) or []
        value = row[0] if row else None
        values[target] = value if finite(value) else None
    evidence = {
        **timing,
        "domain": "temperature",
        "evidence_type": "forecast",
        "source_product": FORECAST_PRODUCT,
        "model": "best_match",
        "model_selection": "provider-selected; model run not supplied",
        "unit": "C",
        "aggregation": "local_daily_extreme",
        "spatial_scope": "model_grid_point",
        "provider_grid": {key: payload.get(key) if finite(payload.get(key)) else None for key in ("latitude", "longitude", "elevation")},
        "provider_units": deepcopy(payload.get("daily_units") or {}),
        "uncertainty": None,

    }
    evidence["revision_id"] = fingerprint({"values": values, **evidence})
    return {**values, **timing, "evidence": evidence}


def attach_evidence(bundle, evidence: dict) -> None:
    """Carry the source contract to every temperature event and its evidence hash."""
    bundle.evidence = deepcopy(evidence)
    for field in (
        "calendar_date_high",
        "calendar_date_low",
        "all_time_high",
        "all_time_low",
        "monthly_high",
        "monthly_low",
        "anomaly_hot",
        "anomaly_cold",
        "absolute_extreme",
        "wet_bulb_extreme",
    ):
        event = getattr(bundle, field, None)
        if event is not None:
            event.evidence = deepcopy(evidence)
            event.signal_date = bundle.signal_date


def project_story_evidence(bundle) -> None:
    """Give writer/checker the same explicit source type, day, baseline and limits."""
    # Construction must retain malformed source packets for the strict audit,
    # rather than raising before its actionable diagnostic can be recorded.
    if not isinstance(bundle.raw_signal_dump, dict) or not isinstance(bundle.current_facts, list) or not isinstance(bundle.historical_context, dict):
        return
    aggregate_failures = temperature_aggregate_failures(bundle)
    if aggregate_failures:
        # Keep the detection reviewable even while generation is withheld. The
        # audit recomputes this decision; a caller cannot clear it by deleting
        # this projection or by setting a claimed approval field.
        bundle.raw_signal_dump = {
            **bundle.raw_signal_dump,
            "temperature_aggregate_review": {
                "status": "withheld",
                "reasons": aggregate_failures,
            },
        }
        bundle.current_facts.append({
            "label": "temperature_aggregate_limit",
            "value": "; ".join(aggregate_failures),
        })
    evidence = bundle.raw_signal_dump.get("evidence") or {}
    if not isinstance(evidence, dict) or not evidence:
        return
    if evidence.get("baseline") is not None and not isinstance(evidence["baseline"], dict):
        return
    if (
        evidence.get("domain") != "temperature"
        and "ghcn" not in str(evidence.get("source_product", "")).lower()
    ):
        return
    for key in (
        "evidence_type",
        "source_product",
        "valid_date",
        "timezone",
        "valid_start",
        "valid_end",
        "issued_at",
        "model_run",
        "retrieved_at",
    ):
        bundle.current_facts.append({"label": key, "value": evidence.get(key)})
    baseline = deepcopy(evidence.get("baseline") or {})
    if evidence.get("source_product") == "sampled-temperature-network":
        bundle.current_facts.append({
            "label": "sampled_network_limit",
            "value": "A comparison within the retained sampled network only, never an official national record. Member local dates are not proof of simultaneous observations. Preserve each member's source, interval and archive cutoff.",
        })
    if evidence.get("comparison"):
        bundle.historical_context["comparison"] = deepcopy(evidence["comparison"])
    if baseline:
        bundle.historical_context["baseline"] = baseline
        bundle.historical_context["scope"] = baseline.get(
            "comparison_scope", "source_archive_samples"
        )
    if evidence.get("valid_date"):
        bundle.when = evidence["valid_date"]
    if evidence.get("evidence_type") == "forecast":
        bundle.current_facts.append(
            {
                "label": "claim_limit",
                "value": "A model forecast, not an observed temperature. Comparators are ERA5 reanalysis samples through their stated cutoff, with the recent-data gap explicitly unverified. Any record comparison must name ERA5 reanalysis and the exact cutoff; it is not a certified station or official country record. Preserve forecast wording.",
            }
        )
        if "observed" in str(bundle.headline_metric.get("label", "")):
            bundle.headline_metric["label"] = bundle.headline_metric["label"].replace(
                "observed", "forecast"
            )
    elif evidence.get("evidence_type") == "observed":
        bundle.current_facts.append(
            {
                "label": "claim_limit",
                "value": "A source-accepted station daily value within the supplied archive/QC scope. For record comparisons, state available/accepted GHCN archive scope and the verified variable cutoff; missing and QC-rejected cells are exclusions, not complete observed history. Unknown reporting intervals and later source revisions are not publication-time certainty.",
            }
        )


def temperature_aggregate_failures(bundle) -> list[str]:
    """Withhold legacy reductions that cannot substantiate their full claim.

    A count, strongest member or boolean ``observed`` flag cannot substitute for
    per-member values, dates, source/QC revisions and comparator coverage. These
    legacy lanes do not yet retain or validate that full aggregate contract.
    This deliberately does not classify a qualified regional reanalysis signal
    or a marine compound as a forecast merely because its name mentions heat.
    """
    kind = bundle.signal_kind
    if not isinstance(kind, str):
        return []  # The strict audit owns the invalid signal-kind diagnostic.
    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    if kind in {"heat_records_cluster", "simultaneous_records"}:
        return ["temperature aggregate scope unverified: same local calendar labels do not establish simultaneous observations; every member needs a qualified source/date/baseline comparison"]
    if kind == "record_streak":
        return ["temperature streak evidence incomplete: retained day count and peak do not preserve every day's source revision, QC and prior comparator"]
    components = raw.get("components")
    if isinstance(kind, str) and kind.startswith("synthesis_") and isinstance(components, list):
        for member in components:
            if not isinstance(member, dict):
                continue
            evidence = member.get("evidence")
            if member.get("kind") == "heat" or (isinstance(evidence, dict) and evidence.get("domain") == "temperature"):
                return ["temperature synthesis evidence incomplete: component peak/count reduction does not retain and validate all source dates, evidence types and baselines"]
    return []


def temperature_claim_failures(tweet: str, bundle) -> list[str]:
    """Narrow deterministic containment of the audited forecast-to-observed error.

    This is a hard floor, not a replacement for full claim extraction (P05/P07).
    Forecast qualifiers elsewhere cannot excuse an observed verb in a temperature
    sentence. The retained Chennai/Bishkek copies must fail even if a model passes.
    """
    import re

    aggregate_failures = temperature_aggregate_failures(bundle)
    if aggregate_failures:
        return aggregate_failures
    evidence = bundle.raw_signal_dump.get("evidence") or {}
    facts = {
        row.get("label"): row.get("value") for row in bundle.current_facts if isinstance(row, dict)
    }
    raw_kind = str(bundle.raw_signal_dump.get("kind", ""))
    comparison_variable = (
        "wet_bulb_temperature_2m_max" if "wet_bulb" in bundle.signal_kind
        else "temperature_2m_min" if raw_kind in {"low", "cold"}
        else "temperature_2m_max"
    )
    def cutoffs_for(baseline):
        rows = baseline.get("variables", {})
        selected = rows.get(baseline.get("variable") or comparison_variable)
        found = {(selected.get("verified_source_cutoff") or selected.get("cutoff"))} if isinstance(selected, dict) else set()
        for member in baseline.get("members", []):
            if isinstance(member, dict):
                found.update(cutoffs_for((member.get("evidence") or {}).get("baseline") or {}))
        return {item for item in found if isinstance(item, str) and item}
    record_words = bool(re.search(r"\b(?:record|hottest|coldest|archive high|archive low)\b", tweet, re.I))
    baseline = evidence.get("baseline") or {}
    sampled = evidence.get("source_product") == "sampled-temperature-network"
    if sampled and record_words:
        if (re.search(r"\b(?:national record|official record|country.wide record|nationwide record)\b", tweet, re.I)
            or not re.search(r"\bsampled\b.{0,35}\b(?:network|stations|cities|locations)\b", tweet, re.I)):
            return ["temperature evidence: sampled-network comparison must name the sampled network and cannot certify an official national record"]
    member_products = [str((row.get("evidence") or {}).get("source_product", "")).lower() for row in baseline.get("members", []) if isinstance(row, dict)]
    ghcn = "ghcn" in str(evidence.get("source_product", "")).lower() or (sampled and bool(member_products) and all("ghcn" in product for product in member_products))
    if evidence.get("evidence_type") == "observed" and ghcn and record_words:
        cutoffs = cutoffs_for(baseline)
        if (not re.search(r"\bGHCN\b", tweet, re.I)
            or not re.search(r"\b(?:available|accepted)\b.{0,35}\b(?:archive|observations|samples|readings)\b", tweet, re.I)
            or not cutoffs or not all(cutoff in tweet for cutoff in cutoffs)):
            return ["temperature evidence: station record comparison must name available/accepted GHCN archive scope and verified cutoff; missing/QC-rejected samples are exclusions"]
        if re.search(r"\b(?:national record|official record|complete (?:weather|observation) history)\b", tweet, re.I):
            return ["temperature evidence: available GHCN samples do not certify national records or a complete observation history"]
    forecast = (
        evidence.get("evidence_type") == "forecast"
        or facts.get("evidence_type") == "forecast"
        or str(bundle.headline_metric.get("label", "")).startswith("forecast_")
    )
    if not forecast:
        return []
    failures = []
    if baseline and record_words:
        cutoffs = cutoffs_for(baseline)
        if not re.search(r"\bERA5\b", tweet, re.I) or not re.search(r"\breanalysis\b", tweet, re.I) or not cutoffs or not all(cutoff in tweet for cutoff in cutoffs):
            failures.append("temperature evidence: archive record comparison must state ERA5 reanalysis and its exact cutoff")
        if not re.search(r"\b(?:gap|unverified|unavailable|not yet available)\b", tweet, re.I):
            failures.append("temperature evidence: reanalysis archive comparison must disclose the recent unverified data gap")
        if re.search(r"\b(?:national record|station record|official record|observed record|all.time record)\b", tweet, re.I):
            failures.append("temperature evidence: forecast against reanalysis cannot establish an official, station or unrestricted all-time record")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", tweet):
        if not re.search(
            r"(?:°\s*[CF]|\b(?:temperature|high|low|hotter|hottest|colder|coldest|record)\b)",
            sentence,
            re.I,
        ):
            continue
        if re.search(
            r"\b(?:hit|reached|recorded|registered|peaked|broke|set a new)\b", sentence, re.I
        ) and not re.search(
            r"\b(?:forecasts?|projected|predicted|expected|on pace|could|may|will|would)\b.{0,35}\b(?:hit|reach|record|register|peak|break|set)\b",
            sentence,
            re.I,
        ):
            failures.append(
                "temperature evidence: forecast cannot support an observed temperature/record claim"
            )
        if not re.search(
            r"\b(?:forecasts?|projected|predicted|expected|on pace|could|may|will|would)\b",
            sentence,
            re.I,
        ) and re.search(r"\b(?:new|hottest|coldest|record)\b", sentence, re.I):
            failures.append(
                "temperature evidence: forecast comparison needs explicit forecast scope"
            )
    return sorted(set(failures))
