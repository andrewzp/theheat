"""Dated provider documentation is not current weather, access or permission."""
from copy import deepcopy
import hashlib
import json
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products

V1 = "theheat.source-product-contracts/v1"
V2 = "theheat.source-product-contracts/v2"
AWC = "awc_observed.metar_observations"
STATIONS = "awc_observed.station_catalogue"
FIRE = "fire_footprint.wfigs_incidents"
FIRE_WITNESS = "newsworthiness.nifc_incidents"
DOCUMENTED = {AWC, STATIONS, FIRE, FIRE_WITNESS}


def by_id(document):
    return {row["product_id"]: row for row in document["products"]}


def rehash(document):
    body = {key: value for key, value in document.items() if key != "contracts_sha256"}
    document["contracts_sha256"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()
    return document


def test_default_export_contains_scoped_dated_provider_facts_and_no_grants():
    document = products.product_contract_document()
    assert document["schema"] == V2
    rows = by_id(document)
    assert {key for key, row in rows.items() if row["provider_cadence"] is not None} == DOCUMENTED
    for key in DOCUMENTED:
        fact = rows[key]["provider_cadence"]
        assert fact["status"] == "documented" and fact["checked_at"] == "2026-11-18T07:44:10Z"
        assert fact["references"] and fact["limits"]
        for ref in fact["references"]:
            assert ref["url"].startswith("https://")
            assert len(ref["sha256"]) == 64
        if key == STATIONS:
            assert rows[key]["provider_quota"] is None
        else:
            assert rows[key]["provider_quota"]["status"] == "partial"
        assert rows[key]["reuse_rights"]["status"] == "partial"
        assert rows[key]["cost"] is None
    assert document["claim_permission_granted"] is False
    assert document["current_availability"] == "unverified"
    assert document["operational_recovery"] == "not_established"
    assert document["source_independence"] == "not_established"
    assert document["coverage_denominator"] is None
    assert all(row["claim_permissions"] == [] and row["claim_permission_granted"] is False
               for row in rows.values())
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]


def test_legacy_export_is_byte_equivalent_to_accepted_127_and_stays_unknown():
    document = products.product_contract_document(schema=V1)
    assert document["schema"] == V1
    assert document["contracts_sha256"] == "9642145d299b8ccb3bbfb273d8bc4f773d9f15420e715e4d7663b5fb0a1f793d"
    assert all(row[field] is None for row in document["products"] for field in products.UNKNOWN_FIELDS)
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    assert {row["products"] for row in document["unmet_criteria"] if row["field"] in products.UNKNOWN_FIELDS} == {"all"}


def test_cadence_is_product_scoped_and_is_not_a_freshness_or_rate_promise():
    rows = by_id(products.product_contract_document())
    assert "minute" in rows[AWC]["provider_cadence"]["summary"]
    assert "day" in rows[STATIONS]["provider_cadence"]["summary"]
    assert rows[AWC]["provider_cadence"] != rows[STATIONS]["provider_cadence"]
    assert "observation" in rows[AWC]["provider_cadence"]["limits"].lower()
    assert "5 minutes" in rows[FIRE]["provider_cadence"]["summary"]
    assert "hourly" in rows[FIRE]["provider_cadence"]["summary"]
    assert "2000" in rows[FIRE]["provider_quota"]["summary"]
    assert "rate" in rows[FIRE]["provider_quota"]["limits"]
    assert "cache" in rows[AWC]["provider_quota"]["limits"].lower()
    assert rows[FIRE]["provider_cadence"] == rows[FIRE_WITNESS]["provider_cadence"]
    assert products.max_independent_source_count([FIRE, FIRE_WITNESS]) == 1


def test_partial_evidence_and_unrelated_products_remain_in_exact_unmet_rows():
    document = products.product_contract_document()
    rows = by_id(document)
    gaps = {(row["field"], row["status"]): row["products"] for row in document["unmet_criteria"]
            if row["field"] in products.UNKNOWN_FIELDS}
    assert set(gaps[("provider_cadence", "unknown")]) == set(rows) - DOCUMENTED
    for field, partial in (("provider_quota", DOCUMENTED - {STATIONS}), ("reuse_rights", DOCUMENTED)):
        assert set(gaps[(field, "partial")]) == partial
        assert set(gaps[(field, "unknown")]) == set(rows) - partial
    assert set(gaps[("cost", "unknown")]) == set(rows)
    assert all(rows[key][field] is None for key in set(rows) - DOCUMENTED for field in products.UNKNOWN_FIELDS)


