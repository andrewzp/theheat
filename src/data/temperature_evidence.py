"""Temperature time and evidence contracts. No provider calls or host-date fallback."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
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


def ghcn_record_point_failures(bundle) -> list[str]:
    """Bind individual station records to the existing accepted-source warrant.

    This is the cluster's qualification floor, also for TMIN/low records. It
    verifies retained agreement, never NOAA authenticity or publication approval.
    Forecast/aggregate families keep their own contracts. Imports stay scoped:
    unrelated hazards must not load station collectors in the sealed runtime.
    """
    comparators = {
        "open_meteo_archive_high": ("high", "all_time"),
        "open_meteo_archive_low": ("low", "all_time"),
        "monthly_high": ("high", "monthly"), "monthly_low": ("low", "monthly"),
        "calendar_record": ("high", "calendar"), "calendar_record_low": ("low", "calendar"),
    }
    if not isinstance(bundle.signal_kind, str):
        return []
    raw = bundle.raw_signal_dump
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    baseline = evidence.get("baseline") if isinstance(evidence, dict) else None
    # Retained projections and exact station-event identities are family hints
    # too. Relabelling raw evidence must not hide an inconsistent GHCN warrant.
    def source_hint(value):
        return isinstance(value, dict) and (value.get("station_id")
            or "ghcn" in str(value.get("source_product", "")).lower())

    history = bundle.historical_context if isinstance(bundle.historical_context, dict) else {}
    facts = bundle.current_facts if isinstance(bundle.current_facts, list) else []
    station_event = r"(?:all_time_(?:high|low)_[A-Z0-9]{11}|monthly_(?:high|low)_[A-Z0-9]{11}_\d{2}|cal_(?:high|low)_[A-Z0-9]{11})_\d{4}-\d{2}-\d{2}"
    event_hint = any(isinstance(value, str) and re.fullmatch(station_event, value)
                     for value in (bundle.event_id, raw.get("event_id") if isinstance(raw, dict) else None))
    if not (source_hint(evidence) or source_hint(baseline) or source_hint(history.get("baseline"))
            or event_hint or isinstance(raw, dict) and "ghcn_claim_view" in raw
            or isinstance(bundle.headline_metric, dict) and str(bundle.headline_metric.get("label", "")).startswith("observed_")
            or any(isinstance(fact, dict) and (fact.get("label") == "station_id"
                or fact.get("label") == "source_product" and "ghcn" in str(fact.get("value", "")).lower())
                for fact in facts)):
        return []
    if bundle.signal_kind not in comparators:
        # Missing required fields cannot reclassify a retained record as an
        # exempt anomaly/absolute family. Identity or either side of its dated
        # comparison is enough to retain the record boundary.
        if (event_hint or isinstance(raw, dict) and any(key in raw for key in ("new_temp_c", "old_record_c"))
            or any(key in history for key in ("prior_record_c", "prior_record_year"))):
            return ["GHCN individual record has an unsupported or changed signal kind"]
        return []  # Non-record GHCN families retain their separate contracts.
    try:
        return _ghcn_record_point_failures(bundle, comparators[bundle.signal_kind])
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return ["Missing or malformed GHCN individual-record warrant"]


def _ghcn_record_point_failures(bundle, comparator) -> list[str]:
    from src.data.ghcn import GHCN_SOURCE_PRODUCT, MIN_ARCHIVE_YEARS, RECORD_MARGIN_C, record_comparison_qualified
    from types import SimpleNamespace
    from src.data.places import country_key
    from src.two_bot.json_utils import json_default

    raw, evidence = bundle.raw_signal_dump, bundle.raw_signal_dump["evidence"]
    direction, period = comparator
    sid, valid_iso = evidence["station_id"], evidence["valid_date"]
    valid = date.fromisoformat(valid_iso)
    variable = "temperature_2m_max" if direction == "high" else "temperature_2m_min"
    element = "TMAX" if direction == "high" else "TMIN"
    baseline = evidence["baseline"]
    if not record_comparison_qualified(baseline, sid, valid_iso, variable):
        return ["GHCN archive qualification failed"]
    scope = baseline["variables"][variable]
    reference = None
    if "ghcn_claim_view" in raw:
        # Preserve the existing passive compact contract. Its typed command
        # resolver still owns replay/current authority; shape is not resolution.
        from src.two_bot.ghcn_claim_contract import structural_view, json_tree
        reference = structural_view(json_tree(bundle.to_dict()))
        field = (f"all_time_{direction}" if period == "all_time" else
                 f"monthly_{direction}" if period == "monthly" else f"calendar_date_{direction}")
        if (reference["selection"] != {"station_id": sid, "signal_date": valid_iso, "signal_field": field}
            or reference["observation_revision"] != evidence.get("revision_id")
            or reference["baseline_revision"] != baseline.get("revision_id")
            or reference["original_archives"][0]["raw_sha256"] != baseline.get("source_payload_sha256")):
            return ["GHCN compact claim disagrees with its retained source reference"]
    reading = evidence["variables"][element]
    current, prior = raw["new_temp_c"], raw["old_record_c"]
    if (evidence.get("domain") != "temperature" or evidence.get("evidence_type") != "observed"
        or evidence.get("source_product") != GHCN_SOURCE_PRODUCT or evidence.get("unit") != "C"
        or not isinstance(sid, str) or not sid
        or not finite(current) or not finite(prior) or reading.get("value_c") != current
        or not isinstance(reading.get("qflag"), str) or reading["qflag"].strip()
        or reading.get("source_payload_sha256") != baseline["source_payload_sha256"]
        or not finite(scope.get("years_with_samples")) or scope["years_with_samples"] < MIN_ARCHIVE_YEARS
        or scope.get("verified_source_cutoff") != (valid-timedelta(days=1)).isoformat()
        or raw.get("kind") != direction
        or not finite(raw.get("lat")) or not -90 <= raw["lat"] <= 90
        or not finite(raw.get("lon")) or not -180 <= raw["lon"] <= 180):
        return ["GHCN point identity, accepted reading or archive cutoff disagrees"]
    if reference is not None:
        comparison = scope["selected_comparison"]
        expected_key = None if period == "all_time" else valid_iso[5:7] if period == "monthly" else valid_iso[5:]
        if (comparison.get("purpose") != "record_comparator" or comparison.get("period") != period
            or comparison.get("key") != expected_key or not finite(comparison.get("years_with_samples"))
            or comparison["years_with_samples"] < MIN_ARCHIVE_YEARS):
            return ["GHCN compact period-specific comparator is unqualified"]
        prior_day, prior_value = comparison["prior_date"], comparison["prior_value_c"]
    else:
        prior_day, prior_value = scope["record_dates"][period], scope["record_values_c"][period]
    if reference is None and period != "all_time":
        key = valid_iso[5:7] if period == "monthly" else valid_iso[5:]
        prior_day, prior_value = prior_day[key], prior_value[key]
        if not finite(scope[f"{period}_years"].get(key)) or scope[f"{period}_years"][key] < MIN_ARCHIVE_YEARS:
            return ["GHCN period-specific comparator coverage is unqualified"]
    prior_date = date.fromisoformat(prior_day)
    if (not finite(prior_value) or prior != prior_value or type(raw.get("old_record_year")) is not int
        or raw["old_record_year"] != prior_date.year or prior_date >= valid
        or not (current > prior_value + RECORD_MARGIN_C if direction == "high" else current < prior_value - RECORD_MARGIN_C)
        or period == "monthly" and (raw.get("month") != valid.month or prior_date.month != valid.month)
        or period == "calendar" and prior_day[5:] != valid_iso[5:]):
        return ["GHCN record does not match its dated comparator"]
    expected_id = (f"all_time_{direction}_{sid}_{valid_iso}" if period == "all_time" else
                   f"monthly_{direction}_{sid}_{valid.month:02d}_{valid_iso}" if period == "monthly" else
                   f"cal_{direction}_{sid}_{valid_iso}")
    source_date = raw["signal_date"].isoformat() if isinstance(raw["signal_date"], date) else raw["signal_date"]
    if bundle.event_id != raw.get("event_id") or bundle.event_id != expected_id or source_date != valid_iso or bundle.when != valid_iso:
        return ["GHCN record event/date differs from its station reading"]
    if reference is None and evidence.get("revision_id") != fingerprint({k: v for k, v in evidence.items() if k not in {"revision_id", "retrieved_at"}}):
        return ["GHCN retained evidence revision differs from its values"]

    # Check the same source-owned projections without importing intern builders
    # (and their collector-only climate dependencies) into the sealed runtime.
    def normalize(value):
        return json.loads(json.dumps(value, default=json_default, allow_nan=False))

    where = ", ".join(value for value in (raw.get("city"), raw.get("state"), raw.get("country")) if value)
    if (bundle.where != where or (getattr(bundle, "country", "") or "") not in {"", country_key(raw.get("country", ""))}
        or bundle.headline_metric != {"label": f"observed_{direction}_c", "value": current,
                                     "unit": "C", "value_f": round(current*9/5+32)}):
        return ["GHCN projected identity/headline differs from its retained event"]
    history = {"prior_record_c": prior, "prior_record_f": round(prior*9/5+32),
               "prior_record_year": prior_date.year, "margin_c": round(current-prior, 2),
               "margin_f": round(current*9/5+32)-round(prior*9/5+32)}
    if period != "calendar":
        history["archive_years"] = raw["years_of_data"]
        if raw["years_of_data"] != scope["years_with_samples"]:
            return ["GHCN projected archive span differs from accepted source years"]
    for key, value in history.items():
        if key not in bundle.historical_context or normalize(bundle.historical_context[key]) != normalize(value):
            return ["GHCN projected comparison differs from its retained event"]
    projection = SimpleNamespace(signal_kind=bundle.signal_kind, raw_signal_dump=raw,
        current_facts=[], historical_context={}, headline_metric={}, when=valid_iso)
    project_story_evidence(projection)
    facts = [("city", raw["city"]), ("country", raw["country"]), ("kind", direction),
             ("today_temp_c", current), ("today_temp_f", round(current*9/5+32))]
    facts.extend((fact["label"], fact["value"]) for fact in projection.current_facts)
    for label, value in facts:
        actual = [row.get("value") for row in bundle.current_facts if row.get("label") == label]
        if len(actual) != 1 or normalize(actual[0]) != normalize(value):
            return ["GHCN projected fact differs from its retained event"]
    for key, value in projection.historical_context.items():
        if key not in bundle.historical_context or normalize(bundle.historical_context[key]) != normalize(value):
            return ["GHCN projected source scope differs from its retained event"]
    return []


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
    elif evidence.get("evidence_type") == "observed" and _regional_observed(evidence):
        bundle.current_facts.append({"label": "claim_limit", "value": REGIONAL_OBSERVED_CLAIM_LIMIT})
    elif evidence.get("evidence_type") == "observed":
        bundle.current_facts.append(
            {
                "label": "claim_limit",
                "value": "A source-accepted station daily value within the supplied archive/QC scope. For record comparisons, state available/accepted GHCN archive scope and the verified variable cutoff; missing and QC-rejected cells are exclusions, not complete observed history. Unknown reporting intervals and later source revisions are not publication-time certainty.",
            }
        )


REGIONAL_OBSERVED_CLAIM_LIMIT = (
    "National-service observed station value for its source reporting day (not an exact UTC day). "
    "Without a scoped comparator warrant only value or absolute-band wording is supported: no record, "
    "national-record or official-record claim. One named station is not national or regional coverage."
)


def _regional_observed(evidence: dict) -> bool:
    """Observed station evidence from a non-GHCN product (W05 national-service adapters)."""
    product = str(evidence.get("source_product", "")).lower()
    return evidence.get("domain") == "temperature" and evidence.get("evidence_type") == "observed" \
        and bool(product) and "ghcn" not in product and product != "sampled-temperature-network"


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
    """Temperature claim floor, plus the Hot10 bulletin's own copy limits."""
    failures = _temperature_claim_failures(tweet, bundle)
    if getattr(bundle, "signal_kind", None) == "hot10":
        from src.two_bot.hot10_claims import claim_failures

        failures = sorted(set(failures) | set(claim_failures(tweet, bundle)))
    return failures


def _temperature_claim_failures(tweet: str, bundle) -> list[str]:
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
    if _regional_observed(evidence) and record_words:
        warrant = evidence.get("comparison_warrant")
        if not isinstance(warrant, dict) or warrant.get("claim_scope") != "record":
            return ["temperature evidence: a national-service observed value without a scoped comparator warrant "
                    "supports value or absolute-band wording only, not a record"]
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
