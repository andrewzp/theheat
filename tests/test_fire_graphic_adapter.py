"""Offline measurement binding, unsupported-source and stale-chart regressions."""

from copy import deepcopy
import json
import math

import pytest

from src.editorial.revisions import fingerprint
from src.media.evidence_graphic import build_alt_text, validate_graphic
from src.media.fire_graphic_adapter import TEMPLATE, fire_graphic_spec, frp_axis
from src.media.temperature_graphic_adapter import _StoredBundle
from tests.fire_graphic_helpers import graphic_bundle


def adapt(bundle, **changes):
    snapshot = bundle.to_dict()
    receipts = [snapshot["raw_signal_dump"].get("acquisition_provenance"),
                *[r.get("acquisition_evidence") for r in snapshot.get("related_signals", [])]]
    return fire_graphic_spec(bundle, **{
        "expected_bundle_sha256": fingerprint(snapshot),
        "expected_receipt_sha256": [fingerprint(r) for r in receipts],
        "synthetic": True, **changes,
    })


@pytest.mark.parametrize("count", [1, 3, 4])
def test_complete_ordered_projection_preserves_full_input_and_old_minute(count):
    values = [500.1234, 125.75, 750.25, 0.0][:count]
    b = graphic_bundle(values)
    before = deepcopy(b.to_dict())
    e = adapt(b)["evidence"]
    assert [p["frp_source"] for p in e["points"]] == values
    assert [p["label"] for p in e["points"]] == list("ABCD")[:count]
    assert [p["role"] for p in e["points"]] == ["primary"] + ["related"] * (count - 1)
    assert e["input_binding"]["bundles"][0]["bundle"] == before
    assert e["acquired_at"] == "2032-02-29T23:59:00Z" and e["acquisition_precision"] == "minute"
    alt = build_alt_text(TEMPLATE, e)
    for phrase in ["SYNTHETIC", "500.1234", "91.0%", "synthetic-v1", "not original HTTP",
                   "simultaneity", "perimeter", "not temperature", "pixel footprints",
                   "semantic review", "source-freshness"]:
        assert phrase in alt
    e["input_binding"]["bundles"][0]["bundle"]["where"] = "mutated"
    assert b.to_dict() == before


@pytest.mark.parametrize("platforms,expected", [(["T", "Terra"], "Terra"), (["Aqua", "A"], "Aqua")])
def test_only_documented_platform_aliases_are_canonicalized(platforms, expected):
    assert adapt(graphic_bundle([10, 20], platforms=platforms))["evidence"]["satellite"] == expected


@pytest.mark.parametrize("change", ["bundle", "receipt", "order", "missing", "extra"])
def test_expected_bindings_are_independent_complete_and_ordered(change):
    b = graphic_bundle()
    hashes = adapt(b)["evidence"]["input_binding"]["selected_receipt_sha256"]
    changes = {"expected_receipt_sha256": hashes}
    if change == "bundle":
        changes["expected_bundle_sha256"] = "a" * 64
    elif change == "receipt":
        hashes[0] = "a" * 64
    elif change == "order":
        hashes.reverse()
    elif change == "missing":
        hashes.pop()
    else:
        hashes.append("a" * 64)
    with pytest.raises(ValueError):
        adapt(b, **changes)


@pytest.mark.parametrize("target", ["primary", "related"])
@pytest.mark.parametrize("change", ["receipt", "lat", "frp", "confidence", "minute", "product",
                                    "headline", "unit", "identity", "when"])
def test_rehashed_source_and_summary_mismatches_are_refused(target, change):
    s = graphic_bundle().to_dict()
    row = s if target == "primary" else s["related_signals"][0]
    holder, key = (s["raw_signal_dump"], "acquisition_provenance") if target == "primary" else (row, "acquisition_evidence")
    if change == "receipt":
        holder[key] = None
    elif change in {"lat", "frp", "confidence", "minute"}:
        field, value = {"lat": ("latitude", "0"), "frp": ("frp", "999"),
                        "confidence": ("confidence", "100"), "minute": ("acq_time", "2358")}[change]
        holder[key]["record"][field] = value
    elif change == "product":
        holder[key]["source_product"] = "VIIRS_NOAA21_NRT"
    elif change == "headline":
        row["headline_metric"]["value"] += 1
    elif change == "unit":
        row["headline_metric"]["unit"] = "hectares"
    elif change == "identity":
        row["event_id"] += "_other"
    else:
        row["when"] = "2032-03-01T00:00:00Z"
    with pytest.raises(ValueError):
        adapt(_StoredBundle(s))


@pytest.mark.parametrize("field,value", [("lat", True), ("frp_source", True), ("frp_source", float("inf")),
                                         ("frp_source", float("nan")), ("frp_source", "500.1234")])
def test_source_projection_must_be_finite_numbers_not_coerced(field, value):
    s = graphic_bundle().to_dict()
    s["raw_signal_dump"][field] = value
    with pytest.raises(ValueError):
        adapt(_StoredBundle(s))


