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
    assert len(CONTRACTS) == 33
    # Preserve all 30 accepted-base entries; supplied warnings, the nominated NHC
    # advisory and owner-supplied regional observed packets (W05) are explicit,
    # default-absent adapters, not autonomous feeds.
    assert len([row for row in CONTRACTS
                if row.source_id not in ("official_warning", "nhc_advisory", "regional_observed")]) == 30
    for row in CONTRACTS:
        legs = [leg for leg in products.LEGS if leg.source_id == row.source_id]
        assert legs and {key for leg in legs for key in leg.health_keys} == set(row.health_keys)
        # No manufactured "unknown" product per adapter: every leg names real code.
        assert all(leg.code_refs for leg in legs)


def test_every_code_and_restriction_reference_names_a_real_module_symbol():
    references = [ref for leg in products.LEGS for ref in leg.code_refs]
    references += [ref for _meaning, scope in products.RESTRICTIONS.values() if scope != products.ADVISORY
                   for _selector, ref in scope]
    for ref in references:
        path, symbol = ref.split(":")
        assert symbol in _module_symbols(path), ref
    assert products.ADVISORY in {scope for _m, scope in products.RESTRICTIONS.values()}


def test_nominated_warning_product_is_conditional_and_not_a_provider_access_grant():
    leg = next(leg for leg in products.LEGS if leg.product_id == "official_warning.nominated_packet")
    assert leg.status == "conditional" and leg.data_kind == "official_warning"
    assert leg.provider == "nominated_input" and leg.upstream == "theheat_supplied.official_warning_v1"
    assert "forecast_not_outcome" in leg.claim_restrictions and leg.claim_permissions == ()
    assert "No source acquisition" in leg.request_bound
    observed = products.serving_disposition("official_warning", status="success")
    assert observed["primary_leg_served_this_run"] is None
    assert observed["serving_product_ids"] == []
    assert "serving_leg_not_evidenced" in observed["reasons"]


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
    assert products.max_independent_source_count(ids) == expected
    assert len(ids) >= expected
    groups = products.corroboration_groups(ids)
    assert sorted(item for group in groups for item in group) == sorted(ids)


def test_each_adapter_is_at_most_one_source_however_many_products():
    document = products.product_contract_document()
    for adapter in document["adapters"]:
        assert products.max_independent_source_count(adapter["product_ids"]) == 1
    assert sum(len(a["product_ids"]) for a in document["adapters"]) > len(document["adapters"])
    with pytest.raises(ValueError, match="source_product_identity"):
        products.max_independent_source_count(["firms.not_a_leg"])


def test_unlabelled_success_is_ambiguous_where_unlabelled_alternate_routes_exist():
    gpm = products.serving_disposition("gpm_imerg", status="success")
    assert gpm["primary_leg_served_this_run"] is None and gpm["alternate_served"] is None
    assert gpm["reasons"] == ["serving_leg_not_evidenced", "unlabelled_alternate_routes_exist"]
    firms = products.serving_disposition("firms", status="success")
    assert firms["primary_leg_served_this_run"] is True and firms["serving_product_ids"] == ["firms.viirs_noaa21_nrt"]
    assert firms["reasons"] == ["unlabelled_success_sole_wired_primary"]
    for status in ("failed", "skipped"):
        result = products.serving_disposition("gpm_imerg", status=status)
        assert result["serving_product_ids"] == [] and result["primary_leg_served_this_run"] is False
        assert result["operational_recovery"] == "not_established"
    unknown = products.serving_disposition("firms", status="degraded", runtime_leg_label="mystery_leg")
    assert unknown["serving_product_ids"] == [] and unknown["reasons"] == ["unknown_serving_label"]
    assert unknown["primary_leg_served_this_run"] is None
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
    assert {row["field"] for row in document["unmet_criteria"]} == {*products.UNKNOWN_FIELDS, "current_availability",
                                                                    "restriction_enforcement"}
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


# G11-R1 repairs: counterexamples from the S1/S3 checkpoint review. Every fixture
# below is invented test evidence, never proof that a source served or an event happened.