@pytest.mark.parametrize("mutation", [
    lambda row: row["provider_cadence"].__setitem__("status", "partial"),
    lambda row: row["provider_cadence"].__setitem__("checked_at", "2026-11-17"),
    lambda row: row["provider_cadence"].__setitem__("summary", "Invented update guarantee"),
    lambda row: row["provider_cadence"]["references"][0].__setitem__("url", "https://example.invalid/"),
    lambda row: row["provider_cadence"]["references"][0].__setitem__("sha256", "0" * 64),
    lambda row: row.__setitem__("provider_quota", 100),
    lambda row: row["reuse_rights"].__setitem__("status", "documented"),
    lambda row: row.__setitem__("cost", 0),
    lambda row: row.__setitem__("provider_cadence", None),
])
def test_rehashed_provider_fact_tampering_is_refused(mutation):
    document = products.product_contract_document()
    mutation(by_id(document)[AWC])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))


def test_partial_gap_cannot_be_removed_by_rehashing():
    document = products.product_contract_document()
    document["unmet_criteria"] = [row for row in document["unmet_criteria"]
                                if not (row["field"] == "reuse_rights" and row["status"] == "partial")]
    with pytest.raises(ValueError, match="source_product_export_summary"):
        products.decode_product_contract_document(rehash(document))


def test_versions_cannot_borrow_each_others_provider_evidence():
    for old, new in ((V1, V2), (V2, V1)):
        document = products.product_contract_document(schema=old)
        document["schema"] = new
        with pytest.raises(ValueError, match="source_product_export_permission"):
            products.decode_product_contract_document(rehash(document))
    with pytest.raises(ValueError, match="source_product_export_schema"):
        products.product_contract_document(schema="theheat.source-product-contracts/v99")


def test_export_is_detached_and_unrelated_product_cannot_borrow_evidence():
    document = products.product_contract_document()
    original = deepcopy(document)
    other = next(row for row in document["products"] if row["product_id"] not in DOCUMENTED)
    other["provider_cadence"] = deepcopy(by_id(document)[AWC]["provider_cadence"])
    with pytest.raises(ValueError, match="source_product_export_permission"):
        products.decode_product_contract_document(rehash(document))
    by_id(document)[AWC]["provider_cadence"]["references"][0]["sha256"] = "0" * 64
    assert products.product_contract_document() == original


@pytest.mark.parametrize("schema", [None, [], {}, 0, True])
def test_malformed_schema_is_a_bounded_refusal_not_a_consumer_crash(schema):
    document = products.product_contract_document()
    document["schema"] = schema
    with pytest.raises(ValueError, match="source_product_export_schema"):
        products.decode_product_contract_document(rehash(document))
    with pytest.raises(ValueError, match="source_product_export_schema"):
        products.product_contract_document(schema=schema)


@pytest.mark.parametrize("schema", [V1, V2])
def test_existing_readiness_cli_accepts_both_versions_without_completing_p17(schema, tmp_path):
    root = tmp_path.resolve()
    source = root / "input.json"
    output = root / "result"
    source.write_text(json.dumps({"schema_version": 1, "assessment_cutoff": "2026-11-18T08:00:00Z",
        "components": [{"component_type": "source_products",
                        "export": products.product_contract_document(schema=schema)}]}))
    result = subprocess.run([sys.executable, "scripts/summarize_global_readiness.py",
                             "--input", str(source), "--output-dir", str(output)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "readiness.json").read_text())
    assert report["evidence_states"]["unsupported"] == []
    assert report["unmet_requirements"]["P17"]


@pytest.mark.parametrize("schema,cutoff,expected", [
    (V1, "2026-10-11T00:00:00Z", "current"),
    (V2, "2026-11-18T07:44:09Z", "held"),
    (V2, "2026-11-18T07:44:10Z", "current"),
])
def test_documentation_cannot_be_backdated_into_a_historical_assessment(schema, cutoff, expected):
    from src.evaluation import global_readiness
    result = global_readiness.assess({"schema_version": 1, "assessment_cutoff": cutoff,
        "components": [{"component_type": "source_products",
                        "export": products.product_contract_document(schema=schema)}]})
    component = result["components"][0]
    assert component["status"] == expected
    if expected == "held":
        assert component["reasons"] == ["provider_documentation_after_cutoff"]
        assert result["unmet_requirements"]["P17"]
