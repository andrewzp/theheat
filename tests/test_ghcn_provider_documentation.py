"""GHCN documentation through strict exports and the real dated consumer."""
from copy import deepcopy
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_observed_provider_documentation import by_id, rehash

V3 = "theheat.source-product-contracts/v3"
V4 = "theheat.source-product-contracts/v4"
GHCN = {"open_meteo_extreme_signals.ghcn_daily", "open_meteo_extreme_signals.ghcn_station_history"}
CHECKED = "2026-11-21T07:47:37Z"


def test_complete_pre_change_v3_export_stays_identical_and_decodable():
    document = products.product_contract_document(schema=V3)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == "1ec9558c1cc40a3f4c50bebc4d1b467ae6aeef1e44dede2cfea139784f3719a3"
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    assert all(by_id(document)[key][field] is None for key in GHCN for field in products.UNKNOWN_FIELDS)


def test_v4_scopes_dataset_cadence_without_granting_station_freshness_or_rights():
    before = by_id(products.product_contract_document(schema=V3))
    document = products.product_contract_document(schema=V4)
    after = by_id(document)
    assert products.GHCN_SCHEMA == V4  # Historical cadence contract stays pinned to v4.
    assert set(before) == set(after)
    assert {key for key in before if before[key] != after[key]} == GHCN
    for key in GHCN:
        cadence = after[key]["provider_cadence"]
        assert cadence["status"] == "documented" and cadence["checked_at"] == CHECKED
        assert "daily" in cadence["summary"] and "weekend" in cadence["summary"]
        assert "not" in cadence["limits"] and "station" in cadence["limits"]
        assert "QC" in cadence["limits"] and "guarantee" in cadence["limits"]
        assert all(after[key][field] is None for field in ("reuse_rights", "provider_quota", "cost"))
        stripped = deepcopy(after[key])
        stripped["provider_cadence"] = None
        assert stripped == before[key]
    for field in ("reuse_rights", "provider_quota", "cost"):
        missing = next(row for row in document["unmet_criteria"]
                       if row["field"] == field and row["status"] == "unknown")
        assert GHCN <= set(missing["products"])
    assert document["current_availability"] == "unverified"
    assert document["operational_recovery"] == document["source_independence"] == "not_established"
    assert document["coverage_denominator"] is None and document["claim_permission_granted"] is False
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]


@pytest.mark.parametrize("schema,cutoff,status", [
    (V3, "2026-11-21T07:47:36Z", "current"),
    (V4, "2026-11-21T07:47:36Z", "held"),
    (V4, CHECKED, "current"),
])
def test_existing_cli_accepts_new_cadence_only_at_its_documentation_cutoff(schema, cutoff, status, tmp_path):
    source, output = tmp_path / "input.json", tmp_path / "result"
    source.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": cutoff,
        "components": [{"component_type": "source_products",
                        "export": products.product_contract_document(schema=schema)}]}))
    result = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source),
                             "--output-dir", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "readiness.json").read_bytes())
    assert report["components"][0]["status"] == status
    assert report["unmet_requirements"]["P17"] and report["evidence_states"]["unsupported"] == []
    if status == "held":
        assert report["components"][0]["reasons"] == ["provider_documentation_after_cutoff"]


@pytest.mark.parametrize("mutation", [
    lambda row: row["provider_cadence"].__setitem__("summary", "Each station reports fresh observations daily"),
    lambda row: row["provider_cadence"].__setitem__("checked_at", "2026-10-01T00:00:00Z"),
    lambda row: row["provider_cadence"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row.__setitem__("reuse_rights", {"status": "documented", "summary": "Unrestricted global reuse"}),
    lambda row: row.__setitem__("provider_quota", 100),
    lambda row: row.__setitem__("cost", 0),
])
def test_rehashed_document_cannot_turn_dataset_updates_into_extra_permission(mutation):
    document = products.product_contract_document(schema=V4)
    mutation(by_id(document)[sorted(GHCN)[0]])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_new_cadence_cannot_be_borrowed_by_other_products_or_old_exports():
    document = products.product_contract_document(schema=V4)
    rows = by_id(document)
    rows["open_meteo_extreme_signals.om_forecast"]["provider_cadence"] = deepcopy(rows[sorted(GHCN)[0]]["provider_cadence"])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))
    document = products.product_contract_document(schema=V4)
    document["schema"] = V3
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_documented_cadence_does_not_clear_other_product_or_availability_gaps():
    document = products.product_contract_document(schema=V4)
    rows = by_id(document)
    missing = next(row for row in document["unmet_criteria"]
                   if row["field"] == "provider_cadence" and row["status"] == "unknown")
    assert "open_meteo_extreme_signals.om_forecast" in missing["products"]
    assert not GHCN.intersection(missing["products"])
    assert rows["open_meteo_extreme_signals.om_forecast"]["provider_cadence"] is None
    document["unmet_criteria"] = [row for row in document["unmet_criteria"]
                                if row["field"] != "current_availability"]
    with pytest.raises(ValueError, match="source_product_export_summary"):
        products.decode_product_contract_document(rehash(document))
