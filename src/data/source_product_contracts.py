"""Per-product serving-leg contracts for the wired source inventory.

Advisory metadata only. It grants no claim permission, activation, source
qualification or production availability. Provider cadence, quota, reuse rights
and cost stay unknown here. Importing or exporting performs no adapter import,
network, environment/credential read or state mutation.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

from src.data.source_registry import CONTRACTS as REGISTRY_CONTRACTS
from src.data.source_registry import SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION

SCHEMA = "theheat.source-product-contracts/v1"
PURPOSE = "product_and_serving_leg_inventory_not_activation_or_claim_permission"
UNKNOWN_FIELDS = ("provider_cadence", "provider_quota", "reuse_rights", "cost")

DATA_KINDS = frozenset({
    "observed_station", "forecast_model", "reanalysis", "satellite_derived", "expert_analysis",
    "official_warning", "official_event_report", "source_reported_impact", "official_reference",
    "derived_index", "derived_combination", "discovery",
})
ROLES = frozenset({
    "primary", "alternate_route", "alternate_product", "witness", "component",
    "reference", "corroboration", "cache", "retired", "unresolved",
})
STATUSES = frozenset({"wired", "conditional", "retired", "unresolved"})
# A provider may only declare the data kinds it can actually supply. A model
# provider can therefore never be relabelled as station observation.
PROVIDER_KINDS = {
    "open_meteo": frozenset({"forecast_model", "reanalysis"}),
    "noaa_ncei_ghcn": frozenset({"observed_station"}),
    "nasa_firms": frozenset({"satellite_derived"}),
    "noaa_nesdis_hms": frozenset({"satellite_derived"}),
    "us_drought_monitor": frozenset({"expert_analysis"}),
    "nifc_wfigs": frozenset({"official_event_report", "source_reported_impact"}),
    "noaa_gml": frozenset({"observed_station", "derived_index"}),
    "nws": frozenset({"official_warning"}),
    "nhc": frozenset({"official_warning"}),
    "jtwc": frozenset({"official_warning"}),
    "gdacs": frozenset({"official_event_report"}),
    "usgs_earthquake": frozenset({"official_event_report"}),
    "copernicus_ems": frozenset({"official_event_report"}),
    "nsidc": frozenset({"satellite_derived", "observed_station"}),
    "osi_saf": frozenset({"satellite_derived"}),
    "noaa_cpc": frozenset({"derived_index"}),
    "noaa_psl": frozenset({"derived_index"}),
    "climate_reanalyzer": frozenset({"satellite_derived"}),
    "noaa_crw": frozenset({"satellite_derived"}),
    "openaq": frozenset({"observed_station"}),
    "noaa_coops": frozenset({"observed_station"}),
    "usgs_nwis": frozenset({"observed_station"}),
    "noaa_nwps": frozenset({"official_reference"}),
    "nasa_gesdisc": frozenset({"satellite_derived"}),
    "nasa_jpl_grace": frozenset({"satellite_derived"}),
    "nasa_ozone_watch": frozenset({"satellite_derived"}),
    "grounded_search": frozenset({"discovery"}),
    "reliefweb": frozenset({"source_reported_impact"}),
    "theheat_retained": frozenset({"derived_combination", "reanalysis", "official_reference"}),
}
# Upstream product keys are namespaced by their provider, so a leg cannot borrow
# another provider's product (or kind) by relabelling.
PROVIDER_NAMESPACES = {
    "open_meteo": "open_meteo", "noaa_ncei_ghcn": "noaa_ncei", "nasa_firms": "nasa_firms",
    "noaa_nesdis_hms": "noaa_nesdis", "us_drought_monitor": "usdm", "nifc_wfigs": "nifc", "noaa_gml": "noaa_gml",
    "nws": "nws", "nhc": "nhc", "jtwc": "jtwc", "gdacs": "gdacs", "usgs_earthquake": "usgs",
    "copernicus_ems": "copernicus_ems", "nsidc": "nsidc", "osi_saf": "osi_saf", "noaa_cpc": "noaa_cpc",
    "noaa_psl": "noaa_psl", "climate_reanalyzer": "climate_reanalyzer", "noaa_crw": "noaa_crw", "openaq": "openaq",
    "noaa_coops": "noaa_coops", "usgs_nwis": "usgs_nwis", "noaa_nwps": "noaa_nwps", "nasa_gesdisc": "nasa_gesdisc",
    "nasa_jpl_grace": "nasa_jpl", "nasa_ozone_watch": "nasa_ozone_watch", "grounded_search": "grounded_search",
    "reliefweb": "reliefweb", "theheat_retained": "theheat",
}
# Each restriction is either advisory (only the accepted registry claim limit
# states it) or enforced by named checks scoped to the products they actually
# see. A product outside every scope keeps the restriction with enforcement
# "unresolved": a symbol elsewhere in the code base is not enforcement. Neither
# basis is a new grant.
_ADVISORY = "src/data/source_registry.py:CONTRACTS"
ADVISORY = "advisory"
_CLAIMS = "src/two_bot/scientific_claims.py:scientific_claim_failures"
_GHCN_HISTORY = "src/data/ghcn.py:record_comparison_qualified"
# forecast_as_observation: bundles marked as forecast evidence, model fallback or air quality.
_FORECAST_MARKED = ("open_meteo_extreme_signals.om_forecast", "ocean.marine_forecast", "air_quality.cams_pm25",
                    "air_quality.cams_dust")
_MODEL_FALLBACK = ("gpm_imerg.open_meteo_witness", "river_gauges.open_meteo_flood")
_RUNNER = "src/orchestrator/sources/{0}.py:run_{0}"
# Runners that record status "degraded" with the serving label for these legs.
_LABELLED_DEGRADED = (
    *((f"gdacs.subtype_witness_{name}", _RUNNER.format("gdacs")) for name in ("usgs", "nhc", "jtwc")),
    ("copernicus_ems.frontend_api", _RUNNER.format("copernicus_ems")),
    ("river_gauges.open_meteo_flood", _RUNNER.format("river_gauges")),
    ("sea_ice.osi_saf_arctic", _RUNNER.format("sea_ice")), ("sea_ice.osi_saf_antarctic", _RUNNER.format("sea_ice")),
    *((f"firms.{name}", _RUNNER.format("firms")) for name in ("viirs_noaa20_nrt", "modis_nrt", "noaa_hms")),
    ("gpm_imerg.open_meteo_witness", _RUNNER.format("gpm_imerg")),
    ("coral_dhw.crw_erddap", _RUNNER.format("coral_dhw")),
    ("jtwc.plain_rss", "src/orchestrator/cyclones.py:_process_cyclone_source"),
)
# Runners that record a retained last-good serving as "degraded", never success.
_CACHE_DEGRADED = tuple((source, _RUNNER.format(source)) for source in (
    "co2", "enso", "sea_ice", "ozone_hole", "nsidc_snow", "climate_indices", "ice_mass"))
RESTRICTIONS: dict[str, tuple[str, Any]] = {
    "not_station_observation": ("A model, reanalysis or satellite value is not a station measurement.",
                                tuple((selector, _CLAIMS) for selector in (*_FORECAST_MARKED, *_MODEL_FALLBACK))),
    "forecast_not_outcome": ("A forecast or warning does not prove the forecast impact occurred.",
                             tuple((selector, _CLAIMS) for selector in _FORECAST_MARKED)),
    "no_landfall_inference": ("Advisory positions and forecast points do not establish landfall.",
                              (("nhc", _CLAIMS), ("jtwc", _CLAIMS), ("gdacs", _CLAIMS))),
    "alternate_not_primary_recovery": ("An alternate or witness serving is degraded service, not primary recovery.",
                                       _LABELLED_DEGRADED),
    "cache_not_current_availability": ("A retained last-good value is not current provider availability.",
                                       _CACHE_DEGRADED),
    "reference_not_reading": ("A baseline, threshold or climatology is comparison input, not a new reading.",
                              (("open_meteo_extreme_signals.om_era5_archive",
                                "src/data/world_thresholds.py:record_comparison_qualification"),
                               ("open_meteo_extreme_signals.ghcn_station_history", _GHCN_HISTORY))),
    "record_needs_qualified_history": ("A record claim needs a qualified history for that station product.",
                                       (("open_meteo_extreme_signals.ghcn_daily", _GHCN_HISTORY),
                                        ("open_meteo_extreme_signals.ghcn_station_history", _GHCN_HISTORY))),
    "threshold_not_record": ("A trigger threshold is not an archive record.", (("gpm_imerg", _CLAIMS),)),
    "ambiguous_episode_held": ("Conflicting current GDACS episodes stay held; no episode is chosen.",
                               (("gdacs.georss", "src/data/gdacs_intake.py:reconcile"),)),
    "aq_window_contract": ("Air-quality windows must pass their model-window contract.",
                           tuple((selector, "src/data/air_quality_evidence.py:bundle_failures")
                                 for selector in ("air_quality.cams_pm25", "air_quality.cams_dust"))),
    "crw_climatology_contract": ("CRW anomalies keep their product climatology and sample bounds.",
                                 (("ocean_sst_anomaly", "src/two_bot/evidence_contract.py:audit_story_bundle"),)),
    "thermal_receipt_contract": ("Thermal detections need a consistent source minute and receipt.",
                                 (("firms.viirs_noaa21_nrt", "src/data/fire_evidence.py:fire_bundle_failures"),)),
    "association_not_shared_footprint": ("Paired products keep their own dates and footprints; a configured "
                                         "association is not a shared footprint or simultaneous event.",
                                         (("synthesis_fire_drought_heat.marine_compound",
                                           "src/editorial/marine_evidence.py:claim_failures"),)),
    "reported_not_adjudicated": ("A reported area, alert or activation is not an adjudicated impact total.", ADVISORY),
    "detection_not_cause_or_area": ("A thermal detection is not burned area, cause or casualties.", ADVISORY),
    "index_not_local_incident": ("An index or series milestone is not a local incident.", ADVISORY),
    "discovery_not_qualified": ("A discovery result is not a qualified candidate or event census.", ADVISORY),
    "crw_heat_stress_not_bleaching": ("Coral heat stress is not observed bleaching or reef death.", ADVISORY),
    "co_occurrence_not_causation": ("A derived overlap does not establish causation.", ADVISORY),
    "region_sample_not_census": ("Sampled points or regions are not complete geographic coverage.", ADVISORY),
}
_KIND_REQUIRES = {
    "forecast_model": {"not_station_observation"},
    "reanalysis": {"not_station_observation"},
    "satellite_derived": {"not_station_observation"},
    "expert_analysis": {"not_station_observation"},
    "official_warning": {"forecast_not_outcome"},
    "official_event_report": {"reported_not_adjudicated"},
    "source_reported_impact": {"reported_not_adjudicated"},
    "official_reference": {"reference_not_reading"},
    "derived_index": {"index_not_local_incident"},
    "derived_combination": {"co_occurrence_not_causation"},
    "discovery": {"discovery_not_qualified"},
    "observed_station": {"record_needs_qualified_history"},
}
_ROLE_REQUIRES = {
    "alternate_route": {"alternate_not_primary_recovery"},
    "alternate_product": {"alternate_not_primary_recovery"},
    "witness": {"alternate_not_primary_recovery"},
    "cache": {"cache_not_current_availability"},
    "reference": {"reference_not_reading"},
}
_SERVING_ROLES = frozenset({"alternate_route", "alternate_product", "witness", "cache"})
_ID = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_PRODUCT_ID = re.compile(r"[a-z][a-z0-9_]{0,79}\.[a-z][a-z0-9_]{0,79}\Z")
_CODE_REF = re.compile(r"src/[a-zA-Z0-9_/]+\.py:[A-Za-z_][A-Za-z0-9_]*\Z")
_UPSTREAM = re.compile(r"[a-z][a-z0-9_]{0,63}\.[a-z0-9][a-z0-9_]{0,79}\Z")


@dataclass(frozen=True)
class ProductLeg:
    product_id: str
    source_id: str
    chain: str
    role: str
    status: str
    provider: str
    upstream: str
    data_kind: str
    health_keys: tuple[str, ...]
    runtime_leg_label: str | None
    product: str
    geographic_limit: str
    time_limit: str
    units_limit: str
    provenance: str
    request_bound: str
    disposition: str
    claim_restrictions: tuple[str, ...]
    code_refs: tuple[str, ...]
    claim_permissions: tuple[str, ...] = ()


_NOT_STATION = ("not_station_observation",)
_ALT = ("alternate_not_primary_recovery",)
_CACHE_TEXT = "Latest retained value only, bounded by the collector's last-good age limit."


def _leg(source_id, leg, chain, role, provider, upstream, kind, product, geo, time_limit, units, provenance,
         restrictions, refs, *, health=None, runtime=None, status="wired", bound="", disposition=""):
    return ProductLeg(f"{source_id}.{leg}", source_id, chain, role, status, provider, upstream, kind,
                      health or (source_id,), runtime, product, geo, time_limit, units, provenance, bound,
                      disposition, tuple(restrictions), tuple(refs))


def _cache(source_id, chain, kind, provider, upstream, refs, *, health=None, leg="last_good_cache"):
    restrictions = ("cache_not_current_availability", *sorted(_KIND_REQUIRES[kind]))
    return _leg(source_id, leg, chain, "cache", provider, upstream, kind, "Retained last-good reading",
                "Same as the product it retains.", _CACHE_TEXT, "Same as the retained product.",
                "Compact last-good payload written after a successful collection.", restrictions, refs,
                health=health, runtime="last_good")


LEGS: tuple[ProductLeg, ...] = (
    # 1. GHCN observed station path versus the Open-Meteo forecast/model path.
    _leg("open_meteo_extreme_signals", "om_forecast", "forecast", "primary", "open_meteo",
         "open_meteo.best_match_forecast_daily", "forecast_model", "Best-match daily forecast",
         "Configured cities only.", "Forecast valid date; collection time is not measurement time.", "degrees C",
         "Open-Meteo best-match forecast product.", ("not_station_observation", "forecast_not_outcome"),
         ("src/data/open_meteo.py:fetch_forecasts_batch", "src/data/temperature_evidence.py:FORECAST_PRODUCT")),
    _leg("open_meteo_extreme_signals", "om_era5_archive", "forecast", "reference", "open_meteo",
         "open_meteo.era5_archive_daily", "reanalysis", "ERA5 daily archive climatology",
         "Configured cities; request-count-limited warm set.", "Archive cutoff and baseline period.", "degrees C",
         "ERA5 reanalysis through the Open-Meteo archive.", ("not_station_observation", "reference_not_reading"),
         ("src/data/open_meteo.py:fetch_archive_daily", "src/data/world_thresholds.py:record_comparison_qualification"),
         bound="Warm refresh is request-count-limited per run; not a spending cap."),
    _leg("open_meteo_extreme_signals", "ghcn_daily", "station", "primary", "noaa_ncei_ghcn",
         "noaa_ncei.ghcn_daily_superghcnd_diff", "observed_station", "GHCN-Daily station observations",
         "Stations returned in the daily diff; not every country.", "Station source-calendar day; not a UTC interval.",
         "degrees C", "NOAA NCEI GHCN-Daily diff files.", ("record_needs_qualified_history",),
         ("src/data/ghcn.py:_fetch_diff", "src/data/ghcn.py:record_comparison_qualified"), status="conditional",
         disposition="Separately gated GHCN supply path; existing qualification rules decide each station."),
    _leg("open_meteo_extreme_signals", "ghcn_station_history", "station", "reference", "noaa_ncei_ghcn",
         "noaa_ncei.ghcn_daily_station_archive", "observed_station", "GHCN-Daily station history",
         "Individual stations checked by the GHCN path.", "Archive cutoff and minimum archive years.", "degrees C",
         "NOAA NCEI per-station archive.", ("record_needs_qualified_history", "reference_not_reading"),
         ("src/data/ghcn.py:_fetch_station_archive", "src/data/ghcn.py:record_comparison_qualified"),
         status="conditional", disposition="Used only by the separately gated GHCN record comparison."),
    # 2. GPM full grid, bounded OPeNDAP fallback and Open-Meteo model witness.
    _leg("gpm_imerg", "imerg_late_opendap", "imerg_late", "primary", "nasa_gesdisc",
         "nasa_gesdisc.gpm_3imergdl_07", "satellite_derived", "IMERG Late daily (V07) point subsets",
         "Rotating canonical window of configured cities.", "Product date; walks back over unpublished dates.",
         "mm per day", "NASA GES DISC OPeNDAP point subsets.", (*_NOT_STATION, "threshold_not_record"),
         ("src/data/gpm_imerg.py:_fetch_city_precip", "src/data/gpm_imerg.py:_network_watchlist"),
         bound="At most 75 per-city network requests per leg per run; not a spending cap."),
    _leg("gpm_imerg", "imerg_late_grid_datapool", "imerg_late", "alternate_route", "nasa_gesdisc",
         "nasa_gesdisc.gpm_3imergdl_07", "satellite_derived", "IMERG Late daily (V07) full grid",
         "Whole qualified watchlist from one downloaded grid.", "Product date; walks back over unpublished dates.",
         "mm per day", "NASA GES DISC data pool grid file.", (*_NOT_STATION, *_ALT, "threshold_not_record"),
         ("src/data/gpm_imerg.py:_fetch_grid_bytes_datapool", "src/data/gpm_imerg.py:_subset_grid"),
         status="conditional", disposition="Selected only by the configured grid source.",
         bound="One grid download per walkback candidate."),
    _leg("gpm_imerg", "imerg_late_grid_s3", "imerg_late", "alternate_route", "nasa_gesdisc",
         "nasa_gesdisc.gpm_3imergdl_07", "satellite_derived", "IMERG Late daily (V07) full grid",
         "Whole qualified watchlist from one downloaded grid.", "Product date; walks back over unpublished dates.",
         "mm per day", "NASA GES DISC cloud bucket grid file.", (*_NOT_STATION, *_ALT, "threshold_not_record"),
         ("src/data/gpm_imerg.py:_fetch_grid_bytes_s3", "src/data/gpm_imerg.py:_gpm_grid_source_chain"),
         status="conditional", disposition="Selected only by deliberate configuration; same-region execution needed.",
         bound="One grid download per walkback candidate."),
    _leg("gpm_imerg", "open_meteo_witness", "imerg_late", "witness", "open_meteo",
         "open_meteo.forecast_ensemble_precipitation", "forecast_model", "Model precipitation with ensemble agreement",
         "Same rotating window; disagreeing cities are omitted.", "Previous UTC day from the fixed selection date.",
         "mm per day", "Open-Meteo deterministic forecast with ensemble agreement.",
         (*_NOT_STATION, *_ALT, "threshold_not_record"),
         ("src/data/gpm_imerg.py:_fetch_precip_open_meteo", "src/data/gpm_imerg.py:_open_meteo_precip_with_agreement"),
         runtime="open_meteo", bound="At most 75 witness points per run; not a spending cap."),
    _leg("gpm_imerg", "imerg_final_reference", "imerg_final", "retired", "nasa_gesdisc",
         "nasa_gesdisc.gpm_3imergdf_07", "satellite_derived", "IMERG Final daily (V07)",
         "Not collected by the alerts runner.", "Months of latency; archive reference only.", "mm per day",
         "NASA GES DISC Final product path retained in code.", _NOT_STATION,
         ("src/data/gpm_imerg.py:FINAL_OPENDAP_BASE",), status="retired",
         disposition="Archive reference path only; Barrow granule/gauge reconciliation remains unresolved."),
    # 3. NHC index versus retained advisory text products; JTWC serving RSS legs.
    _leg("nhc", "current_storms_index", "nhc", "primary", "nhc", "nhc.current_storms_json", "official_warning",
         "CurrentStorms index", "Atlantic and East Pacific active storms.", "Storm issue time; never file update time.",
         "kt, mb, degrees", "NHC CurrentStorms index rows.", ("forecast_not_outcome", "no_landfall_inference"),
         ("src/data/nhc.py:fetch_active_cyclones", "src/data/nhc.py:_parse_active_storm")),
    _leg("nhc", "public_advisory_text", "nhc_public", "component", "nhc", "nhc.public_advisory_text",
         "official_warning", "Public advisory text", "Storms named by the index.", "Product issuance in the advisory.",
         "As stated in the product", "NHC public advisory text product.", ("forecast_not_outcome", "no_landfall_inference"),
         ("src/data/nhc.py:_fetch_advisory_text",)),
    _leg("nhc", "forecast_advisory_text", "nhc_forecast", "component", "nhc", "nhc.forecast_advisory_tcm",
         "official_warning", "Forecast/advisory track text", "Storms named by the index.",
         "Forecast valid times; future points are forecasts.", "kt, degrees",
         "NHC forecast/advisory text, retained with exact bytes when observed.",
         ("forecast_not_outcome", "no_landfall_inference"),
         ("src/data/nhc.py:_fetch_advisory_text", "src/orchestrator/cyclone_episodes.py:CycloneEpisodeLane")),
    _leg("jtwc", "enhanced_rss", "jtwc", "primary", "jtwc", "jtwc.rss_enhanced", "official_warning",
         "Enhanced RSS warnings", "JTWC areas of responsibility represented in the RSS.", "Warning issue time.",
         "kt, degrees", "JTWC enhanced RSS layout.", ("forecast_not_outcome", "no_landfall_inference"),
         ("src/data/jtwc.py:fetch_active_cyclones", "src/data/jtwc.py:parse_rss")),
    _leg("jtwc", "plain_rss", "jtwc", "alternate_route", "jtwc", "jtwc.rss_plain", "official_warning",
         "Plain RSS warnings", "JTWC areas of responsibility represented in the RSS.", "Warning issue time.",
         "kt, degrees", "JTWC plain RSS layout.", ("forecast_not_outcome", "no_landfall_inference", *_ALT),
         ("src/data/jtwc.py:JTWC_PLAIN_RSS_LEG",), runtime="plain_rss"),
    _leg("jtwc", "warning_text", "jtwc_text", "component", "jtwc", "jtwc.warning_product_text", "official_warning",
         "Warning product text", "Warnings linked from the serving RSS.", "Warning issue time.", "kt, degrees",
         "JTWC warning text linked from the RSS item.", ("forecast_not_outcome", "no_landfall_inference"),
         ("src/data/jtwc.py:_fetch_product_text",)),
    # 4. GDACS current routes and ambiguous-episode containment.
    _leg("gdacs", "georss", "gdacs", "primary", "gdacs", "gdacs.georss", "official_event_report",
         "Limited GeoRSS product", "Configured alert levels in the returned feed.",
         "Publication clock and explicit current episode only.", "Alert level and source magnitude fields",
         "GDACS GeoRSS feed.", ("reported_not_adjudicated", "ambiguous_episode_held"),
         ("src/data/gdacs.py:_fetch_disasters_primary", "src/data/gdacs_intake.py:reconcile")),
    _leg("gdacs", "map_api", "gdacs_map", "retired", "gdacs", "gdacs.events_map_api", "official_event_report",
         "Events MAP API", "Not requested.", "Not applicable while withdrawn.", "Not applicable",
         "GDACS MAP route retained only as a parser.", ("reported_not_adjudicated",),
         ("src/data/gdacs.py:_events_from_features",), status="retired",
         disposition="Withdrawn pending qualification; never probed by the current primary."),
    *(
        _leg("gdacs", f"subtype_witness_{name}", "gdacs", "witness", provider, upstream, kind, label,
             scope, "Each upstream product's own time.", "As in the upstream product", provenance,
             ("reported_not_adjudicated", *_ALT, *extra), ("src/data/gdacs.py:_fetch_subtype_witnesses",),
             runtime="subtype_witnesses")
        for name, provider, upstream, kind, label, scope, provenance, extra in (
            ("usgs", "usgs_earthquake", "usgs.significant_day_feed", "official_event_report",
             "Earthquake subtype witness", "Earthquake subtype only.", "Reuses the USGS significant feed.", ()),
            ("nhc", "nhc", "nhc.current_storms_json", "official_warning", "Cyclone subtype witness",
             "Tropical-cyclone subtype only.", "Reuses the NHC CurrentStorms index.",
             ("forecast_not_outcome", "no_landfall_inference")),
            ("jtwc", "jtwc", "jtwc.rss_enhanced", "official_warning", "Cyclone subtype witness",
             "Tropical-cyclone subtype only.", "Reuses the JTWC warning RSS.",
             ("forecast_not_outcome", "no_landfall_inference")),
        )
    ),
    _leg("gdacs", "reliefweb_witness", "gdacs_reliefweb", "unresolved", "reliefweb", "reliefweb.disasters",
         "source_reported_impact", "Disaster reports", "Not requested.", "Not applicable.", "Not applicable",
         "No wired ReliefWeb route.", ("reported_not_adjudicated",), ("src/data/gdacs.py:_fetch_subtype_witnesses",),
         status="unresolved", disposition="Blocked on provider application approval; no route is wired."),
    # 5. FIRMS available instrument legs and retired S-NPP.
    _leg("firms", "viirs_noaa21_nrt", "firms", "primary", "nasa_firms", "nasa_firms.viirs_noaa21_nrt",
         "satellite_derived", "VIIRS NOAA-21 NRT detections", "Configured cluster selection.",
         "Acquisition minute; not fire start time.", "MW (FRP), confidence class", "NASA FIRMS area API.",
         (*_NOT_STATION, "detection_not_cause_or_area", "thermal_receipt_contract"),
         ("src/data/firms.py:fetch_fires", "src/data/fire_source_contract.py:parse_record")),
    _leg("firms", "viirs_noaa20_nrt", "firms", "alternate_product", "nasa_firms", "nasa_firms.viirs_noaa20_nrt",
         "satellite_derived", "VIIRS NOAA-20 NRT detections", "Same host and selection.",
         "Acquisition minute; not fire start time.", "MW (FRP), confidence class", "NASA FIRMS area API.",
         (*_NOT_STATION, "detection_not_cause_or_area", *_ALT), ("src/data/firms.py:_fetch_fires_product_chain",),
         runtime="VIIRS_NOAA20_NRT"),
    _leg("firms", "modis_nrt", "firms", "alternate_product", "nasa_firms", "nasa_firms.modis_nrt",
         "satellite_derived", "MODIS NRT detections", "Same host and selection.",
         "Acquisition minute; not fire start time.", "MW (FRP), confidence class", "NASA FIRMS area API.",
         (*_NOT_STATION, "detection_not_cause_or_area", *_ALT), ("src/data/firms.py:_fetch_fires_product_chain",),
         runtime="MODIS_NRT"),
    _leg("firms", "noaa_hms", "firms", "witness", "noaa_nesdis_hms", "noaa_nesdis.hms_fire_points",
         "satellite_derived", "HMS fire points", "North American box only; nothing outside it.",
         "Source minute on the daily file.", "MW (FRP) where supplied", "NOAA NESDIS HMS text file.",
         (*_NOT_STATION, "detection_not_cause_or_area", *_ALT), ("src/data/firms.py:_fetch_fires_hms",),
         runtime="noaa_hms"),
    _leg("firms", "viirs_snpp_nrt", "firms_snpp", "retired", "nasa_firms", "nasa_firms.viirs_snpp_nrt",
         "satellite_derived", "VIIRS S-NPP NRT detections", "Not collected.", "Historical receipts only.",
         "MW (FRP)", "Retained product enum for historical receipts.", (*_NOT_STATION, "detection_not_cause_or_area"),
         ("src/data/fire_source_contract.py:FIRMS_PRODUCTS", "src/data/firms.py:fetch_fires"), status="retired",
         disposition="Active collection refuses S-NPP; historical receipts stay readable."),
    # 6. CRW primary/alternate products and their point/region/climatology limits.
    _leg("ocean_sst_anomaly", "coastwatch_erddap", "crw_ssta", "primary", "noaa_crw", "noaa_crw.ssta_daily_v3_1",
         "satellite_derived", "CRW SST anomaly (5 km)", "Configured regional boxes; valid sampled cells only.",
         "Product day; CRW climatology baseline.", "degrees C anomaly", "NOAA CoastWatch ERDDAP grid.",
         (*_NOT_STATION, "crw_climatology_contract", "region_sample_not_census"),
         ("src/data/ocean_sst_anomaly.py:_fetch_region_sample_strict", "src/data/crw_contract.py:decode_csv")),
    _leg("ocean_sst_anomaly", "noaa_star_nc", "crw_ssta", "alternate_route", "noaa_crw", "noaa_crw.ssta_daily_v3_1",
         "satellite_derived", "CRW SST anomaly native file", "Same regional boxes from the native file.",
         "Product day; CRW climatology baseline.", "degrees C anomaly", "NOAA STAR native netCDF.",
         (*_NOT_STATION, "crw_climatology_contract", "region_sample_not_census", *_ALT),
         ("src/data/ocean_sst_anomaly.py:_fetch_noaa_star_ssta_samples_strict",), runtime="noaa_star_nc"),
    _leg("coral_dhw", "crw_virtual_station", "crw_dhw", "primary", "noaa_crw", "noaa_crw.regional_virtual_stations",
         "satellite_derived", "CRW regional virtual-station DHW", "Active regional virtual stations.",
         "Station product date.", "degree heating weeks", "NOAA CRW virtual-station files.",
         (*_NOT_STATION, "crw_heat_stress_not_bleaching", "region_sample_not_census"),
         ("src/data/coral_dhw.py:_fetch_coral_dhw_primary", "src/data/coral_regional_contract.py:decode_station")),
    _leg("coral_dhw", "crw_erddap", "crw_dhw", "alternate_product", "noaa_crw", "noaa_crw.dhw_daily_v3_1",
         "satellite_derived", "CRW DHW grid points", "Fixed point list, not the regional product.",
         "Grid day; can lag the regional index.", "degree heating weeks", "NOAA CoastWatch ERDDAP grid points.",
         (*_NOT_STATION, "crw_heat_stress_not_bleaching", "region_sample_not_census", *_ALT),
         ("src/data/coral_dhw.py:_fetch_coral_dhw_erddap", "src/data/coral_source_contract.py:decode_point"),
         runtime="crw_erddap"),
    # 7. AQ PM2.5, dust and optional station corroboration, with distinct availability.
    _leg("air_quality", "cams_pm25", "aq_pm25", "primary", "open_meteo", "open_meteo.cams_air_quality",
         "forecast_model", "CAMS PM2.5 window", "Configured cities; PM2.5 lane flag.",
         "Model window valid hours.", "micrograms per cubic metre", "CAMS estimates through Open-Meteo.",
         (*_NOT_STATION, "forecast_not_outcome", "aq_window_contract"),
         ("src/data/air_quality.py:detect_pm25_hazard", "src/data/air_quality_availability.py:source_status"),
         status="conditional", disposition="Enabled by the PM2.5 lane flag; availability reported per lane."),
    _leg("air_quality", "cams_dust", "aq_dust", "primary", "open_meteo", "open_meteo.cams_air_quality",
         "forecast_model", "CAMS dust window", "Configured cities; dust lane flag.", "Model window valid hours.",
         "micrograms per cubic metre", "CAMS estimates through Open-Meteo.",
         (*_NOT_STATION, "forecast_not_outcome", "aq_window_contract"),
         ("src/data/air_quality.py:detect_dust_event", "src/data/air_quality_availability.py:source_status"),
         status="conditional", disposition="Enabled by the dust lane flag; dust is not proof of smoke or cause."),
    _leg("air_quality", "openaq_pm25", "aq_pm25", "corroboration", "openaq", "openaq.latest_pm25",
         "observed_station", "OpenAQ latest PM2.5", "Nearest reporting station, when configured.",
         "Station reading time.", "micrograms per cubic metre", "OpenAQ latest measurements.",
         ("record_needs_qualified_history",), ("src/data/openaq.py:fetch_latest_pm25",), status="conditional",
         disposition="Optional; absent configuration means no station corroboration."),
)


def _single(source_id, leg, provider, upstream, kind, product, geo, units, provenance, refs, *,
            restrictions=(), health=None, time_limit="Product's own date or valid period.", status="wired",
            disposition="", chain=None, role="primary", runtime=None, bound=""):
    required = set(_KIND_REQUIRES[kind]) | set(restrictions)
    return _leg(source_id, leg, chain or source_id, role, provider, upstream, kind, product, geo, time_limit,
                units, provenance, tuple(sorted(required)), refs, health=health, runtime=runtime,
                status=status, disposition=disposition, bound=bound)


# Every other adapter in the frozen accepted-base inventory, including the leaderboard.
LEGS += (
    _single("drought", "usdm_state_statistics", "us_drought_monitor", "usdm.state_statistics", "expert_analysis",
            "US Drought Monitor state statistics", "US states selected by the collector.", "percent of area",
            "Weekly drought analysis.", ("src/data/drought.py:fetch_drought_data",)),
    _single("fire_footprint", "wfigs_incidents", "nifc_wfigs", "nifc.wfigs_incident_locations_current",
            "source_reported_impact", "WFIGS current incident locations", "US incidents in the configured query.",
            "acres (reported)", "NIFC WFIGS reported incident size.",
            ("src/data/fire_footprint.py:fetch_active_fire_perimeters",)),
    _single("co2", "mlo_daily", "noaa_gml", "noaa_gml.co2_daily_mlo", "observed_station",
            "Mauna Loa daily CO2", "One observatory series; milestone framing only.", "ppm",
            "NOAA GML Mauna Loa daily series.", ("src/data/co2.py:fetch_co2_data",),
            restrictions=("index_not_local_incident",)),
    _cache("co2", "co2", "observed_station", "noaa_gml", "noaa_gml.co2_daily_mlo",
           ("src/orchestrator/sources/co2.py:_write_co2_last_good", "src/data/last_good.py:read")),
    _single("ch4_milestone", "global_monthly_mean", "noaa_gml", "noaa_gml.ch4_global_monthly", "derived_index",
            "Global monthly methane", "Global marine-surface mean.", "ppb", "NOAA GML global monthly series.",
            ("src/data/methane.py:fetch_ch4_milestones",)),
    _single("nws_alerts", "active_alerts", "nws", "nws.alerts_active", "official_warning", "Active alerts",
            "US warning areas returned by the feed.", "As stated in the product", "NWS issued alert products.",
            ("src/data/nws_alerts.py:fetch_alerts",), time_limit="Issue, effective and expiry times."),
    _single("usgs_quakes", "significant_day_feed", "usgs_earthquake", "usgs.significant_day_feed",
            "official_event_report", "Significant earthquakes (past day)", "Events in the feed.",
            "magnitude, depth km", "USGS event products.", ("src/data/usgs_quakes.py:fetch_significant_earthquakes",)),
    _single("copernicus_ems", "rapid_mapping_api", "copernicus_ems", "copernicus_ems.rapid_mapping_activations",
            "official_event_report", "Rapid Mapping flood activations", "Activations in the configured routes.",
            "Not a measured footprint", "Copernicus EMS activation summary/detail routes.",
            ("src/data/copernicus_ems.py:_fetch_active_flood_activations_primary",)),
    _single("copernicus_ems", "frontend_api", "copernicus_ems", "copernicus_ems.rapid_mapping_activations",
            "official_event_report", "Rapid Mapping activations (frontend route)", "Same activations, other route.",
            "Not a measured footprint", "Copernicus EMS frontend activation route.",
            ("src/data/copernicus_ems.py:_fetch_frontend_flood_activations",), role="alternate_route",
            restrictions=_ALT, runtime="frontend_api", chain="copernicus_ems"),
    *(
        leg
        for hemisphere, key in (("arctic", "sea_ice_arctic"), ("antarctic", "sea_ice_antarctic"))
        for leg in (
            _single("sea_ice", f"nsidc_{hemisphere}", "nsidc", f"nsidc.g02135_{hemisphere}_daily", "satellite_derived",
                    f"Sea Ice Index daily extent ({hemisphere})", f"{hemisphere.title()} hemisphere series.",
                    "million km2", "NSIDC G02135 daily extent file.", ("src/data/sea_ice.py:_fetch_sea_ice_primary",),
                    health=(key,), chain=f"sea_ice_{hemisphere}"),
            _single("sea_ice", f"osi_saf_{hemisphere}", "osi_saf", f"osi_saf.ice_conc_{hemisphere}",
                    "satellite_derived", f"Sea-ice concentration witness ({hemisphere})",
                    f"{hemisphere.title()} hemisphere grids.", "million km2 (derived extent)",
                    "OSI SAF concentration grids; extent derived locally.",
                    ("src/data/sea_ice_witness.py:fetch_osi_saf_sea_ice",), health=(key,),
                    chain=f"sea_ice_{hemisphere}", role="witness", restrictions=_ALT, runtime="osi_saf"),
            _cache("sea_ice", f"sea_ice_{hemisphere}", "satellite_derived", "nsidc", f"nsidc.g02135_{hemisphere}_daily",
                   ("src/orchestrator/sources/sea_ice.py:run_sea_ice", "src/data/last_good.py:read"),
                   health=(key,), leg=f"last_good_cache_{hemisphere}"),
        )
    ),
    _single("enso", "oni", "noaa_cpc", "noaa_cpc.oni", "derived_index", "Oceanic Nino Index",
            "Nino 3.4 region index.", "degrees C anomaly", "NOAA CPC ONI table.", ("src/data/enso.py:fetch_enso_data",),
            time_limit="Three-month season of the index row."),
    _cache("enso", "enso", "derived_index", "noaa_cpc", "noaa_cpc.oni",
           ("src/orchestrator/sources/enso.py:run_enso", "src/data/last_good.py:read")),
    *(
        leg
        for name, provider, upstream, ref in (
            ("nao", "noaa_cpc", "noaa_cpc.nao_monthly", "src/data/climate_indices.py:fetch_nao"),
            ("ao", "noaa_cpc", "noaa_cpc.ao_monthly", "src/data/climate_indices.py:fetch_ao"),
            ("pdo", "noaa_psl", "noaa_psl.pdo_ersstv5", "src/data/climate_indices.py:fetch_pdo"),
        )
        for leg in (
            _single("climate_indices", name, provider, upstream, "derived_index", f"{name.upper()} monthly index",
                    "Basin-scale index.", "standardized index", "Published monthly index series.", (ref,),
                    health=(name,), chain=name, time_limit="Index month."),
            _cache("climate_indices", name, "derived_index", provider, upstream,
                   ("src/orchestrator/sources/climate_indices.py:run_climate_indices", "src/data/last_good.py:read"),
                   health=(name,), leg=f"last_good_cache_{name}"),
        )
    ),
    _single("climate_indices", "nao_ao_alignment", "theheat_retained", "theheat.nao_ao_alignment",
            "derived_combination", "NAO/AO alignment", "Derived from the two index rows.", "index sign agreement",
            "Local combination of NAO and AO.", ("src/data/climate_indices.py:detect_nao_ao_alignment",),
            health=("nao_ao_alignment",), chain="nao_ao_alignment", restrictions=("index_not_local_incident",)),
    _single("ocean", "marine_forecast", "open_meteo", "open_meteo.marine", "forecast_model", "Marine model",
            "Configured marine sampling points.", "m, s", "Open-Meteo Marine model.",
            ("src/data/ocean.py:fetch_ocean_conditions",), restrictions=("forecast_not_outcome", "region_sample_not_census")),
    _single("ocean_sst", "oisst_global", "climate_reanalyzer", "climate_reanalyzer.oisst_v2_1_world",
            "satellite_derived", "OISST v2.1 world series", "Global summary series only.", "degrees C",
            "NOAA OISST v2.1 via ClimateReanalyzer.", ("src/data/ocean_sst.py:fetch_global_sst",),
            restrictions=("region_sample_not_census",)),
    _single("water_levels", "coops_water_level", "noaa_coops", "noaa_coops.water_level", "observed_station",
            "CO-OPS water level", "Configured coastal stations.", "m relative to station datum",
            "NOAA CO-OPS station readings.", ("src/data/water_levels.py:fetch_water_levels",),
            restrictions=("region_sample_not_census",)),
    _single("river_gauges", "usgs_gauge_height", "usgs_nwis", "usgs_nwis.instantaneous_values", "observed_station",
            "Instantaneous gauge height", "Configured US river stations.", "ft gauge height",
            "USGS NWIS instantaneous values.", ("src/data/river_gauges.py:_fetch_river_levels_primary",),
            chain="river_gauges"),
    _single("river_gauges", "nwps_flood_stage", "noaa_nwps", "noaa_nwps.gauge_flood_categories",
            "official_reference", "NWPS flood categories", "Configured US river stations.", "ft stage thresholds",
            "NOAA NWPS gauge flood categories.", ("src/data/river_gauges.py:_fetch_flood_stages",),
            chain="river_gauges", role="reference"),
    _single("river_gauges", "open_meteo_flood", "open_meteo", "open_meteo.glofas_flood", "forecast_model",
            "GloFAS model discharge", "Explicitly mapped alternate points only.", "m3/s discharge (not stage)",
            "Open-Meteo flood (GloFAS) model.", ("src/data/river_gauges.py:_fetch_open_meteo_flood",),
            chain="river_gauges", role="witness", restrictions=_ALT, runtime="open_meteo_flood"),
    *(
        leg
        for region, key in (("greenland", "ice_mass_greenland"), ("antarctica", "ice_mass_antarctica"))
        for leg in (
            _single("ice_mass", f"grace_fo_{region}", "nasa_jpl_grace", f"nasa_jpl.grace_fo_mascon_{region}",
                    "satellite_derived", f"GRACE-FO mass series ({region})", f"{region.title()} regional series.",
                    "Gt", "NASA GRACE-FO granules found through CMR.", ("src/data/ice_mass.py:fetch_grace_mass",),
                    health=(key,), chain=f"ice_mass_{region}", time_limit="Monthly solution period."),
            _cache("ice_mass", f"ice_mass_{region}", "satellite_derived", "nasa_jpl_grace",
                   f"nasa_jpl.grace_fo_mascon_{region}",
                   ("src/orchestrator/sources/ice_mass.py:run_ice_mass", "src/data/last_good.py:read"),
                   health=(key,), leg=f"last_good_cache_{region}"),
        )
    ),
    _single("nsidc_snow", "snow_today_swe", "nsidc", "nsidc.snow_today_swe_points", "observed_station",
            "Snow Today SWE points", "Provider-returned points; completeness unverified.", "mm SWE (not depth)",
            "NSIDC Snow Today point product.", ("src/data/nsidc_snow.py:fetch_snow_today",),
            restrictions=("region_sample_not_census",)),
    _cache("nsidc_snow", "nsidc_snow", "observed_station", "nsidc", "nsidc.snow_today_swe_points",
           ("src/orchestrator/sources/nsidc_snow.py:run_nsidc_snow", "src/data/last_good.py:read")),
    _single("ozone_hole", "area_daily", "nasa_ozone_watch", "nasa_ozone_watch.to3_areas", "satellite_derived",
            "Ozone-hole daily area", "Antarctic ozone hole.", "million km2", "NASA Ozone Watch area table.",
            ("src/data/ozone_hole.py:fetch_ozone_hole_data",)),
    _single("ozone_hole", "annual_peaks", "nasa_ozone_watch", "nasa_ozone_watch.annual_peaks", "satellite_derived",
            "Ozone-hole annual peaks", "Antarctic ozone hole.", "million km2", "NASA Ozone Watch annual statistics.",
            ("src/data/ozone_hole.py:fetch_ozone_hole_annual_peaks",), role="reference",
            restrictions=("reference_not_reading",), chain="ozone_hole"),
    _cache("ozone_hole", "ozone_hole", "satellite_derived", "nasa_ozone_watch", "nasa_ozone_watch.to3_areas",
           ("src/orchestrator/sources/ozone_hole.py:run_ozone_hole", "src/data/last_good.py:read")),
    _single("reanalysis_anomaly", "era5_daily", "open_meteo", "open_meteo.era5_archive_daily", "reanalysis",
            "ERA5 daily 2 m temperature", "Configured sampled-city regions.", "degrees C",
            "ERA5 reanalysis through the Open-Meteo archive.", ("src/data/reanalysis_anomaly.py:fetch_all_reganom_t2m",),
            restrictions=("region_sample_not_census",), status="conditional",
            disposition="Collected only when its opt-in flag and climatology allow."),
    _single("reanalysis_anomaly", "retained_climatology", "theheat_retained", "theheat.era5_daily_climatology",
            "reanalysis", "Checked-in daily climatology", "Configured sampled-city regions.", "degrees C",
            "Repository ERA5-derived climatology cache.", ("src/data/reanalysis_anomaly.py:load_daily_climatology",),
            role="reference", restrictions=("reference_not_reading",), chain="reanalysis_anomaly",
            status="conditional", disposition="Absent cache skips the collector."),
    _single("newsworthiness", "nifc_incidents", "nifc_wfigs", "nifc.wfigs_incident_locations_current",
            "official_event_report", "WFIGS current incidents", "US incidents in the configured query.",
            "acres, personnel (reported)", "NIFC WFIGS structured incident fields.",
            ("src/data/newsworthiness.py:_fetch_nifc_events",), chain="nifc", status="conditional",
            disposition="Collected only when the newsworthiness opt-in flag allows."),
    _single("newsworthiness", "grounded_search", "grounded_search", "grounded_search.cited_results", "discovery",
            "Grounded-search cited events", "Results cited by the verification path.", "As cited",
            "Search-grounded model output, kept only when verified.", ("src/data/newsworthiness.py:_grounded_leg",),
            chain="grounded", status="conditional",
            disposition="Opt-in discovery lane; verification usage cost remains unattributed."),
    _single("synthesis_fire_drought_heat", "component_overlap", "theheat_retained", "theheat.fire_drought_heat_overlap",
            "derived_combination", "Fire/drought/heat overlap", "Overlaps among retained components.",
            "Component units", "Derived from component sources; not an independent feed.",
            ("src/orchestrator/sources/synthesis.py:run_synthesis", "src/editorial/synthesis.py:detect_fire_drought_heat")),
    # The same runner also pairs retained CRW DHW and regional SST anomaly components.
    _single("synthesis_fire_drought_heat", "marine_compound", "theheat_retained", "theheat.crw_dhw_sst_marine_compound",
            "derived_combination", "CRW DHW / regional SST anomaly pairing",
            "Configured coral-region to SST-region association; not a shared measurement footprint.",
            "degree heating weeks; degrees C anomaly",
            "Pairs separately qualified retained CRW DHW and regional SST anomaly components; not an independent feed.",
            ("src/editorial/synthesis.py:detect_marine_compound", "src/editorial/marine_evidence.py:select_component"),
            chain="marine_compound",
            restrictions=("crw_heat_stress_not_bleaching", "region_sample_not_census", "association_not_shared_footprint"),
            time_limit="Each component keeps its own independent product date within the 14-day window; not simultaneous."),
    _single("leaderboard", "om_forecast_daily_max", "open_meteo", "open_meteo.best_match_forecast_daily",
            "forecast_model", "Best-match daily maximum temperature forecast", "Configured city sample.", "degrees C",
            "Open-Meteo best-match daily forecast: temperature_2m_max, provider-local day, one forecast day.",
            ("src/data/open_meteo.py:fetch_city_forecast", "src/data/open_meteo.py:fetch_all_city_temps"),
            chain="leaderboard", restrictions=("forecast_not_outcome", "region_sample_not_census"),
            time_limit="Forecast valid date in the provider-local day; not a current or measured temperature."),
    _single("leaderboard", "attributable_normals", "theheat_retained", "theheat.city_normals", "official_reference",
            "Attributable city normals", "Configured city sample.", "degrees C",
            "Repository normals with their product and period.", ("src/data/open_meteo.py:load_normals",),
            chain="leaderboard", role="reference"),
)


def validate_legs(legs=LEGS, registry=REGISTRY_CONTRACTS) -> None:
    """Reject unknown identities, invalid parents/keys and unsupported permissions."""
    parents = {row.source_id: row for row in registry}
    if not 1 <= len(legs) <= 256:
        raise ValueError("source_product_size")
    seen: set[str] = set()
    chains: dict[tuple[str, str], list[ProductLeg]] = {}
    for leg in legs:
        if not isinstance(leg, ProductLeg) or not _PRODUCT_ID.fullmatch(leg.product_id) or leg.product_id in seen:
            raise ValueError("source_product_identity")
        seen.add(leg.product_id)
        parent = parents.get(leg.source_id)
        if parent is None or leg.product_id.split(".", 1)[0] != leg.source_id or not _ID.fullmatch(leg.chain):
            raise ValueError("source_product_parent")
        if not leg.health_keys or len(set(leg.health_keys)) != len(leg.health_keys) or \
                not set(leg.health_keys) <= set(parent.health_keys):
            raise ValueError("source_product_health_key")
        if leg.role not in ROLES or leg.status not in STATUSES or leg.data_kind not in DATA_KINDS:
            raise ValueError("source_product_vocabulary")
        if leg.data_kind not in PROVIDER_KINDS.get(leg.provider, frozenset()) or not _UPSTREAM.fullmatch(leg.upstream) \
                or leg.upstream.split(".", 1)[0] != PROVIDER_NAMESPACES[leg.provider]:
            raise ValueError("source_product_kind_provider")
        if (leg.status == "retired") != (leg.role == "retired") or (leg.status == "unresolved") != (leg.role == "unresolved"):
            raise ValueError("source_product_disposition")
        if leg.status in {"retired", "unresolved", "conditional"} and not leg.disposition:
            raise ValueError("source_product_disposition")
        if leg.claim_permissions:
            raise ValueError("source_product_claim_permission")
        restrictions = set(leg.claim_restrictions)
        if not restrictions or len(restrictions) != len(leg.claim_restrictions) or not restrictions <= RESTRICTIONS.keys():
            raise ValueError("source_product_restriction")
        if not _KIND_REQUIRES[leg.data_kind] <= restrictions or not _ROLE_REQUIRES.get(leg.role, set()) <= restrictions:
            raise ValueError("source_product_required_restriction")
        if leg.runtime_leg_label is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", leg.runtime_leg_label):
            raise ValueError("source_product_runtime_label")
        if leg.role in _SERVING_ROLES and leg.role != "alternate_route" and leg.runtime_leg_label is None:
            raise ValueError("source_product_runtime_label")
        if not leg.code_refs or len(leg.code_refs) > 4 or not all(_CODE_REF.fullmatch(ref) for ref in leg.code_refs):
            raise ValueError("source_product_code_ref")
        for value in (leg.product, leg.geographic_limit, leg.time_limit, leg.units_limit, leg.provenance,
                      leg.request_bound, leg.disposition):
            if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value) or "://" in value:
                raise ValueError("source_product_text")
        chains.setdefault((leg.source_id, leg.chain), []).append(leg)
    for (source_id, _chain), members in chains.items():
        active = [leg for leg in members if leg.status in {"wired", "conditional"}]
        primaries = [leg for leg in active if leg.role == "primary"]
        if len(primaries) > 1 or (len(primaries) == 0 and any(leg.role in _SERVING_ROLES | {"corroboration"}
                                                                for leg in active)):
            raise ValueError("source_product_chain_primary")
        if primaries and primaries[0].runtime_leg_label is not None:
            raise ValueError("source_product_chain_primary")
    # One runtime label names one leg per chain. GDACS subtype witnesses are the
    # single exception: one label covers several reused upstream feeds.
    labels = Counter((leg.source_id, leg.chain, leg.runtime_leg_label) for leg in legs
                     if leg.runtime_leg_label is not None and leg.status != "retired")
    for (_source, _chain, label), count in labels.items():
        if count > 1 and label != "subtype_witnesses":
            raise ValueError("source_product_runtime_label")
    covered = {leg.source_id for leg in legs}
    if covered != set(parents):
        raise ValueError("source_product_inventory")
    for row in registry:
        keys = {key for leg in legs if leg.source_id == row.source_id for key in leg.health_keys}
        if keys != set(row.health_keys):
            raise ValueError("source_product_health_key")
    # A scoped check must name products that actually carry its restriction.
    for code, (_meaning, enforcement) in RESTRICTIONS.items():
        if enforcement == ADVISORY:
            continue
        if len({selector for selector, _ref in enforcement}) != len(enforcement):
            raise ValueError("source_product_enforcement_scope")
        for selector, ref in enforcement:
            carriers = [leg for leg in legs if code in leg.claim_restrictions
                        and selector in {leg.product_id, leg.source_id}]
            if not carriers or not _CODE_REF.fullmatch(ref):
                raise ValueError("source_product_enforcement_scope")


def legs_by_id(legs=LEGS) -> dict[str, ProductLeg]:
    return {leg.product_id: leg for leg in legs}


def restriction_enforcement(leg: ProductLeg) -> dict[str, dict[str, str | None]]:
    """Per-product enforcement: a scoped check, advisory text, or explicitly unresolved."""
    result: dict[str, dict[str, str | None]] = {}
    for code in leg.claim_restrictions:
        _meaning, enforcement = RESTRICTIONS[code]
        if enforcement == ADVISORY:
            result[code] = {"basis": "advisory", "reference": _ADVISORY}
            continue
        scoped = dict(enforcement)
        ref = scoped.get(leg.product_id) or scoped.get(leg.source_id)
        result[code] = {"basis": "check", "reference": ref} if ref else {"basis": "unresolved", "reference": None}
    return result


def corroboration_groups(product_ids, legs=LEGS) -> list[list[str]]:
    """Group products that are known not to corroborate one another.

    Products of one adapter, or legs reading the same upstream product through
    different adapters, form one group. Separate groups are not proven
    independent: the group count is only an upper bound on independent sources,
    and product count is never a source count.
    """
    index = legs_by_id(legs)
    ids = sorted(set(product_ids))
    if any(product_id not in index for product_id in ids):
        raise ValueError("source_product_identity")
    parent = {product_id: product_id for product_id in ids}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    by_key: dict[tuple[str, str], str] = {}
    for product_id in ids:
        leg = index[product_id]
        for key in (("source", leg.source_id), ("upstream", leg.upstream)):
            if key in by_key:
                parent[find(product_id)] = find(by_key[key])
            else:
                by_key[key] = product_id
    groups: dict[str, list[str]] = {}
    for product_id in ids:
        groups.setdefault(find(product_id), []).append(product_id)
    return sorted(groups.values())


def max_independent_source_count(product_ids, legs=LEGS) -> int:
    """Upper bound only; independence between the remaining groups is not established."""
    return len(corroboration_groups(product_ids, legs))


def shared_upstream_groups(legs=LEGS) -> list[list[str]]:
    """Products of different adapters that read one upstream product."""
    by_upstream: dict[str, list[ProductLeg]] = {}
    for leg in legs:
        by_upstream.setdefault(leg.upstream, []).append(leg)
    return sorted(sorted(leg.product_id for leg in members) for members in by_upstream.values()
                  if len({leg.source_id for leg in members}) > 1)


_OBSERVED_STATUSES = frozenset({"success", "degraded", "partial_failure", "failed", "skipped"})


def serving_disposition(source_id: str, *, status: str, runtime_leg_label: str | None = None,
                        served_product_ids=None, health_key: str | None = None, legs=LEGS) -> dict[str, Any]:
    """Describe what one observed source-run entry can and cannot show.

    Status alone never identifies a served product: evidence is a runtime leg label
    or explicit served product IDs. The one exception is an unlabelled success
    when a single wired, unlabelled primary exists for the observed health key,
    because runners record every labelled alternate or retained serving as
    degraded. Anything else stays unknown (None). A workflow success, empty
    result, alternate response or static contract never establishes operational
    recovery, and an alternate or retained serving is not primary recovery.
    """
    members = [leg for leg in legs if leg.source_id == source_id and leg.status != "retired"
               and (health_key is None or health_key in leg.health_keys)]
    if not members or status not in _OBSERVED_STATUSES or (runtime_leg_label is not None
                                                             and served_product_ids is not None):
        raise ValueError("source_product_disposition_input")
    served: list[ProductLeg] = []
    reasons: list[str] = []
    evidence = "none"
    if status in {"failed", "skipped"}:
        if runtime_leg_label is not None or served_product_ids is not None:
            raise ValueError("source_product_disposition_input")
        reasons.append(f"observed_{status}")
    elif served_product_ids is not None:
        ids = list(served_product_ids)
        index = {leg.product_id: leg for leg in members}
        if not ids or len(set(ids)) != len(ids) or any(type(item) is not str or item not in index for item in ids):
            raise ValueError("source_product_disposition_input")
        served, evidence = [index[item] for item in sorted(ids)], "served_product_ids"
    elif runtime_leg_label is not None:
        served, evidence = [leg for leg in members if leg.runtime_leg_label == runtime_leg_label], "runtime_leg_label"
        if not served:
            reasons.append("unknown_serving_label")
    else:
        candidates = [leg for leg in members if leg.role in {"primary", "alternate_route"} and leg.runtime_leg_label is None]
        if status == "success" and len(candidates) == 1 and candidates[0].role == "primary" \
                and candidates[0].status == "wired":
            served, evidence = candidates, "sole_wired_unlabelled_primary"
            reasons.append("unlabelled_success_sole_wired_primary")
        else:
            reasons.append("serving_leg_not_evidenced")
            if any(leg.role == "alternate_route" for leg in candidates):
                reasons.append("unlabelled_alternate_routes_exist")
    nothing_served = status in {"failed", "skipped"}
    primary_served: bool | None = False if nothing_served else None
    alternate: bool | None = False if nothing_served else None
    retained: bool | None = None
    if served:
        alternate = any(leg.role in _SERVING_ROLES for leg in served)
        has_primary = any(leg.role == "primary" for leg in served)
        retained = any(leg.role == "cache" for leg in served)
        if alternate:
            reasons.append("alternate_served_primary_not_recovered")
        if has_primary and alternate:
            primary_served = None
            reasons.append("mixed_chain_serving")
        else:
            primary_served = has_primary and not alternate
    kinds = sorted({leg.data_kind for leg in served})
    station_only: bool | None = (bool(served) and kinds == ["observed_station"] and alternate is False) \
        if served or nothing_served else None
    return {
        "source_id": source_id,
        "health_key": health_key,
        "observed_status": status,
        "evidence": evidence,
        "serving_product_ids": sorted(leg.product_id for leg in served),
        "candidate_product_ids": sorted(leg.product_id for leg in members),
        "serving_roles": sorted({leg.role for leg in served}),
        "serving_data_kinds": kinds,
        "primary_leg_served_this_run": primary_served,
        "alternate_served": alternate,
        "retained_not_fresh": retained,
        "observed_station_kind_only": station_only,
        "operational_recovery": "not_established",
        "reasons": reasons,
    }


# Runner wording: _witness.degraded_via and the last-good fallbacks.
_SERVED_VIA = re.compile(r"served via ([A-Za-z][A-Za-z0-9_]{0,63})(?![A-Za-z0-9_])")
_SERVED_LAST_GOOD = "served last-good ("
_AQ_LANES = (("pm25", "air_quality.cams_pm25"), ("dust", "air_quality.cams_dust"))


def _aq_served(details: Any) -> list[str] | None:
    """Enabled CAMS lanes with complete slots, from the runner's own availability summary."""
    try:
        hazards = details["aq_availability"]["hazards"]
        served = []
        for key, product_id in _AQ_LANES:
            lane = hazards[key]
            if type(lane.get("enabled")) is not bool or type(lane.get("complete")) is not int or lane["complete"] < 0:
                return None
            if lane["enabled"] and lane["complete"] > 0:
                served.append(product_id)
    except (KeyError, TypeError, AttributeError):
        return None
    return served or None


