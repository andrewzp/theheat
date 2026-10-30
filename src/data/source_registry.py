"""Code-supported source inventory. Metadata never grants scientific permission.

No adapter imports, network, environment/credential reads or acquisition occurs
here. Collection rules describe wired code, not an active schedule or provider SLA.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re

SCHEMA_VERSION = 1
PURPOSE = "wired_inventory_not_activation_or_claim_permission"
CLAIM_POLICY = "Existing per-story evidence and required checks remain mandatory."
UNKNOWN_LIMITS = (
    "Current access and availability",
    "Provider quota and update guarantee",
    "Reuse rights for a particular product",
    "Scientific qualification of an individual story",
    "Geographic completeness and missed events",
)
_CYCLE = "Each eligible alerts run; existing deduplication and story limits still apply."
_DATED = "Use the product's own date or valid period; collection time is not measurement time."
_KEY = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_FAMILIES = frozenset({
    "mixed", "forecast_model", "station_points", "satellite_analysis",
    "official_warning", "official_report", "derived_index", "discovery", "internal",
})


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    health_keys: tuple[str, ...]
    kind: str
    entry_point: str
    scope: str
    data_family: str
    provenance: str
    collection_rule: str
    time_rule: str
    claim_limit: str
    evidence_files: tuple[str, ...]


def _source(source_id, module, function, scope, family, provenance, claim_limit,
            *, health=None, collection=_CYCLE, time_rule=_DATED, support=(), kind="adapter"):
    entry_file = f"src/orchestrator/sources/{module}.py"
    return SourceContract(source_id, health or (source_id,), kind,
                          f"{entry_file}:{function}", scope, family, provenance,
                          collection, time_rule, claim_limit, (entry_file, *support))


CONTRACTS = (
    _source("open_meteo_extreme_signals", "open_meteo", "run_extreme_signals",
            "Configured cities and station candidates; not every place worldwide.", "mixed",
            "Open-Meteo forecasts/models and the separately gated GHCN station path.",
            "Keep forecast, model and station evidence distinct; a station record needs its qualified history.",
            support=("src/data/temperature_evidence.py", "src/data/ghcn.py")),
    _source("firms", "firms", "run_firms", "Configured fire-cluster selection and available source legs.", "mixed",
            "FIRMS satellite detections; an alternate leg retains its own provenance.",
            "A detection or alternate footprint is not burned area, a death toll or proof of fire cause.",
            support=("src/data/fire_source_contract.py", "src/data/firms.py")),
    _source("drought", "drought", "run_drought", "US Drought Monitor areas selected by the collector.", "official_report",
            "US Drought Monitor analysis.", "A regional drought analysis is not a local rainfall observation.",
            collection="Fridays on the collector's calendar; existing tier and deduplication guards apply.",
            support=("src/data/drought.py",)),
    _source("fire_footprint", "nifc", "run_fire_footprint", "US fire complexes returned by the configured NIFC feed.", "official_report",
            "NIFC reported fire perimeters/complex areas.", "Cumulative reported area is not a new daily burn total.",
            collection="After a successful collection, at most once per collector calendar date.",
            support=("src/data/fire_footprint.py",)),
    _source("co2", "co2", "run_co2", "NOAA GML series used for carbon-dioxide milestones.", "derived_index",
            "NOAA GML dated atmospheric CO2 series.", "A series milestone is not a local extreme-weather incident.",
            support=("src/data/co2.py",)),
    _source("ch4_milestone", "methane", "run_methane", "NOAA GML series used for methane milestones.", "derived_index",
            "NOAA GML dated methane series.", "A series milestone is not a local extreme-weather incident.",
            support=("src/data/methane.py",)),
    _source("nws_alerts", "nws_alerts", "run_nws_alerts", "NWS warning areas returned by the active-alert feed.", "official_warning",
            "NWS issued alert products, including their issue, effective and expiry times.",
            "A warning or forecast does not prove the forecast impact occurred.",
            support=("src/data/nws_alerts.py",)),
    _source("official_warning", "official_warning", "run_official_warning_source",
            "One explicitly nominated English-original warning; not an autonomous provider feed.", "official_warning",
            "Exact retained source bytes and an independent issuer/origin/report/revision nomination.",
            "Attributed prospective warning only; no inferred observed impact, source authentication or translation.",
            collection="Only with an explicitly supplied WarningSource and EditorialScore; absent by default; no source fetch.",
            time_rule="Require coherent issue/capture/expiry times and an independently current matching source revision.",
            support=("src/editorial/official_warning.py", "src/editorial/warning_runtime.py", "src/two_bot/intern/warnings.py")),
    _source("nhc_advisory", "nhc_advisory", "run_nhc_advisory_source",
            "One explicitly nominated NHC public advisory (operator storm/advisory/hazard/place scope); not discovery.",
            "official_warning",
            "Exact CurrentStorms row and public-advisory bulletin bytes from the fixed www.nhc.noaa.gov products.",
            "Attributed NHC forecast only; no observed impact, inferred landfall, population or record; upstream expiry unknown.",
            collection="Only with THEHEAT_NHC_ADVISORY_ACQUISITION=1 and an explicit nomination; absent by default; "
                       "two fixed requests per current read and at most 32 per command.",
            time_rule="Issue non-future and at most 6 h old; operator recheck deadline at most 60 min after capture; "
                      "a fresh index/advisory read must match at each spend, admission and send boundary.",
            support=("src/data/nhc_advisory.py", "src/editorial/nhc_advisory.py",
                     "src/editorial/nhc_advisory_runtime.py", "src/two_bot/intern/nhc_advisory.py")),
    SourceContract("nhc", ("nhc",), "adapter", "src/orchestrator/cyclones.py:_process_cyclone_source",
                   "NHC Atlantic and East Pacific active-storm products.", "official_warning",
                   "NHC active-storm entries and their advisory products.", _CYCLE, _DATED,
                   "Keep advisory conditions and future forecast points distinct; do not infer landfall.",
                   ("src/orchestrator/cyclones.py", "src/data/nhc.py")),
    SourceContract("jtwc", ("jtwc",), "adapter", "src/orchestrator/cyclones.py:_process_cyclone_source",
                   "JTWC tropical warnings represented by the configured RSS products.", "official_warning",
                   "JTWC enhanced or plain RSS; the serving leg remains explicit.", _CYCLE, _DATED,
                   "Keep advisory conditions and future forecast points distinct; do not infer landfall.",
                   ("src/orchestrator/cyclones.py", "src/data/jtwc.py")),
    _source("gdacs", "gdacs", "run_gdacs", "Disaster alerts/reports returned by the configured GDACS routes.", "official_report",
            "GDACS dated disaster products and explicit route provenance.",
            "One alert/report is not a complete incident census or a validated impact total.",
            support=("src/data/gdacs.py",)),
    _source("usgs_quakes", "usgs_quakes", "run_usgs_quakes", "Significant earthquakes returned by the USGS feed.", "official_report",
            "USGS event products.", "Earthquake magnitude alone does not certify weather relevance or human impacts.",
            support=("src/data/usgs_quakes.py",)),
    _source("copernicus_ems", "copernicus_ems", "run_copernicus_ems", "Flood mapping activations returned by the configured EMS routes.", "official_report",
            "Copernicus EMS Rapid Mapping activations and explicit alternate legs.",
            "A mapping activation is not a measured flood footprint or certified impact total.",
            support=("src/data/copernicus_ems.py",)),
    _source("sea_ice", "sea_ice", "run_sea_ice", "Arctic and Antarctic sea-ice extent series.", "satellite_analysis",
            "NSIDC series and explicitly retained alternate/cache provenance.",
            "Series extent and source dates must remain distinct from local ice conditions.",
            health=("sea_ice_arctic", "sea_ice_antarctic"),
            collection="Mondays on the collector's calendar; existing caps still apply.",
            support=("src/data/sea_ice.py",)),
    _source("enso", "enso", "run_enso", "NOAA CPC ENSO index series used by this collector.", "derived_index",
            "NOAA CPC dated index and transition products.", "An ENSO state is not a prediction of a specific local disaster.",
            collection="First day of the month on the collector's calendar.", support=("src/data/enso.py",)),
    _source("climate_indices", "climate_indices", "run_climate_indices", "NAO, AO, PDO and the derived NAO/AO alignment.", "derived_index",
            "NOAA index series; alignment is a derived combination.",
            "Do not turn an index or alignment into a supported local impact forecast.",
            health=("nao", "ao", "pdo", "nao_ao_alignment"),
            collection="First day of the month on the collector's calendar; existing annual caps apply.",
            support=("src/data/climate_indices.py",)),
    _source("ocean", "marine", "run_ocean", "Configured marine sampling points; not all oceans or buoys.", "forecast_model",
            "Open-Meteo Marine model/forecast products.", "A sampled model grid point is not a buoy observation.",
            support=("src/data/ocean.py",)),
    _source("ocean_sst", "ocean_sst", "run_ocean_sst", "Global ocean SST summary series used by this collector.", "satellite_analysis",
            "NOAA OISST v2.1 series via ClimateReanalyzer and retained alternate provenance.",
            "A global summary is not an individual coast's water temperature.", support=("src/data/ocean_sst.py",)),
    _source("ocean_sst_anomaly", "ocean_sst_anomaly", "run_ocean_sst_anomaly", "Configured regional SST-anomaly boxes and valid sampled cells.", "satellite_analysis",
            "NOAA Coral Reef Watch gridded anomaly products and native-product fallback.",
            "Qualified regional cells are not a global event/opportunity denominator.",
            support=("src/data/ocean_sst_anomaly.py", "src/data/crw_contract.py")),
    _source("air_quality", "air_quality", "run_air_quality", "Configured cities with separately enabled PM2.5 and dust windows.", "mixed",
            "CAMS via Open-Meteo model estimates; optional OpenAQ station corroboration.",
            "A model estimate is not a station observation; dust does not prove wildfire smoke or cause.",
            collection="Each eligible alerts run; PM2.5/dust flags and optional station access apply.",
            support=("src/data/air_quality_contract.py", "src/data/air_quality_availability.py")),
    _source("coral_dhw", "coral_dhw", "run_coral_dhw", "Configured coral-reef sites/regions in the CRW collector.", "satellite_analysis",
            "NOAA Coral Reef Watch heat-stress products and retained source leg.",
            "Heat stress is not observed bleaching, reef death or a measured local impact.",
            support=("src/data/coral_source_contract.py", "src/data/coral_dhw.py")),
    _source("water_levels", "co_ops", "run_water_levels", "Configured NOAA coastal-water-level stations.", "station_points",
            "NOAA CO-OPS station readings and their station/datum context.",
            "A station water level is not a supported regional inundation or damage claim.",
            support=("src/data/water_levels.py",)),
    _source("river_gauges", "river_gauges", "run_river_gauges", "Configured US river stations and explicitly mapped alternate points.", "mixed",
            "USGS gauge height plus NOAA NWPS thresholds; Open-Meteo/GloFAS model alternate.",
            "Model discharge is not an observed gauge height; retain the serving leg and units.",
            support=("src/data/river_gauges.py",)),
    _source("ice_mass", "ice_mass", "run_ice_mass", "Greenland and Antarctica ice-mass series.", "satellite_analysis",
            "NASA GRACE-FO / JPL PODAAC regional series and retained cache provenance.",
            "A dated regional series change is not today's local melt measurement.",
            health=("ice_mass_greenland", "ice_mass_antarctica"),
            collection="Mondays on the collector's calendar; existing annual caps apply.", support=("src/data/ice_mass.py",)),
    _source("gpm_imerg", "gpm_imerg", "run_gpm_imerg", "Bounded configured-city selection and rotating rainfall scan.", "mixed",
            "GPM IMERG Late daily product; Final archive reference; model alternate remains labeled.",
            "A grid product/model is not a gauge record; product-window and gauge reconciliation remain required.",
            support=("src/data/gpm_imerg.py",)),
    _source("regional_observed", "regional_observed", "run_regional_observed",
            "Named stations in owner-supplied AEMET/IMD/SAWS packets; default off; not national coverage.",
            "station_points", "National-service observed station values from retained packets with their access contract.",
            "A source reporting day is not an exact UTC day; without a scoped comparator only value wording is supported.",
            collection="Only when THEHEAT_REGIONAL_OBSERVED is exactly 1 and packets are supplied; nothing is fetched.",
            support=("src/data/regional_observations.py",)),
    _source("nsidc_snow", "nsidc_snow", "run_nsidc_snow", "Provider-returned Snow Today SWE points; completeness is unverified.", "station_points",
            "NSIDC Snow Today dated snow-water-equivalent point product.",
            "Snow water equivalent is not snowfall depth; record claims require qualified history.",
            support=("src/data/nsidc_snow.py",)),
    _source("ozone_hole", "ozone_hole", "run_ozone_hole", "Antarctic ozone-hole series used by this collector.", "satellite_analysis",
            "NASA Ozone Watch dated area series.", "A seasonal area peak is not local UV exposure or a health impact measurement.",
            collection="August–November on the collector's calendar; existing annual cap applies.",
            support=("src/data/ozone_hole.py",)),
    _source("reanalysis_anomaly", "reanalysis_anomaly", "run_reanalysis_anomaly", "Configured sampled-city regions and retained daily climatology.", "forecast_model",
            "ERA5 reanalysis via Open-Meteo archive, compared with the configured climatology.",
            "Reanalysis is not station observation; samples do not establish a whole-region record.",
            collection="Only when the existing opt-in flag and required climatology allow collection.",
            support=("src/data/reanalysis_anomaly.py",)),
    _source("newsworthiness", "newsworthiness", "run_newsworthiness", "Retrieved cited events selected by this discovery lane.", "discovery",
            "NIFC feed and the existing grounded-search verification path.",
            "Discovery results are not scientifically qualified candidates or a global event census.",
            collection="Only when the existing newsworthiness opt-in flag allows collection.",
            support=("src/data/newsworthiness.py",), kind="discovery"),
    _source("synthesis_fire_drought_heat", "synthesis", "run_synthesis", "Overlaps among retained fire/drought/heat and marine components.", "mixed",
            "Derived combinations of the original component sources, not an independent feed.",
            "Co-occurrence does not establish causation; all component provenance and time bounds still apply.",
            kind="derived"),
    SourceContract("leaderboard", ("leaderboard",), "derived", "src/orchestrator/hot10.py:run_leaderboard",
                   "Configured city sample ranked against its attributable normals.", "mixed",
                   "Open-Meteo temperatures and the collector's retained normals.",
                   "Requested leaderboard runs; existing score/deduplication gates apply.", _DATED,
                   "A sample ranking is not the hottest places on Earth or a station-record table.",
                   ("src/orchestrator/hot10.py", "src/data/open_meteo.py")),
)

TELEMETRY_KEYS = ("load_cities", "budget", "twitter_metrics", "manual_publish", "auto_publish_due")


def validate_contracts(contracts=CONTRACTS):
    """Reject ambiguous ownership and malformed metadata before generation."""
    if not 1 <= len(contracts) <= 96:
        raise ValueError("source_registry_size")
    ids, keys = set(), set()
    for row in contracts:
        if not isinstance(row, SourceContract) or not _KEY.fullmatch(row.source_id) or row.source_id in ids:
            raise ValueError("source_registry_identity")
        ids.add(row.source_id)
        if row.kind not in {"adapter", "derived", "discovery"} or row.data_family not in _FAMILIES:
            raise ValueError("source_registry_family")
        if not row.health_keys or len(row.health_keys) > 8:
            raise ValueError("source_registry_health_keys")
        for key in row.health_keys:
            if not isinstance(key, str) or not _KEY.fullmatch(key) or key in keys or key in TELEMETRY_KEYS:
                raise ValueError("source_registry_ambiguous_health_key")
            keys.add(key)
        for value in (row.scope, row.provenance, row.collection_rule, row.time_rule, row.claim_limit):
            if not isinstance(value, str) or not 1 <= len(value) <= 300 or any(ord(c) < 32 for c in value):
                raise ValueError("source_registry_text")
        if not row.evidence_files or len(row.evidence_files) > 8 or len(set(row.evidence_files)) != len(row.evidence_files):
            raise ValueError("source_registry_evidence")
        for path in row.evidence_files:
            if not re.fullmatch(r"src/[a-zA-Z0-9_/]+\.py", path) or ".." in path:
                raise ValueError("source_registry_evidence")
        file, separator, name = row.entry_point.partition(":")
        if separator != ":" or file not in row.evidence_files or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
            raise ValueError("source_registry_entry_point")


def registry_document(root: Path) -> dict:
    """Generate from local code bytes only; no source/client modules are executed."""
    validate_contracts()
    paths = {"src/data/source_registry.py", "src/orchestrator/run_alerts.py", "src/orchestrator/hot10.py"}
    paths.update(path for row in CONTRACTS for path in row.evidence_files)
    body = {
        "schema_version": SCHEMA_VERSION,
        "purpose": PURPOSE,
        "claim_policy": CLAIM_POLICY,
        "unknown_limits": list(UNKNOWN_LIMITS),
        "provider_quota": None,
        "reuse_rights": None,
        "current_availability": "unverified",
        "coverage_denominator": None,
        "claim_permission_granted": False,
        "sources": [asdict(row) for row in CONTRACTS],
        "telemetry_keys": list(TELEMETRY_KEYS),
        "referenced_code_sha256": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in sorted(paths)},
        "evidence_scope": "Referenced local code inventory; not live/provider/transitive-source qualification.",
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {**body, "registry_sha256": digest}
