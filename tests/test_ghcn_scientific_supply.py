"""P09a: engineered source archives, real qualification/clustering, no providers.

The six nearby US stations and archive values below are synthetic. They prove
input retention and eligibility boundaries, not a real regional event or the
publication readiness of the legacy aggregate contract.
"""

from copy import deepcopy
from datetime import date

import pytest

from src.data import ghcn
from src.data.ghcn_db import open_db, upsert_thresholds
from src.data.ghcn_format import DailyObs, compute_thresholds
from src.data.open_meteo import ExtremeSignalBundle
from src.data.temperature_evidence import temperature_aggregate_failures
from src.editorial import records_cluster
from src.orchestrator import caps
from src.orchestrator.sources import open_meteo as source
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from tests.test_ghcn_time_integrity import DAY, NOW, baseline_rows, dly


@pytest.fixture
def supply(tmp_path):
    stations, observations, payloads = [], {}, {}
    history = baseline_rows()
    path = tmp_path / "stations.sqlite"
    with open_db(path) as conn:
        for index in range(9):
            sid = f"USW{index:08d}"
            stations.append({
                "station_id": sid, "name": f"FIXTURE STATION {index}",
                "country_code": "US", "country_name": "United States",
                "state": "UT", "lat": 40 + index * 0.05, "lon": -111.0,
            })
            upsert_thresholds(conn, compute_thresholds([
                DailyObs(sid, date(2020, 6, 25), "TMAX", 31.9),
            ]))
            value = float("nan") if index == 8 else 39.9
            observations[(sid, DAY)] = [DailyObs(sid, DAY, "TMAX", value)]
            rows = history if index != 7 else [history[0], history[-1]]
            # Station6 has a current QC rejection; station7 has omitted years;
            # station8's diff reading is non-finite. None can supply a record.
            payloads[sid] = dly(rows + [(DAY, "TMAX", 399, "S" if index == 6 else "", "T")], sid)
    metrics = {}
    bundles, countries = ghcn.check_extreme_signals_for_stations(
        stations=stations, db_path=path, _fetch_obs_fn=lambda _: observations,
        _fetch_archive_fn=payloads.__getitem__, _now_fn=lambda: NOW, metrics_out=metrics,
    )
    return bundles, countries, metrics


def test_source_retains_all_six_qualified_stations_and_excludes_bad_inputs(supply):
    bundles, _, metrics = supply
    assert {bundle.station_id for bundle in bundles} == {f"USW{index:08d}" for index in range(6)}
    assert len(bundles) == metrics["raw_signals"] == metrics["scientific_signal_bundles"] == 6
    assert metrics["bundles_after_dedup"] == 6  # legacy telemetry alias
    assert metrics["baseline_cutoff_gaps"] >= 1
    members = [source._records_cluster_member(bundle, DAY.isoformat()) for bundle in bundles]
    assert all(member is not None for member in members)
    clusters = records_cluster.cluster_record_stations(members)
    assert len(clusters) == 1 and len(clusters[0]) == 6
    assert records_cluster.is_significant_cluster(records_cluster.cluster_tier_counts(clusters[0]))
    assert all(member["evidence"]["baseline"]["comparison_scope"] == "available_source_accepted_station_samples" for member in clusters[0])


@pytest.mark.parametrize("individual_cap", [0, 1, 2, 6])
def test_real_prepass_sees_six_stations_before_changed_individual_caps(monkeypatch, supply, individual_cap):
    bundles, countries, metrics = supply
    original = deepcopy(bundles)
    detected, submitted = [], []
    real_cluster = records_cluster.cluster_record_stations

    def inspect_cluster(rows):
        detected.append(deepcopy(rows))
        return real_cluster(rows)

    def source_result(**kwargs):
        kwargs["metrics_out"].update(metrics)
        return deepcopy(bundles), deepcopy(countries)

    def inspect_candidate(state, **kwargs):
        submitted.append(kwargs)
        # No writer call or candidate approval. P06 still withholds aggregates.
        if kwargs["legacy_type"] == "heat_records_cluster":
            assert temperature_aggregate_failures(kwargs["bundle"])
            assert not audit_story_bundle(kwargs["bundle"]).prompt_ready
        return False

    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", source_result)
    monkeypatch.setattr(records_cluster, "cluster_record_stations", inspect_cluster)
    monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", individual_cap)
    monkeypatch.setattr(source, "_should_draft", lambda *args, **kwargs: True)
    monkeypatch.setattr(source, "_enqueue_story_candidate", inspect_candidate)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "1")
    state = deepcopy(DEFAULT_STATE)
    source.run_extreme_signals(state, None, [], {}, {})
    assert len(detected) == 1 and len(detected[0]) == 6
    assert len([row for row in submitted if row["legacy_type"] == "heat_records_cluster"]) == 1
    assert len([row for row in submitted if row["legacy_type"] == "all_time_high"]) == individual_cap
    assert bundles == original
    assert state["heat_records_cluster_fired"] == {}


