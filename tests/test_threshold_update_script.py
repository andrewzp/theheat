"""Synthetic daily intervals only; no source, provider or release transport calls."""

from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

import pytest
import requests

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


def fake_source(monkeypatch, records=(), missing=None, payload=None):
    calls = []

    def fetch(day):
        calls.append(day)
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

    dates_to_fetch = [
        date(2026, 5, 1),
        date(2026, 5, 2),
        date(2026, 5, 3),
    ]
    successful_dates = [date(2026, 5, 1), date(2026, 5, 3)]

    assert _resolve_new_watermark(
        dates_to_fetch=dates_to_fetch,
        successful_dates=successful_dates,
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 1)


def test_threshold_watermark_advances_when_successes_are_contiguous():
    from scripts.update_thresholds_incremental import _resolve_new_watermark

    assert _resolve_new_watermark(
        dates_to_fetch=[date(2026, 5, 1), date(2026, 5, 2)],
        successful_dates=[date(2026, 5, 1), date(2026, 5, 2)],
        current_watermark=date(2026, 4, 30),
    ) == date(2026, 5, 2)


@pytest.mark.parametrize("prior", [date(2026, 9, 26), date(2026, 9, 27)])
def test_completed_dates_do_not_stall_new_contiguous_success(prior):
    assert updater._resolve_new_watermark(
        dates_to_fetch=[date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)],
        successful_dates=[date(2026, 9, 27), date(2026, 9, 28)],
        current_watermark=prior,
    ) == date(2026, 9, 28)


@pytest.mark.parametrize("prior", [None, date(2026, 9, 24)])
def test_success_dates_cannot_fill_an_unknown_prior_gap(prior):
    assert (
        updater._resolve_new_watermark(
            dates_to_fetch=[date(2026, 9, 26)],
            successful_dates=[date(2026, 9, 26)],
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
def test_missing_or_empty_required_interval_preserves_all_database_bytes(
    baseline, monkeypatch, missing, has_records, empty
):
    calls = fake_source(
        monkeypatch,
        [record()] if has_records else [],
        missing=date(2026, 9, missing),
        payload=b"" if empty else None,
    )
    before = baseline.read_bytes()
    assert updater.main(["--db", str(baseline)]) == 1
    assert calls == [date(2026, 9, d) for d in range(26, missing + 1)]
    assert baseline.read_bytes() == before
    assert read_watermark(baseline) == "2026-09-25"


@pytest.mark.parametrize(
    "watermark", [None, "", "20260925", "2026-02-30", "2026-09-24", "2026-10-01"]
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

    def recompute(station):
        recomputed.append(station)
        return StationThresholds(station, all_time_max_c=25, all_time_max_year=2001)

    monkeypatch.setattr(updater, "_fetch_station_thresholds", recompute)
    assert updater.main(["--db", str(baseline)]) == 0
    assert calls == [date(2026, 9, d) for d in (28, 29, 30)]
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

    def broken(station):
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

    def recompute(station):
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
