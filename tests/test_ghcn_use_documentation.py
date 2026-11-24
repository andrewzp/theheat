"""GHCN citation and use limits remain partial facts through the real consumer."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from tests.test_observed_provider_documentation import by_id, rehash

V8 = "theheat.source-product-contracts/v8"
V9 = "theheat.source-product-contracts/v9"
CHECKED = "2026-11-24T19:01:10Z"
GHCN = {
    "open_meteo_extreme_signals.ghcn_daily": "noaa_ncei.ghcn_daily_superghcnd_diff",
    "open_meteo_extreme_signals.ghcn_station_history": "noaa_ncei.ghcn_daily_station_archive",
    "open_meteo_extreme_signals.ghcn_archive_observations": "noaa_ncei.ghcn_daily_station_archive",
}
REFERENCES = [
    {"url": "https://www.ncei.noaa.gov/pub/data/cdo/documentation/GHCND_documentation.pdf",
     "sha256": "d67e69ce657d175dd301c2b9cdb162ff5be95327c9247f82235b1228577d717b"},
    {"url": "https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt",
     "sha256": "0e4e6f0e6947cf1add884c328a01760f31c56ef5fb86b85ed57dd5dc4c4aeaa6"},
]
HISTORICAL_HASHES = (
    "dc4f2ae2c4c9daeff22dd6e6c2429d2da7c3922f2795954ecbb14a14dd4f3081",
    "3752622c1b4465ade98d9f37be2a2793d5ab796aec50abe92025e943ac099ebe",
    "1ec9558c1cc40a3f4c50bebc4d1b467ae6aeef1e44dede2cfea139784f3719a3",
    "6313bea9af27a23164955a2500686d7e22a0a114cc418b24cc730809658763f3",
    "37d92dc95e08a047787fa12daa9dd35729dc501dda01a91bb59e88a1f5030f48",
    "b0ec4fa9d893180389ce6eadf3c33d2061915886268372ec9bac33581bed873d",
    "9a84f5050f0b5ebb5ea925c3db2a7d6f0d11ee85f39b9376f4945a8cae98573e",
    "647ad22b9c58651f86ee2a31cd7e8216d2766e363b27949c78ac206912a76946",
)


def test_default_v9_adds_only_three_partial_use_facts_to_the_existing_inventory():
    previous = products.product_contract_document(schema=V8)
    current = products.product_contract_document()
    assert current["schema"] == V9
    old, new = by_id(previous), by_id(current)
    assert set(old) == set(new)
    assert {key for key in old if old[key] != new[key]} == GHCN.keys()
    for key in GHCN:
        stripped = deepcopy(new[key])
        stripped["reuse_rights"] = None
        assert stripped == old[key]
        assert new[key]["provider_cadence"]["checked_at"] == "2026-11-21T07:47:37Z"
    for field in previous.keys() - {"schema", "products", "contracts_sha256", "unmet_criteria"}:
        assert current[field] == previous[field]
    assert products.verify_product_contract_document(current) == current["contracts_sha256"]


@pytest.mark.parametrize("product_id", sorted(GHCN))
def test_use_fact_preserves_citation_and_international_redistribution_limits(product_id):
    document = products.product_contract_document()
    row = by_id(document)[product_id]
    fact = row["reuse_rights"]
    assert fact is not None and fact["status"] == "partial" and fact["checked_at"] == CHECKED
    assert fact["references"] == REFERENCES
    assert all(term in fact["summary"] for term in ("citation", "version", "subset", "access date", "non-commercial"))
    assert all(term in fact["limits"] for term in
               ("2016", "non-US", "onward", "derived products", "commercial", "current", "unqualified",
                "social", "third-party", "quota", "cost", "activation"))
    assert row["provider"] == "noaa_ncei_ghcn" and row["upstream"] == GHCN[product_id]
    assert row["cost"] is None and row["provider_quota"] is None
    assert row["claim_permission_granted"] is False
    assert any(gap["field"] == "reuse_rights" and gap["status"] == "partial"
               and product_id in gap["products"] for gap in document["unmet_criteria"])


@pytest.mark.parametrize("version", range(1, 9))
def test_all_eight_historical_exports_keep_their_complete_bytes_and_decode(version):
    document = products.product_contract_document(schema=f"theheat.source-product-contracts/v{version}")
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    assert hashlib.sha256(raw).hexdigest() == HISTORICAL_HASHES[version - 1]
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    assert all(by_id(document)[key]["reuse_rights"] is None for key in GHCN if key in by_id(document))


@pytest.mark.parametrize("product_id", sorted(GHCN))
@pytest.mark.parametrize("change", ["product_id", "provider", "upstream"])
def test_use_fact_requires_exact_product_provider_and_upstream(product_id, change):
    leg = products.legs_by_id()[product_id]
    changed = replace(leg, **{change: getattr(leg, change) + "_unqualified"})
    assert products._provider_fields(changed)["reuse_rights"] is None


@pytest.mark.parametrize("field,value", [
    ("status", "documented"),
    ("summary", "Unrestricted global reuse"),
    ("limits", "No restrictions"),
    ("checked_at", "2016-05-05T00:00:00Z"),
    ("references", [{"url": REFERENCES[0]["url"], "sha256": "0" * 64}]),
    ("references", [{"url": "https://example.invalid/terms", "sha256": REFERENCES[0]["sha256"]}]),
])
def test_rehashing_cannot_upgrade_or_redate_the_use_fact(field, value):
    document = products.product_contract_document(schema=V9)
    by_id(document)[sorted(GHCN)[0]]["reuse_rights"][field] = value
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


@pytest.mark.parametrize("field,value", [("cost", 0), ("provider_quota", 100),
                                        ("reuse_rights", None), ("claim_permission_granted", True)])
def test_partial_use_fact_cannot_clear_cost_quota_or_claim_holds(field, value):
    document = products.product_contract_document(schema=V9)
    by_id(document)[sorted(GHCN)[0]][field] = value
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_readiness_gaps_cannot_be_removed_and_use_evidence_cannot_be_borrowed():
    original = products.product_contract_document(schema=V9)
    for target in ("open_meteo_extreme_signals.ghcn_daily_access_hints",
                   "open_meteo_extreme_signals.om_forecast", "awc_observed.metar_observations"):
        document = deepcopy(original)
        by_id(document)[target]["reuse_rights"] = deepcopy(by_id(document)[sorted(GHCN)[0]]["reuse_rights"])
        with pytest.raises(ValueError, match="source_product_export_permission"):
            products.decode_product_contract_document(rehash(document))
    document = deepcopy(original)
    document["unmet_criteria"] = [gap for gap in document["unmet_criteria"]
                                if not (gap["field"] == "reuse_rights" and gap["status"] == "partial")]
    with pytest.raises(ValueError, match="source_product_export_summary"):
        products.decode_product_contract_document(rehash(document))
    assert all(by_id(original)["open_meteo_extreme_signals.ghcn_daily_access_hints"][field] is None
               for field in products.UNKNOWN_FIELDS)


@pytest.mark.parametrize("old,new", [(V8, V9), (V9, V8)])
def test_schema_relabelling_does_not_move_use_facts_across_historical_exports(old, new):
    document = products.product_contract_document(schema=old)
    document["schema"] = new
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


@pytest.mark.parametrize("schema,cutoff,status", [
    (V8, "2026-11-24T19:01:09Z", "current"),
    (V9, "2026-11-24T19:01:09Z", "held"),
    (V9, "2026-11-24T19:01:09.100000Z", "held"),
    (V9, CHECKED, "current"),
    (V9, "2026-11-24T19:01:11Z", "current"),
])
def test_actual_readiness_cli_qualifies_documentation_time_and_keeps_p17_open(schema, cutoff, status, tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "report"
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


def test_export_is_detached_and_partial_use_documentation_establishes_no_operating_outcome():
    original = products.product_contract_document(schema=V9)
    assert original["claim_permission_granted"] is False
    assert original["current_availability"] == "unverified" and original["coverage_denominator"] is None
    assert original["source_independence"] == original["operational_recovery"] == "not_established"
    edited = deepcopy(original)
    by_id(edited)[sorted(GHCN)[0]]["reuse_rights"]["references"][0]["sha256"] = "0" * 64
    assert products.product_contract_document(schema=V9) == original
