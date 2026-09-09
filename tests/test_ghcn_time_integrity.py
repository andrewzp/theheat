"""Offline source-byte regressions for GHCN chronology, QC and claim retention.

The Beaver Dams dates/values/QFLAG mirror the audited source case. Surrounding
historical samples are engineered; no claim is made about historical QC timing.
"""
from copy import deepcopy
from datetime import date, timedelta
import gzip
import io
import tarfile

import pytest

from src.data import ghcn
from src.data.ghcn_db import open_db, upsert_thresholds, load_thresholds
from src.data.ghcn_format import DailyObs, DiffRecord, StationThresholds, compute_thresholds, parse_dly_records_text, update_thresholds_with_obs
from src.data.temperature_history import retained_claims, record_claim_finding, record_observation_revision, tracked_points, merge_temperature_history
from src.editorial.revisions import record_human_review, authorize_draft, approval_is_current

SID = "USS0011K13S"
NOW = "2026-09-09T12:00:00Z"
DAY = date(2026, 6, 25)
META = {"station_id": SID, "name": "BEAVER DAMS", "country_code": "US", "country_name": "United States", "state": "UT", "lat": 40.0, "lon": -111.0}


def dly(rows, sid=SID):
    """Serialize explicit (date, element, tenths C, QFLAG, SFLAG) cells."""
    months = {}
    for day, element, value, qflag, sflag in rows:
        key = (day.year, day.month, element)
        cells = months.setdefault(key, ["-9999   "] * 31)
        cells[day.day - 1] = f"{value:5d} {qflag or ' '}{sflag or ' '}"
    return "\n".join(f"{sid}{year:04d}{month:02d}{element}" + "".join(cells)
                     for (year, month, element), cells in sorted(months.items())).encode()


def baseline_rows():
    # Complete engineered source calendar; only the named audited point values
    # are historical evidence. Other daily samples are synthetic test support.
    start = date(2003, 6, 25)
    return [(day, "TMAX", 319 if day == date(2020, 6, 25) else 280, "", "T")
            for offset in range((DAY - start).days) if (day := start + timedelta(days=offset))]


def archive(qflag="", candidate=399, *, intervening=True):
    rows = baseline_rows()
    if intervening:
        rows.append((date(2026, 6, 12), "TMAX", 348, "", "T"))
    if candidate is not None:
        rows.append((DAY, "TMAX", candidate, qflag, "T"))
    return dly(rows)


def db(tmp_path):
    path = tmp_path / "thresholds.sqlite"
    with open_db(path) as conn:
        # Deliberately stale cache misses the June 12 progression.
        thresholds = compute_thresholds([DailyObs(SID, date(2020, 6, 25), "TMAX", 31.9)])
        upsert_thresholds(conn, thresholds)
    return path


def run(tmp_path, payload, *, state=None, obs=None, **kwargs):
    observations = [DailyObs(SID, DAY, "TMAX", 39.9)] if obs is None else obs
    grouped = {}
    for row in observations:
        grouped.setdefault((row.station_id, row.obs_date), []).append(row)
    metrics = {}
    bundles, countries = ghcn.check_extreme_signals_for_stations(
        stations=[META], db_path=db(tmp_path), _fetch_obs_fn=lambda _: grouped,
        _fetch_archive_fn=lambda _: payload, _now_fn=lambda: NOW,
        bot_state=state, metrics_out=metrics, **kwargs,
    )
    return bundles, countries, metrics


def draft(status="approved", *, event_day=DAY, sid=SID, prior=31.9):
    row = {"id": f"claim-{sid}-{event_day}", "event_id": f"all_time_high_{sid}_{event_day}",
           "type": "all_time_record", "status": "pending", "text": "Retained exact weather claim.",
           "content_revision": 1, "created_at": "2026-06-28T00:00:00Z",
           "review_context": {"two_bot": {"bundle": {"raw_signal_dump": {
               "new_temp_c": 39.9, "old_record_c": prior, "signal_date": str(event_day), "station_id": sid,
           }}, "critic": {"passed": True, "verbatim": "Original review"}}}}
    record_human_review(row)
    authorize_draft(row, "manual", intent_id="retained-intent")
    row["status"] = status
    if status == "posted":
        row["tweet_id"] = "receipt-123"
        row["posted_at"] = "2026-06-28T00:01:00Z"
    return row


