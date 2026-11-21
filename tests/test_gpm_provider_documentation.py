"""Product-scoped NASA documentation; no data access or claim authorization."""
from copy import deepcopy
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_observed_provider_documentation import by_id, rehash

V1 = "theheat.source-product-contracts/v1"
V2 = "theheat.source-product-contracts/v2"
V3 = "theheat.source-product-contracts/v3"
GPM = {"gpm_imerg.imerg_late_opendap", "gpm_imerg.imerg_late_grid_datapool"}


def canonical(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


@pytest.mark.parametrize("schema,expected", [
    (V1, "dc4f2ae2c4c9daeff22dd6e6c2429d2da7c3922f2795954ecbb14a14dd4f3081"),
    (V2, "3752622c1b4465ade98d9f37be2a2793d5ab796aec50abe92025e943ac099ebe"),
])
def test_complete_previous_export_bytes_are_preserved(schema, expected):
    document = products.product_contract_document(schema=schema)
    assert hashlib.sha256(canonical(document)).hexdigest() == expected
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    assert all(by_id(document)[key][field] is None for key in GPM for field in products.UNKNOWN_FIELDS)


def test_v3_adds_only_two_exact_late_daily_legs_and_keeps_unknowns():
    old = products.product_contract_document(schema=V2)
    new = products.product_contract_document(schema=V3)
    assert new["schema"] == V3
    before, after = by_id(old), by_id(new)
    assert set(before) == set(after)
    assert {key for key in before if before[key] != after[key]} == GPM
    for key in GPM:
        fact = after[key]["provider_cadence"]
        assert fact["status"] == "documented"
        assert "14 hours" in fact["summary"] and "UTC day" in fact["summary"]
        assert "not" in fact["limits"] and "guarantee" in fact["limits"]
        assert after[key]["reuse_rights"]["status"] == "partial"
        assert after[key]["provider_quota"] is None and after[key]["cost"] is None
        for field in ("provider_cadence", "reuse_rights"):
            assert after[key][field]["checked_at"] > "2026-11-18T11:26:46Z"
            assert all(len(ref["sha256"]) == 64 for ref in after[key][field]["references"])
        stripped = deepcopy(after[key])
        for field in products.UNKNOWN_FIELDS:
            stripped[field] = None
        assert stripped == before[key]
    assert after["gpm_imerg.imerg_late_grid_s3"] == before["gpm_imerg.imerg_late_grid_s3"]
    assert after["gpm_imerg.imerg_final_reference"] == before["gpm_imerg.imerg_final_reference"]
    assert after["gpm_imerg.open_meteo_witness"] == before["gpm_imerg.open_meteo_witness"]
    assert products.max_independent_source_count(sorted(GPM)) == 1
    assert new["claim_permission_granted"] is False and new["current_availability"] == "unverified"
    assert new["operational_recovery"] == "not_established"
    gaps = {(row["field"], row["status"]): row["products"] for row in new["unmet_criteria"]}
    assert GPM <= set(gaps["reuse_rights", "partial"])
    assert GPM <= set(gaps["provider_quota", "unknown"])
    assert GPM <= set(gaps["cost", "unknown"])
    assert products.verify_product_contract_document(new) == new["contracts_sha256"]


@pytest.mark.parametrize("schema,cutoff,status", [
    (V1, "2026-10-11T00:00:00Z", "current"),
    (V2, "2026-11-18T08:00:00Z", "current"),
    (V3, "2026-11-18T11:26:46Z", "held"),
    (V3, "2026-11-18T11:28:57Z", "current"),
    (V3, "2026-11-19T00:00:00Z", "current"),
])
def test_all_versions_reach_actual_readiness_cli_without_backdating(schema, cutoff, status, tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "result"
    source.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": cutoff,
        "components": [{"component_type": "source_products",
                        "export": products.product_contract_document(schema=schema)}]}))
    result = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source),
                             "--output-dir", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "readiness.json").read_text())
    assert report["components"][0]["status"] == status
    assert report["unmet_requirements"]["P17"]
    assert report["evidence_states"]["unsupported"] == []


@pytest.mark.parametrize("change", [
    lambda row: row["provider_cadence"].__setitem__("summary", "Guaranteed real-time observations"),
    lambda row: row["provider_cadence"].__setitem__("checked_at", "2026-10-01T00:00:00Z"),
    lambda row: row["provider_cadence"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row["reuse_rights"].__setitem__("status", "documented"),
    lambda row: row.__setitem__("provider_quota", {"status": "documented", "limit": 75}),
    lambda row: row.__setitem__("cost", 0),
])
def test_rehashed_gpm_facts_cannot_invent_guarantees_or_clear_unknowns(change):
    document = products.product_contract_document(schema=V3)
    change(by_id(document)[sorted(GPM)[0]])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_gpm_documentation_cannot_be_borrowed_by_another_product_or_version():
    document = products.product_contract_document(schema=V3)
    row = by_id(document)["gpm_imerg.imerg_late_grid_s3"]
    row["provider_cadence"] = deepcopy(by_id(document)[sorted(GPM)[0]]["provider_cadence"])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))
    document = products.product_contract_document(schema=V3)
    document["schema"] = V2
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))
