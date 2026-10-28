"""Per-product serving-leg contracts, checked against actual code without executing adapters."""

import ast
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.data import source_product_contracts as products
from src.data.source_registry import CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
BY_ID = products.legs_by_id()


def _module_symbols(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _string_literals(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def _mutated(target, /, **change):
    return tuple(replace(leg, **change) if leg.product_id == target else leg for leg in products.LEGS)


def test_every_wired_adapter_and_health_key_has_product_legs():
    document = products.product_contract_document()
    assert [row["source_id"] for row in document["adapters"]] == [row.source_id for row in CONTRACTS]
    assert len(CONTRACTS) == 30  # frozen accepted-base inventory: 29 alert collectors plus leaderboard
    for row in CONTRACTS:
        legs = [leg for leg in products.LEGS if leg.source_id == row.source_id]
        assert legs and {key for leg in legs for key in leg.health_keys} == set(row.health_keys)
        # No manufactured "unknown" product per adapter: every leg names real code.
        assert all(leg.code_refs for leg in legs)


def test_every_code_and_restriction_reference_names_a_real_module_symbol():
    references = [ref for leg in products.LEGS for ref in leg.code_refs]
    references += [ref for _meaning, _basis, ref in products.RESTRICTIONS.values()]
    for ref in references:
        path, symbol = ref.split(":")
        assert symbol in _module_symbols(path), ref
    assert {basis for _m, basis, _r in products.RESTRICTIONS.values()} == {"check", "advisory"}


def test_runtime_leg_labels_are_the_labels_the_actual_code_emits():
    for leg in products.LEGS:
        if leg.runtime_leg_label is None or leg.status == "retired":
            continue
        modules = {ref.split(":")[0] for ref in leg.code_refs}
        if leg.role == "cache":
            assert any("last_good" in _module_symbols(path) or "last_good.read" in (ROOT / path).read_text()
                       for path in modules), leg.product_id
            continue
        assert any(leg.runtime_leg_label in _string_literals(path) for path in modules), leg.product_id


def test_first_families_keep_observed_model_satellite_warning_and_discovery_distinct():
    assert BY_ID["open_meteo_extreme_signals.ghcn_daily"].data_kind == "observed_station"
    assert BY_ID["open_meteo_extreme_signals.om_forecast"].data_kind == "forecast_model"
    assert BY_ID["open_meteo_extreme_signals.om_era5_archive"].role == "reference"
    gpm = {leg.product_id.split(".")[1]: leg for leg in products.LEGS if leg.source_id == "gpm_imerg"}
    assert gpm["imerg_late_opendap"].role == "primary"
    assert {gpm["imerg_late_grid_datapool"].role, gpm["imerg_late_grid_s3"].role} == {"alternate_route"}
    assert (gpm["open_meteo_witness"].role, gpm["open_meteo_witness"].data_kind) == ("witness", "forecast_model")
    assert gpm["imerg_final_reference"].status == "retired"
    assert BY_ID["nhc.current_storms_index"].role == "primary"
    assert {BY_ID["nhc.public_advisory_text"].role, BY_ID["nhc.forecast_advisory_text"].role} == {"component"}
    assert BY_ID["jtwc.plain_rss"].role == "alternate_route"
    assert "ambiguous_episode_held" in BY_ID["gdacs.georss"].claim_restrictions
    assert BY_ID["gdacs.map_api"].status == "retired" and BY_ID["gdacs.reliefweb_witness"].status == "unresolved"
    assert BY_ID["firms.viirs_noaa21_nrt"].role == "primary" and BY_ID["firms.viirs_snpp_nrt"].status == "retired"
    assert BY_ID["ocean_sst_anomaly.noaa_star_nc"].role == "alternate_route"
    assert BY_ID["coral_dhw.crw_erddap"].role == "alternate_product"
    aq = {leg.product_id: leg for leg in products.LEGS if leg.source_id == "air_quality"}
    assert {aq["air_quality.cams_pm25"].chain, aq["air_quality.cams_dust"].chain} == {"aq_pm25", "aq_dust"}
    assert aq["air_quality.openaq_pm25"].role == "corroboration" and aq["air_quality.openaq_pm25"].status == "conditional"
    assert BY_ID["newsworthiness.grounded_search"].data_kind == "discovery"
    assert BY_ID["synthesis_fire_drought_heat.component_overlap"].data_kind == "derived_combination"


@pytest.mark.parametrize("product_id,change,code", [
    ("firms.noaa_hms", {"product_id": "firms.viirs_noaa21_nrt"}, "identity"),
    ("firms.noaa_hms", {"product_id": "firms"}, "identity"),
    ("firms.noaa_hms", {"source_id": "imaginary"}, "parent"),
    ("firms.noaa_hms", {"health_keys": ("gdacs",)}, "health_key"),
    ("sea_ice.osi_saf_arctic", {"health_keys": ("sea_ice_arctic", "sea_ice_arctic")}, "health_key"),
    ("firms.noaa_hms", {"claim_permissions": ("publish_record",)}, "claim_permission"),
    ("firms.noaa_hms", {"claim_restrictions": ("not_station_observation", "anything_goes")}, "restriction"),
    ("firms.noaa_hms", {"claim_restrictions": ("not_station_observation",)}, "required_restriction"),
    ("firms.noaa_hms", {"role": "trusted"}, "vocabulary"),
    ("firms.noaa_hms", {"provenance": "see https://example.invalid"}, "text"),
    ("firms.noaa_hms", {"code_refs": ("src/../secret.py:x",)}, "code_ref"),
    ("gdacs.map_api", {"disposition": ""}, "disposition"),
    ("gdacs.map_api", {"status": "wired"}, "disposition"),
    ("firms.viirs_noaa21_nrt", {"runtime_leg_label": "noaa_hms"}, "chain_primary"),
    ("jtwc.plain_rss", {"runtime_leg_label": None, "role": "witness"}, "runtime_label"),
])
def test_invalid_contracts_refuse(product_id, change, code):
    with pytest.raises(ValueError, match=f"source_product_{code}"):
        products.validate_legs(_mutated(product_id, **change))


def test_dropping_an_adapter_or_one_of_its_health_keys_refuses():
    without = tuple(leg for leg in products.LEGS if leg.source_id != "drought")
    with pytest.raises(ValueError, match="source_product_inventory"):
        products.validate_legs(without)
    without_key = tuple(leg for leg in products.LEGS if leg.product_id not in {
        "climate_indices.pdo", "climate_indices.last_good_cache_pdo"})
    with pytest.raises(ValueError, match="source_product_health_key"):
        products.validate_legs(without_key)


# Mutation controls named by the contract.

@pytest.mark.parametrize("product_id", [leg.product_id for leg in products.LEGS
                                        if leg.role in {"alternate_route", "alternate_product", "witness"}
                                        and leg.status != "retired"])
def test_mutation_alternate_promoted_to_primary_is_refused(product_id):
    leg = BY_ID[product_id]
    with pytest.raises(ValueError, match="source_product_(chain_primary|required_restriction)"):
        products.validate_legs(_mutated(product_id, role="primary", runtime_leg_label=None,
                                        claim_restrictions=tuple(sorted(set(leg.claim_restrictions)
                                                                        - {"alternate_not_primary_recovery"}))))


@pytest.mark.parametrize("product_id", [leg.product_id for leg in products.LEGS
                                        if leg.runtime_leg_label and leg.role != "cache"])
def test_mutation_alternate_serving_never_reports_primary_recovery(product_id):
    leg = BY_ID[product_id]
    result = products.serving_disposition(leg.source_id, status="degraded", runtime_leg_label=leg.runtime_leg_label)
    assert result["alternate_served"] is True and result["primary_leg_served_this_run"] is False
    assert result["operational_recovery"] == "not_established"
    assert "alternate_served_primary_not_recovered" in result["reasons"]


@pytest.mark.parametrize("product_id", [leg.product_id for leg in products.LEGS
                                        if leg.data_kind in {"forecast_model", "reanalysis", "satellite_derived"}])
def test_mutation_modeled_or_satellite_relabelled_as_station_is_refused(product_id):
    with pytest.raises(ValueError, match="source_product_(kind_provider|required_restriction)"):
        products.validate_legs(_mutated(product_id, data_kind="observed_station"))
    # Borrowing a station provider without changing the upstream product also refuses.
    with pytest.raises(ValueError, match="source_product_kind_provider"):
        products.validate_legs(_mutated(product_id, data_kind="observed_station", provider="noaa_ncei_ghcn",
                                        claim_restrictions=("record_needs_qualified_history",)))


def test_model_witness_serving_is_never_reported_as_station_observation():
    for source_id, label in (("gpm_imerg", "open_meteo"), ("river_gauges", "open_meteo_flood")):
        result = products.serving_disposition(source_id, status="degraded", runtime_leg_label=label)
        assert result["serving_data_kinds"] == ["forecast_model"]
        assert result["observed_station_kind_only"] is False


@pytest.mark.parametrize("ids,expected", [
    (["firms.viirs_noaa21_nrt", "firms.viirs_noaa20_nrt", "firms.modis_nrt", "firms.noaa_hms"], 1),
    (["fire_footprint.wfigs_incidents", "newsworthiness.nifc_incidents"], 1),
    (["usgs_quakes.significant_day_feed", "gdacs.subtype_witness_usgs"], 1),
    (["nhc.current_storms_index", "gdacs.subtype_witness_nhc", "gdacs.georss"], 1),
    (["air_quality.cams_pm25", "air_quality.openaq_pm25"], 1),
    (["firms.viirs_noaa21_nrt", "usgs_quakes.significant_day_feed", "nws_alerts.active_alerts"], 3),
])
def test_mutation_product_count_is_never_source_count(ids, expected):
    assert products.independent_source_count(ids) == expected
    assert len(ids) >= expected
    groups = products.corroboration_groups(ids)
    assert sorted(item for group in groups for item in group) == sorted(ids)


def test_each_adapter_exports_one_independent_source_however_many_products():
    document = products.product_contract_document()
    for adapter in document["adapters"]:
        assert adapter["independent_source_count"] == 1
        assert products.independent_source_count(adapter["product_ids"]) == 1
    assert sum(len(a["product_ids"]) for a in document["adapters"]) > len(document["adapters"])
    with pytest.raises(ValueError, match="source_product_identity"):
        products.independent_source_count(["firms.not_a_leg"])


def test_unlabelled_success_is_ambiguous_where_unlabelled_alternate_routes_exist():
    gpm = products.serving_disposition("gpm_imerg", status="success")
    assert gpm["primary_leg_served_this_run"] is None and gpm["alternate_served"] is None
    assert gpm["reasons"] == ["unlabelled_serving_route_ambiguous"]
    firms = products.serving_disposition("firms", status="success")
    assert firms["primary_leg_served_this_run"] is True and firms["serving_product_ids"] == ["firms.viirs_noaa21_nrt"]
    for status in ("failed", "skipped"):
        result = products.serving_disposition("gpm_imerg", status=status)
        assert result["serving_product_ids"] == [] and result["primary_leg_served_this_run"] is False
        assert result["operational_recovery"] == "not_established"
    unknown = products.serving_disposition("firms", status="degraded", runtime_leg_label="mystery_leg")
    assert unknown["serving_product_ids"] == [] and unknown["reasons"] == ["unknown_serving_label"]
    with pytest.raises(ValueError, match="disposition_input"):
        products.serving_disposition("firms", status="green")


def test_export_grants_nothing_and_keeps_provider_terms_unknown():
    document = products.product_contract_document()
    assert document["claim_permission_granted"] is False and document["coverage_denominator"] is None
    assert document["current_availability"] == "unverified" and document["operational_recovery"] == "not_established"
    for row in document["products"]:
        assert row["claim_permission_granted"] is False and row["claim_permissions"] == []
        assert all(row[field] is None for field in products.UNKNOWN_FIELDS)
    assert {row["product_id"] for row in document["missing_work"]} == {
        "gpm_imerg.imerg_final_reference", "gdacs.map_api", "gdacs.reliefweb_witness", "firms.viirs_snpp_nrt"}
    assert {row["field"] for row in document["unmet_criteria"]} == {*products.UNKNOWN_FIELDS, "current_availability"}
    assert products.verify_product_contract_document(document) == document["contracts_sha256"]
    assert document == products.product_contract_document()


def test_export_verification_refuses_tampering_and_injected_permissions():
    document = products.product_contract_document()
    tampered = copy.deepcopy(document)
    tampered["products"][0]["data_kind"] = "observed_station"
    with pytest.raises(ValueError, match="export_digest"):
        products.verify_product_contract_document(tampered)
    for field, value in (("claim_permission_granted", True), ("provider_quota", 1000)):
        injected = copy.deepcopy(document)
        injected["products"][0][field] = value
        body = {k: v for k, v in injected.items() if k != "contracts_sha256"}
        injected["contracts_sha256"] = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        with pytest.raises(ValueError, match="export_permission"):
            products.verify_product_contract_document(injected)
    with pytest.raises(ValueError, match="export_schema"):
        products.verify_product_contract_document({"schema": "theheat.source-product-contracts/v2"})


def test_import_and_export_perform_no_adapter_import_network_environment_or_file_access():
    code = '''
import builtins, os, socket
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'requests', 'httpx', 'anthropic', 'google', 'boto3', 'h5py'}:
        raise AssertionError('Client import: ' + name)
    if name.startswith('src.orchestrator') or name in {'src.data.gpm_imerg', 'src.data.firms', 'src.data.nhc'}:
        raise AssertionError('Adapter import: ' + name)
    return original(name, *args, **kwargs)
class Trap(dict):
    def __getitem__(self, key): raise AssertionError('Environment read: ' + key)
    def get(self, key, default=None): raise AssertionError('Environment read: ' + key)
def network(*args, **kwargs): raise AssertionError('Network forbidden')
def no_files(*args, **kwargs): raise AssertionError('File access forbidden')
builtins.__import__ = guarded
socket.socket = network
from src.data import source_product_contracts as products
os.environ = Trap()
builtins.open = no_files
document = products.product_contract_document()
assert document['claim_permission_granted'] is False
products.verify_product_contract_document(document)
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, timeout=20)
