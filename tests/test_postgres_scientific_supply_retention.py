"""Real qualified GHCN -> existing PG -> actual prepass; invented archives only."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid

import pytest

from src.data import ghcn, open_meteo
from src.editorial import records_cluster
from src.orchestrator import caps, suppression
from src.orchestrator.sources import open_meteo as source
from src.state import DEFAULT_STATE
from src.storage import postgres_projection as p
from src.storage.scientific_supply import (COUNTERS, NAMESPACE, ScientificSupplySession,
                                           SupplyError, detached_json)
from tests import test_ghcn_scientific_supply as supply_fixtures
from tests.test_ghcn_time_integrity import DAY, NOW
from tests import test_postgres_projection as pg_fixtures

supply = supply_fixtures.supply
supply_inputs = supply_fixtures.supply_inputs
cluster = pg_fixtures.cluster
database = pg_fixtures.database
repository = pg_fixtures.repository

BASE = "1bb94c136df7ae143fccc59c27d4c925170f1aba"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in tuple(os.environ):
        if (key.startswith(("PG", "AWS_", "TWITTER_", "BLUESKY_", "X_API_"))
            or re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIALS?|PRIVATE_KEY|GIST_ID|DATABASE_URL)$", key)
            or key in {"NODE_ENV", "THEHEAT_ENVIRONMENT"}):
            monkeypatch.delenv(key)
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "1")
    with suppression._suppression_context({}, source="test-sentinel"):
        yield


@pytest.fixture
def capture(repository):
    return ScientificSupplySession(repository[1], str(uuid.uuid4()), "capture", NOW, BASE)


def metrics_for(supply):
    return {**supply[2], "status": "success", "threshold_verification": "success"}


def replay(capture):
    return replace(capture, mode="replay", captured_at=None, producer_revision=None)


def forbid(*args, **kwargs):
    raise AssertionError("unwanted acquisition or operational mutation")


def trap_replay(monkeypatch):
    for obj, names in [
        (ghcn, ["check_extreme_signals_for_stations", "_fetch_recent_obs", "_fetch_station_archive"]),
        (source, ["_record_source_run", "_enqueue_story_candidate", "_run_world_cached_half", "_check_city_extreme_signals"]),
        (source.state, ["increment_data_source_failure", "reset_data_source_failure", "prune_stale_record_streaks",
                        "update_record_streak", "record_coverage_observation", "record_synthesis_component",
                        "record_heat_records_cluster", "record_candidate_observation", "log_error"]),
        (source.world_cache, ["write_cache"]),
    ]:
        for name in names:
            monkeypatch.setattr(obj, name, forbid)


def test_real_source_capture_then_caps_read_same_all_six(capture, supply_inputs, monkeypatch):
    original_check = ghcn.check_extreme_signals_for_stations
    qualified = []
    calls = []
    def actual_source(**kwargs):
        calls.append(1)
        result = original_check(**supply_inputs, **kwargs)
        qualified.extend(deepcopy(result[0]))
        return result
    observed = []
    real_cluster = records_cluster.cluster_record_stations
    def cluster_probe(rows):
        observed.append(deepcopy(rows))
        return real_cluster(rows)
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", actual_source)
    monkeypatch.setattr(records_cluster, "cluster_record_stations", cluster_probe)
    monkeypatch.setattr(source, "_should_draft", lambda *a, **k: True)
    monkeypatch.setattr(source, "_enqueue_story_candidate", lambda *a, **k: False)
    state = deepcopy(DEFAULT_STATE)
    source.run_extreme_signals(state, None, [], {}, {}, ghcn_supply=capture)
    receipt, bundles, _, envelope = capture.read()
    assert calls == [1]
    assert bundles == qualified
    assert {b.station_id for b in bundles} == {f"USW{i:08d}" for i in range(6)}
    assert len(observed[0]) == 6
    assert envelope["source_outcome"]["counters"]["baseline_cutoff_gaps"] >= 1
    assert state["heat_records_cluster_fired"] == {}
    for bundle in bundles:
        assert bundle.evidence["valid_start"] is None
        assert bundle.evidence["reporting_interval_known"] is False
        assert bundle.evidence["publication_time_qc_known"] is False
    trap_replay(monkeypatch)
    signatures = []
    for cap in (0, 1, 2, 6):
        monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", cap)
        result = source.replay_retained_ghcn_supply(replay(capture), deepcopy(DEFAULT_STATE))
        assert result["status"] == "available"
        assert len(result["retained_bundle_keys"]) == len(result["routed_bundle_keys"]) == 6
        assert len(result["individual_bundle_keys"]) == cap
        assert len(result["cluster_candidates"]) == 1
        cluster = result["cluster_candidates"][0]
        assert len(cluster["members"]) == 6 and cluster["aggregate_hold_codes"]
        signatures.append(cluster["event_id"])
        assert result["source_acquisition"] == "not_attempted" and not result["publication_eligible"]
        assert capture.read()[0] == receipt
        assert capture.read()[3] == envelope
    assert len(set(signatures)) == 1


def test_read_back_not_live_list_is_runner_input(capture, supply, monkeypatch):
    bundles, countries, metrics = supply
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", lambda **kw: (bundles, countries))
    actual_read = p.PostgresProjectionRepository.read
    def read(repo, *args):
        result = actual_read(repo, *args)
        bundles.clear()
        return result
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", read)
    rows = []
    actual_prepass = source._scientific_prepass
    def prepass(state, restored):
        rows.extend(restored)
        return actual_prepass(state, restored)
    monkeypatch.setattr(source, "_scientific_prepass", prepass)
    monkeypatch.setattr(source, "_enqueue_story_candidate", lambda *a, **k: False)
    source.run_extreme_signals(deepcopy(DEFAULT_STATE), None, [], {}, {}, ghcn_supply=capture)
    assert len(rows) == 6 and bundles == []


@pytest.mark.parametrize("status,error,empty", [("failed", "ghcn_fetch_failed", True), ("degraded", None, False), ("success", None, True)])
def test_original_failure_degradation_and_empty_not_fresh_success(capture, supply, monkeypatch, status, error, empty):
    bundles = [] if empty else supply[0]
    metrics = {"status": status, "error": error, "threshold_verification": "success",
               "diff_dates_missing": 1, "diff_missing_dates": [DAY.isoformat()]}
    capture.capture(bundles, [], metrics)
    trap_replay(monkeypatch)
    monkeypatch.setattr(source, "_classify_ghcn_source_status", forbid)
    result = source.replay_retained_ghcn_supply(replay(capture), {})
    assert result["status"] == "available" and result["source_acquisition"] == "not_attempted"
    assert result["original_source_outcome"]["status"] == status
    assert result["original_source_outcome"]["supply_empty"] is empty
    assert result["original_source_outcome"]["counters"]["stations_active"] is None
    assert result["original_source_outcome"]["diff_missing_dates"] == [DAY.isoformat()]


def test_preview_preserves_every_operational_field_and_context(capture, supply, monkeypatch):
    capture.capture(*supply[:2], metrics_for(supply))
    snapshot = deepcopy(DEFAULT_STATE)
    snapshot.update(data_source_failures={"ghcn": 4}, source_health={"ghcn": {"last_success": "old", "incident": "open"}},
                    record_streaks={"USW00000000": {"days": 4, "last_date": "1900-01-01"}},
                    heat_records_cluster_fired={"old": "1900-01-01"}, source_incidents={"open": True},
                    world_cache={"sentinel": 1}, coverage_log=[{"sentinel": 2}], candidates_log=[{"sentinel": 3}],
                    synthesis_components={"sentinel": 4}, drafts=[{"id": "synthetic", "status": "approved"}],
                    publication_ledger=[{"sentinel": 5}], approval={"sentinel": 6})
    before = deepcopy(snapshot)
    ctx = suppression._current_suppression_ctx()
    ctx_before = deepcopy(ctx)
    trap_replay(monkeypatch)
    result = source.replay_retained_ghcn_supply(replay(capture), snapshot)
    assert result["status"] == "available"
    assert snapshot == before and suppression._current_suppression_ctx() is ctx
    assert ctx == ctx_before
    # Rejection during the shared helper must restore context too.
    monkeypatch.setattr(source, "_scientific_prepass", lambda *a: (_ for _ in ()).throw(ValueError("synthetic")))
    assert source.replay_retained_ghcn_supply(replay(capture), snapshot)["status"] == "unavailable"
    assert snapshot == before and suppression._current_suppression_ctx() is ctx and ctx == ctx_before


def test_combined_capture_precedes_partition_and_replay_routes_without_world(capture, supply, monkeypatch):
    foreign = deepcopy(supply[0][0])
    foreign.station_id, foreign.country = "CAW00000000", "Canada"
    for event in [foreign.all_time_high, foreign.monthly_high, foreign.calendar_date_high]:
        if event:
            event.country = "Canada"
            event.evidence["station_id"] = foreign.station_id
    foreign.evidence["station_id"] = foreign.station_id
    bundles = [*supply[0], foreign]
    def fetched(**kw):
        kw["metrics_out"].update(supply[2])
        return bundles, supply[1]
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", fetched)
    monkeypatch.setattr(source, "_run_world_cached_half", lambda cities, metrics, **kw: ([], []))
    monkeypatch.setattr(source, "_enqueue_story_candidate", lambda *a, **kw: False)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    source.run_extreme_signals(deepcopy(DEFAULT_STATE), None, [], {}, {}, ghcn_supply=capture)
    assert len(capture.read()[1]) == 7
    trap_replay(monkeypatch)
    result = source.replay_retained_ghcn_supply(replay(capture), {}, routing_mode="both")
    assert len(result["retained_bundle_keys"]) == 7 and len(result["routed_bundle_keys"]) == 6
    assert result["world_supply"] == "not_replayed"


@pytest.mark.parametrize("operation", ["source", "top"])
def test_replay_rejected_by_live_runner_before_any_mutation(capture, monkeypatch, operation):
    top = importlib.import_module("src.orchestrator.run_alerts")
    monkeypatch.setattr(top, "_activate_suppression_ctx", forbid)
    state, current = {"_triage_queue": ["sentinel"]}, {"id": "same"}
    before = deepcopy((state, current))
    with pytest.raises(SupplyError, match="invalid_supply_mode"):
        if operation == "source":
            source.run_extreme_signals(state, current, [], {}, {}, ghcn_supply=replay(capture))
        else:
            top.run_alerts(state, current, ghcn_supply=replay(capture))
    assert (state, current) == before


@pytest.mark.parametrize("concurrent", [False, True])
def test_actual_top_level_both_calls_forward_capture(capture, monkeypatch, concurrent):
    top = importlib.import_module("src.orchestrator.run_alerts")
    monkeypatch.setattr(top, "concurrent_sources_enabled", lambda: concurrent)
    monkeypatch.setattr(top.open_meteo, "load_cities", lambda: [])
    class StopAfterJoin(Exception):
        pass
    seen = []
    def boundary(*args, **kwargs):
        seen.append(kwargs["ghcn_supply"])
        raise StopAfterJoin
    monkeypatch.setattr(top, "run_extreme_signals", boundary)
    if concurrent:
        monkeypatch.setattr(top, "run_stage1_then_synthesis", lambda *a, **kw: kw["serial_runners"][0].run())
    with pytest.raises(StopAfterJoin):
        top.run_alerts(deepcopy(DEFAULT_STATE), None, ghcn_supply=capture)
    assert seen == [capture]


@pytest.mark.parametrize("name,value", [("NODE_ENV", "production"), ("THEHEAT_ENVIRONMENT", "production"),
 ("PGHOST", ""), ("GITHUB_TOKEN", "invented"), ("THEHEAT_SECRET", "invented"), ("DB_PASSWORD", "invented"),
 ("GOOGLE_API_KEY", "invented"), ("SERVICE_CREDENTIAL", "invented"), ("SERVICE_CREDENTIALS", "invented"),
 ("SSH_PRIVATE_KEY", "invented"), ("GIST_ID", "invented"), ("DATABASE_URL", "invented"),
 ("AWS_REGION", "invented"), ("TWITTER_ID", "invented"), ("BLUESKY_USER", "invented"), ("X_API_ID", "invented")])
def test_ambient_guard_rechecked_before_db_source_state(capture, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", forbid)
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", forbid)
    with pytest.raises(SupplyError, match="unsafe_supply_environment"):
        source.replay_retained_ghcn_supply(replay(capture), {})
    with pytest.raises(SupplyError, match="unsafe_supply_environment"):
        source.run_extreme_signals({}, None, [], {}, {}, ghcn_supply=capture)


@pytest.mark.parametrize("environment", ["production", "staging", None])
def test_mutated_repository_environment_refused(capture, monkeypatch, environment):
    monkeypatch.setattr(capture.repository, "environment", environment)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", forbid)
    with pytest.raises(SupplyError, match="production_supply_refused"):
        source.replay_retained_ghcn_supply(replay(capture), {})


def test_replay_refuses_background_threads_and_reentrancy(capture, monkeypatch):
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", forbid)
    ready, stop = threading.Event(), threading.Event()
    thread = threading.Thread(target=lambda: (ready.set(), stop.wait(5)))
    thread.start()
    ready.wait(5)
    try:
        with pytest.raises(SupplyError, match="isolated_replay_process_required"):
            source.replay_retained_ghcn_supply(replay(capture), {})
    finally:
        stop.set()
        thread.join()
    with source._isolated_replay(replay(capture)):
        with pytest.raises(SupplyError, match="replay_already_active"):
            source.replay_retained_ghcn_supply(replay(capture), {})


def test_exact_retry_conflict_new_revision_and_commit_uncertainty(capture, supply, monkeypatch):
    first = capture.capture(*supply[:2], metrics_for(supply))
    assert capture.capture(*supply[:2], metrics_for(supply)) == first
    changed = deepcopy(supply[0])
    changed[0].evidence["later_source_revision"] = "invented"
    with pytest.raises(SupplyError):
        capture.capture(changed, supply[1], metrics_for(supply))
    assert capture.read() == first
    newer = replace(capture, supply_run_id=str(uuid.uuid4()))
    real_record, real_read = p.PostgresProjectionRepository.record, p.PostgresProjectionRepository.read
    calls = []
    def lost_ack(repo, *args):
        real_record(repo, *args)
        calls.append("write")
        raise p.ProjectionError("write_outcome_unknown")
    def read(repo, *args):
        calls.append("read")
        return real_read(repo, *args)
    monkeypatch.setattr(p.PostgresProjectionRepository, "record", lost_ack)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", read)
    newer.capture(changed, supply[1], metrics_for(supply))
    assert calls == ["write", "read"]
    assert capture.read() == first


def test_unknown_before_commit_no_retry_or_partial_supply(capture, supply, monkeypatch):
    calls = []
    real_read = p.PostgresProjectionRepository.read
    def failed(repo, *args):
        calls.append("write")
        raise p.ProjectionError("write_outcome_unknown")
    def read(repo, *args):
        calls.append("read")
        return real_read(repo, *args)
    monkeypatch.setattr(p.PostgresProjectionRepository, "record", failed)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", read)
    with pytest.raises(SupplyError, match="supply_write_outcome_unknown"):
        capture.capture(*supply[:2], metrics_for(supply))
    assert calls == ["write", "read"]
    with pytest.raises(p.ProjectionError, match="projection_not_found"):
        real_read(capture.repository, NAMESPACE, capture.snapshot_id)


def test_capture_failure_withholds_actual_lane(capture, supply, monkeypatch):
    calls = []
    def fetch(**kw):
        calls.append(1)
        kw["metrics_out"].update(supply[2])
        return supply[:2]
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", fetch)
    monkeypatch.setattr(p.PostgresProjectionRepository, "record", lambda *a: (_ for _ in ()).throw(p.ProjectionError("unavailable")))
    metrics = {}
    assert source._verified_ghcn_signals({}, metrics, ghcn_supply=capture) == ([], [])
    assert calls == [1] and metrics["status"] == "failed" and metrics["supply_retention"] == "unavailable"


def test_unconfigured_source_never_touches_pg(supply, monkeypatch):
    monkeypatch.setattr(p.PostgresProjectionRepository, "record", forbid)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", forbid)
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", lambda **kw: supply[:2])
    assert source._verified_ghcn_signals({}, {}) == supply[:2]


@pytest.mark.parametrize("corrupt", ["schema", "field", "type", "date", "counter", "identity", "duplicate", "nonfinite", "oversize"])
def test_invalid_envelope_withheld_not_coerced(capture, supply, monkeypatch, corrupt):
    receipt, _, _, envelope = capture.capture(*supply[:2], metrics_for(supply))
    if corrupt == "schema":
        envelope["schema_version"] = 2
    if corrupt == "field":
        envelope["bundles"][0].pop("country")
    if corrupt == "type":
        envelope["bundles"][0]["all_time_high"]["type"] = "RecordEvent"
    if corrupt == "date":
        envelope["bundles"][0]["signal_date"] += "T00:00:00Z"
    if corrupt == "counter":
        envelope["source_outcome"]["counters"]["stations_active"] = False
    if corrupt == "identity":
        envelope["supply_run_id"] = str(uuid.uuid4())
    if corrupt == "duplicate":
        envelope["bundles"].append(deepcopy(envelope["bundles"][0]))
    if corrupt == "nonfinite":
        envelope["bundles"][0]["today_max_c"] = float("nan")
    if corrupt == "oversize":
        envelope["bundles"][0]["evidence"]["large"] = "x" * (p.MAX_BYTES + 1)
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", lambda *a: (receipt, envelope))
    assert source.replay_retained_ghcn_supply(replay(capture), {})["status"] == "unavailable"


def test_all_typed_signals_and_numeric_null_evidence_roundtrip(capture, supply):
    bundle = deepcopy(supply[0][0])
    day = DAY
    bundle.calendar_date_low = open_meteo.RecordEvent("Fixture", "United States", -30.0, -29.0, 2000, "low", day, "low")
    bundle.all_time_low = open_meteo.AllTimeRecord("Fixture", "United States", "low", -30.0, -29.0, 2000, 30, "all-low", day)
    bundle.monthly_low = open_meteo.MonthlyRecord("Fixture", "United States", "low", 6, -30.0, -29.0, 2000, 30, "month-low", day)
    bundle.anomaly_hot = open_meteo.AnomalyEvent("Fixture", "United States", 40.0, 20.0, 20.0, 30, "anom-hot", day)
    bundle.anomaly_cold = open_meteo.AnomalyEvent("Fixture", "United States", -20.0, 20.0, -40.0, 30, "anom-cold", day)
    bundle.absolute_extreme = open_meteo.AbsoluteExtremeEvent("Fixture", "United States", 40.0, "test", 39.0, "hot", 40.0, -111.0, "abs", day, data_source="ghcn")
    bundle.wet_bulb_extreme = open_meteo.WetBulbEvent("Fixture", "United States", 35.0, 3, "tier_3", 35.0, "wet", day)
    bundle.evidence["unknown_extension"] = [1, 1.0, None, False, -0.0]
    country = open_meteo.CountryRecord("United States", "high", 40.0, "Fixture", 39.0, 2000, "Other", 30, 6, "country", day)
    _, restored, countries, _ = capture.capture([bundle], [country], metrics_for(supply))
    assert restored == [bundle] and countries == [country]
    assert type(restored[0].evidence["unknown_extension"][0]) is int
    assert type(restored[0].evidence["unknown_extension"][1]) is float
    assert type(restored[0].signal_date) is date


def _fresh_process(repo, run_id):
    code = '''import json,sys
from src.storage.postgres_projection import PostgresProjectionRepository
from src.storage.scientific_supply import ScientificSupplySession
from src.orchestrator.sources.open_meteo import replay_retained_ghcn_supply
from src.state import DEFAULT_STATE
from src.data import ghcn
from src.orchestrator.sources import open_meteo as source
import requests
def forbidden(*args, **kwargs):
    raise AssertionError('replay attempted acquisition or operational mutation')
requests.sessions.Session.request=forbidden
for name in ('check_extreme_signals_for_stations','_fetch_recent_obs','_fetch_station_archive'):
    setattr(ghcn,name,forbidden)
for name in ('_record_source_run','_enqueue_story_candidate','_run_world_cached_half'):
    setattr(source,name,forbidden)
for name in ('increment_data_source_failure','reset_data_source_failure','prune_stale_record_streaks','update_record_streak','record_heat_records_cluster'):
    setattr(source.state,name,forbidden)
args=json.loads(sys.argv[1])
repo=PostgresProjectionRepository(**args['repository'])
print(json.dumps(replay_retained_ghcn_supply(ScientificSupplySession(repo,args['run_id'],'replay'),DEFAULT_STATE)))
'''
    args = {"repository": {"socket_directory": repo.socket_directory, "port": repo.port, "database": repo.database,
                           "user": repo.user, "environment": repo.environment}, "run_id": run_id}
    completed = subprocess.run([sys.executable, "-c", code, json.dumps(args)], text=True, capture_output=True,
                               check=True, timeout=30, env=dict(os.environ))
    return json.loads(completed.stdout.splitlines()[-1])


def test_fresh_process_and_dump_restore_recover_exact_real_prepass(capture, supply, cluster, repository):
    import psycopg
    receipt, _, _, _ = capture.capture(*supply[:2], metrics_for(supply))
    # New interpreter receives only repository coordinates and stable run identity.
    result = _fresh_process(capture.repository, capture.supply_run_id)
    assert result["status"] == "available" and result["receipt_sha256"] == receipt.canonical_sha256
    assert len(result["retained_bundle_keys"]) == 6
    assert len(result["cluster_candidates"]) == 1 and len(result["cluster_candidates"][0]["members"]) == 6
    args, command, root = cluster
    dump = root / "supply.dump"
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    command("pg_dump", *common, "-Fc", "-f", dump, capture.repository.database)
    name = "supply_restore_" + uuid.uuid4().hex
    with psycopg.connect(**args) as connection:
        connection.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        command("pg_restore", *common, "--single-transaction", "-d", name, dump)
        restored = p.PostgresProjectionRepository(socket_directory=args["host"], port=args["port"], database=name, user=capture.repository.user)
        second = _fresh_process(restored, capture.supply_run_id)
        assert second == result
    finally:
        with psycopg.connect(**args) as connection:
            connection.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_policy_binds_codec_guard_and_runner():
    from src.editorial.policy import source_manifest
    files = source_manifest()["files"]
    assert {"src/storage/scientific_supply.py", "src/commands/preview_ingress.py", "src/orchestrator/sources/open_meteo.py"} <= files.keys()
    assert len(COUNTERS) == 20
    assert detached_json({"value": 1.0}) == {"value": 1.0}


@pytest.mark.parametrize("corruption", [
    "missing_day", "different_day", "nan", "coordinates", "missing_evidence", "baseline_shape",
    "baseline_unverified", "station_mismatch", "qc_rejected", "value_mismatch", "source_mismatch",
    "cutoff_gap", "non_record", "missing_qflag", "comparator_value", "comparator_year", "comparator_date",
])
def test_existing_scientific_rejections_survive_retention(capture, supply, monkeypatch, corruption):
    bundles = deepcopy(supply[0])
    bad = bundles[0]
    event = bad.all_time_high
    if corruption == "missing_day":
        bad.signal_date = None
    elif corruption == "different_day":
        event.signal_date = date(2020, 1, 1)
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
    if corruption == "nan":
        with pytest.raises(SupplyError, match="invalid_supply_json"):
            capture.capture(bundles, supply[1], metrics_for(supply))
        return
    _, restored, _, _ = capture.capture(bundles, supply[1], metrics_for(supply))
    assert source._records_cluster_member(restored[0], DAY.isoformat()) is None
    trap_replay(monkeypatch)
    result = source.replay_retained_ghcn_supply(replay(capture), {})
    assert result["status"] == "available" and result["cluster_candidates"] == []


@pytest.mark.parametrize("snapshot", [{"_triage_queue": []}, {"_funnel_sink": {}}, {"callback": forbid}])
def test_replay_transient_or_callback_input_withheld(capture, monkeypatch, snapshot):
    monkeypatch.setattr(p.PostgresProjectionRepository, "read", forbid)
    assert source.replay_retained_ghcn_supply(replay(capture), snapshot)["status"] == "unavailable"


def test_missing_snapshot_does_not_select_other_run(capture, supply, monkeypatch):
    capture.capture(*supply[:2], metrics_for(supply))
    other = replace(replay(capture), supply_run_id=str(uuid.uuid4()))
    trap_replay(monkeypatch)
    result = source.replay_retained_ghcn_supply(other, {})
    assert result["status"] == "unavailable" and "retained_bundle_keys" not in result


def test_failed_threshold_acquisition_is_retained_as_failed_empty(capture, monkeypatch):
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "failure")
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", forbid)
    metrics = {}
    assert source._verified_ghcn_signals({}, metrics, ghcn_supply=capture) == ([], [])
    assert metrics["status"] == "failed" and metrics["supply_retention"] == "retained"
    outcome = capture.read()[3]["source_outcome"]
    assert outcome["status"] == "failed" and outcome["threshold_verification"] == "failure" and outcome["supply_empty"]


def test_runtime_role_cannot_alter_supply_and_failed_transaction_keeps_no_rows(capture, supply, repository, monkeypatch):
    import psycopg
    capture.capture(*supply[:2], metrics_for(supply))
    _, _, params = repository
    runtime = {**params, "user": capture.repository.user}
    with psycopg.connect(**runtime) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM theheat_projection.versions")
    before = capture.read()
    real_record = p.PostgresProjectionRepository._record
    def fail_inside(connection, *args):
        real_record(connection, *args)
        raise ValueError("synthetic rollback")
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", staticmethod(fail_inside))
    other = replace(capture, supply_run_id=str(uuid.uuid4()))
    with pytest.raises(ValueError, match="synthetic rollback"):
        other.capture(*supply[:2], metrics_for(supply))
    with pytest.raises(SupplyError, match="supply_storage_unavailable"):
        other.read()
    assert capture.read() == before
