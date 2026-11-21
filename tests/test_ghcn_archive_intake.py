"""Source-byte reuse is bounded supply, never a cached or model factual pass."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from dashboard.tests.fixtures.ghcn_archive_intake_producer import DAY, NOW, archive_bytes, produce_archive
from src.data import ghcn
from src.data.ghcn_db import open_db, upsert_thresholds
from src.data.ghcn_format import DiffRecord, compute_thresholds, parse_dly_text
from src.data.temperature_history import record_observation_revision
from src.storage.ghcn_runtime_inputs import Effects, InventedResponse, ReplayIO, configuration
from tests.ghcn_intake_cases import DATES, SID, Replies, payloads

META = {"station_id": SID, "name": "INVENTED FIXTURE STATION", "country_code": "BR",
        "country_name": "Brazil", "state": "", "lat": -10.0, "lon": -50.0}


def invoke(tmp_path, *, payload=None, data=None, tracked=True, stations=None, injected=None, runtime=False):
    payload = archive_bytes() if payload is None else payload
    path = tmp_path / "fixture.sqlite"
    with open_db(path) as conn:
        upsert_thresholds(conn, compute_thresholds(parse_dly_text(archive_bytes(target=None).decode())))
    state = {"drafts": [], "publish_ledger": {"invented-preserved": {"phase": "unknown"}}}
    if tracked:
        record_observation_revision(state, DiffRecord("insert", SID, date(2000, 1, 1), "TMAX", 25),
                                    retrieved_at=NOW, source_revision=sha256(archive_bytes(target=None)).hexdigest())
    original = deepcopy(state)
    extra = {f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{SID}.dly": payload}
    replies = Replies(data or {}, extra)
    metrics = {}
    io = None
    if runtime:
        responses = [InventedResponse("diff", d.isoformat(), NOW, None, "missing") for d in DATES]
        responses.append(InventedResponse("station_archive", SID, NOW, payload))
        io = ReplayIO(responses, configuration(), NOW)
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
        output = ghcn.check_extreme_signals_for_stations(
            stations=[META] if stations is None else stations, db_path=path,
            metrics_out=metrics, bot_state=state, _now_fn=lambda: NOW,
            _fetch_obs_fn=injected, _runtime=io,
        )
    assert state["drafts"] == original["drafts"] and state["publish_ledger"] == original["publish_ledger"]
    return output, metrics, state, replies, io


def test_missing_diffs_reuse_only_already_requested_verified_archive_for_high_and_low(tmp_path):
    (bundles, _), m, _, replies, _ = invoke(tmp_path)
    assert len(bundles) == 1, "Fresh accepted source bytes already fetched for revision checks must not be discarded"
    b = bundles[0]
    assert b.signal_date == DAY and b.all_time_high.new_temp_c == 33
    assert b.all_time_low.new_temp_c == -15
    assert b.all_time_high.old_record_c == 25 and b.all_time_low.old_record_c == 15
    assert b.evidence["baseline"]["cutoff"] == "2026-11-17"
    assert b.evidence["variables"]["TMAX"]["source_payload_sha256"] == sha256(archive_bytes()).hexdigest()
    assert m["diff_dates_fetched"] == 0 and m["diff_fetch_failed"] == 1
    assert m["stations_with_obs"] == m["station_obs_pairs"] == 1
    assert m["station_archive_intake"]["counts"]["accepted_values"] == 2
    assert m["archive_verification_attempted"] == m["archive_verification_verified"] == 1
    assert len(replies.calls) == 31
    assert sum("/all/" in url for url, _ in replies.calls) == 1


@pytest.mark.parametrize("case", ["empty", "stale", "future", "qc"])
def test_source_runner_never_qualifies_old_future_missing_or_qc_rejected_archive_values(case):
    row = produce_archive(case)["run_history"][0]["sources"][0]
    m = row["details"]["pipeline_metrics"]
    assert row["promoted"] == 0 and m["station_obs_pairs"] == 0
    assert m["station_archive_intake"]["counts"]["accepted_values"] == 0
    assert row["status"] == "degraded"


def test_real_source_runner_and_durable_json_retain_actual_archive_supply_without_diff_recovery():
    state = produce_archive()
    row = state["run_history"][0]["sources"][0]
    m = row["details"]["pipeline_metrics"]
    assert m["station_obs_pairs"] == 1 and row["observed"] == 1
    assert row["status"] == "degraded" and m["diff_dates_fetched"] == 0
    assert m["station_archive_intake"]["counts"]["accepted_values"] == 2
    assert state["request_count"] == 31 and state["drafts"] == []
    assert produce_archive(provider="both_global")["run_history"][0]["sources"][0]["details"]["ghcn_pipeline_metrics"]["station_archive_intake"] == m["station_archive_intake"]


def test_real_retained_replay_derives_identical_qualified_output_and_uses_every_original_response(tmp_path):
    live = invoke(tmp_path)
    replay = invoke(tmp_path, runtime=True)
    assert live[0] and live[0][0], "Parity of two empty results is not supply proof"
    assert [[asdict(b) for b in group] for group in live[0]] == [[asdict(b) for b in group] for group in replay[0]]
    lm = {k: v for k, v in live[1].items() if k != "diff_fetch"}
    assert lm == replay[1]
    assert replay[3].calls == []
    assert live[2] == replay[2]
    assert replay[4].used == {("diff", d.isoformat()) for d in DATES} | {("station_archive", SID)}
    assert isinstance(replay[4].effects, Effects) and replay[4].effects.rows


def test_no_tracked_archive_does_not_expand_source_requests(tmp_path):
    with pytest.raises(RuntimeError, match="no diff files available"):
        invoke(tmp_path, tracked=False)


def test_custom_observation_reader_cannot_enable_archive_recovery(tmp_path):
    output, metrics, _, replies, _ = invoke(tmp_path, injected=lambda _: {})
    assert output == ([], []) and "station_archive_intake" not in metrics
    assert len(replies.calls) == 1


def test_partial_successful_diff_does_not_borrow_more_observations_from_archive(tmp_path):
    output, metrics, _, _, _ = invoke(tmp_path, data=payloads("missing"))
    assert metrics["diff_dates_fetched"] == 1 and "station_archive_intake" not in metrics
    assert metrics["station_obs_pairs"] == 2


@pytest.mark.parametrize("raw", [b"invalid archive", archive_bytes(station="BRX00000002")], ids=["malformed", "wrong_station"])
def test_unverified_or_wrong_station_archives_never_supply_candidates(tmp_path, raw):
    output, metrics, _, _, _ = invoke(tmp_path, payload=raw)
    assert output == ([], []) and metrics["archive_verification_failed"] == 1
    assert metrics["station_archive_intake"]["counts"]["accepted_values"] == 0


def test_inactive_tracked_station_remains_revision_only(tmp_path):
    other = dict(META, station_id="BRX00000002")
    output, metrics, _, replies, _ = invoke(tmp_path, stations=[other])
    assert output == ([], []) and metrics["station_obs_pairs"] == 0
    assert metrics["station_archive_intake"]["counts"]["inactive_station_rows"] > 0
    assert len(replies.calls) == 31


@pytest.mark.parametrize("case", ["no_temperature", "empty"])
def test_recognized_empty_diff_results_do_not_trigger_archive_substitution(tmp_path, case):
    output, metrics, _, _, _ = invoke(tmp_path, data=payloads(case))
    assert output == ([], []) and metrics["diff_dates_fetched"] == 3
    assert "station_archive_intake" not in metrics


def test_malformed_diff_is_not_rescued_by_a_valid_current_archive(tmp_path):
    with pytest.raises(ValueError):
        invoke(tmp_path, data=payloads("malformed"))


@pytest.mark.parametrize("message", ["Unexpected reader failure", "GHCN: no diff files available from NOAA"])
def test_arbitrary_or_unbound_reader_exception_cannot_enable_archive_intake(tmp_path, message):
    with patch.object(ghcn, "_fetch_recent_obs", side_effect=RuntimeError(message)):
        output, metrics, _, replies, _ = invoke(tmp_path)
    assert output == ([], []) and "station_archive_intake" not in metrics
    assert len(replies.calls) == 1  # Existing tracked revision check only.


def test_inclusive_age_cutoff_and_explicit_clock_keep_the_original_news_window(tmp_path):
    cutoff = date(2026, 11, 17)
    output, metrics, _, _, _ = invoke(tmp_path, payload=archive_bytes(target=cutoff))
    assert output[0] and output[0][0].signal_date == cutoff
    assert metrics["station_archive_intake"]["cutoff_day"] == cutoff.isoformat()
    with patch.object(ghcn, "MAX_OBS_AGE_DAYS", 1):
        output, metrics, _, _, _ = invoke(tmp_path)
    assert output == ([], []) and metrics["station_obs_pairs"] == 0
    assert metrics["station_archive_intake"]["cutoff_day"] == "2026-11-20"


def test_reused_metrics_sink_cannot_lend_an_old_archive_intake_to_an_empty_run(tmp_path):
    _, metrics, _, _, _ = invoke(tmp_path)
    assert "station_archive_intake" in metrics
    assert ghcn.check_extreme_signals_for_stations(stations=[], db_path=tmp_path / "fixture.sqlite", metrics_out=metrics) == ([], [])
    assert "station_archive_intake" not in metrics and "diff_fetch" not in metrics