def test_beaver_intervening_record_is_reconciled_from_source_not_published_history(tmp_path):
    state = {}
    bundles, _, metrics = run(tmp_path, archive(), state=state)
    assert len(bundles) == 1
    event = bundles[0].all_time_high
    assert event.old_record_c == 34.8
    assert event.new_temp_c == 39.9
    evidence = event.evidence
    assert evidence["valid_date"] == "2026-06-25"
    assert evidence["timezone"] is evidence["valid_start"] is evidence["issued_at"] is None
    assert evidence["variables"]["TMAX"]["sflag"] == "T"
    scope = evidence["baseline"]["variables"]["temperature_2m_max"]
    assert scope["previous_date"] == "2026-06-12"
    assert scope["years_with_samples"] == 24
    assert evidence["baseline"]["cutoff"] == "2026-06-24"
    assert scope["complete"] is True
    assert scope["source_coverage_complete"] is True
    assert scope["sample_count"] == (DAY - date(2003, 6, 25)).days
    assert metrics["archive_verification_verified"] == 1
    kept = [row for row in state["temperature_history"].values() if row["kind"] == "observation_revision"]
    assert {row["valid_date"] for row in kept} == {"2026-06-12", "2026-06-25", "2020-06-25"}
    # Daily history stays in the source archive; only record points/comparators persist.
    assert len(kept) == 3


def test_candidate_itself_never_enters_its_baseline():
    snap = ghcn._archive_snapshot(SID, archive(), NOW)
    thresholds, obs = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, DAY, "TMAX", 39.9)], snap)
    assert thresholds.all_time_max_c == 34.8
    assert thresholds.provenance["variables"]["temperature_2m_max"]["candidate_accepted"] is True
    assert obs[0].source_revision == snap["source_revision"]


def test_current_qc_failure_withholds_record_and_preserves_publication_evidence(tmp_path):
    original = draft("posted")
    state = {"drafts": [deepcopy(original)], "publish_ledger": {original["event_id"]: {"phase": "confirmed", "tweet_id": "receipt-123"}}}
    ledger = deepcopy(state["publish_ledger"])
    bundles, countries, metrics = run(tmp_path, archive(qflag="S"), state=state)
    assert bundles == countries == []
    assert state["drafts"] == [original]
    assert state["publish_ledger"] == ledger
    rows = list(state["temperature_history"].values())
    qc = next(row for row in rows if row["kind"] == "observation_revision" and row["valid_date"] == str(DAY))
    assert qc["qflag"] == "S" and qc["sflag"] == "T" and qc["source_accepted"] is False
    assert qc["publication_time_qc_known"] is False
    findings = [row for row in rows if row["kind"] == "affected_claim"]
    assert {row["reason"] for row in findings} == {"current_source_qc_or_value_revision", "current_archive_comparator_changed"}
    assert all(row["publication_time_qc_known"] is False for row in findings)
    assert next(row for row in findings if row["reason"] == "current_source_qc_or_value_revision")["details"]["publication_time_flag_timing"] == "unknown"
    assert metrics["affected_claims"] == 2


@pytest.mark.parametrize("status", ["approved", "pending"])
def test_verified_revision_revokes_exact_unpublished_approval_and_is_idempotent(tmp_path, status):
    original = draft(status)
    state = {"drafts": [deepcopy(original)]}
    run(tmp_path, archive(qflag="S"), state=state)
    changed = state["drafts"][0]
    assert changed["text"] == original["text"]
    assert changed["publish_intent_id"] == "retained-intent"
    assert changed["status"] == "pending" and not approval_is_current(changed)
    assert changed["revision_history"][0]["draft_snapshot"] == original
    once = deepcopy(state)
    run(tmp_path, archive(qflag="S"), state=state)
    assert state == once