@pytest.mark.parametrize("corruption", [
    "missing_day", "different_day", "nan", "coordinates", "missing_evidence",
    "baseline_shape", "baseline_unverified", "station_mismatch", "qc_rejected",
    "value_mismatch", "source_mismatch", "cutoff_gap", "non_record",
    "missing_qflag", "comparator_value", "comparator_year", "comparator_date",
])
def test_malformed_or_unqualified_member_never_enters_cluster_count(supply, corruption):
    bundles, _, _ = supply
    bad = deepcopy(bundles[0])
    event = bad.all_time_high
    if corruption == "missing_day":
        bad.signal_date = None
    elif corruption == "different_day":
        event.signal_date = date(2026, 6, 24)
    elif corruption == "nan":
        event.new_temp_c = float("nan")
    elif corruption == "coordinates":
        event.lat = 91
    elif corruption == "missing_evidence":
        event.evidence = {}
    elif corruption == "baseline_shape":
        event.evidence["baseline"] = []
    elif corruption == "baseline_unverified":
        event.evidence["baseline"]["reconciled"] = False
    elif corruption == "station_mismatch":
        event.evidence["station_id"] = "USW99999999"
    elif corruption == "qc_rejected":
        event.evidence["variables"]["TMAX"]["qflag"] = "S"
    elif corruption == "value_mismatch":
        event.new_temp_c += 1
    elif corruption == "source_mismatch":
        event.evidence["variables"]["TMAX"]["source_payload_sha256"] = "another-source"
    elif corruption == "cutoff_gap":
        event.evidence["baseline"]["variables"]["temperature_2m_max"]["verified_source_cutoff"] = None
    elif corruption == "non_record":
        event.new_temp_c = event.old_record_c
    elif corruption == "missing_qflag":
        event.evidence["variables"]["TMAX"].pop("qflag")
    elif corruption == "comparator_value":
        event.old_record_c -= 10
    elif corruption == "comparator_year":
        event.old_record_year -= 1
    elif corruption == "comparator_date":
        event.evidence["baseline"]["variables"]["temperature_2m_max"]["record_dates"]["all_time"] = DAY.isoformat()
    assert source._records_cluster_member(bad, DAY.isoformat()) is None
    rows = [source._records_cluster_member(bundle, DAY.isoformat()) for bundle in [bad, *bundles[1:]]]
    assert records_cluster.cluster_record_stations([row for row in rows if row is not None]) == []


@pytest.mark.parametrize("tier", ["monthly", "daily"])
@pytest.mark.parametrize("corruption", [None, "short_history", "wrong_value", "wrong_year", "wrong_period"])
def test_period_record_requires_its_own_source_comparator_and_sample_years(supply, tier, corruption):
    bundles, _, _ = supply
    packet = deepcopy(bundles[0])
    packet.all_time_high = None
    if tier == "daily":
        packet.monthly_high = None
    event = packet.monthly_high if tier == "monthly" else packet.calendar_date_high
    assert event is not None
    period = "monthly" if tier == "monthly" else "calendar"
    period_key = DAY.strftime("%m" if tier == "monthly" else "%m-%d")
    scope = event.evidence["baseline"]["variables"]["temperature_2m_max"]
    if corruption == "short_history":
        scope[f"{period}_years"][period_key] = 1
    elif corruption == "wrong_value":
        event.old_record_c -= 10
    elif corruption == "wrong_year":
        event.old_record_year -= 1
    elif corruption == "wrong_period":
        if tier == "monthly":
            event.month = 1
        else:
            scope["record_dates"][period].pop(period_key)
    member = source._records_cluster_member(packet, DAY.isoformat())
    assert (member is not None) == (corruption is None)


def test_individual_station_cap_does_not_truncate_forecast_city_candidates(supply):
    bundles, _, _ = supply
    forecasts = [ExtremeSignalBundle(city=f"World city {i}", country="France") for i in range(6)]
    selected = caps.select_individual_station_bundles([*bundles, *forecasts], max_per_country=1)
    assert len([bundle for bundle in selected if bundle.station_id]) == 1
    assert all(bundle in selected for bundle in forecasts)
