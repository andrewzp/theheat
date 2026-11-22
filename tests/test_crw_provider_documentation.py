"""Historical v6 CRW cadence remains exact through the existing dated reader."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_observed_provider_documentation import by_id, rehash

V5 = "theheat.source-product-contracts/v5"
V6 = "theheat.source-product-contracts/v6"
CHECKED = "2026-11-22T01:46:45Z"
CRW = {"ocean_sst_anomaly.coastwatch_erddap", "ocean_sst_anomaly.noaa_star_nc"}
URL = "https://coralreefwatch.noaa.gov/product/5km/methodology.php"
DOCUMENT_SHA = "402f7b1c4629bdec4e2749e37351826e8e202bd8900afa9fd9ad415b02f66273"


def test_v6_document_includes_crw_cadence_without_replacing_v5_inventory():
    before = products.product_contract_document(schema=V5)
    current = products.product_contract_document(schema=V6)
    assert current["schema"] == V6
    old, new = by_id(before), by_id(current)
    assert set(old) == set(new)
    assert {key for key in old if old[key] != new[key]} == CRW
    for key in CRW:
        stripped = deepcopy(new[key])
        stripped["provider_cadence"] = None
        assert stripped == old[key]
    for field in ("adapters", "shared_upstream_groups", "missing_work", "restrictions",
                  "current_availability", "operational_recovery", "source_independence",
                  "coverage_denominator", "unknown_fields", "claim_permission_granted"):
        assert current[field] == before[field]
    assert products.verify_product_contract_document(current) == current["contracts_sha256"]


@pytest.mark.parametrize("product_id", sorted(CRW))
def test_exact_ssta_routes_have_daily_product_cadence_not_delivery_or_coverage(product_id):
    row = by_id(products.product_contract_document(schema=V6))[product_id]
    fact = row["provider_cadence"]
    assert fact is not None
    assert fact["status"] == "documented" and fact["checked_at"] == CHECKED
    assert "daily" in fact["summary"] and "5 km" in fact["summary"] and "v3.1" in fact["summary"]
    assert "not" in fact["limits"] and "delivery" in fact["limits"] and "guarantee" in fact["limits"]
    assert fact["references"] == [{"url": URL, "sha256": DOCUMENT_SHA}]
    assert all(row[field] is None for field in ("provider_quota", "reuse_rights", "cost"))
    assert row["data_kind"] == "satellite_derived" and row["claim_permission_granted"] is False


@pytest.mark.parametrize("version", range(1, 6))
def test_historical_versions_keep_their_original_unknown_crw_fields(version):
    document = products.product_contract_document(schema=f"theheat.source-product-contracts/v{version}")
    assert all(by_id(document)[key][field] is None for key in CRW for field in products.UNKNOWN_FIELDS)
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]


def test_complete_existing_v5_export_remains_byte_identical():
    document = products.product_contract_document(schema=V5)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == "37d92dc95e08a047787fa12daa9dd35729dc501dda01a91bb59e88a1f5030f48"
    assert {"open_meteo_extreme_signals.ghcn_daily_access_hints",
            "open_meteo_extreme_signals.ghcn_archive_observations"} <= by_id(document).keys()


@pytest.mark.parametrize("schema,cutoff,status", [
    (V5, "2026-11-22T01:46:44Z", "current"),
    (None, "2026-11-22T01:46:44Z", "held"),
    (None, CHECKED, "current"),
    (None, "2026-11-22T01:46:46Z", "current"),
])
def test_real_readiness_cli_does_not_backdate_crw_documentation(schema, cutoff, status, tmp_path):
    document = products.product_contract_document(schema=schema or V6)
    source, output = tmp_path / "input.json", tmp_path / "result"
    source.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": cutoff,
        "components": [{"component_type": "source_products", "export": document}]}))
    result = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py", "--input", str(source),
                             "--output-dir", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "readiness.json").read_bytes())
    assert report["components"][0]["status"] == status
    assert report["unmet_requirements"]["P17"] and report["evidence_states"]["unsupported"] == []
    if status == "held":
        assert report["components"][0]["reasons"] == ["provider_documentation_after_cutoff"]


@pytest.mark.parametrize("provider,upstream", [("noaa_awc", "noaa_crw.ssta_daily_v3_1"),
                                              ("noaa_crw", "noaa_crw.dhw_daily_v3_1")])
def test_source_fact_cannot_be_borrowed_by_a_relabelled_product(provider, upstream):
    leg = products.legs_by_id()[sorted(CRW)[0]]
    altered = replace(leg, provider=provider, upstream=upstream)
    assert products._provider_fields(altered, schema=V6)["provider_cadence"] is None


@pytest.mark.parametrize("mutation", [
    lambda row: row["provider_cadence"].__setitem__("summary", "Every regional route serves fresh data at noon UTC"),
    lambda row: row["provider_cadence"].__setitem__("checked_at", "2026-10-01T00:00:00Z"),
    lambda row: row["provider_cadence"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row.__setitem__("provider_cadence", None),
    lambda row: row.__setitem__("provider_quota", 100),
    lambda row: row.__setitem__("reuse_rights", {"status": "documented", "summary": "Unrestricted imagery reuse"}),
    lambda row: row.__setitem__("cost", 0),
])
def test_rehash_cannot_change_documented_cadence_or_clear_other_unknowns(mutation):
    document = products.product_contract_document(schema=V6)
    mutation(by_id(document)[sorted(CRW)[0]])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_unrelated_crw_products_and_missing_work_keep_their_own_bounds():
    document = products.product_contract_document(schema=V6)
    rows = by_id(document)
    missing = {row["field"]:set(row["products"]) for row in document["unmet_criteria"]
               if row.get("status") == "unknown" and "products" in row}
    assert not CRW.intersection(missing["provider_cadence"])
    for field in ("provider_quota", "reuse_rights", "cost"):
        assert CRW <= missing[field]
    dhw = "coral_dhw.crw_erddap"
    assert rows[dhw]["provider_cadence"] is None and dhw in missing["provider_cadence"]
    rows[dhw]["provider_cadence"] = deepcopy(rows[sorted(CRW)[0]]["provider_cadence"])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_new_facts_do_not_mutate_later_exports_or_clear_availability():
    document = products.product_contract_document(schema=V6)
    previous = deepcopy(document)
    by_id(document)[sorted(CRW)[0]]["provider_cadence"]["summary"] = "changed"
    assert products.product_contract_document(schema=V6) == previous
    assert previous["current_availability"] == "unverified"
    assert previous["operational_recovery"] == previous["source_independence"] == "not_established"
    assert previous["coverage_denominator"] is None and previous["claim_permission_granted"] is False