@pytest.mark.parametrize("protection", ["unknown", "submitted", "attempt", "receipt"])
def test_unknown_send_or_retained_receipt_is_findings_only(tmp_path, protection):
    item = draft()
    state = {"drafts": [item]}
    if protection in ("unknown", "submitted"):
        item["publish_outcome"] = protection
    elif protection == "attempt":
        state["publish_ledger"] = {item["event_id"]: {"phase": "submitted", "publish_intent_id": "retained-intent"}}
    else:
        state["publish_ledger"] = {item["event_id"]: {"phase": "confirmed", "text": item["text"], "tweet_id": "receipt-123"}}
    before = deepcopy(state)
    run(tmp_path, archive(qflag="S"), state=state)
    assert state["drafts"] == before["drafts"]
    assert state.get("publish_ledger") == before.get("publish_ledger")
    assert any(row["kind"] == "affected_claim" for row in state["temperature_history"].values())


def test_unrelated_station_and_date_do_not_revoke_approval(tmp_path):
    other = draft(sid="USC00000001")
    later = draft(event_day=date(2026, 7, 1), prior=None)
    state = {"drafts": [other, later]}
    before = deepcopy(state["drafts"])
    run(tmp_path, archive(qflag="S"), state=state)
    assert state["drafts"] == before


def test_missing_source_or_unknown_legacy_cutoff_never_refutes_a_published_claim(tmp_path):
    item = draft()
    state = {"drafts": [deepcopy(item)]}
    bundles, countries, metrics = run(tmp_path, b"invalid", state=state)
    assert bundles == countries == []
    assert state["drafts"] == [item]
    assert metrics["baseline_cutoff_gaps"] == metrics["archive_verification_failed"] == 1
    assert {row["reason"] for row in state["temperature_history"].values()} == {"current_archive_unverified"}
    assert all(row["details"]["historical_correctness"] == "not_determined" for row in state["temperature_history"].values())


def test_unverified_record_does_not_leak_historical_values_to_country():
    thresholds = StationThresholds(station_id=SID, archive_years=50, all_time_max_c=20, all_time_max_year=2000)
    bundle = ghcn._detect_signals_for_station(META, [DailyObs(SID, DAY, "TMAX", 39.9)], thresholds)
    assert bundle.today_max_c == 39.9
    assert bundle.archive_max_c is None and bundle.all_time_high is None


def test_tmax_year_span_cannot_qualify_tmin_or_sparse_calendar_date():
    rows = baseline_rows() + [(date(2025, 1, 10), "TMIN", -50, "", "T"), (DAY, "TMIN", -100, "", "T")]
    snap = ghcn._archive_snapshot(SID, dly(rows), NOW)
    thresholds, observations = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, DAY, "TMIN", -10)], snap)
    bundle = ghcn._detect_signals_for_station(META, observations, thresholds)
    assert bundle.all_time_low is bundle.monthly_low is bundle.calendar_date_low is None
    assert thresholds.provenance["variables"]["temperature_2m_min"]["years_with_samples"] == 1
    # Fifteen years of July data do not invent fifteen years for June 12.
    rows = [(date(y, 7, 1), "TMAX", 280, "", "T") for y in range(2000, 2025)]
    rows += [(date(2025, 6, 12), "TMAX", 250, "", "T"), (date(2026, 6, 12), "TMAX", 270, "", "T")]
    snap = ghcn._archive_snapshot(SID, dly(rows), NOW)
    thresholds, observations = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, date(2026, 6, 12), "TMAX", 27)], snap)
    bundle = ghcn._detect_signals_for_station(META, observations, thresholds)
    assert bundle.monthly_high is bundle.calendar_date_high is bundle.anomaly_hot is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_or_boolean_observations_never_enter_baseline(value):
    assert compute_thresholds([DailyObs(SID, DAY, "TMAX", value)]) is None
    assert DiffRecord("update", SID, DAY, "TMAX", value).to_daily_obs() is None


def test_wrong_station_and_contradictory_archive_are_rejected():
    with pytest.raises(ValueError, match="another station"):
        ghcn._archive_snapshot("USC00000001", archive(), NOW)
    with pytest.raises(ValueError, match="contradictory"):
        ghcn._archive_snapshot(SID, archive() + b"\n" + dly([(DAY, "TMAX", 410, "", "T")]), NOW)


