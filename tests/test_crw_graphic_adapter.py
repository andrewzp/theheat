"""Adversarial source-to-preview qualification, entirely invented and offline."""

from copy import deepcopy
import hashlib
import json
import math

import pytest

from src.editorial.revisions import fingerprint
from src.media.crw_graphic_adapter import (
    TEMPLATE,
    anomaly_axis_limit,
    crw_graphic_spec,
    signed_anomaly,
)
from src.media.evidence_graphic import build_alt_text, template_version, validate_graphic
from src.media.temperature_graphic_adapter import _StoredBundle, story_bundle_snapshot
from tests.crw_graphic_helpers import graphic_inputs


def adapt(bundle, packet, **overrides):
    return crw_graphic_spec(
        bundle,
        packet,
        **{
            "expected_bundle_sha256": fingerprint(story_bundle_snapshot(bundle)),
            "expected_packet_sha256": fingerprint(packet),
            "synthetic": True,
            **overrides,
        },
    )


def rebind_bodies(bundle, packet):
    p = bundle.raw_signal_dump["provenance"]
    for key, row, sha in (
        ("csv_utf8", p, "response_sha256"),
        ("metadata_utf8", p["primary_metadata"], "metadata_sha256"),
    ):
        body = packet[key].encode()
        row[sha], row["response_bytes"] = hashlib.sha256(body).hexdigest(), len(body)


def test_uniform_sample_exact_inputs_are_detached_and_never_approved():
    bundle, packet = graphic_inputs()
    before = deepcopy((bundle, packet))
    spec = adapt(bundle, packet)
    e = spec["evidence"]
    assert e["value"] == 3.6 and e["valid_cells"] == e["total_cells"] == 561
    assert e["evidence_type"] == "satellite_analysis" and e["reporting_interval_known"] is False
    assert e["input_binding"]["bundles"][0]["bundle"] == bundle.to_dict()
    assert (bundle, packet) == before
    assert template_version(TEMPLATE) == "p31-crw-anomaly-1"
    assert template_version("temperature_comparator") == "p31-preview-3-mobile"
    alt = build_alt_text(TEMPLATE, e)
    for phrase in (
        "SYNTHETIC",
        "+3.60°C",
        "1985–1990 + 1993",
        "not the 1991–2020",
        "no interpolation",
        "not a verified measurement interval",
    ):
        assert phrase in alt
    e["input_binding"]["source_packet"]["csv_utf8"] = "changed"
    assert (bundle, packet) == before


def test_exclusions_are_explicit_and_weighting_is_recalculated():
    selected = {(float(lat), float(lon)): 3.6 for lat in range(-5, 6) for lon in range(-170, -168)}
    bundle, packet = graphic_inputs(selected=selected)
    spec = adapt(bundle, packet)
    assert spec["evidence"]["valid_cells"] == 22
    assert spec["evidence"]["excluded_cells"] == 539
    assert "539 excluded" in build_alt_text(TEMPLATE, spec["evidence"])


def test_nonuniform_sample_uses_latitude_weights_not_a_simple_average():
    from src.data.ocean_sst_anomaly import REGION_REGISTRY

    bundle, packet = graphic_inputs(region=REGION_REGISTRY[0])
    rows = packet["csv_utf8"].splitlines()
    values, weights = [], []
    for i, row in enumerate(rows[2:], 2):
        parts = row.split(",")
        lat = float(parts[1])
        value = 8.0 if lat > 30 else 2.6
        values.append(value)
        weights.append(math.cos(math.radians(lat)))
        parts[3] = str(value)
        rows[i] = ",".join(parts)
    packet["csv_utf8"] = "\n".join(rows) + "\n"
    mean = round(sum(v * w for v, w in zip(values, weights)) / sum(weights), 2)
    # Make a new invented event with the independently calculated source mean.
    from src.data.ocean_sst_anomaly import RegionalSSTAnomalyEvent
    from src.two_bot.intern.marine import build_regional_sst_anomaly_bundle

    raw = bundle.raw_signal_dump
    raw["anomaly_c"] = raw["provenance"]["mean_anomaly_c"] = mean
    raw["tier"] = 3
    raw["event_id"] = raw["event_id"].replace("tier2", "tier3")
    rebind_bodies(bundle, packet)
    bundle = build_regional_sst_anomaly_bundle(RegionalSSTAnomalyEvent(**raw))
    assert adapt(bundle, packet)["evidence"]["value"] == mean
    assert mean != round(sum(values) / len(values), 2)


@pytest.mark.parametrize("value", [-15, -3.6, -0.004, 0, 0.004, 2.49])
def test_below_threshold_or_negative_values_cannot_be_promoted_to_warm_events(value):
    with pytest.raises(ValueError):
        adapt(*graphic_inputs(value))


@pytest.mark.parametrize(
    "value,label,limit",
    [
        (3.6, "+3.60", 5),
        (-3.6, "-3.60", 5),
        (-0.004, "0.00", 5),
        (0, "0.00", 5),
        (5.01, "+5.01", 6),
        (15, "+15.00", 15),
    ],
)
def test_signed_rounding_and_unclipped_symmetric_scale(value, label, limit):
    assert signed_anomaly(value) == label and anomaly_axis_limit(value) == limit


@pytest.mark.parametrize("field", ["expected_bundle_sha256", "expected_packet_sha256"])
def test_expected_identity_cannot_be_substituted(field):
    with pytest.raises(ValueError, match="binding"):
        adapt(*graphic_inputs(), **{field: "0" * 64})