def _rehashed(document):
    body = {key: value for key, value in document.items() if key != "contracts_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {**body, "contracts_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def _function_names(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_names(path: str, function: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    body = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function)
    return {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(body) if isinstance(node, ast.Call)}


def test_r1_status_alone_never_names_a_served_product():
    """S1-R1: the CO2 cache fallback emits unlabelled degraded; AQ success can mean one lane."""
    co2 = products.serving_disposition("co2", status="degraded")
    assert co2["serving_product_ids"] == [] and co2["primary_leg_served_this_run"] is None
    assert co2["observed_station_kind_only"] is not True and co2["alternate_served"] is None
    aq = products.serving_disposition("air_quality", status="success")
    assert aq["serving_product_ids"] == [] and aq["primary_leg_served_this_run"] is None
    assert aq["observed_station_kind_only"] is not True
    unknown = products.serving_disposition("firms", status="degraded", runtime_leg_label="mystery_leg")
    assert unknown["serving_product_ids"] == [] and unknown["primary_leg_served_this_run"] is None


def test_r1_actual_co2_runner_cache_fallback_is_retained_not_fresh_primary(monkeypatch):
    from datetime import date, timedelta

    from src.data import last_good
    from src.data.co2 import CO2Reading
    from src.orchestrator.sources import co2 as runner
    from src.state import _fresh_state

    bot_state, current_run = _fresh_state(), {"sources": []}
    recent = (date.today() - timedelta(days=1)).isoformat()
    last_good.write(bot_state, "co2", recent, {"date": recent, "ppm": 429.8}, captured_at=f"{recent}T00:00:00Z")

    def unavailable(**_kwargs):
        raise RuntimeError("invented upstream outage")

    monkeypatch.setattr(runner.co2, "fetch_co2_data", unavailable)
    runner.run_co2(bot_state, current_run)
    entry = current_run["sources"][0]
    assert entry["status"] == "degraded" and entry["error"].startswith("served last-good (")
    cached = products.serving_disposition_from_run_entry(entry)
    assert cached["serving_product_ids"] == ["co2.last_good_cache"]
    assert cached["retained_not_fresh"] is True and cached["alternate_served"] is True
    assert cached["primary_leg_served_this_run"] is False and cached["observed_station_kind_only"] is False
    assert cached["operational_recovery"] == "not_established"

    fresh_run = {"sources": []}
    readings = [CO2Reading(date="2026-06-10", ppm=429.8, event_id="co2_2026-06-10_429")]
    monkeypatch.setattr(runner.co2, "fetch_co2_data", lambda: readings)
    monkeypatch.setattr(runner.co2, "detect_milestone", lambda _readings: None)
    runner.run_co2(_fresh_state(), fresh_run)
    fresh = products.serving_disposition_from_run_entry(fresh_run["sources"][0])
    assert fresh["serving_product_ids"] == ["co2.mlo_daily"] and fresh["retained_not_fresh"] is False
    assert fresh["primary_leg_served_this_run"] is True and fresh["observed_station_kind_only"] is True


def _aq_summary(pm25, dust):
    def lane(state):
        enabled = state is not None
        counts = {"complete": 3 if state in {"available", "partial"} else 0, "incomplete": 0,
                  "missing": 0 if state != "partial" else 2, "invalid": 0, "unavailable_window": 0}
        coverage = None if not enabled else counts["complete"] / 5
        return dict(enabled=enabled, status=state or "disabled", requested=5 if enabled else 0,
                    coverage=coverage, **counts)
    return dict(schema_version=1, evidence_type="model_forecast", requested_cities=5, observed_cities=3,
                result_shape="matched", received_slots=5, hazards={"pm25": lane(pm25), "dust": lane(dust)})


@pytest.mark.parametrize("pm25,dust,served", [
    ("available", None, ["air_quality.cams_pm25"]),
    (None, "available", ["air_quality.cams_dust"]),
    ("available", "partial", ["air_quality.cams_dust", "air_quality.cams_pm25"]),
    ("available", "unavailable", ["air_quality.cams_pm25"]),
])
def test_r1_actual_aq_availability_names_only_enabled_served_lanes(pm25, dust, served):
    from src.data.air_quality_availability import source_status

    summary = _aq_summary(pm25, dust)
    entry = {"source": "air_quality", "status": source_status(summary), "error": None, "note": None,
             "details": {"aq_availability": summary, "pm25_enabled": pm25 is not None,
                         "dust_enabled": dust is not None, "openaq_enabled": False}}
    result = products.serving_disposition_from_run_entry(entry)
    assert result["serving_product_ids"] == served
    assert result["serving_data_kinds"] == ["forecast_model"] and result["observed_station_kind_only"] is False
    explicit = products.serving_disposition("air_quality", status="success",
                                            served_product_ids=["air_quality.cams_dust"])
    assert explicit["serving_product_ids"] == ["air_quality.cams_dust"]
    with pytest.raises(ValueError, match="disposition_input"):
        products.serving_disposition("air_quality", status="success", served_product_ids=["firms.modis_nrt"])


def test_r1_leaderboard_is_the_daily_max_forecast_shared_with_the_alert_adapter():
    """S1-R2: fetch_city_forecast requests daily temperature_2m_max, timezone auto, one day."""
    tree = ast.parse((ROOT / "src/data/open_meteo.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "fetch_city_forecast")
    params = next(kw.value for node in ast.walk(function) if isinstance(node, ast.Call)
                  for kw in node.keywords if kw.arg == "params")
    request = {key.value: value.value for key, value in zip(params.keys, params.values)
               if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
    assert request["daily"] == "temperature_2m_max" and request["forecast_days"] == 1
    assert request["timezone"] == "auto" and "current" not in request
    assert "fetch_city_forecast" in _called_names("src/data/open_meteo.py", "fetch_all_city_temps")
    leaderboard = [leg for leg in products.LEGS if leg.source_id == "leaderboard" and leg.provider == "open_meteo"]
    assert len(leaderboard) == 1
    leg, alert = leaderboard[0], BY_ID["open_meteo_extreme_signals.om_forecast"]
    assert leg.data_kind == "forecast_model" and leg.upstream == alert.upstream
    assert "current" not in (leg.product + leg.upstream + leg.product_id).lower()
    assert "forecast" in leg.time_limit.lower() and "forecast_not_outcome" in leg.claim_restrictions
    assert any(ref.endswith(":fetch_city_forecast") for ref in leg.code_refs)
    # One shared daily forecast is one corroboration group, whatever the adapter IDs.
    assert len(products.corroboration_groups([leg.product_id, alert.product_id])) == 1


def test_r1_unknown_independence_is_reported_as_an_upper_bound_only():
    document = products.product_contract_document()
    assert document["source_independence"] == "not_established"
    assert all("independent_source_count" not in adapter for adapter in document["adapters"])
    shared = {tuple(group) for group in document["shared_upstream_groups"]}
    assert ("leaderboard.om_forecast_daily_max", "open_meteo_extreme_signals.om_forecast") in shared
    assert products.max_independent_source_count(["leaderboard.om_forecast_daily_max",
                                                  "open_meteo_extreme_signals.om_forecast"]) == 1


def _set_row(product_id, **change):
    def mutate(document):
        row = next(row for row in document["products"] if row["product_id"] == product_id)
        row.update(change)
    return mutate


def _drop_row(product_id):
    def mutate(document):
        document["products"] = [row for row in document["products"] if row["product_id"] != product_id]
    return mutate


@pytest.mark.parametrize("mutate,code", [
    (_set_row("open_meteo_extreme_signals.om_forecast", data_kind="observed_station"), "kind_provider"),
    (_set_row("gpm_imerg.open_meteo_witness", data_kind="observed_station",
              claim_restrictions=["record_needs_qualified_history"]), "kind_provider"),
    (lambda d: d.update(products=[]), "source_product_(size|export)"),
    (_drop_row("firms.noaa_hms"), "source_product_(export_inventory|export_adapters|enforcement_scope)"),
    (_set_row("firms.noaa_hms", code_refs=["src/data/firms.py:invented_symbol"]), "export_inventory"),
    (_set_row("firms.noaa_hms", health_keys="firms"), "export_row"),
    (_set_row("firms.noaa_hms", surprise=True), "export_row"),
    (_set_row("firms.noaa_hms", restriction_enforcement={}), "export_(row|enforcement)"),
    (lambda d: d["restrictions"]["forecast_not_outcome"].update(meaning="Forecasts are outcomes."),
     "export_restrictions"),
    (lambda d: d["adapters"][0].update(product_ids=[]), "export_adapters"),
    (lambda d: d.update(unmet_criteria=[]), "export_summary"),
    (lambda d: d.update(missing_work=[]), "export_summary"),
    (lambda d: d.update(registry_schema_version=99), "export_schema"),
    (lambda d: d.update(source_independence="established"), "export_(schema|permission|summary)"),
])
def test_r1_rehashed_detached_export_is_decoded_not_just_hashed(mutate, code):
    """S1-R3: the digest binds bytes, not truth."""
    document = copy.deepcopy(products.product_contract_document())
    mutate(document)
    with pytest.raises(ValueError, match=code):
        products.verify_product_contract_document(_rehashed(document))


def test_r1_legitimate_detached_export_stays_readable_and_derives_its_own_summary():
    document = products.product_contract_document()
    reloaded = json.loads(json.dumps(document))
    assert products.verify_product_contract_document(reloaded) == document["contracts_sha256"]
    view = products.decode_product_contract_document(reloaded)
    assert view["missing_work"] == document["missing_work"] and view["unmet_criteria"] == document["unmet_criteria"]
    assert {row["field"] for row in view["unmet_criteria"]} >= {*products.UNKNOWN_FIELDS, "current_availability",
                                                                "restriction_enforcement"}
    with pytest.raises(ValueError, match="export_schema"):
        products.decode_product_contract_document({**reloaded, "schema": "theheat.source-product-contracts/v9"})


def test_r1_marine_compound_supply_called_by_the_runner_is_inventoried():
    """S1-R4: run_synthesis calls both detectors; both derived legs are inventoried."""
    called = _called_names("src/orchestrator/sources/synthesis.py", "run_synthesis")
    assert {"detect_fire_drought_heat", "detect_marine_compound"} <= called
    marine = [leg for leg in products.LEGS if any(ref.endswith(":detect_marine_compound") for ref in leg.code_refs)]
    assert len(marine) == 1
    leg = marine[0]
    assert leg.source_id == "synthesis_fire_drought_heat" and leg.status == "wired"
    assert leg.data_kind == "derived_combination" and leg.role == "primary"
    assert {"crw_heat_stress_not_bleaching", "association_not_shared_footprint",
            "co_occurrence_not_causation"} <= set(leg.claim_restrictions)
    assert "independent" in leg.time_limit.lower() and "footprint" in leg.geographic_limit.lower()
    overlap = [leg for leg in products.LEGS if any(ref.endswith(":detect_fire_drought_heat") for ref in leg.code_refs)]
    assert len(overlap) == 1 and overlap[0].chain != leg.chain


GHCN_HISTORY = "src/data/ghcn.py:record_comparison_qualified"


def _applicable(document, row, code):
    scoped = row.get("restriction_enforcement")
    if scoped:
        return scoped[code]
    table = document["restrictions"][code]
    return {"basis": table["basis"], "reference": table["reference"]}


def test_r1_ghcn_history_qualification_is_not_claimed_for_other_station_products():
    """S1-R5: Snow Today, OpenAQ, CO-OPS and CO2 are not enforced by a GHCN-only function."""
    document = products.product_contract_document()
    checked = []
    for row in document["products"]:
        if "record_needs_qualified_history" not in row["claim_restrictions"]:
            continue
        enforcement = _applicable(document, row, "record_needs_qualified_history")
        if row["source_id"] != "open_meteo_extreme_signals":
            checked.append(row["product_id"])
            assert not (enforcement["basis"] == "check" and enforcement["reference"] == GHCN_HISTORY), row["product_id"]
    assert {"co2.mlo_daily", "air_quality.openaq_pm25", "water_levels.coops_water_level",
            "nsidc_snow.snow_today_swe"} <= set(checked)


def test_r1_every_check_enforcement_is_a_scoped_function_and_the_rest_is_explicit():
    document = products.product_contract_document()
    unresolved = set()
    for row in document["products"]:
        for code in row["claim_restrictions"]:
            enforcement = row["restriction_enforcement"][code]
            assert enforcement["basis"] in {"check", "advisory", "unresolved"}
            if enforcement["basis"] == "check":
                path, symbol = enforcement["reference"].split(":")
                assert symbol in _function_names(path), enforcement["reference"]  # a symbol is not enforcement
            elif enforcement["basis"] == "unresolved":
                assert enforcement["reference"] is None
                unresolved.add(row["product_id"])
    assert unresolved
    listed = next(item for item in document["unmet_criteria"] if item["field"] == "restriction_enforcement")
    assert set(listed["products"]) == unresolved
    ghcn = BY_ID["open_meteo_extreme_signals.ghcn_daily"]
    assert products.restriction_enforcement(ghcn)["record_needs_qualified_history"] == {
        "basis": "check", "reference": GHCN_HISTORY}
    assert products.restriction_enforcement(BY_ID["co2.mlo_daily"])["record_needs_qualified_history"] == {
        "basis": "unresolved", "reference": None}
