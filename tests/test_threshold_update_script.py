"""Synthetic daily intervals only; no source, provider or release transport calls."""

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest
import requests
import yaml

from scripts import update_thresholds_incremental as updater
from scripts.threshold_artifacts import ArtifactError, pending_diff_dates
from src.data.ghcn_db import get_meta, load_thresholds, open_db, set_meta, upsert_thresholds
from src.data.ghcn_format import DiffRecord, StationThresholds


class FixedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 4, 2, 0, tzinfo=timezone.utc)


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    path = tmp_path / "invented.sqlite"
    with open_db(path) as conn:
        conn.execute("INSERT INTO stations(station_id,lat,lon,is_active) VALUES('SYNTHETIC',0,0,1)")
        upsert_thresholds(
            conn, StationThresholds("SYNTHETIC", all_time_max_c=20, all_time_max_year=2000)
        )
        set_meta(conn, "last_diff_date", "2026-09-25")
        conn.commit()
    monkeypatch.setattr(updater, "datetime", FixedNow)
    monkeypatch.setattr(
        updater.requests, "get", lambda *a, **kw: pytest.fail("unexpected source call")
    )
    return path


def read_watermark(path):
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as conn:
        return get_meta(conn, "last_diff_date")


def set_watermark(path, watermark):
    with closing(sqlite3.connect(path)) as conn:
        if watermark is None:
            conn.execute("DELETE FROM meta WHERE key='last_diff_date'")
        else:
            set_meta(conn, "last_diff_date", watermark)
        conn.commit()


def fake_source(monkeypatch, records=(), missing=None, payload=None, bridges=()):
    calls = []

    def fetch(start, day):
        calls.append((start, day))
        if (start, day) in bridges:
            return b"invented multi-day interval"
        if (day - start).days != 1:
            return None
        if day == missing:
            return payload
        return b"invented parsed interval"

    monkeypatch.setattr(updater, "_fetch_diff", fetch)
    monkeypatch.setattr(updater, "parse_superghcnd_diff_records_bytes", lambda data: list(records))
    return calls


def record(action="insert", station="SYNTHETIC", qflag=""):
    return DiffRecord(action, station, date(2026, 9, 29), "TMAX", 30.0, qflag=qflag)


def test_threshold_watermark_refuses_to_advance_past_missing_diff():
    from scripts.update_thresholds_incremental import _resolve_new_watermark

    assert _resolve_new_watermark(
        successful_intervals=[
            (date(2026, 4, 30), date(2026, 5, 1)),
            (date(2026, 5, 2), date(2026, 5, 3)),
        ],
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 1)


def test_threshold_watermark_advances_when_successes_are_contiguous():
    from scripts.update_thresholds_incremental import _resolve_new_watermark

    assert _resolve_new_watermark(
        successful_intervals=[
            (date(2026, 4, 30), date(2026, 5, 1)),
            (date(2026, 5, 1), date(2026, 5, 2)),
        ],
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 2)


@pytest.mark.parametrize("prior", [date(2026, 9, 26), date(2026, 9, 27)])
def test_completed_dates_do_not_stall_new_contiguous_success(prior):
    assert updater._resolve_new_watermark(
        successful_intervals=[(date(2026, 9, d - 1), date(2026, 9, d)) for d in (26, 27, 28)],
        current_watermark=prior,
    ) == date(2026, 9, 28)


@pytest.mark.parametrize("prior", [None, date(2026, 9, 24)])
def test_success_dates_cannot_fill_an_unknown_prior_gap(prior):
    assert (
        updater._resolve_new_watermark(
            successful_intervals=[(date(2026, 9, 25), date(2026, 9, 26))],
            current_watermark=prior,
        )
        == prior
    )


@pytest.mark.parametrize(
    "prior,expected",
    [
        ("2026-09-25", [26, 27, 28, 29, 30]),
        ("2026-09-27", [28, 29, 30]),
        ("2026-09-30", []),
    ],
)
def test_shared_plan_has_only_contiguous_unprocessed_dates(prior, expected):
    assert pending_diff_dates(prior, days=8, today=date(2026, 10, 4)) == [
        date(2026, 9, day) for day in expected
    ]


