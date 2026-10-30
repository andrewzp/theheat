"""Source-bound Hot10 bulletin -> the native Gist post-image evidence contract.

The only input is the retained qualified bulletin (``hot10_contract`` schema)
saved with the draft. Nothing here fetches, re-ranks, re-qualifies, substitutes a
city or estimates a value. The contract's own ``validate_bundle`` is the first
seam (ten unique fingerprinted rows in ranking order, provenance, universe and
leader); this adapter then refuses what an image would otherwise silently
misstate: a unit other than degrees Celsius, a normal for another month or with no
stated period, a universe whose local days disagree with its rows, or a bundle
other than the one the caller named. Source time (local day over, stale or future
capture) stays the contract's ``current_hold``, checked at approval and send, so a
delivered image remains inspectable later.

The projected evidence feeds the real renderer (``gist_hazard_media``) and both
descriptions. Every displayed value is the retained one; the image rounds to the
0.1 °C the provider reports, never to fit.
"""
from __future__ import annotations

from datetime import date
import math

from src.editorial import hot10_contract as contract
from src.editorial.revisions import fingerprint

TEMPLATE = "hot10_departure_table"
TEMPLATE_VERSION = "w01-hot10-table-1"
ADAPTER_VERSION = "w01-hot10-bulletin-1"
SOURCE_LABEL = "Open-Meteo forecast · Meteostat point normals"
TITLE = "Hot 10 forecast highs vs normal"
UNIT = "C"
AGGREGATION = "local_daily_extreme"
MIN_NORMAL_C, MAX_NORMAL_C = -90.0, 60.0
MAX_FULL_BYTES = 100_000


class Hot10GraphicRefused(ValueError):
    """A bounded refusal; the text draft stays usable and unchanged."""

    def __init__(self, code: str, reason: str):
        self.code = code
        super().__init__("Hot 10 image withheld: " + reason)


def _refuse(condition: bool, code: str, reason: str) -> None:
    if not condition:
        raise Hot10GraphicRefused(code, reason)


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _text(value) -> bool:
    return type(value) is str and value.strip() == value and 0 < len(value) <= 120


def _row(row: dict) -> dict:
    forecast, baseline = row.get("forecast"), row.get("baseline")
    if not isinstance(forecast, dict) or not isinstance(baseline, dict):
        raise Hot10GraphicRefused("media_hot10_row_unqualified", "a ranked row lost its forecast or normal provenance")
    _refuse(forecast.get("unit") == UNIT and forecast.get("aggregation") == AGGREGATION,
            "media_hot10_unit_unsupported", "a ranked forecast is not a local daily maximum in °C")
    _refuse(_text(row.get("city")) and _text(row.get("country")), "media_hot10_row_unqualified",
            "a ranked row has no readable place name")
    try:
        valid = date.fromisoformat(row["valid_date"])
        start, end = int(baseline["period_start"]), int(baseline["period_end"])
    except (KeyError, TypeError, ValueError):
        raise Hot10GraphicRefused("media_hot10_normal_incompatible",
                                  "a normal has no stated period or the local day is malformed") from None
    normal = row.get("normal_high_c")
    if not (baseline.get("month") == valid.month and 1800 <= start <= end <= 2200
            and isinstance(normal, (int, float)) and _finite(normal) and MIN_NORMAL_C <= normal <= MAX_NORMAL_C):
        raise Hot10GraphicRefused("media_hot10_normal_incompatible",
                                  "a normal is for another month, period or plausible range")
    return {
        "rank": row["rank"], "city": row["city"], "country": row["country"], "place_id": row["place_id"],
        "valid_date": row["valid_date"], "timezone": row["timezone"], "valid_start": row["valid_start"],
        "valid_end": row["valid_end"], "retrieved_at": row["retrieved_at"], "forecast_high_c": row["temp_high_c"],
        "normal_high_c": normal, "departure_c": row["anomaly_c"], "unit": UNIT,
        "normal_period": f"{start}-{end}", "forecast_revision_id": forecast.get("revision_id"),
        "row_fingerprint": row["row_fingerprint"],
    }