def _gdacs_witness_served(details: Any) -> list[str] | None:
    """Resolve the shared witness label from the runner's per-feed diagnostics.

    Missing/contradictory diagnostics establish no serving product. Success with
    zero selected events is still a completed feed, never proof of global recall.
    """
    try:
        diagnostics = details["feed_diagnostics"]
        feeds = diagnostics["legs"]
        if diagnostics.get("source_leg") != "subtype_witnesses" or type(feeds) is not dict \
                or set(feeds) != {"usgs_quakes", "nhc", "jtwc"}:
            return None
        served = []
        selected_total = 0
        for name, product in (("usgs_quakes", "usgs"), ("nhc", "nhc"), ("jtwc", "jtwc")):
            feed = feeds[name]
            if type(feed) is not dict or set(feed) != {"status", "records_received", "records_selected"}:
                return None
            received, selected = feed.get("records_received"), feed.get("records_selected")
            if feed.get("status") == "success":
                if type(received) is not int or type(selected) is not int or not 0 <= selected <= received:
                    return None
                selected_total += selected
                served.append("gdacs.subtype_witness_" + product)
            elif feed.get("status") != "failed" or received is not None or selected is not None:
                return None
        if type(diagnostics.get("selected_alerts")) is not int or diagnostics["selected_alerts"] != selected_total:
            return None
        expected = "witnesses_completed" if len(served) == 3 else "partial_witness_failure"
        if "status" in diagnostics and diagnostics["status"] != expected:
            return None
        if "primary_status" in diagnostics and diagnostics["primary_status"] != "unavailable":
            return None
    except (KeyError, TypeError, AttributeError):
        return None
    return served or None