@pytest.mark.parametrize("days,lag", [(True, 1), (8, False), (8.0, 4), (8, 0), (4, 5), (32, 4)])
def test_shared_plan_rejects_unbounded_or_ambiguous_windows(days, lag):
    with pytest.raises(ArtifactError, match="invalid_threshold_update_window"):
        pending_diff_dates("2026-09-25", days=days, lag_days=lag, today=date(2026, 10, 4))


@pytest.mark.parametrize("missing", [26, 28, 30])
@pytest.mark.parametrize("has_records", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_uncovered_interval_never_advances_past_verified_prefix(
    baseline, monkeypatch, capsys, missing, has_records, empty
):
    calls = fake_source(
        monkeypatch,
        [record()] if has_records else [],
        missing=date(2026, 9, missing),
        payload=b"" if empty else None,
    )
    before = baseline.read_bytes()
    result = updater.main(["--db", str(baseline)])
    expected = [(date(2026, 9, d - 1), date(2026, 9, d)) for d in range(26, missing + 1)]
    if not empty:
        expected += [(date(2026, 9, missing - 1), date(2026, 9, d)) for d in range(missing + 1, 31)]
    assert calls == expected
    if empty or missing == 26:
        assert result == 1 and baseline.read_bytes() == before
        assert read_watermark(baseline) == "2026-09-25"
    else:
        assert result == 0
        assert read_watermark(baseline) == f"2026-09-{missing - 1}"
        assert "remains incomplete" in capsys.readouterr().err


@pytest.mark.parametrize(
    "watermark", [None, "", "20260925", "2026-02-30", "2026-09-20", "2026-10-01"]
)
def test_invalid_or_unknown_lineage_never_fetches_or_migrates(baseline, monkeypatch, watermark):
    set_watermark(baseline, watermark)
    calls = fake_source(monkeypatch)
    # A legacy schema would be migrated by open_db; rejection must leave it intact.
    with closing(sqlite3.connect(baseline)) as conn:
        conn.execute("DROP TABLE threshold_provenance")
        conn.commit()
    before = baseline.read_bytes()
    assert updater.main(["--db", str(baseline)]) == 1
    assert calls == [] and baseline.read_bytes() == before


@pytest.mark.parametrize("mode", ["absent", "corrupt", "schema", "symlink", "wal", "journal"])
def test_unavailable_or_active_database_blocks_without_replacement(baseline, monkeypatch, mode):
    path = baseline
    if mode == "absent":
        path = baseline.with_name("absent.sqlite")
    elif mode == "corrupt":
        baseline.write_bytes(b"invented-invalid-database")
    elif mode == "schema":
        with closing(sqlite3.connect(baseline)) as conn:
            conn.execute("DROP TABLE meta")
            conn.commit()
    elif mode == "symlink":
        path = baseline.with_name("link.sqlite")
        path.symlink_to(baseline)
    else:
        Path(str(baseline) + ("-wal" if mode == "wal" else "-journal")).write_bytes(
            b"synthetic-active"
        )
    calls = fake_source(monkeypatch)
    before = baseline.read_bytes()
    assert updater.main(["--db", str(path)]) == 1
    assert not calls and baseline.read_bytes() == before


def test_already_complete_window_is_noop_without_schema_migration(baseline, monkeypatch):
    set_watermark(baseline, "2026-09-30")
    with closing(sqlite3.connect(baseline)) as conn:
        conn.execute("DROP TABLE threshold_provenance")
        conn.commit()
    calls = fake_source(monkeypatch)
    before = baseline.read_bytes()
    assert updater.main(["--db", str(baseline)]) == 0
    assert not calls and baseline.read_bytes() == before


@pytest.mark.parametrize("kind", ["empty", "insert", "update", "delete", "inactive", "qc_failed"])
def test_complete_window_uses_one_checkpoint_for_all_observation_paths(baseline, monkeypatch, kind):
    set_watermark(baseline, "2026-09-27")
    records = (
        []
        if kind == "empty"
        else [
            record(
                action=kind if kind in {"update", "delete"} else "insert",
                station="INACTIVE" if kind == "inactive" else "SYNTHETIC",
                qflag="X" if kind == "qc_failed" else "",
            )
        ]
    )
    calls = fake_source(monkeypatch, records)
    recomputed = []

    def recompute(station, *, through):
        recomputed.append(station)
        return StationThresholds(station, all_time_max_c=25, all_time_max_year=2001)

    monkeypatch.setattr(updater, "_fetch_station_thresholds", recompute)
    assert updater.main(["--db", str(baseline)]) == 0
    assert calls == [(date(2026, 9, d - 1), date(2026, 9, d)) for d in (28, 29, 30)]
    assert read_watermark(baseline) == "2026-09-30"
    assert recomputed == (["SYNTHETIC"] if kind in {"update", "delete"} else [])
    with closing(sqlite3.connect(baseline)) as conn:
        threshold = load_thresholds(conn, "SYNTHETIC")
    assert threshold.all_time_max_c == (30 if kind == "insert" else 25 if recomputed else 20)
    if kind == "insert":
        assert threshold.provenance == {
            "reconciled": False,
            "limitation": "partial_threshold_delta",
        }


@pytest.mark.parametrize("has_records", [False, True])
def test_dry_run_reads_complete_window_without_mutation(baseline, monkeypatch, has_records):
    fake_source(monkeypatch, [record()] if has_records else [])
    before = baseline.read_bytes()
    assert updater.main(["--db", str(baseline), "--dry-run"]) == 0
    assert baseline.read_bytes() == before


@pytest.mark.parametrize("phase", ["fetch", "parse"])
def test_source_exception_before_application_preserves_database(baseline, monkeypatch, phase):
    fake_source(monkeypatch, [record()])
    before = baseline.read_bytes()

    def broken(*args):
        raise ValueError("synthetic source failure")

    monkeypatch.setattr(
        updater,
        "_fetch_diff" if phase == "fetch" else "parse_superghcnd_diff_records_bytes",
        broken,
    )
    with pytest.raises(ValueError, match="synthetic source failure"):
        updater.main(["--db", str(baseline)])
    assert baseline.read_bytes() == before


@pytest.mark.parametrize("kind", ["update", "new_station"])
@pytest.mark.parametrize("failure", ["empty", "request", "parse"])
def test_failed_recompute_never_advances_checkpoint(baseline, monkeypatch, kind, failure):
    if kind == "new_station":
        with closing(sqlite3.connect(baseline)) as conn:
            conn.execute("DELETE FROM thresholds")
            conn.commit()
    fake_source(monkeypatch, [record("update" if kind == "update" else "insert")])

    def broken(station, *, through):
        if failure == "request":
            raise requests.RequestException("synthetic failure")
        if failure == "parse":
            raise ValueError("synthetic failure")
        return None

    monkeypatch.setattr(updater, "_fetch_station_thresholds", broken)
    if failure == "parse" or (failure == "request" and kind == "new_station"):
        with pytest.raises((ValueError, requests.RequestException)):
            updater.main(["--db", str(baseline)])
    else:
        assert updater.main(["--db", str(baseline)]) == 1
    assert read_watermark(baseline) == "2026-09-25"


def test_failure_after_a_committed_chunk_retains_old_checkpoint_without_claiming_rollback(
    baseline, monkeypatch
):
    stations = [f"S{n:03}" for n in range(50)]
    with closing(sqlite3.connect(baseline)) as conn:
        conn.executemany(
            "INSERT INTO stations(station_id,lat,lon,is_active) VALUES(?,0,0,1)",
            [(station,) for station in stations],
        )
        conn.commit()
    fake_source(monkeypatch, [record("update", station) for station in [*stations, "SYNTHETIC"]])

    def recompute(station, *, through):
        if station == "SYNTHETIC":
            return None
        return StationThresholds(station, all_time_max_c=25, all_time_max_year=2001)

    monkeypatch.setattr(updater, "_fetch_station_thresholds", recompute)
    before = baseline.read_bytes()
    assert updater.main(["--db", str(baseline)]) == 1
    assert read_watermark(baseline) == "2026-09-25"
    assert baseline.read_bytes() != before  # Failed candidates are not the committed artifact.
    with closing(sqlite3.connect(baseline)) as conn:
        assert load_thresholds(conn, "S000").all_time_max_c == 25
        assert load_thresholds(conn, "SYNTHETIC").all_time_max_c == 20


@pytest.mark.parametrize("damage", [None, "station", "diff", "missing_diff", "baseline", "manifest", "date", "inventory"])
def test_resumable_capture_keeps_the_baseline_unchanged_and_skips_completed_reads(
    baseline, tmp_path, monkeypatch, capsys, damage,
):
    from scripts import refresh_station_inventory as inventory, threshold_checkpoint_transport as transport

    stations = [f"S{i:03}" for i in range(1, 65)] if damage is None else ["S001"]
    with closing(sqlite3.connect(baseline)) as conn:
        conn.executemany("INSERT INTO stations(station_id,lat,lon,is_active) VALUES(?,0,0,1)",
                         [(station,) for station in stations])
        conn.commit()
        conn.execute("PRAGMA journal_mode=DELETE")
    diff_calls = fake_source(monkeypatch, [record("update", station) for station in (*stations, "SYNTHETIC")])
    completed = []
    fail = True

    def recompute(station, *, through):
        if station == "SYNTHETIC" and fail:
            raise requests.ConnectionError("invented connection interruption")
        completed.append(station)
        return StationThresholds(
            station, all_time_max_c=25, all_time_max_year=2001,
            provenance={"source_payload_sha256": "a" * 64, "requested_comparison_cutoff": through.isoformat()},
        )

    monkeypatch.setattr(updater, "_fetch_station_thresholds", recompute)
    before = baseline.read_bytes()
    checkpoint = tmp_path / "checkpoint"
    monkeypatch.setattr(inventory, "_fetch_text", lambda url: f"invented parser input for {url}")
    inventory._inventory_inputs(checkpoint, 2025)
    manifest = baseline.with_suffix(".version")
    manifest.write_text("invented installed manifest\n")
    argv = ["--db", str(baseline), "--resume-dir", str(checkpoint)]
    assert updater.main(argv) == 1
    assert baseline.read_bytes() == before
    assert sorted(completed) == stations
    first_calls = diff_calls.copy()
    fail = False
    if damage is not None:
        if damage == "baseline":
            with closing(sqlite3.connect(baseline)) as conn, conn:
                conn.execute("UPDATE stations SET lat = 1 WHERE station_id = 'S001'")
        elif damage == "manifest":
            manifest.write_text("different installed manifest\n")
        elif damage == "inventory":
            (checkpoint / inventory.INVENTORY_FILE).write_text("different frozen inventory\n")
        else:
            mutations = {
                "station": "UPDATE thresholds SET value_c = 99",
                "diff": "UPDATE refresh_diffs SET payload = X'00'",
                "missing_diff": "DELETE FROM refresh_diffs",
                "date": "UPDATE meta SET value = '2026-10-03' WHERE key = 'incremental_today'",
            }
            with closing(sqlite3.connect(checkpoint / "refresh.sqlite")) as conn, conn:
                conn.execute(mutations[damage])
        before_resume = baseline.read_bytes()
        assert updater.main(argv) == 1
        assert "threshold_checkpoint_" in capsys.readouterr().err
        assert baseline.read_bytes() == before_resume
        assert read_watermark(baseline) == "2026-09-25"
        assert diff_calls == first_calls and completed == ["S001"]
        return
    # Reconstruct a separate runner directory from the sealed checkpoint.
    archive = tmp_path / "checkpoint.aead"
    restored = tmp_path / "restored"
    cipher = transport._cipher("a2" * 32)
    context = transport._context(manifest, "example/repo", "123", 12)
    transport.seal(checkpoint, archive, cipher, context)
    transport.unseal(archive, restored, cipher, context)
    assert (restored / inventory.INVENTORY_FILE).read_bytes() == (checkpoint / inventory.INVENTORY_FILE).read_bytes()
    assert updater.main(["--db", str(baseline), "--resume-dir", str(restored)]) == 0
    assert diff_calls == first_calls
    assert sorted(completed) == [*stations, "SYNTHETIC"]
    assert read_watermark(baseline) == "2026-09-30"
    with closing(sqlite3.connect(baseline)) as conn:
        assert load_thresholds(conn, "S001").all_time_max_c == 25
        assert load_thresholds(conn, "SYNTHETIC").all_time_max_c == 25


def test_resume_refuses_a_baseline_changed_after_metadata_read(baseline, tmp_path, monkeypatch, capsys):
    calls = fake_source(monkeypatch, [record("update")])
    original = updater._read_baseline

    def concurrent_change(path):
        retained = original(path)
        set_watermark(path, "2026-09-30")
        return retained

    monkeypatch.setattr(updater, "_read_baseline", concurrent_change)
    assert updater.main(["--db", str(baseline), "--resume-dir", str(tmp_path / "checkpoint")]) == 1
    assert "threshold_checkpoint_scope_changed" in capsys.readouterr().err
    assert not calls and read_watermark(baseline) == "2026-09-30"


def test_refresh_owner_refuses_second_directory_before_egress(baseline, tmp_path, monkeypatch, capsys):
    calls = fake_source(monkeypatch, [record("update")])
    with updater.lock_baseline(baseline):
        assert updater.main(["--db", str(baseline), "--resume-dir", str(tmp_path / "other")]) == 1
    assert "threshold_refresh_already_owned" in capsys.readouterr().err
    assert not calls and not (tmp_path / "other").exists()


def test_checkpoint_database_cannot_be_the_baseline(baseline, tmp_path, monkeypatch, capsys):
    from shutil import copyfile

    calls = fake_source(monkeypatch, [record("update")])
    directory = tmp_path / "checkpoint"
    directory.mkdir(mode=0o700)
    aliased = directory / "refresh.sqlite"
    copyfile(baseline, aliased)
    before = aliased.read_bytes()
    assert updater.main(["--db", str(aliased), "--resume-dir", str(directory)]) == 1
    assert "threshold_checkpoint_aliases_baseline" in capsys.readouterr().err
    assert not calls and aliased.read_bytes() == before


@pytest.mark.parametrize("has_records", [False, True])
def test_explicit_multiday_bridge_completes_without_inventing_a_missing_snapshot(
    baseline, monkeypatch, has_records
):
    calls = fake_source(
        monkeypatch,
        [record()] if has_records else [],
        missing=date(2026, 9, 27),
        bridges=[(date(2026, 9, 26), date(2026, 9, 29))],
    )
    assert updater.main(["--db", str(baseline)]) == 0
    assert calls == [
        (date(2026, 9, 25), date(2026, 9, 26)),
        (date(2026, 9, 26), date(2026, 9, 27)),
        (date(2026, 9, 26), date(2026, 9, 28)),
        (date(2026, 9, 26), date(2026, 9, 29)),
        (date(2026, 9, 29), date(2026, 9, 30)),
    ]
    assert read_watermark(baseline) == "2026-09-30"


def test_overlapping_interval_from_wrong_predecessor_is_not_accepted():
    assert updater._resolve_new_watermark(
        successful_intervals=[(date(2026, 9, 24), date(2026, 9, 30))],
        current_watermark=date(2026, 9, 25),
    ) == date(2026, 9, 25)


@pytest.mark.parametrize("status", [200, 404, 301, 500])
def test_transport_requests_one_exact_interval_and_never_redirects_or_retries(monkeypatch, status):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = status
        response._content = b"invented interval"
        return response

    monkeypatch.setattr(updater.requests, "get", get)
    start, end = date(2026, 9, 25), date(2026, 9, 28)
    if status in {301, 500}:
        with pytest.raises((ArtifactError, requests.HTTPError)):
            updater._fetch_diff(start, end)
    else:
        assert updater._fetch_diff(start, end) == (None if status == 404 else b"invented interval")
    assert calls == [
        (
            f"{updater.BASE_URL}/superghcnd_diff_20260925_to_20260928.tar.gz",
            {"timeout": 120, "allow_redirects": False},
        )
    ]


@pytest.mark.parametrize("length", [-1, 0, 32])
def test_transport_invalid_interval_never_requests_source(monkeypatch, length):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **kw: pytest.fail("unexpected request"))
    with pytest.raises(ArtifactError, match="invalid_threshold_diff_interval"):
        updater._fetch_diff(date(2026, 9, 25), date(2026, 9, 25) + timedelta(days=length))


