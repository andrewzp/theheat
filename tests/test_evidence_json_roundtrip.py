"""Actual JSON storage between real source builders/validators, invented weather."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from src.data import air_quality
from src.data import air_quality_contract as aq
from src.data.air_quality_evidence import bundle_failures
from src.editorial import hot10_contract
from src.two_bot.intern.air_quality import build_dust_event_bundle, build_pm25_hazard_bundle
from src.two_bot.types import RelatedSignal, StoryBundle
from tests.air_quality_fixtures import observation
from tests.gist_hazard_helpers import HOT10_CAPTURE, hot10_bundle, pm25_bundle


def wire(value):
    node = os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    assert node, "The real Node runtime is required for this storage boundary"
    program = 'import fs from "node:fs";const v=JSON.parse(fs.readFileSync(0,"utf8"));process.stdout.write(JSON.stringify(v));'
    result = subprocess.run([node, "--input-type=module", "-e", program],
        input=json.dumps(value), capture_output=True, text=True, timeout=10, check=True,
        env={"PATH": str(Path(node).parent) + ":/usr/bin:/bin", "LC_ALL": "C"})
    return json.loads(result.stdout)


def restore(value):
    fields = deepcopy(value)
    related = fields.pop("related_signals", [])
    return StoryBundle(**fields, related_signals=[RelatedSignal(**row) for row in related])


def source_bundle(*, pm10=90.0, pm25=300.0):
    obs = observation(city="Luma", pm25=pm25, dust=2000.0, pm10_24h_mean=pm10)
    dust, fine = air_quality.detect_dust_event(obs), air_quality.detect_pm25_hazard(obs)
    assert dust is not None and fine is not None
    source, related = build_dust_event_bundle(dust), build_pm25_hazard_bundle(fine)
    source.related_signals = [RelatedSignal(event_id=related.event_id, signal_kind=related.signal_kind,
        where=related.where, when=related.when, headline_metric=related.headline_metric,
        country=related.country, air_quality_evidence=related.raw_signal_dump)]
    return source


@pytest.mark.parametrize("pm10,pm25", [(90.0, 300.0), (90.5, 300.25)])
def test_primary_and_related_aq_evidence_survive_repeated_real_node_storage(pm10, pm25):
    source = source_bundle(pm10=pm10, pm25=pm25)
    assert bundle_failures(source) == []
    original = json.dumps(source.to_dict(), sort_keys=True)
    stored = source.to_dict()
    for _ in range(3):
        stored = wire(stored)
        assert bundle_failures(restore(stored)) == []
    assert json.dumps(source.to_dict(), sort_keys=True) == original


def test_real_qualified_hot10_rows_survive_repeated_real_node_storage():
    source = hot10_bundle()
    assert hot10_contract.validate_bundle(source) == []
    original = json.dumps(source, sort_keys=True)
    stored = source
    for _ in range(3):
        stored = wire(stored)
        assert hot10_contract.validate_bundle(stored) == []
    assert json.dumps(source, sort_keys=True) == original


@pytest.mark.parametrize("field", ["utc_offset_seconds", "month", "period_start", "period_end"])
def test_hot10_integer_metadata_is_strict_without_rehashing(field):
    source = hot10_bundle()
    row = source["raw_signal_dump"]["cities"][0]
    target = row if field == "utc_offset_seconds" else row["baseline"]
    target[field] = float(target[field])
    assert hot10_contract.validate_bundle(source)
    assert hot10_contract.current_hold(source, HOT10_CAPTURE) is not None


@pytest.mark.parametrize("field", ["utc_offset_seconds", "month", "period_start", "period_end"])
def test_hot10_qualification_refuses_floating_integer_metadata(tmp_path, field):
    from tests import live_content_harness as h

    _catalogue, normals, temps = h.qualified_inputs(tmp_path, HOT10_CAPTURE, h.CITIES[:10])
    assert hot10_contract.qualify(temps, normals, sampled=len(temps), now=HOT10_CAPTURE)["complete"]
    if field == "utc_offset_seconds":
        target = temps[0].evidence
    else:
        from src.data import places

        first = temps[0]
        key = places.event_location_key(first.city, first.country, first.lat, first.lon)
        target = normals[key]["_meta"][HOT10_CAPTURE.month]
    target[field] = float(target[field])
    result = hot10_contract.qualify(temps, normals, sampled=len(temps), now=HOT10_CAPTURE)
    assert result["complete"] is False
    assert result["universe"]["qualified_cities"] == len(temps) - 1


@pytest.mark.parametrize("family", ["hot10", "pm25"])
def test_pillow_graphic_and_exact_description_survive_real_node_storage(family):
    from src.media import gist_media

    source = hot10_bundle() if family == "hot10" else pm25_bundle()
    before = gist_media.prepare_media(source)
    after = gist_media.prepare_media(wire(source))
    for key in ("png", "descriptor", "delivery_text", "full_text"):
        assert before[key] == after[key], key


@pytest.mark.parametrize("field", ["temp_high_c", "normal_high_c", "anomaly_c"])
def test_hot10_signed_zero_graphic_and_description_survive_node_storage(field):
    from src.media import gist_media

    source = hot10_bundle()
    row = source["raw_signal_dump"]["cities"][-1]
    row[field] = -0.0
    if field == "temp_high_c":
        row["normal_high_c"] = -row["anomaly_c"]
    elif field == "normal_high_c":
        row["temp_high_c"] = row["anomaly_c"]
    else:
        row["temp_high_c"] = row["normal_high_c"]
    row["row_fingerprint"] = hot10_contract.row_fingerprint(row)
    assert hot10_contract.validate_bundle(source) == []
    assert hot10_contract.validate_bundle(wire(source)) == []
    before, after = gist_media.prepare_media(source), gist_media.prepare_media(wire(source))
    for key in ("png", "descriptor", "delivery_text", "full_text"):
        assert before[key] == after[key], key


def test_legacy_air_window_stays_held_even_with_its_original_valid_json_hash():
    packet = deepcopy(source_bundle().raw_signal_dump["forecast_window"])
    packet["schema_version"] = 1
    core = {key: value for key, value in packet.items() if key != "selected_record_sha256"}
    packet["selected_record_sha256"] = hashlib.sha256(aq._encoded(core)).hexdigest()
    original = json.dumps(packet, sort_keys=True)
    with pytest.raises(aq.SourceFetchError):
        aq.validate_window(packet)
    assert json.dumps(packet, sort_keys=True) == original


def test_legacy_hot10_profile_stays_held_without_upgrading_its_rows():
    from src.data.temperature_evidence import fingerprint as old_fingerprint

    source = hot10_bundle()
    source["raw_signal_dump"]["schema"] = "theheat.hot10-bulletin/v1"
    for row in source["raw_signal_dump"]["cities"]:
        row["row_fingerprint"] = old_fingerprint({k: v for k, v in row.items() if k not in ("rank", "row_fingerprint")})
    original = json.dumps(source, sort_keys=True)
    assert hot10_contract.validate_bundle(source) == ["bulletin_schema"]
    assert json.dumps(source, sort_keys=True) == original


@pytest.mark.parametrize("value", [True, "2", float("nan"), float("inf"), (1 << 53) + 1])
def test_corrupt_or_unsupported_measurement_is_not_numeric_equivalence(value):
    packet = deepcopy(source_bundle().raw_signal_dump["forecast_window"])
    packet["series"]["dust"]["values"][0] = value
    with pytest.raises(aq.SourceFetchError):
        aq.validate_window(packet)


@pytest.mark.parametrize("target", ["raw_tier", "fact_tier", "window_schema", "window_offset"])
def test_integer_metadata_does_not_become_floating_metadata(target):
    source = source_bundle()
    if target == "raw_tier":
        source.raw_signal_dump["tier"] = float(source.raw_signal_dump["tier"])
    elif target == "fact_tier":
        next(row for row in source.current_facts if row["label"] == "tier")["value"] = 2.0
    else:
        packet = source.raw_signal_dump["forecast_window"]
        key = "schema_version" if target == "window_schema" else "utc_offset_seconds"
        packet[key] = float(packet[key])
    assert bundle_failures(source)


@pytest.mark.parametrize("target", ["value", "unit", "missing_hour", "mean", "tier"])
def test_storage_stability_never_repairs_changed_source_values_or_metadata(target):
    stored = wire(source_bundle().to_dict())
    raw = stored["raw_signal_dump"]
    if target == "value":
        raw["dust_daily_max"] += 1
    elif target == "unit":
        raw["forecast_window"]["series"]["dust"]["unit"] = "mg/m³"
    elif target == "missing_hour":
        raw["forecast_window"]["series"]["pm10"]["values"].pop()
    elif target == "mean":
        raw["pm10_24h_mean"] += 1
    else:
        raw["tier"] = True
    assert bundle_failures(restore(stored))


def test_numeric_identity_has_one_value_without_collapsing_boolean_or_string_types():
    from src.data.json_evidence import fingerprint

    def identity(value):
        return fingerprint(value, profile="invented-numbers/v2")

    for value in (0.0, -0.0, 2.0, 2.5, 1e-9):
        assert identity([value]) == identity(wire([value]))
    assert identity(2) == identity(2.0)
    assert identity(0) != identity(False) and identity(1) != identity(True)
    assert identity(2) != identity("2") and identity(2) != identity(2.0000000000000004)
    assert fingerprint(2, profile="a/v2") != fingerprint(2, profile="b/v2")


@pytest.mark.parametrize("value", [(1 << 53), -(1 << 53), 1 << 10000, float("inf"), float("nan"), {1: "value"}, (1, 2)],
                         ids=["unsafe-positive", "unsafe-negative", "huge-int", "infinity", "nan", "nonstring-key", "tuple"])
def test_unsupported_numeric_or_nonjson_values_are_held_before_hashing(value):
    from src.data.json_evidence import fingerprint

    with pytest.raises(ValueError):
        fingerprint(value, profile="invented-numbers/v2")


def test_cyclic_or_excessively_deep_evidence_has_a_bounded_refusal():
    from src.data.json_evidence import fingerprint

    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="capacity"):
        fingerprint(cyclic, profile="invented-numbers/v2")