@pytest.mark.parametrize(
    "kind",
    [
        "units",
        "mixed_time",
        "coordinate",
        "duplicate",
        "missing_cell",
        "stride",
        "infinity",
        "metadata_product",
        "metadata_end",
        "too_few",
    ],
)
def test_changed_source_is_rejected_even_with_updated_body_hashes(kind):
    bundle, packet = graphic_inputs()
    rows = packet["csv_utf8"].splitlines()
    if kind == "units":
        rows[1] = rows[1].replace("degree_C", "K")
    elif kind == "mixed_time":
        rows[2] = rows[2].replace("T12:", "T13:")
    elif kind == "coordinate":
        rows[2] = rows[2].replace("5.025", "88.0", 1)
    elif kind == "duplicate":
        rows.append(rows[2])
    elif kind == "missing_cell":
        rows.pop()
    elif kind == "stride":
        rows[2] = rows[2].replace("-169.975", "-169.9", 1)
    elif kind == "infinity":
        rows[2] = rows[2].rsplit(",", 1)[0] + ",inf"
    elif kind == "too_few":
        rows[11:] = [r.rsplit(",", 1)[0] + ",NaN" for r in rows[11:]]
    elif kind == "metadata_product":
        packet["metadata_utf8"] = packet["metadata_utf8"].replace('"3.1"', '"3.0"')
    elif kind == "metadata_end":
        packet["metadata_utf8"] = packet["metadata_utf8"].replace("2026-06-14", "2026-06-13")
    packet["csv_utf8"] = "\n".join(rows) + "\n"
    rebind_bodies(bundle, packet)
    with pytest.raises(ValueError):
        adapt(bundle, packet)


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", 4.0),
        ("valid_date", "2026-06-15"),
        ("climatology", "1991–2020"),
        ("location", "Invented basin"),
        ("excluded_cells", 0),
        ("sample_stride_degrees", 0.05),
        ("evidence_type", "observed"),
        ("reporting_interval_known", True),
        ("unit", "K"),
    ],
)
def test_rehashed_graphic_cannot_change_source_claims(field, value):
    bundle, packet = graphic_inputs(selected={(float(lat), -170.0): 3.6 for lat in range(-5, 6)})
    e = adapt(bundle, packet)["evidence"]
    e[field] = value
    with pytest.raises(ValueError):
        validate_graphic(TEMPLATE, e, expected_evidence_sha256=fingerprint(e))


@pytest.mark.parametrize(
    "field,value",
    [
        ("where", "Different sea"),
        ("when", "2026-06-15"),
        ("event_id", "invented"),
        ("human_impact", [{"claim": "fake"}]),
    ],
)
def test_rehashed_bundle_cannot_change_source_projection(field, value):
    bundle, packet = graphic_inputs()
    snapshot = bundle.to_dict()
    snapshot[field] = value
    with pytest.raises(ValueError):
        adapt(_StoredBundle(snapshot), packet)


@pytest.mark.parametrize(
    "change",
    [
        "old_csv",
        "metadata_after_csv",
        "oversized_csv",
        "oversized_metadata",
        "packet_version",
        "extra_field",
        "missing_packet_hash",
        "new_adapter",
        "missing_bundle",
        "bad_synthetic",
    ],
)
def test_packet_bounds_acquisition_order_and_adapter_are_enforced(change):
    bundle, packet = graphic_inputs()
    if change == "old_csv":
        packet["csv_retrieved_at"] = "2026-06-13T12:00:00Z"
    elif change == "metadata_after_csv":
        packet["metadata_retrieved_at"] = "2026-06-17T12:00:00Z"
    elif change == "oversized_csv":
        packet["csv_utf8"] = "x" * 400001
    elif change == "oversized_metadata":
        packet["metadata_utf8"] = "x" * 100001
    elif change == "packet_version":
        packet["schema_version"] = True
    elif change == "extra_field":
        packet["invented"] = True
    elif change == "bad_synthetic":
        with pytest.raises(ValueError):
            adapt(bundle, packet, synthetic=1)
        return
    else:
        e = adapt(bundle, packet)["evidence"]
        if change == "missing_packet_hash":
            del e["input_binding"]["source_packet_sha256"]
        elif change == "new_adapter":
            e["input_binding"]["adapter_version"] = "unknown"
        elif change == "missing_bundle":
            e["input_binding"]["bundles"] = []
        with pytest.raises(ValueError):
            validate_graphic(TEMPLATE, e, expected_evidence_sha256=fingerprint(e))
        return
    with pytest.raises(ValueError):
        adapt(bundle, packet)


def test_earlier_matching_capture_is_not_relabelled_as_production_transfer():
    bundle, packet = graphic_inputs()
    packet["csv_retrieved_at"] = packet["metadata_retrieved_at"] = "2026-06-15T12:00:00Z"
    spec = adapt(bundle, packet)
    alt = build_alt_text(TEMPLATE, spec["evidence"])
    assert "Bundle reports retrieval 2026-06-16" in alt
    assert "matching CSV acquired 2026-06-15" in alt
    assert "not transfer attestations" in alt


def test_explicit_offline_cli_binds_inputs_and_refuses_overwrite(tmp_path):
    from scripts.build_crw_graphic_spec import main

    bundle, packet = graphic_inputs()
    snapshot = bundle.to_dict()
    b, p, out = (tmp_path / name for name in ("bundle.json", "source.json", "spec.json"))
    b.write_text(json.dumps(snapshot))
    p.write_text(json.dumps(packet))
    args = ["--bundle", str(b), "--source-packet", str(p),
            "--expected-bundle-sha256", fingerprint(snapshot),
            "--expected-packet-sha256", fingerprint(packet),
            "--synthetic", "true", "--output", str(out)]
    assert main(args) == 0
    before = out.read_bytes()
    assert json.loads(before) == adapt(bundle, packet)
    assert main(args) == 2 and out.read_bytes() == before
    p.write_text('{"schema_version":1,"schema_version":1}')
    assert main(args) == 2 and out.read_bytes() == before