def test_weekly_workflow_lookback_covers_prior_lagged_checkpoint(baseline, monkeypatch):
    # Seven days since the previous run, whose four-day lag left Sept23 as its cutoff.
    set_watermark(baseline, "2026-09-23")
    calls = fake_source(monkeypatch)
    assert updater.main(["--db", str(baseline)]) == 0
    assert calls[0] == (date(2026, 9, 23), date(2026, 9, 24))
    assert read_watermark(baseline) == "2026-09-30"
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1] / ".github/workflows/refresh-thresholds.yml"
        ).read_text()
    )
    # PyYAML's YAML1.1 parser reads the workflow's 'on' key as True.
    assert workflow[True]["workflow_dispatch"]["inputs"]["days"]["default"] == "12"
    steps = workflow["jobs"]["refresh"]["steps"]
    for needle in (" require-lineage ", "scripts.update_thresholds_incremental"):
        step = next(s for s in steps if needle in s.get("run", ""))
        assert step["env"]["THRESHOLD_DAYS"] == "${{ github.event.inputs.days || '12' }}"


@pytest.mark.parametrize("kind", ["update", "delete", "new_station"])
@pytest.mark.parametrize("resumable", [False, True])
def test_full_station_archive_stops_at_connected_watermark(baseline, monkeypatch, tmp_path, kind, resumable):
    from tests.test_ghcn_time_integrity import dly
    from hashlib import sha256

    station_id = "TESTST00001"
    with open_db(baseline) as conn:
        conn.execute("INSERT INTO stations(station_id,lat,lon,is_active) VALUES(?,0,0,1)", (station_id,))
        conn.commit()
    through = date(2026, 9, 29)
    fake_source(monkeypatch, [record("insert" if kind == "new_station" else kind, station_id)],
                missing=through + timedelta(days=1))
    archive = dly([
        (through, "TMAX", 350, "", "T"),
        (through, "TMIN", 20, "", "T"),
        (through + timedelta(days=1), "TMAX", 499, "", "T"),
        (through + timedelta(days=1), "TMIN", -200, "", "T"),
        (through - timedelta(days=1), "TMAX", 490, "X", "T"),
    ], station_id)

    def get(url, **_kwargs):
        assert url == updater.STATION_DLY_URL.format(station_id=station_id)
        response = requests.Response()
        response.status_code = 200
        response._content = archive
        return response

    monkeypatch.setattr(updater.requests, "get", get)
    argv = ["--db", str(baseline)]
    if resumable:
        argv.extend(["--resume-dir", str(tmp_path / "checkpoint")])
    assert updater.main(argv) == 0
    assert read_watermark(baseline) == through.isoformat()
    with open_db(baseline) as conn:
        threshold = load_thresholds(conn, station_id)
    assert threshold.all_time_max_c == 35
    assert threshold.all_time_min_c == 2
    assert threshold.provenance["source_payload_sha256"] == sha256(archive).hexdigest()


