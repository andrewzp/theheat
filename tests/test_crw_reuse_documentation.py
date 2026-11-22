"""CRW terms reach the strict dated consumer without clearing other source gates."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_observed_provider_documentation import by_id, rehash

V6 = "theheat.source-product-contracts/v6"
V7 = "theheat.source-product-contracts/v7"
CHECKED = "2026-11-22T02:59:20Z"
URL = "https://coralreefwatch.noaa.gov/satellite/docs/recommendations_crw_citation.php"
DOCUMENT_SHA = "eaf0a271b96c1950eb5897691a8f56899cba5c9c97316216421b0f645c59f93a"
CRW = {
    "ocean_sst_anomaly.coastwatch_erddap": "noaa_crw.ssta_daily_v3_1",
    "ocean_sst_anomaly.noaa_star_nc": "noaa_crw.ssta_daily_v3_1",
    "coral_dhw.crw_virtual_station": "noaa_crw.regional_virtual_stations",
    "coral_dhw.crw_erddap": "noaa_crw.dhw_daily_v3_1",
}
LEGACY_HASHES = (
    "dc4f2ae2c4c9daeff22dd6e6c2429d2da7c3922f2795954ecbb14a14dd4f3081",
    "3752622c1b4465ade98d9f37be2a2793d5ab796aec50abe92025e943ac099ebe",
    "1ec9558c1cc40a3f4c50bebc4d1b467ae6aeef1e44dede2cfea139784f3719a3",
    "6313bea9af27a23164955a2500686d7e22a0a114cc418b24cc730809658763f3",
    "37d92dc95e08a047787fa12daa9dd35729dc501dda01a91bb59e88a1f5030f48",
    "b0ec4fa9d893180389ce6eadf3c33d2061915886268372ec9bac33581bed873d",
)


def test_default_v7_adds_only_four_reuse_facts_and_preserves_all_source_bounds():
    old = products.product_contract_document(schema=V6)
    current = products.product_contract_document()
    assert current["schema"] == V7
    before, after = by_id(old), by_id(current)
    assert set(before) == set(after)
    assert {key for key in before if before[key] != after[key]} == CRW.keys()
    for key in CRW:
        stripped = deepcopy(after[key])
        stripped["reuse_rights"] = None
        assert stripped == before[key]
    for field in old.keys() - {"schema", "products", "contracts_sha256", "unmet_criteria"}:
        assert current[field] == old[field]
    assert products.max_independent_source_count(sorted(CRW)) == 2
    assert products.verify_product_contract_document(current) == current["contracts_sha256"]


@pytest.mark.parametrize("product_id", sorted(CRW))
def test_new_terms_name_crw_data_credit_and_exclusions_without_a_claim_grant(product_id):
    row = by_id(products.product_contract_document())[product_id]
    fact = row["reuse_rights"]
    assert fact is not None and fact["status"] == "partial" and fact["checked_at"] == CHECKED
    assert "public domain" in fact["summary"] and "credit" in fact["summary"]
    assert "NOAA Coral Reef Watch" in fact["summary"] and "citation" in fact["summary"]
    assert all(word in fact["limits"] for word in ("third-party", "logos", "access", "cost", "qualification"))
    assert fact["references"] == [{"url": URL, "sha256": DOCUMENT_SHA}]
    assert row["provider"] == "noaa_crw" and row["upstream"] == CRW[product_id]
    assert row["provider_quota"] is None and row["cost"] is None
    assert row["data_kind"] == "satellite_derived" and row["claim_permission_granted"] is False


@pytest.mark.parametrize("version", range(1, 7))
def test_complete_legacy_exports_keep_bytes_and_unknown_rights(version):
    document = products.product_contract_document(schema=f"theheat.source-product-contracts/v{version}")
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == LEGACY_HASHES[version - 1]
    assert all(by_id(document)[key]["reuse_rights"] is None for key in CRW)
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]


@pytest.mark.parametrize("schema,cutoff,status", [
    (V6, "2026-11-22T02:59:19Z", "current"),
    (V7, "2026-11-22T02:59:19Z", "held"),
    (V7, CHECKED, "current"),
    (V7, "2026-11-22T02:59:21Z", "current"),
])
def test_existing_cli_honors_new_terms_review_time_without_clearing_p17(schema, cutoff, status, tmp_path):
    document = products.product_contract_document(schema=schema)
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


@pytest.mark.parametrize("product_id", sorted(CRW))
@pytest.mark.parametrize("change", ["provider", "upstream", "product"])
def test_terms_require_exact_product_provider_and_upstream(product_id, change):
    leg = products.legs_by_id()[product_id]
    altered = replace(leg, **{"provider": "noaa_awc"} if change == "provider" else
                      {"upstream": "noaa_crw.unreviewed_product"} if change == "upstream" else
                      {"product_id": product_id + "_unreviewed"})
    assert products._provider_fields(altered, schema=V7)["reuse_rights"] is None


@pytest.mark.parametrize("mutation", [
    lambda row: row["reuse_rights"].__setitem__("summary", "All NOAA and third-party images may be used without credit"),
    lambda row: row["reuse_rights"].__setitem__("limits", "No limits"),
    lambda row: row["reuse_rights"].__setitem__("checked_at", "2026-10-01T00:00:00Z"),
    lambda row: row["reuse_rights"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row.__setitem__("reuse_rights", None),
    lambda row: row.__setitem__("provider_quota", 100),
    lambda row: row.__setitem__("cost", 0),
    lambda row: row.__setitem__("claim_permission_granted", True),
])
def test_rehash_cannot_change_or_expand_documented_terms(mutation):
    document = products.product_contract_document()
    mutation(by_id(document)[sorted(CRW)[0]])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_rights_gaps_change_only_for_the_named_products_and_exports_are_detached():
    document = products.product_contract_document()
    old = products.product_contract_document(schema=V6)
    before, after = by_id(old), by_id(document)
    def gaps(doc, field):
        return {key for row in doc["unmet_criteria"] if row["field"] == field for key in row["products"]}
    assert gaps(document, "reuse_rights") == gaps(old, "reuse_rights")
    for status in ("unknown", "partial"):
        before_ids = next(set(row["products"]) for row in old["unmet_criteria"]
                          if row["field"] == "reuse_rights" and row["status"] == status)
        after_ids = next(set(row["products"]) for row in document["unmet_criteria"]
                         if row["field"] == "reuse_rights" and row["status"] == status)
        assert after_ids == (before_ids - CRW.keys() if status == "unknown" else before_ids | CRW.keys())
    for field in ("provider_cadence", "provider_quota", "cost"):
        assert gaps(old, field) == gaps(document, field)
    assert all(after[key] == before[key] for key in before.keys() - CRW.keys())
    assert document["current_availability"] == "unverified" and document["coverage_denominator"] is None
    assert document["operational_recovery"] == document["source_independence"] == "not_established"
    assert document["claim_permission_granted"] is False
    original = deepcopy(document)
    after[sorted(CRW)[0]]["reuse_rights"]["summary"] = "changed"
    assert products.product_contract_document() == original


def test_crw_terms_cannot_clear_other_noaa_or_derived_combination_products():
    document = products.product_contract_document()
    rows = by_id(document)
    for target in ("awc_observed.metar_observations", "synthesis_fire_drought_heat.marine_compound"):
        altered = deepcopy(document)
        by_id(altered)[target]["reuse_rights"] = deepcopy(rows[sorted(CRW)[0]]["reuse_rights"])
        with pytest.raises(ValueError, match="source_product_export_permission"):
            products.decode_product_contract_document(rehash(altered))


def test_availability_and_website_redistribution_statements_have_separate_scopes():
    rows = by_id(products.product_contract_document())
    for product_id in CRW:
        fact = rows[product_id]["reuse_rights"]
        assert fact["status"] == "partial"
        assert fact["summary"].split("; ") == [
            "CRW internet data are freely available to the public",
            "CRW website content is public domain and freely distributable",
            "NOAA Coral Reef Watch credit and dataset citation are requested.",
        ]
        assert "separately served material remain unresolved" in fact["limits"]


def test_partial_terms_keep_every_exact_product_in_unmet_redistribution_work():
    document = products.product_contract_document()
    partial = next(row for row in document["unmet_criteria"]
                   if row["field"] == "reuse_rights" and row["status"] == "partial")
    assert CRW.keys() <= set(partial["products"])
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    altered = deepcopy(document)
    by_id(altered)[sorted(CRW)[0]]["reuse_rights"]["status"] = "documented"
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(altered))