def hot10_graphic_spec(bundle: dict, *, expected_bundle_sha256: str, synthetic: bool) -> dict:
    """Validated evidence for the renderer, or a refusal; never a repaired bulletin."""
    _refuse(isinstance(bundle, dict) and bundle.get("signal_kind") == "hot10", "media_unsupported",
            "unsupported source for a Hot 10 image")
    _refuse(type(synthetic) is bool, "media_unsupported", "synthetic status must be explicit")
    _refuse(fingerprint(bundle) == expected_bundle_sha256, "media_source_changed", "retained bulletin changed")
    failures = contract.validate_bundle(bundle)
    _refuse(not failures, "media_hot10_" + (failures[0] if failures else "contract"),
            "retained bulletin fails its contract (" + (failures[0] if failures else "") + ")")
    raw = bundle["raw_signal_dump"]
    _refuse(raw["evidence"].get("unit") == UNIT and raw["evidence"].get("aggregation") == AGGREGATION,
            "media_hot10_unit_unsupported", "the bulletin is not local daily maxima in °C")
    rows = [_row(row) for row in raw["cities"]]
    universe = raw["universe"]
    local_days = sorted({row["valid_date"] for row in rows})
    _refuse(universe.get("local_days") == local_days, "media_hot10_universe",
            "the disclosed local days differ from the ranked rows")
    evidence = {
        "template": TEMPLATE, "synthetic": synthetic, "source_label": SOURCE_LABEL,
        "source_product": raw["source_product"], "baseline_product": raw["evidence"]["baseline_product"],
        "source_url": raw["source_url"], "rows_sha256": fingerprint([row["row_fingerprint"] for row in rows]),
        "rows": rows, "local_days": local_days, "sampled_cities": universe["sampled_cities"],
        "qualified_cities": universe["qualified_cities"], "ranked_by": universe["ranked_by"],
        "baseline_scope": universe["baseline_scope"], "scope": universe["scope"],
    }
    return {"template": TEMPLATE, "expected_evidence_sha256": fingerprint(evidence), "evidence": evidence}


def signed(value: float, *, minus: str = "\N{MINUS SIGN}") -> str:
    """The provider's 0.1 °C precision with an explicit sign; never rounded to fit."""
    return f"{value:+.1f}".replace("-", minus)


def full_description(evidence: dict) -> str:
    """Every ranked row's complete retained provenance (expanded details; not sent to X)."""
    lines = [
        ("SYNTHETIC; not real weather. " if evidence["synthetic"] else "") + TITLE + ".",
        f"Ranked by {evidence['ranked_by']}.",
        f"{evidence['qualified_cities']} qualified of {evidence['sampled_cities']} sampled catalogue cities; "
        f"local days {', '.join(evidence['local_days'])}.",
        evidence["scope"], evidence["baseline_scope"] + ".",
        f"Forecast: {evidence['source_product']} ({evidence['source_url']}). Normals: {evidence['baseline_product']}.",
    ]
    for row in evidence["rows"]:
        lines.append(
            f"{row['rank']}. {row['city']}, {row['country']}: forecast daily high {row['forecast_high_c']!r} °C vs "
            f"normal {row['normal_high_c']!r} °C ({row['normal_period']}), departure {signed(row['departure_c'], minus='-')} °C; "
            f"local day {row['valid_date']} ({row['timezone']}, UTC {row['valid_start']} to {row['valid_end']}); "
            f"retrieved {row['retrieved_at']}; place {row['place_id']}.")
    lines.append("Model run time is not supplied by the forecast source. Not observations, records or the world's "
                 "hottest places; no health or other consequence is stated.")
    text = "\n".join(lines)
    _refuse(len(text.encode("utf-8")) <= MAX_FULL_BYTES, "media_description_too_long", "full description bound")
    return text


__all__ = ["ADAPTER_VERSION", "Hot10GraphicRefused", "SOURCE_LABEL", "TEMPLATE", "TEMPLATE_VERSION", "TITLE",
           "full_description", "hot10_graphic_spec", "signed"]