def test_threshold_provenance_round_trips_and_partial_delta_revokes_qualification(tmp_path):
    snap = ghcn._archive_snapshot(SID, archive(), NOW)
    thresholds, _ = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, DAY, "TMAX", 39.9)], snap)
    with open_db(tmp_path / "roundtrip.sqlite") as conn:
        upsert_thresholds(conn, thresholds)
        loaded = load_thresholds(conn, SID)
    assert loaded.provenance == thresholds.provenance
    assert update_thresholds_with_obs(loaded, [DailyObs(SID, DAY, "TMAX", 39.9)])
    assert loaded.provenance["reconciled"] is False


def test_bounded_verification_reports_unscanned_and_rotates_tracked_stations(tmp_path):
    path = db(tmp_path)
    ids = [f"USC{i:08d}" for i in range(24)]
    state = {"drafts": [draft("posted", sid=sid) for sid in ids]}
    calls = []
    def fetch(sid):
        calls.append(sid)
        return archive().replace(SID.encode(), sid.encode())
    metrics = {}
    ghcn.check_extreme_signals_for_stations(stations=[META], db_path=path, bot_state=state,
        _fetch_obs_fn=lambda _: {}, _fetch_archive_fn=fetch, _now_fn=lambda: NOW,
        archive_verification_limit=999, metrics_out=metrics)
    assert len(calls) == 20
    assert metrics["archive_verification_exhausted"] == metrics["tracked_stations_unscanned"] == 4
    selection = metrics["archive_selection"]
    assert selection["limit"] == 20
    assert selection["tracked"]["pool_stations"] == 24
    assert selection["tracked"]["verified_stations"] == 20
    assert selection["tracked"]["unverified_stations"] == 4
    assert selection["tracked"]["stable_sweep_opportunities"] == 2
    first = set(calls)
    calls.clear()
    ghcn.check_extreme_signals_for_stations(stations=[META], db_path=path, bot_state=state,
        _fetch_obs_fn=lambda _: {}, _fetch_archive_fn=fetch, _now_fn=lambda: "2026-09-09T16:00:00Z")
    assert set(calls) != first
    assert set(calls) | first == set(ids)


def test_failed_verifications_report_actual_coverage_without_spending_extra_fetches(tmp_path):
    path = db(tmp_path)
    ids = [f"USC{i:08d}" for i in range(24)]
    original_drafts = [draft("posted", sid=sid) for sid in ids]
    state = {"drafts": deepcopy(original_drafts)}
    calls = []

    def unavailable(sid):
        calls.append(sid)
        raise OSError("offline fixture: unavailable archive")

    metrics = {}
    ghcn.check_extreme_signals_for_stations(stations=[META], db_path=path, bot_state=state,
        _fetch_obs_fn=lambda _: {}, _fetch_archive_fn=unavailable, _now_fn=lambda: NOW,
        metrics_out=metrics)
    assert len(calls) == len(set(calls)) == 20
    assert metrics["archive_verification_attempted"] == metrics["archive_verification_failed"] == 20
    assert metrics["archive_verification_verified"] == 0
    assert metrics["archive_verification_exhausted"] == 4
    assert metrics["tracked_stations_unscanned"] == 24
    selection = metrics["archive_selection"]
    assert selection["tracked"]["selected_stations"] == 20
    assert selection["tracked"]["verified_stations"] == 0
    assert selection["tracked"]["unverified_stations"] == 24
    assert state["drafts"] == original_drafts


def test_material_revision_history_union_preserves_conflicting_payloads():
    a = {"same": {"value": 34.8}}
    b = {"same": {"value": 39.9}}
    result = merge_temperature_history(a, b)
    assert result == merge_temperature_history(b, a)
    assert sorted(row["value"] for row in result.values()) == [34.8, 39.9]
    assert result == merge_temperature_history(result, a)