def serving_disposition_from_run_entry(entry: Any, *, legs=LEGS, registry=REGISTRY_CONTRACTS) -> dict[str, Any]:
    """Read serving evidence from one actual source-run entry, never from status alone."""
    if type(entry) is not dict or type(entry.get("source")) is not str or type(entry.get("status")) is not str:
        raise ValueError("source_product_disposition_input")
    health_key = entry["source"]
    source_id = next((row.source_id for row in registry if health_key in row.health_keys), None)
    if source_id is None:
        raise ValueError("source_product_disposition_input")
    labels = set()
    for field in ("error", "note"):
        text = entry.get(field)
        if isinstance(text, str):
            if text.startswith(_SERVED_LAST_GOOD):
                labels.add("last_good")
            match = _SERVED_VIA.match(text)
            if match:
                labels.add(match.group(1))
    if entry["status"] in {"failed", "skipped"} or len(labels) > 1:
        result = serving_disposition(source_id, status=entry["status"], health_key=health_key, legs=legs)
        if len(labels) > 1:
            result["reasons"].append("conflicting_serving_labels")
        return result
    if labels:
        label = labels.pop()
        if source_id == "gdacs" and label == "subtype_witnesses":
            served = _gdacs_witness_served(entry.get("details"))
            result = serving_disposition(source_id, status=entry["status"], served_product_ids=served,
                                         health_key=health_key, legs=legs)
            if served is None:
                result["reasons"].append("witness_serving_diagnostics_missing_or_inconsistent")
            return result
        return serving_disposition(source_id, status=entry["status"], runtime_leg_label=label,
                                   health_key=health_key, legs=legs)
    served = _aq_served(entry.get("details")) if source_id == "air_quality" else None
    return serving_disposition(source_id, status=entry["status"], served_product_ids=served,
                               health_key=health_key, legs=legs)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _missing_work(legs) -> list[dict[str, Any]]:
    return [{"product_id": leg.product_id, "status": leg.status, "disposition": leg.disposition}
            for leg in legs if leg.status in {"unresolved", "retired"}]


