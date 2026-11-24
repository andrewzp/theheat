"""FIRMS service limits remain scoped documentation, never key capacity or truth."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_crw_reuse_documentation import LEGACY_HASHES
from tests.test_observed_provider_documentation import by_id, rehash

V7 = "theheat.source-product-contracts/v7"
V8 = "theheat.source-product-contracts/v8"
CHECKED = "2026-11-22T05:08:14Z"
URL = "https://firms.modaps.eosdis.nasa.gov/api/area/"
DOCUMENT_SHA = "cf7e8c1a26561bd42f4829ae6b45c697195d4ff24798f3be6aa2242ad14fcb64"
FIRMS = {f"firms.{name}": f"nasa_firms.{name}"
         for name in ("viirs_noaa21_nrt", "viirs_noaa20_nrt", "modis_nrt")}
V7_SHA = "9a84f5050f0b5ebb5ea925c3db2a7d6f0d11ee85f39b9376f4945a8cae98573e"


def test_historical_v8_adds_only_three_partial_firms_quotas_to_existing_inventory():
    previous = products.product_contract_document(schema=V7)
    current = products.product_contract_document(schema=V8)
    assert current["schema"] == V8
    old, new = by_id(previous), by_id(current)
    assert set(old) == set(new)
    assert {name for name in old if old[name] != new[name]} == FIRMS.keys()
    for name in FIRMS:
        stripped = deepcopy(new[name])
        stripped["provider_quota"] = None
        assert stripped == old[name]
    for field in previous.keys() - {"schema", "products", "contracts_sha256", "unmet_criteria"}:
        assert current[field] == previous[field]
    assert products.verify_product_contract_document(current) == current["contracts_sha256"]


@pytest.mark.parametrize("product_id", sorted(FIRMS))
def test_published_default_is_weighted_transactions_not_our_key_budget(product_id):
    document = products.product_contract_document()
    row = by_id(document)[product_id]
    fact = row["provider_quota"]
    assert fact is not None and fact["status"] == "partial" and fact["checked_at"] == CHECKED
    assert all(text in fact["summary"] for text in ("5000", "10-minute", "MAP_KEY", "transactions", "multiple"))
    assert all(text in fact["limits"] for text in ("default", "actual", "remaining", "HTTP", "enforcement", "cost", "availability"))
    assert fact["references"] == [{"url": URL, "sha256": DOCUMENT_SHA}]
    assert row["provider"] == "nasa_firms" and row["upstream"] == FIRMS[product_id]
    assert all(row[field] is None for field in ("provider_cadence", "reuse_rights", "cost"))
    assert row["claim_permission_granted"] is False
    assert any(item["field"] == "provider_quota" and item["status"] == "partial"
               and product_id in item["products"] for item in document["unmet_criteria"])


@pytest.mark.parametrize("product_id", ["firms.noaa_hms", "firms.viirs_snpp_nrt"])
def test_hms_and_retired_snpp_never_inherit_nasa_service_quota(product_id):
    old, new = (by_id(products.product_contract_document(schema=schema))[product_id]
                for schema in (V7, products.SCHEMA))
    assert new == old and new["provider_quota"] is None
    if product_id.endswith("snpp_nrt"):
        assert new["status"] == "retired"


@pytest.mark.parametrize("version", range(1, 8))
def test_all_seven_complete_historical_exports_keep_exact_bytes(version):
    document = products.product_contract_document(schema=f"theheat.source-product-contracts/v{version}")
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == (*LEGACY_HASHES, V7_SHA)[version - 1]
    assert all(by_id(document)[key]["provider_quota"] is None for key in FIRMS)
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]


@pytest.mark.parametrize("product_id", sorted(FIRMS))
@pytest.mark.parametrize("change", ["product", "provider", "upstream"])
def test_quota_requires_exact_installed_product_provider_and_upstream(product_id, change):
    leg = products.legs_by_id()[product_id]
    fields = {"product_id": product_id + "_other"} if change == "product" else (
        {"provider": "noaa_nesdis_hms"} if change == "provider" else {"upstream": "nasa_firms.unreviewed"})
    assert products._provider_fields(replace(leg, **fields))["provider_quota"] is None


@pytest.mark.parametrize("mutation", [
    lambda row: row["provider_quota"].__setitem__("status", "documented"),
    lambda row: row["provider_quota"].__setitem__("summary", "5000 HTTP requests per product every minute"),
    lambda row: row["provider_quota"].__setitem__("limits", "Reserved independent capacity with no limits"),
    lambda row: row["provider_quota"].__setitem__("checked_at", "2026-01-01T00:00:00Z"),
    lambda row: row["provider_quota"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row["provider_quota"]["references"][0].__setitem__("url", "https://example.invalid/terms"),
    lambda row: row.__setitem__("provider_quota", None),
    lambda row: row.__setitem__("cost", 0),
    lambda row: row.__setitem__("reuse_rights", {"status": "documented", "summary": "All imagery cleared"}),
    lambda row: row.__setitem__("claim_permission_granted", True),
])
def test_rehashed_export_cannot_clear_unknowns_or_change_partial_documentation(mutation):
    document = products.product_contract_document()
    row = by_id(document)[sorted(FIRMS)[0]]
    # On the baseline the quota is absent; the mutation still must not grant one.
    if row["provider_quota"] is None:
        row["provider_quota"] = {"status": "partial", "summary": "invented baseline control",
                                 "limits": "unknown", "checked_at": CHECKED,
                                 "references": [{"url": URL, "sha256": DOCUMENT_SHA}]}
    mutation(row)
    rehash(document)
    with pytest.raises(ValueError):
        products.verify_product_contract_document(document)


@pytest.mark.parametrize("schema,cutoff,status", [
    (V7, "2026-11-22T05:08:13Z", "current"),
    (V8, "2026-11-22T05:08:13Z", "held"),
    (V8, CHECKED, "current"),
    (V8, "2026-11-22T05:08:15Z", "current"),
])
def test_real_readiness_cli_preserves_review_time_and_unmet_quota(schema, cutoff, status, tmp_path):
    document = products.product_contract_document(schema=schema)
    source, output = tmp_path / "source.json", tmp_path / "report"
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


def test_quota_export_is_detached_and_grants_no_current_service_or_corroboration():
    document = products.product_contract_document()
    assert document["current_availability"] == "unverified"
    assert document["source_independence"] == "not_established"
    assert document["claim_permission_granted"] is False and document["coverage_denominator"] is None
    before = products.product_contract_document()
    by_id(document)[sorted(FIRMS)[0]]["provider_quota"]["summary"] = "not retained"
    assert products.product_contract_document() == before