def test_old_qc_record_is_retained_before_freshness_filter(monkeypatch):
    stale = DiffRecord("update", SID, DAY, "TMAX", 39.9, qflag="S", sflag="T")
    fresh = DiffRecord("update", SID, date(2026, 9, 8), "TMAX", 20.0)
    monkeypatch.setattr(ghcn, "_fetch_diff", lambda _: b"fixture")
    monkeypatch.setattr(ghcn, "parse_superghcnd_diff_records_bytes", lambda _: [stale, fresh])
    revisions = []
    values = ghcn._fetch_recent_obs(frozenset([SID]), today=date(2026, 9, 9), lookback_days=1,
                                   revisions_out=revisions, tracked_keys={(SID, DAY, "TMAX")})
    assert list(values) == [(SID, date(2026, 9, 8))]
    assert revisions[0][0] == stale


def test_missing_candidate_value_records_uncertainty_without_rewriting_draft(tmp_path):
    item = draft(prior=34.8)
    state = {"drafts": [deepcopy(item)]}
    # The month exists, with an explicit missing (-9999) June 25 cell.
    bundles, _, _ = run(tmp_path, archive(candidate=None), state=state)
    assert bundles == []
    assert state["drafts"] == [item]
    findings = [row for row in state["temperature_history"].values() if row["kind"] == "affected_claim"]
    assert [row["reason"] for row in findings] == ["tracked_observation_missing_current_value"]


def test_no_fresh_diff_still_reviews_old_tracked_archive(tmp_path, monkeypatch):
    item = draft("posted")
    state = {"drafts": [deepcopy(item)]}
    def unavailable(*args, **kwargs):
        raise RuntimeError("No recent diff files")
    monkeypatch.setattr(ghcn, "_fetch_recent_obs", unavailable)
    metrics = {}
    ghcn.check_extreme_signals_for_stations(stations=[META], db_path=db(tmp_path), bot_state=state,
        _fetch_archive_fn=lambda _: archive(qflag="S"), _now_fn=lambda: NOW, metrics_out=metrics)
    assert state["drafts"] == [item]
    assert metrics["diff_fetch_failed"] == 1 and metrics["affected_claims"] == 2


def test_old_diff_qc_revision_survives_archive_failure_end_to_end(tmp_path, monkeypatch):
    item = draft("posted")
    state = {"drafts": [deepcopy(item)]}
    stale = DiffRecord("update", SID, DAY, "TMAX", 39.9, qflag="S", sflag="T")
    monkeypatch.setattr(ghcn, "_fetch_diff", lambda _: b"fixture")
    monkeypatch.setattr(ghcn, "parse_superghcnd_diff_records_bytes", lambda _: [stale])
    metrics = {}
    ghcn.check_extreme_signals_for_stations(stations=[META], db_path=db(tmp_path), bot_state=state,
        _fetch_archive_fn=lambda _: b"invalid", _now_fn=lambda: NOW, metrics_out=metrics)
    assert state["drafts"] == [item]
    assert metrics["station_obs_pairs"] == 0 and metrics["material_revisions"] == 1
    assert any(row["kind"] == "observation_revision" and row["qflag"] == "S" for row in state["temperature_history"].values())


def test_finding_preserves_a_reviewed_candidate_list_verbatim(tmp_path):
    item = draft()
    item["review_context"]["two_bot"]["candidates"] = [{"rank": 1, "tweet": "A"}, {"rank": 2, "tweet": "B"}]
    state = {"drafts": [deepcopy(item)]}
    run(tmp_path, archive(qflag="S"), state=state)
    assert state["drafts"][0]["revision_history"][0]["draft_snapshot"] == item


def test_shared_history_contract_and_real_dashboard_roundtrip(tmp_path):
    import json
    from pathlib import Path
    from tests.test_persistence_contract import node_store
    from src.storage import sqlite_store
    from src.state import DEFAULT_STATE
    cases = json.loads((Path(__file__).parent / "fixtures/temperature_history_contract.json").read_text())
    for index, case in enumerate(cases):
        assert merge_temperature_history(case["base"], case["incoming"]) == case["expected"]
        assert merge_temperature_history(case["incoming"], case["base"]) == case["expected"]
        path = tmp_path / f"history-{index}.sqlite"
        state = deepcopy(DEFAULT_STATE)
        state["temperature_history"] = case["base"]
        assert sqlite_store.write_state(str(path), state)
        result = node_store(path, "write", {"temperature_history": case["incoming"]})
        assert result["temperature_history"] == case["expected"]
        assert sqlite_store.read_state(str(path), DEFAULT_STATE)["temperature_history"] == case["expected"]