def _unmet_criteria(legs) -> list[dict[str, Any]]:
    """Requirements the rows themselves leave open; derived, never supplied."""
    unmet: list[dict[str, Any]] = [
        {"field": field, "products": "all", "status": "unknown",
         "needs": "Exact current provider documentation or a measured record for that product."}
        for field in UNKNOWN_FIELDS]
    unmet.append({"field": "current_availability", "products": "all", "status": "unverified",
                  "needs": "Observed qualified collection; static contracts cannot show it."})
    unresolved = {leg.product_id: sorted(code for code, item in restriction_enforcement(leg).items()
                                         if item["basis"] == "unresolved") for leg in legs}
    unresolved = {product_id: codes for product_id, codes in unresolved.items() if codes}
    if unresolved:
        unmet.append({"field": "restriction_enforcement", "products": sorted(unresolved),
                      "codes": sorted({code for codes in unresolved.values() for code in codes}),
                      "status": "unresolved",
                      "needs": "A product-specific automated check; advisory text or another product's check is not one."})
    return unmet


def product_contract_document(legs=LEGS, registry=REGISTRY_CONTRACTS) -> dict[str, Any]:
    """Versioned read-only export joined to the v1 registry by exact source/health key."""
    validate_legs(legs, registry)
    adapters = []
    for row in registry:
        members = [leg for leg in legs if leg.source_id == row.source_id]
        adapters.append({
            "source_id": row.source_id,
            "registry_kind": row.kind,
            "health_keys": list(row.health_keys),
            "product_ids": [leg.product_id for leg in members],
            "chains": sorted({leg.chain for leg in members}),
            "unresolved_product_ids": [leg.product_id for leg in members if leg.status == "unresolved"],
            "retired_product_ids": [leg.product_id for leg in members if leg.status == "retired"],
        })
    rows = []
    for leg in legs:
        item = asdict(leg)
        item.update({field: None for field in UNKNOWN_FIELDS})
        item["configured_collection_rule"] = next(r.collection_rule for r in registry if r.source_id == leg.source_id)
        item["claim_permission_granted"] = False
        item["restriction_enforcement"] = restriction_enforcement(leg)
        rows.append(item)
    restrictions = {}
    for code, (meaning, enforcement) in RESTRICTIONS.items():
        advisory = enforcement == ADVISORY
        restrictions[code] = {"meaning": meaning, "basis": "advisory" if advisory else "scoped_checks",
                              "reference": _ADVISORY if advisory else None,
                              "checks": [] if advisory else [{"applies_to": selector, "reference": ref}
                                                             for selector, ref in enforcement]}
    body = {
        "schema": SCHEMA,
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "purpose": PURPOSE,
        "claim_permission_granted": False,
        "current_availability": "unverified",
        "operational_recovery": "not_established",
        "source_independence": "not_established",
        "coverage_denominator": None,
        "unknown_fields": list(UNKNOWN_FIELDS),
        "restrictions": restrictions,
        "adapters": adapters,
        "products": rows,
        "shared_upstream_groups": shared_upstream_groups(legs),
        "missing_work": _missing_work(legs),
        "unmet_criteria": _unmet_criteria(legs),
    }
    body = json.loads(_canonical(body))  # JSON-native: identical once detached and reloaded
    return {**body, "contracts_sha256": hashlib.sha256(_canonical(body).encode()).hexdigest()}