@pytest.mark.parametrize("change", ["too_many", "duplicate", "colliding_identity", "platform", "minute", "other_hazard",
                                    "extension", "human_impact", "footprint", "viirs", "hms"])
def test_unsupported_full_stories_are_never_silently_trimmed(change):
    b = graphic_bundle()
    if change == "too_many":
        b = graphic_bundle([1, 2, 3, 4, 5])
    elif change == "duplicate":
        b.related_signals.append(deepcopy(b.related_signals[0]))
    elif change == "colliding_identity":
        b = graphic_bundle([10, 20], coordinates=[(35.2501, -110.5), (35.2502, -110.5)])
    elif change == "platform":
        b = graphic_bundle([10, 20], platforms=["Terra", "Aqua"])
    elif change == "minute":
        from datetime import UTC, datetime
        from src.two_bot.intern.fire import build_fire_bundle
        from tests.fire_source_fixtures import fire_event
        other = build_fire_bundle(fire_event(product="MODIS_NRT", confidence=91,
                                            when=datetime(2032, 2, 29, 23, 58, tzinfo=UTC)))
        r = b.related_signals[0]
        r.event_id, r.when, r.headline_metric = other.event_id, other.when, other.headline_metric
        r.acquisition_evidence = other.raw_signal_dump["acquisition_provenance"]
    elif change == "other_hazard":
        b.related_signals[0].signal_kind = "dust_event"
    elif change in {"viirs", "hms"}:
        from src.two_bot.intern.fire import build_fire_bundle
        from src.data.fire_source_contract import HMS_PRODUCT
        from tests.fire_source_fixtures import fire_event
        b = build_fire_bundle(fire_event(product=HMS_PRODUCT if change == "hms" else "VIIRS_NOAA21_NRT"))
    else:
        s = b.to_dict()
        if change == "footprint":
            s["signal_kind"] = "fire_footprint"
        else:
            s["human_impact" if change == "human_impact" else "extra"] = {"unqualified": True}
        b = _StoredBundle(s)
    before = deepcopy(b.to_dict())
    with pytest.raises(ValueError):
        adapt(b)
    assert b.to_dict() == before


@pytest.mark.parametrize("change", ["value", "coordinate", "confidence", "order", "dropped", "scope", "time", "product", "synthetic"])
def test_rehashed_graphic_does_not_override_full_source_projection(change):
    e = adapt(graphic_bundle())["evidence"]
    if change in {"value", "coordinate", "confidence"}:
        e["points"][1][{"value": "frp_source", "coordinate": "lat", "confidence": "source_confidence"}[change]] = 0
    elif change == "order":
        e["points"].reverse()
    elif change == "dropped":
        e["points"].pop()
    elif change == "scope":
        e["scope"] = "One physical fire"
    elif change == "time":
        e["acquired_at"] = "2032-03-01T00:00:00Z"
    elif change == "product":
        e["source_product"] = "VIIRS_NOAA21_NRT"
    else:
        e["input_binding"]["synthetic"] = False
    with pytest.raises(ValueError):
        validate_graphic(TEMPLATE, e, expected_evidence_sha256=fingerprint(e))


@pytest.mark.parametrize("synthetic", [None, 0, "false"])
def test_synthetic_status_is_explicit(synthetic):
    with pytest.raises(ValueError, match="synthetic"):
        adapt(graphic_bundle(), synthetic=synthetic)


@pytest.mark.parametrize("values", [[0, 10], [0.01], [500.1234, 125.75, 750.25], [1e100]])
def test_axis_contains_all_exact_values(values):
    top = frp_axis(values)
    assert math.isfinite(top) and top >= max(values) and top > 0


@pytest.mark.parametrize("values", [[0, 0], [1.7e308], [5e-324]])
def test_uninformative_or_unrenderable_scale_is_refused(values):
    with pytest.raises(ValueError):
        frp_axis(values)


def test_cli_is_offline_bounded_and_never_replaces_output(tmp_path, capsys):
    from scripts.build_fire_graphic_spec import main
    b = graphic_bundle()
    s = b.to_dict()
    source, output = tmp_path / "bundle.json", tmp_path / "spec.json"
    source.write_text(json.dumps(s))
    hashes = adapt(b)["evidence"]["input_binding"]["selected_receipt_sha256"]
    args = ["--bundle", str(source), "--expected-bundle-sha256", fingerprint(s), "--synthetic", "true", "--output", str(output)]
    for digest in hashes:
        args.extend(["--expected-receipt-sha256", digest])
    assert main(args) == 0 and json.loads(output.read_text()) == adapt(b)
    before = output.read_bytes()
    assert main(args) == 2 and output.read_bytes() == before
    for content in ['{"secret-marker":1,"secret-marker":2}', '{"value":NaN}', "{" * 1500, " " * 1_000_001]:
        source.write_text(content)
        assert main(args) == 2
    assert "secret-marker" not in capsys.readouterr().err