def test_omitted_intervening_source_years_withhold_record_and_comparator_refutation(tmp_path):
    rows = [(date(year, 6, 25), "TMAX", 280, "", "T") for year in range(2000, 2015)]
    rows.append((DAY, "TMAX", 399, "", "T"))
    item = draft(prior=31.9)
    state = {"drafts": [deepcopy(item)]}
    bundles, countries, metrics = run(tmp_path, dly(rows), state=state)
    assert bundles == countries == []
    assert metrics["baseline_cutoff_gaps"] == 1
    assert state["drafts"] == [item]
    assert any(row.get("reason") == "current_archive_comparison_gap" for row in state["temperature_history"].values())
    snap = ghcn._archive_snapshot(SID, dly(rows), NOW)
    thresholds, _ = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, DAY, "TMAX", 39.9)], snap)
    scope = thresholds.provenance["variables"]["temperature_2m_max"]
    assert scope["source_coverage_complete"] is False
    assert scope["verified_source_cutoff"] is thresholds.provenance["cutoff"] is None
    assert thresholds.provenance["requested_comparison_cutoff"] == "2026-06-24"


def test_explicit_missing_and_qc_cells_are_exclusions_from_accepted_sample_scope():
    rows = baseline_rows()
    rows.append((date(2025, 6, 24), "TMAX", -9999, "", ""))
    rows.append((date(2025, 6, 23), "TMAX", 900, "S", "T"))
    rows.append((DAY, "TMAX", 399, "", "T"))
    snap = ghcn._archive_snapshot(SID, dly(rows), NOW)
    thresholds, observations = ghcn._thresholds_from_verified_archive(SID, [DailyObs(SID, DAY, "TMAX", 39.9)], snap)
    scope = thresholds.provenance["variables"]["temperature_2m_max"]
    assert scope["source_coverage_complete"] is True
    assert scope["complete"] is False
    assert scope["source_missing_count"] == scope["source_qc_rejected_count"] == 1
    assert scope["sample_count"] == scope["source_calendar_count"] - 2
    bundle = ghcn._detect_signals_for_station(META, observations, thresholds)
    assert bundle.all_time_high.old_record_c == 31.9
    assert bundle.all_time_high.evidence["baseline"]["comparison_scope"] == "available_source_accepted_station_samples"


@pytest.mark.parametrize("conflict", [None, {}, [None], [3], [{"phase": "not_sent", "attempt_conflicts": [None]}]])
def test_source_revision_cannot_mutate_malformed_unknown_outcomes(conflict):
    item = draft()
    state = {"drafts": [deepcopy(item)], "publish_ledger": {item["event_id"]: {"phase": "not_sent", "attempt_conflicts": conflict}}}
    claim = retained_claims(state)[0]
    record_claim_finding(state, claim, reason="verified_current_qc", source_revision="source-1", retrieved_at=NOW,
                         details={"qflag": "S"}, verified_change=True)
    assert state["drafts"] == [item]


def test_requested_cutoff_does_not_claim_accepted_or_verified_source_coverage():
    observations = [DailyObs(SID, date(year, 6, 25), "TMAX", 28.0) for year in range(2000, 2015)]
    thresholds = compute_thresholds(observations, before=DAY, retrieved_at=NOW, source_revision="fixture-source")
    assert thresholds.provenance["requested_comparison_cutoff"] == "2026-06-24"
    assert thresholds.provenance["cutoff"] is None
    assert thresholds.provenance["variables"]["temperature_2m_max"]["cutoff"] == "2014-06-25"