_LEG_FIELDS = tuple(ProductLeg.__dataclass_fields__)
_TUPLE_FIELDS = frozenset({"health_keys", "claim_restrictions", "code_refs", "claim_permissions"})
_ROW_KEYS = frozenset({*_LEG_FIELDS, *UNKNOWN_FIELDS, "configured_collection_rule", "claim_permission_granted",
                       "restriction_enforcement"})
_DOCUMENT_KEYS = frozenset({"schema", "registry_schema_version", "purpose", "claim_permission_granted",
                            "current_availability", "operational_recovery", "source_independence",
                            "coverage_denominator", "unknown_fields", "restrictions", "adapters", "products",
                            "shared_upstream_groups", "missing_work", "unmet_criteria", "contracts_sha256"})


def _decode_leg(row: Any) -> ProductLeg:
    if type(row) is not dict or set(row) != _ROW_KEYS:
        raise ValueError("source_product_export_row")
    values: dict[str, Any] = {}
    for field in _LEG_FIELDS:
        value = row[field]
        if field in _TUPLE_FIELDS:
            if type(value) is not list or len(value) > 32 or any(type(item) is not str for item in value):
                raise ValueError("source_product_export_row")
            value = tuple(value)
        elif field == "runtime_leg_label":
            if value is not None and type(value) is not str:
                raise ValueError("source_product_export_row")
        elif type(value) is not str or len(value) > 300:
            raise ValueError("source_product_export_row")
        values[field] = value
    if values["claim_permissions"] or row["claim_permission_granted"] is not False \
            or any(row[field] is not None for field in UNKNOWN_FIELDS):
        raise ValueError("source_product_export_permission")
    if type(row["restriction_enforcement"]) is not dict or type(row["configured_collection_rule"]) is not str:
        raise ValueError("source_product_export_row")
    return ProductLeg(**values)