def test_full_station_archive_refuses_another_station(monkeypatch):
    from tests.test_ghcn_time_integrity import dly

    through = date(2026, 9, 29)
    response = requests.Response()
    response.status_code = 200
    response._content = dly([(through, "TMAX", 350, "", "T")], "TESTST00002")
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(ArtifactError, match="threshold_station_archive_identity_mismatch"):
        updater._fetch_station_thresholds("TESTST00001", through=through)


@pytest.mark.parametrize("fail", [False, True])
def test_full_station_prefetch_is_bounded_ordered_and_joined(monkeypatch, fail):
    from threading import Barrier, Lock

    station_ids = {f"S{index:02}" for index in range(8)}
    through = date(2026, 9, 29)
    first_window = Barrier(4, timeout=5)
    lock = Lock()
    calls = []
    active = peak = 0

    def fetch(station_id, *, through):
        nonlocal active, peak
        assert through == date(2026, 9, 29)
        with lock:
            calls.append(station_id)
            active += 1
            peak = max(peak, active)
        try:
            if station_id in {"S00", "S01", "S02", "S03"}:
                first_window.wait()
            if fail and station_id == "S00":
                raise requests.RequestException("invented source failure")
            return StationThresholds(station_id, all_time_max_c=25)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(updater, "_fetch_station_thresholds", fetch)
    with closing(updater._recompute_stations(station_ids, through=through)) as results:
        if fail:
            with pytest.raises(requests.RequestException, match="invented source failure"):
                list(results)
        else:
            assert [row.station_id for row in results] == sorted(station_ids)
    assert peak == 4 and active == 0
    assert sorted(calls) == (sorted(station_ids)[:4] if fail else sorted(station_ids))