def test_one_variables_contiguous_source_cannot_qualify_another_variables_gap():
    sparse_highs = [(date(year, 6, 25), "TMAX", 280, "", "T") for year in range(2000, 2015)]
    complete_lows = [(day, "TMIN", 100, flag, source) for day, _, _, flag, source in baseline_rows()]
    rows = sparse_highs + complete_lows + [(DAY, "TMAX", 399, "", "T"), (DAY, "TMIN", -100, "", "T")]
    snap = ghcn._archive_snapshot(SID, dly(rows), NOW)
    thresholds, obs = ghcn._thresholds_from_verified_archive(
        SID, [DailyObs(SID, DAY, "TMAX", 39.9), DailyObs(SID, DAY, "TMIN", -10)], snap,
    )
    high, low = [thresholds.provenance["variables"][key] for key in ("temperature_2m_max", "temperature_2m_min")]
    assert high["source_coverage_complete"] is False and high["source_gap_count"] > 0
    assert high["verified_source_cutoff"] is None
    assert low["source_coverage_complete"] is True and low["source_gap_count"] == 0
    assert low["verified_source_cutoff"] == "2026-06-24"
    assert thresholds.provenance["cutoff"] is None
    bundle = ghcn._detect_signals_for_station(META, obs, thresholds)
    assert bundle.all_time_high is bundle.monthly_high is bundle.calendar_date_high is None
    assert bundle.all_time_low is not None and bundle.monthly_low is not None


def test_material_history_union_is_associative_commutative_and_idempotent():
    from itertools import permutations
    from src.editorial.revisions import fingerprint
    samples = [{"value_c": None}, {"value_c": 34.8}, {"value_c": 39.9, "qflag": "S"}]
    canonical = sorted(samples, key=fingerprint)
    expected = {"point" if index == 0 else f"point:conflict:{fingerprint(row)}": row
                for index, row in enumerate(canonical)}
    for a, b, c in permutations({"point": row} for row in samples):
        left = merge_temperature_history(merge_temperature_history(a, b), c)
        right = merge_temperature_history(a, merge_temperature_history(b, c))
        assert left == right == expected
        assert merge_temperature_history(left, left) == left


def test_material_observation_revision_retains_supplied_observation_time():
    state = {}
    row = DiffRecord("update", SID, DAY, "TMAX", 39.9, mflag="A", sflag="T", observation_time="0700")
    revision, added = record_observation_revision(state, row, retrieved_at=NOW, source_revision="source-response")
    assert added
    assert state["temperature_history"][revision]["observation_time"] == "0700"
    assert state["temperature_history"][revision]["mflag"] == "A"
    assert state["temperature_history"][revision]["publication_time_qc_known"] is False


def test_malformed_existing_finding_list_cannot_partially_rewrite_approval():
    item = draft()
    item["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["source_revision_findings"] = "legacy unknown"
    state = {"drafts": [deepcopy(item)]}
    claim = retained_claims(state)[0]
    assert record_claim_finding(state, claim, reason="verified_current_qc", source_revision="source-1", retrieved_at=NOW,
                                details={"qflag": "S"}, verified_change=True)
    assert state["drafts"] == [item]


def test_real_diff_tar_bytes_retain_old_qc_flags_and_original_payload_fingerprint(monkeypatch):
    import hashlib
    csv = (f"{SID},20260625,TMAX,399,A,S,T,0700\n"
           f"{SID},20260908,TMAX,200,,,T,0800\n").encode()
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as archive_file:
        member = tarfile.TarInfo("superghcnd_update.csv")
        member.size = len(csv)
        archive_file.addfile(member, io.BytesIO(csv))
    payload = gzip.compress(tar_bytes.getvalue(), mtime=0)
    monkeypatch.setattr(ghcn, "_fetch_diff", lambda _: payload)
    revisions = []
    observations = ghcn._fetch_recent_obs(frozenset([SID]), today=date(2026, 9, 9), lookback_days=1,
                                         revisions_out=revisions, tracked_keys={(SID, DAY, "TMAX")})
    assert list(observations) == [(SID, date(2026, 9, 8))]
    assert len(revisions) == 1
    row, retrieved_at, source_revision = revisions[0]
    assert row.obs_date == DAY and row.value_c == 39.9
    assert (row.mflag, row.qflag, row.sflag, row.observation_time) == ("A", "S", "T", "0700")
    assert source_revision == hashlib.sha256(payload).hexdigest()
    assert retrieved_at
    assert row.to_daily_obs() is None