def decode_product_contract_document(document: Any) -> dict[str, Any]:
    """Validate a detached export's decoded rows, not just its digest.

    The digest binds bytes, not truth. Rows must decode to the finite supported
    inventory with valid kinds, parents, health keys, restrictions and scoped
    enforcement, and every summary is recomputed from those rows. Unknown
    versions or data are refused (held by the caller), never coerced.
    """
    if type(document) is not dict or document.get("schema") != SCHEMA or set(document) != _DOCUMENT_KEYS \
            or document.get("registry_schema_version") != REGISTRY_SCHEMA_VERSION \
            or type(document["registry_schema_version"]) is not int or document.get("purpose") != PURPOSE \
            or document.get("unknown_fields") != list(UNKNOWN_FIELDS):
        raise ValueError("source_product_export_schema")
    digest = document["contracts_sha256"]
    body = {key: value for key, value in document.items() if key != "contracts_sha256"}
    try:
        canonical = _canonical(body)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("source_product_export_schema") from None
    if type(digest) is not str or hashlib.sha256(canonical.encode()).hexdigest() != digest:
        raise ValueError("source_product_export_digest")
    if document["claim_permission_granted"] is not False or document["operational_recovery"] != "not_established" \
            or document["current_availability"] != "unverified" or document["coverage_denominator"] is not None \
            or document["source_independence"] != "not_established":
        raise ValueError("source_product_export_permission")
    rows = document["products"]
    if type(rows) is not list or len(rows) > 256:
        raise ValueError("source_product_export_row")
    legs = tuple(_decode_leg(row) for row in rows)
    validate_legs(legs, REGISTRY_CONTRACTS)
    if legs != LEGS:
        raise ValueError("source_product_export_inventory")
    expected = product_contract_document(legs)
    if [row["restriction_enforcement"] for row in rows] != [row["restriction_enforcement"] for row in expected["products"]]:
        raise ValueError("source_product_export_enforcement")
    if rows != expected["products"]:
        raise ValueError("source_product_export_row")
    if document["restrictions"] != expected["restrictions"]:
        raise ValueError("source_product_export_restrictions")
    if document["adapters"] != expected["adapters"]:
        raise ValueError("source_product_export_adapters")
    for key in ("shared_upstream_groups", "missing_work", "unmet_criteria"):
        if document[key] != expected[key]:
            raise ValueError("source_product_export_summary")
    return {
        "contracts_sha256": digest,
        "product_ids": sorted(leg.product_id for leg in legs),
        "adapters": len(expected["adapters"]),
        "missing_work": expected["missing_work"],
        "unmet_criteria": expected["unmet_criteria"],
    }


def verify_product_contract_document(document: Any) -> str:
    """Return the export identity after full decoded validation."""
    return decode_product_contract_document(document)["contracts_sha256"]
