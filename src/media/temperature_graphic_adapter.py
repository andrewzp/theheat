"""Local GHCN StoryBundle-to-graphic adapter; no rendering or publication imports.

Input hashes must come from the caller's retained evidence, not edited chart
copy. This validates existing source warrants; it does not fetch/certify NOAA
again, approve tweet text, or grant posting approval.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import re

from src.data.ghcn import GHCN_SOURCE_PRODUCT, MIN_ARCHIVE_YEARS, RECORD_MARGIN_C, record_comparison_qualified
from src.data.temperature_evidence import finite, fingerprint as source_fingerprint
from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import _time, validate_graphic
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.json_utils import json_default
from src.two_bot.types import StoryBundle

ADAPTER_VERSION = "p31-ghcn-observed-1"
_KINDS = {
    "open_meteo_archive_high": ("high", "all_time"),
    "open_meteo_archive_low": ("low", "all_time"),
    "monthly_high": ("high", "monthly"), "monthly_low": ("low", "monthly"),
    "calendar_record": ("high", "calendar"), "calendar_record_low": ("low", "calendar"),
}


def story_bundle_snapshot(bundle: StoryBundle) -> dict:
    """Use the existing finite JSON boundary before calculating an input hash."""
    audit = audit_story_bundle(bundle)
    if not audit.prompt_ready:
        raise ValueError("Graphic requires a P05-qualified StoryBundle: " + ", ".join(
            issue.code for issue in audit.issues if issue.severity == "error"))
    encoded = json.dumps(bundle.to_dict(), default=json_default, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise ValueError("StoryBundle exceeds local graphic input bound")
    return json.loads(encoded)


def _require(condition, reason):
    if not condition:
        raise ValueError("GHCN graphic withheld: " + reason)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _count(value):
    return type(value) is int and value >= 0


def _qualified(bundle, expected_sha):
    snapshot = story_bundle_snapshot(bundle)
    _require(_sha(expected_sha) and fingerprint(snapshot) == expected_sha, "obsolete input bundle binding")
    _require(bundle.signal_kind in _KINDS, "unsupported signal; only individual GHCN daily extrema are supported")
    direction, tier = _KINDS[bundle.signal_kind]
    raw, headline, history = snapshot["raw_signal_dump"], snapshot["headline_metric"], snapshot["historical_context"]
    evidence = raw.get("evidence")
    _require(isinstance(evidence, dict), "missing temperature evidence")
    _require(evidence.get("domain") == "temperature" and evidence.get("source_product") == GHCN_SOURCE_PRODUCT
             and evidence.get("evidence_type") == "observed", "forecast/grid/legacy sources have no adapter yet")
    sid = evidence.get("station_id")
    _require(isinstance(sid, str) and re.fullmatch(r"[A-Z0-9]{11}", sid), "invalid source station identity")
    valid = date.fromisoformat(evidence["valid_date"])
    valid_iso = valid.isoformat()
    _require(snapshot["when"] == raw.get("signal_date") == valid_iso, "conflicting source dates")
    expected_id = (f"all_time_{direction}_{sid}_{valid_iso}" if tier == "all_time" else
                   f"monthly_{direction}_{sid}_{valid.month:02d}_{valid_iso}" if tier == "monthly" else
                   f"cal_{direction}_{sid}_{valid_iso}")
    _require(snapshot["event_id"] == raw.get("event_id") == expected_id and raw.get("kind") == direction,
             "conflicting station/event/variable identity")
    _require(evidence.get("aggregation") == "station_reported_daily_extreme"
             and evidence.get("reporting_interval_known") is False
             and all(evidence.get(key) is None for key in ("timezone", "valid_start", "valid_end", "issued_at", "model_run")),
             "unsupported or contradictory station reporting interval")
    _require(evidence.get("unit") == headline.get("unit") == "C", "incompatible source/headline units")
    _require(headline.get("label") == f"observed_{direction}_c", "headline changes observation or variable type")
    _require(evidence.get("publication_time_qc_known") is False, "publication-time QC certainty is unsupported")
    _require(_sha(evidence.get("revision_id")) and evidence["revision_id"] == source_fingerprint(
        {key: value for key, value in evidence.items() if key not in {"revision_id", "retrieved_at"}}),
        "source evidence revision no longer matches its retained values")

    variable = "temperature_2m_max" if direction == "high" else "temperature_2m_min"
    element = "TMAX" if direction == "high" else "TMIN"
    baseline = evidence.get("baseline")
    _require(record_comparison_qualified(baseline, sid, valid_iso, variable), "P06 archive qualification failed")
    scope = baseline["variables"][variable]
    _require(type(baseline.get("schema_version")) is int and baseline["schema_version"] == 2
             and baseline.get("evidence_type") == "observed"
             and baseline.get("comparison_scope") == "available_source_accepted_station_samples",
             "legacy or expanded comparator scope")
    reading = evidence.get("variables", {}).get(element, {})
    current = reading.get("value_c")
    _require(finite(current) and current == raw.get("new_temp_c") == headline.get("value"),
             "candidate value differs from the retained observation")
    _require(isinstance(reading.get("qflag"), str) and not reading["qflag"].strip(), "candidate QC is not accepted")
    payload_sha = baseline.get("source_payload_sha256")
    _require(_sha(payload_sha) and reading.get("source_payload_sha256") == payload_sha,
             "candidate and comparator do not share the same archive bytes")
    _require(_sha(baseline.get("revision_id")), "missing comparator revision")
    retrieved = evidence.get("retrieved_at")
    _require(retrieved == baseline.get("retrieved_at") and valid <= _time(retrieved).date(),
             "source retrieval cannot establish this observed date")
    cutoff = (valid - timedelta(days=1)).isoformat()
    _require(all(value == cutoff for value in (
        baseline.get("requested_comparison_cutoff"), scope.get("requested_comparison_cutoff"),
        scope.get("verified_source_cutoff"), scope.get("source_latest_cell"))), "comparator cutoff is unverified or obsolete")
    start, accepted_cutoff = date.fromisoformat(scope["start"]), date.fromisoformat(scope["cutoff"])
    expected_count = (valid - start).days
    _require(start <= accepted_cutoff < valid and expected_count > 0, "invalid accepted sample interval")
    _require(all(_count(scope.get(key)) for key in (
        "expected_count", "sample_count", "source_calendar_count", "source_gap_count",
        "source_missing_count", "source_qc_rejected_count", "years_with_samples")), "invalid source coverage counts")
    _require(scope["expected_count"] == scope["source_calendar_count"] == expected_count
             and scope["source_gap_count"] == 0 and 0 < scope["sample_count"] <= expected_count
             and scope.get("conflicting_dates") == []
             and MIN_ARCHIVE_YEARS <= scope["years_with_samples"] <= valid.year - start.year + 1,
             "source calendar/accepted coverage counts do not qualify")
    _require(all(scope["sample_count"] + scope[key] <= expected_count for key in ("source_missing_count", "source_qc_rejected_count"))
             and scope["sample_count"] >= expected_count - scope["source_missing_count"] - scope["source_qc_rejected_count"],
             "missing/QC exclusions conflict with accepted coverage")
    _require(scope.get("complete") is (scope["sample_count"] == expected_count), "accepted-sample completeness conflicts with counts")

    period_key = valid_iso[5:7] if tier == "monthly" else valid_iso[5:]
    prior_date, prior = scope["record_dates"][tier], scope["record_values_c"][tier]
    accepted_count = scope["sample_count"]
    if tier != "all_time":
        prior_date, prior = prior_date[period_key], prior[period_key]
        years, accepted_count = scope[f"{tier}_years"][period_key], scope[f"{tier}_samples"][period_key]
        _require(_count(years) and MIN_ARCHIVE_YEARS <= years <= scope["years_with_samples"]
                 and _count(accepted_count) and years <= accepted_count <= scope["sample_count"],
                 "period-specific sample/year coverage is incomplete")
    prior_day = date.fromisoformat(prior_date)
    _require(start <= prior_day <= accepted_cutoff and all(finite(value) for value in (prior, raw.get("old_record_c"), history.get("prior_record_c")))
             and prior == raw.get("old_record_c") == history.get("prior_record_c")
             and type(raw.get("old_record_year")) is int and raw["old_record_year"] == prior_day.year == history.get("prior_record_year"),
             "comparator differs from its dated source warrant")
    _require((current > prior + RECORD_MARGIN_C if direction == "high" else current < prior - RECORD_MARGIN_C),
             "event does not exceed its qualified comparator")
    _require(tier != "monthly" or (type(raw.get("month")) is int and raw["month"] == valid.month == prior_day.month),
             "monthly comparator belongs to another month")
    _require(tier != "calendar" or valid_iso[5:] == prior_date[5:], "calendar comparator belongs to another calendar date")
    _require(history.get("baseline") == baseline and history.get("margin_c") == round(current - prior, 2),
             "projected comparison disagrees with retained source evidence")
    for label, expected in (("today_temp_c", current), ("kind", direction), ("city", raw.get("city")),
                            ("evidence_type", "observed"), ("source_product", GHCN_SOURCE_PRODUCT), ("valid_date", valid_iso)):
        values = [fact["value"] for fact in snapshot["current_facts"] if fact["label"] == label]
        _require(bool(values) and all(value == expected for value in values), "projected facts disagree with source evidence")
    where = ", ".join(value for value in (raw.get("city"), raw.get("state"), raw.get("country")) if value)
    _require(snapshot["where"] == where, "display location disagrees with source station event")
    source = {"product": GHCN_SOURCE_PRODUCT,
              # This is the existing GHCN adapter's exact station-archive route;
              # it is derived from the qualified product/station, never a diff URL.
              "url": f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{sid}.dly",
              "revision_sha256": payload_sha, "station_id": sid}
    point = {"value": current, "unit": "°C", "valid_date": valid_iso, "evidence_type": "observed", "source": source}
    period_label = {"all_time": "archive", "monthly": f"month {valid.month:02d}", "calendar": f"calendar {period_key}"}[tier]
    graphic_baseline = {
        "complete": True, "coverage_kind": "available_accepted_source_samples",
        "accepted_sample_count": accepted_count, "source_calendar_count": expected_count,
        "source_calendar_expected_count": expected_count,
        "source_missing_count": scope["source_missing_count"], "source_qc_rejected_count": scope["source_qc_rejected_count"],
        "start": start.isoformat(), "cutoff": cutoff, "accepted_sample_cutoff": accepted_cutoff.isoformat(),
        "scope": f"{accepted_count} accepted GHCN {period_label} samples; no official record",
        "point": {**point, "value": prior, "valid_date": prior_date},
        "source_baseline_revision_id": baseline["revision_id"], "source_variable": variable,
        "source_baseline_payload_sha256": fingerprint(baseline),
    }
    return {"point": point, "baseline": graphic_baseline, "location": where, "station_id": sid,
            "variable": "daily_maximum_temperature" if direction == "high" else "daily_minimum_temperature",
            "retrieved_at": retrieved, "snapshot": snapshot, "bundle_sha256": expected_sha,
            "source_evidence_revision_id": evidence["revision_id"]}


def _project(template, rows, synthetic):
    first = rows[0]
    _require(all((row["station_id"], row["variable"], row["location"]) == (first["station_id"], first["variable"], first["location"])
                 for row in rows), "trajectory station, variable or location changed")
    _require(all((row["point"]["source"]["revision_sha256"], row["retrieved_at"]) ==
                 (first["point"]["source"]["revision_sha256"], first["retrieved_at"]) for row in rows),
             "trajectory requires one shared archive payload and retrieval snapshot; revisions are not reconciled here")
    dates = [date.fromisoformat(row["point"]["valid_date"]) for row in rows]
    _require(all(right - left == timedelta(days=1) for left, right in zip(dates, dates[1:])),
             "trajectory requires ordered consecutive source dates; gaps are not interpolated")
    plotted = {row["point"]["valid_date"]: row["point"]["value"] for row in rows}
    _require(all(row["baseline"]["point"]["valid_date"] not in plotted
                 or row["baseline"]["point"]["value"] == plotted[row["baseline"]["point"]["valid_date"]] for row in rows),
             "a retained comparator contradicts another plotted observation")
    return {
        "schema_version": 1, "synthetic": synthetic,
        "event_id": first["snapshot"]["event_id"] if len(rows) == 1 else "ghcn-trajectory-" + fingerprint([row["bundle_sha256"] for row in rows])[:24],
        "location": first["location"], "scope": f"Station {first['station_id']}; interval/timezone unknown",
        "spatial_scope": "station", "station_id": first["station_id"], "variable": first["variable"], "unit": "°C",
        "time_basis": "source_calendar_date", "reporting_interval_known": False, "timezone": None,
        "evidence_as_of": first["retrieved_at"],
        "points": [row["point"] for row in rows],
        "baseline": first["baseline"] if template == "temperature_comparator" else None,
        "input_binding": {"adapter_version": ADAPTER_VERSION, "synthetic": synthetic, "bundles": [
            {"bundle_sha256": row["bundle_sha256"], "source_evidence_revision_id": row["source_evidence_revision_id"],
             "source_baseline_payload_sha256": row["baseline"]["source_baseline_payload_sha256"],
             "bundle": row["snapshot"]} for row in rows]},
    }


class _StoredBundle:
    """Read an already serialized bundle without rerunning mutating projections."""
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def __getattr__(self, name):
        return self.snapshot.get(name)

    def to_dict(self):
        return self.snapshot


def validate_temperature_adapter_binding(template, evidence):
    """Rebuild the projection before rendering/reuse, even if chart hash changed."""
    try:
        binding = evidence["input_binding"]
        _require(binding["adapter_version"] == ADAPTER_VERSION, "unsupported adapter revision")
        inputs = binding["bundles"]
        _require(isinstance(inputs, list) and (len(inputs) == 1 if template == "temperature_comparator" else 2 <= len(inputs) <= 8),
                 "invalid retained input bundle count")
        rows = [_qualified(_StoredBundle(row["bundle"]), row["bundle_sha256"]) for row in inputs]
        _require(fingerprint(_project(template, rows, evidence["synthetic"])) == fingerprint(evidence),
                 "graphic projection differs from its retained qualified StoryBundle inputs")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("GHCN graphic withheld: malformed adapter input binding") from exc


def temperature_graphic_spec(template: str, bundles: list[StoryBundle], *, expected_bundle_sha256: list[str], synthetic: bool) -> dict:
    """Adapt one comparison, or 2–8 consecutive same-station daily observations.

    Unsupported world/forecast/aggregate bundles are refused explicitly. A
    trajectory uses only each independently qualified candidate, never a legacy
    streak count, archive peak sequence, related signal, or interpolated value.
    """
    if type(synthetic) is not bool:
        raise ValueError("Synthetic status must be declared explicitly")
    if template not in {"temperature_comparator", "temperature_trajectory"}:
        raise ValueError("Unsupported temperature graphic template")
    if not isinstance(bundles, list) or not isinstance(expected_bundle_sha256, list) or len(bundles) != len(expected_bundle_sha256):
        raise ValueError("Every input bundle requires its expected evidence hash")
    if not (len(bundles) == 1 if template == "temperature_comparator" else 2 <= len(bundles) <= 8):
        raise ValueError("Provide one comparator bundle or two to eight trajectory bundles")
    try:
        rows = [_qualified(bundle, expected) for bundle, expected in zip(bundles, expected_bundle_sha256)]
        evidence = _project(template, rows, synthetic)
        expected = fingerprint(evidence)
        return {"template": template, "expected_evidence_sha256": expected,
                "evidence": validate_graphic(template, evidence, expected_evidence_sha256=expected)}
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("GHCN graphic withheld: malformed or legacy source warrant") from exc
