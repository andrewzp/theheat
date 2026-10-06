"""Invented offline GHCN-shaped sources. No real weather records or provider calls."""
from dataclasses import replace
from datetime import date, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts import ingest_ghcn_snapshot as importer
from scripts.threshold_artifacts import ArtifactError, database_stats

ONE = "ZZ000000001"
TWO = "ZZ000000002"
LIMITS = importer.Limits(1024**2, 1024**2, 10000, 10000, 1024**2)


def row(sid=ONE, day="20010401", element="TMAX", value="250", m="", q="", s="A", time="0700"):
    return f"{sid},{day},{element},{value},{m},{q},{s},{time}\n"


def fixture(tmp_path, text=None, *, compressed=None, update=None):
    archive, receipt, output = (tmp_path / name for name in ("source.csv.gz", "receipt.json", "candidate.sqlite"))
    data = compressed if compressed is not None else gzip.compress((text or row()).encode("ascii"), mtime=0)
    archive.write_bytes(data)
    meta = {
        "schema_version": 1, "source_kind": importer.SOURCE_KIND,
        "url": importer.BASE_URL + "superghcnd_full_20010405.csv.gz",
        "snapshot_date": "2001-04-05", "retrieved_at": "2001-04-06T02:00:00Z",
        "http_status": 200, "compressed_sha256": hashlib.sha256(data).hexdigest(),
        "compressed_bytes": len(data),
    }
    meta.update(update or {})
    receipt.write_text(json.dumps(meta))
    return archive, receipt, output


def run(paths, *, station_ids=None, limits=LIMITS):
    return importer.ingest(*paths, station_ids=station_ids or [ONE], limits=limits)


def blocked(paths, label, **kwargs):
    original = paths[0].read_bytes()
    with pytest.raises(importer.SnapshotError, match=f"^{label}$"):
        run(paths, **kwargs)
    assert not os.path.lexists(paths[2])
    assert not list(paths[2].parent.glob(".ghcn-snapshot-*"))
    assert paths[0].read_bytes() == original


def test_raw_candidate_preserves_unsorted_flags_missing_values_and_raw_time(tmp_path):
    paths = fixture(tmp_path, row(TWO, "20010404", value="-9999", m=" ", q="X", time="9999")
                    + row(ONE, "20010403", element="TMIN", value="-120", time="2400")
                    + row(ONE, "20010401", q=" ", time="")
                    + row(ONE, element="PRCP", value="100")
                    + row("ZZ000000003"))
    receipt = run(paths, station_ids=[TWO, ONE])
    assert receipt["counts"] == {
        "rows": 5, "selected_rows": 3, "expanded_bytes": len(gzip.decompress(paths[0].read_bytes())),
        "missing_rows": 1, "flagged_rows": 1,
    }
    assert receipt["station_ids"] == [ONE, TWO]
    assert receipt["production_threshold_asset"] is False
    assert receipt["scientific_qualification"] == "not_evaluated"
    assert "not_independently_attested" in receipt["source_authenticity"]
    assert receipt["candidate_sha256"] == hashlib.sha256(paths[2].read_bytes()).hexdigest()
    assert receipt["candidate_bytes"] == paths[2].stat().st_size
    assert paths[2].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(paths[2]) as conn:
        rows = conn.execute("SELECT * FROM snapshot_observations ORDER BY station_id,observation_date").fetchall()
        assert rows == [
            (ONE, "2001-04-01", "TMAX", 250, "", " ", "A", ""),
            (ONE, "2001-04-03", "TMIN", -120, "", "", "A", "2400"),
            (TWO, "2001-04-04", "TMAX", -9999, " ", "X", "A", "9999"),
        ]
        saved = json.loads(conn.execute("SELECT value FROM snapshot_metadata WHERE key='completed_receipt'").fetchone()[0])
        assert saved == {k: v for k, v in receipt.items() if k not in {"candidate_sha256", "candidate_bytes"}}
        assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    # New staging schema cannot accidentally pass as the production baseline.
    with pytest.raises(ArtifactError, match="threshold_database_invalid"):
        database_stats(paths[2])


@pytest.mark.parametrize("update", [
    {"schema_version": True}, {"schema_version": 2}, {"extra": 1},
    {"source_kind": "ghcnd_all.tar.gz"}, {"http_status": True}, {"http_status": 206},
    {"compressed_sha256": "A" * 64}, {"compressed_sha256": None},
    {"compressed_bytes": True}, {"compressed_bytes": 0}, {"compressed_bytes": 1.0},
    {"snapshot_date": "20010405"}, {"snapshot_date": "2001-02-30"},
    {"snapshot_date": "2001-04-04"}, {"snapshot_date": None},
    {"retrieved_at": "2001-04-06"}, {"retrieved_at": "2001-04-04T23:59:00Z"},
    {"retrieved_at": "2001-04-05T00:00:00+01:00"},
    {"url": importer.BASE_URL + "superghcnd_full_20010405.csv.gz?other=1"},
    {"url": importer.BASE_URL.replace("https", "http") + "superghcnd_full_20010405.csv.gz"},
], ids=["bool-version", "version", "unknown-key", "legacy", "bool-status", "partial-transfer",
        "uppercase-hash", "null-hash", "bool-size", "zero-size", "float-size", "compact-date",
        "invalid-date", "wrong-date", "null-date", "naive-time", "early-time", "utc-before-date",
        "query-url", "insecure-url"])
def test_invalid_receipt_never_creates_candidate(tmp_path, update):
    blocked(fixture(tmp_path, update=update), "snapshot_invalid_receipt")


@pytest.mark.parametrize("raw", ['{}', '[]', '{"schema_version":1,"schema_version":1}',
                                  '{"value":NaN}', '[' * 1500 + ']' * 1500, ' ' * 4097],
                         ids=["missing", "array", "duplicate-key", "nan", "deep", "oversize"])
def test_malformed_receipt_is_sanitized(tmp_path, raw):
    paths = fixture(tmp_path)
    paths[1].write_text(raw)
    blocked(paths, "snapshot_invalid_receipt")


@pytest.mark.parametrize("change", ["hash", "size"])
def test_wrong_archive_identity_precedes_candidate_writes(tmp_path, monkeypatch, change):
    paths = fixture(tmp_path, update={"compressed_sha256": "0" * 64} if change == "hash" else {"compressed_bytes": 1})
    monkeypatch.setattr(importer.tempfile, "TemporaryDirectory", lambda **kw: pytest.fail("created staging before identity verification"))
    blocked(paths, "snapshot_digest_mismatch")


@pytest.mark.parametrize("kind", ["truncated", "crc", "trailing", "not-gzip", "empty"])
def test_invalid_gzip_never_promotes_candidate(tmp_path, kind):
    data = gzip.compress(row().encode(), mtime=0)
    if kind == "truncated":
        data = data[:-5]
    elif kind == "crc":
        data = data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]
    elif kind == "trailing":
        data += b"unexpected trailing bytes"
    elif kind == "not-gzip":
        data = row().encode()
    else:
        data = b""
    paths = fixture(tmp_path, compressed=data)
    blocked(paths, "snapshot_invalid_receipt" if kind == "empty" else "snapshot_invalid_gzip")


def test_concatenated_gzip_members_are_all_checked(tmp_path):
    data = gzip.compress(row(day="20010402").encode(), mtime=0) + gzip.compress(row().encode(), mtime=0)
    result = run(fixture(tmp_path, compressed=data))
    assert result["counts"]["selected_rows"] == 2


@pytest.mark.parametrize("bad", [
    row(day="20010230"), row(sid="bad-id"), row(element="LONGER"), row(value="nan"),
    row(value="1.5"), row(q="AB"), row(time="7:00"), row(time="x700"),
    "\n", row().rstrip(",\n").rsplit(",", 1)[0] + "\n", row().replace("250", '"250'),
    row(sid=TWO, value="bad"), row(element="PRCP", value="bad"),
], ids=["bad-date", "bad-id", "bad-element", "nan", "fraction", "long-flag", "colon-time",
        "non-digit-time", "blank", "missing-field", "bad-quote", "unselected-station", "unselected-element"])
def test_late_invalid_rows_in_any_scope_fail(tmp_path, bad):
    blocked(fixture(tmp_path, row() + bad), "snapshot_invalid_row")


def test_non_ascii_row_is_not_lossily_decoded(tmp_path):
    paths = fixture(tmp_path, compressed=gzip.compress(row().encode() + b"\xff\n"))
    blocked(paths, "snapshot_invalid_row")


def test_oversized_line_is_bounded(tmp_path):
    blocked(fixture(tmp_path, row() + "x" * 257), "snapshot_line_limit")


def test_future_source_calendar_date_is_not_silently_accepted(tmp_path):
    blocked(fixture(tmp_path, row(day="20010406")), "snapshot_future_observation")


@pytest.mark.parametrize("value", ["250", "251"])
def test_identical_and_conflicting_duplicate_keys_both_fail(tmp_path, value):
    blocked(fixture(tmp_path, row() + row(value=value)), "snapshot_duplicate_observation")


@pytest.mark.parametrize("text", [row(element="PRCP"), row(TWO), ""], ids=["no-temperature", "other-station", "empty-source"])
def test_missing_requested_station_is_incomplete(tmp_path, text):
    paths = fixture(tmp_path, compressed=gzip.compress(text.encode()))
    blocked(paths, "snapshot_station_scope_incomplete")


def test_only_missing_and_flagged_rows_do_not_become_a_scientific_pass(tmp_path):
    result = run(fixture(tmp_path, row(value="-9999", q="X")))
    assert result["counts"]["missing_rows"] == result["counts"]["flagged_rows"] == 1
    assert result["scientific_qualification"] == "not_evaluated"


@pytest.mark.parametrize("field,limit,label", [
    ("compressed_bytes", 1, "snapshot_compressed_limit"),
    ("expanded_bytes", 1, "snapshot_expanded_limit"),
    ("rows", 1, "snapshot_row_limit"),
    ("selected_rows", 1, "snapshot_selected_limit"),
])
def test_resource_limits_are_enforced_before_output(tmp_path, field, limit, label):
    limits = replace(LIMITS, **{field: limit, **({"selected_rows": 1} if field == "rows" else {})})
    blocked(fixture(tmp_path, row() + row(day="20010402")), label, limits=limits)


def test_nonselected_rows_count_toward_limit(tmp_path):
    paths = fixture(tmp_path, row() + row(TWO))
    blocked(paths, "snapshot_row_limit", limits=replace(LIMITS, rows=1, selected_rows=1))


def test_sqlite_page_limit_removes_partial_staging(tmp_path):
    start = date(1980, 1, 1)
    text = "".join(row(day=(start + timedelta(days=i)).strftime("%Y%m%d")) for i in range(3000))
    blocked(fixture(tmp_path, text), "snapshot_database_limit", limits=replace(LIMITS, database_bytes=65536))


@pytest.mark.parametrize("limits", [replace(LIMITS, rows=True), replace(LIMITS, selected_rows=0),
    replace(LIMITS, expanded_bytes=1.0), replace(LIMITS, database_bytes=65535),
    replace(LIMITS, compressed_bytes=33 * 1024**3), replace(LIMITS, selected_rows=LIMITS.rows + 1)],
    ids=["bool", "zero", "float", "too-small-db", "oversize", "inverted"])
def test_invalid_limits_are_rejected(tmp_path, limits):
    blocked(fixture(tmp_path), "snapshot_invalid_limits", limits=limits)


@pytest.mark.parametrize("scope", [[ONE, ONE], ["short"], [True], [ONE.lower()], "ZZ000000001"],
                         ids=["duplicate", "invalid", "bool", "lowercase", "not-list"])
def test_invalid_station_scope_is_rejected(tmp_path, scope):
    blocked(fixture(tmp_path), "snapshot_invalid_station_scope", station_ids=scope)


def test_empty_station_scope_is_rejected(tmp_path):
    paths = fixture(tmp_path)
    with pytest.raises(importer.SnapshotError, match="snapshot_invalid_station_scope"):
        importer.ingest(*paths, station_ids=[], limits=LIMITS)
    assert not paths[2].exists()


def test_archive_directory_is_not_a_regular_file(tmp_path):
    paths = list(fixture(tmp_path))
    paths[0] = tmp_path
    with pytest.raises(importer.SnapshotError, match="snapshot_input_not_regular"):
        run(paths)
    assert not paths[2].exists()


def test_legacy_tar_gzip_cannot_be_relabelled_as_csv(tmp_path):
    import io
    import tarfile
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        member = tarfile.TarInfo("ghcnd_all/ZZ000000001.dly")
        raw = b"invented fixed-width legacy sample\n"
        member.size = len(raw)
        archive.addfile(member, io.BytesIO(raw))
    paths = fixture(tmp_path, compressed=payload.getvalue())
    with pytest.raises(importer.SnapshotError, match="snapshot_(line_limit|invalid_row)"):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize("which", [0, 1], ids=["archive", "receipt"])
def test_symlink_input_cannot_alias_another_file(tmp_path, which):
    paths = list(fixture(tmp_path))
    link = tmp_path / "alias"
    link.symlink_to(paths[which])
    paths[which] = link
    blocked(paths, "snapshot_io_failed")


def test_fifo_is_rejected_without_blocking(tmp_path):
    paths = list(fixture(tmp_path))
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    paths[0] = fifo
    with pytest.raises(importer.SnapshotError, match="snapshot_input_not_regular"):
        run(paths)
    assert not paths[2].exists()


@pytest.mark.parametrize("kind", ["file", "dangling-symlink"])
def test_existing_output_is_never_replaced(tmp_path, kind):
    paths = fixture(tmp_path)
    if kind == "file":
        paths[2].write_bytes(b"preserve existing baseline")
    else:
        paths[2].symlink_to(tmp_path / "missing")
    with pytest.raises(importer.SnapshotError, match="snapshot_output_exists"):
        run(paths)
    if kind == "file":
        assert paths[2].read_bytes() == b"preserve existing baseline"
    else:
        assert paths[2].is_symlink()


def test_racing_output_creation_does_not_clobber(tmp_path, monkeypatch):
    paths = fixture(tmp_path)
    link = os.link

    def race(source, destination):
        destination.write_bytes(b"another completed candidate")
        link(source, destination)

    monkeypatch.setattr(importer.os, "link", race)
    with pytest.raises(importer.SnapshotError, match="snapshot_output_exists"):
        run(paths)
    assert paths[2].read_bytes() == b"another completed candidate"
    assert not list(tmp_path.glob(".ghcn-snapshot-*"))


@pytest.mark.parametrize("phase", ["before-decode", "after-decode"])
def test_source_changes_between_hashing_and_promotion_are_rejected(tmp_path, monkeypatch, phase):
    paths = fixture(tmp_path)
    candidate = importer._candidate

    def mutate(*args):
        if phase == "after-decode":
            report = candidate(*args)
        paths[0].write_bytes(gzip.compress(row(value="251").encode(), mtime=0))
        if phase == "before-decode":
            return candidate(*args)
        return report

    monkeypatch.setattr(importer, "_candidate", mutate)
    with pytest.raises(importer.SnapshotError, match="snapshot_source_changed"):
        run(paths)
    assert not paths[2].exists()
    assert not list(tmp_path.glob(".ghcn-snapshot-*"))


def test_interruption_after_staging_a_row_leaves_no_final_candidate(tmp_path, monkeypatch):
    paths = fixture(tmp_path, row() + row(day="20010402"))
    original = importer._parse
    calls = 0

    def interrupt(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return original(*args)

    monkeypatch.setattr(importer, "_parse", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(paths)
    assert not paths[2].exists()
    assert not list(tmp_path.glob(".ghcn-snapshot-*"))


def test_late_failure_after_a_committed_staging_chunk_exposes_no_output(tmp_path):
    start = date(1980, 1, 1)
    text = "".join(row(day=(start + timedelta(days=i)).strftime("%Y%m%d")) for i in range(5000))
    blocked(fixture(tmp_path, text + "malformed after staging commit\n"), "snapshot_invalid_row")


def test_lost_promotion_acknowledgement_leaves_complete_file_and_retry_cannot_replace(tmp_path, monkeypatch):
    paths = fixture(tmp_path)
    link = os.link

    def lost_ack(source, destination):
        link(source, destination)
        raise OSError("acknowledgement lost after successful link")

    monkeypatch.setattr(importer.os, "link", lost_ack)
    with pytest.raises(importer.SnapshotError, match="snapshot_io_failed"):
        run(paths)
    before = paths[2].read_bytes()
    with sqlite3.connect(paths[2]) as conn:
        assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        receipt = json.loads(conn.execute("SELECT value FROM snapshot_metadata").fetchone()[0])
        assert receipt["completed"] is True
        assert conn.execute("SELECT COUNT(*) FROM snapshot_observations").fetchone()[0] == 1
    with pytest.raises(importer.SnapshotError, match="snapshot_output_exists"):
        run(paths)
    assert paths[2].read_bytes() == before
    assert not list(tmp_path.glob(".ghcn-snapshot-*"))


def args(paths):
    values = ["--archive", str(paths[0]), "--receipt", str(paths[1]), "--output", str(paths[2]), "--station", ONE]
    for name, value in vars(LIMITS).items():
        values += ["--max-" + name.replace("_", "-"), str(value)]
    return values


def test_real_cli_reports_complete_candidate_and_rejects_repeated_output(tmp_path, capsys):
    paths = fixture(tmp_path)
    assert importer.main(args(paths)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["completed"] is True
    assert result["candidate_sha256"] == hashlib.sha256(paths[2].read_bytes()).hexdigest()
    before = paths[2].read_bytes()
    assert importer.main(args(paths)) == 1
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"status": "blocked", "reason": "snapshot_output_exists"}
    assert paths[2].read_bytes() == before


def test_module_entrypoint_builds_fixture_candidate_in_a_real_process(tmp_path):
    paths = fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.ingest_ghcn_snapshot", *args(paths)],
        cwd=Path(importer.__file__).resolve().parents[1], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["candidate_sha256"] == hashlib.sha256(paths[2].read_bytes()).hexdigest()
    assert receipt["scientific_qualification"] == "not_evaluated"


def test_promotion_error_does_not_expose_private_exception_text(tmp_path, monkeypatch, capsys):
    paths = fixture(tmp_path)

    def failed_link(*args):
        raise OSError("private path and source body")

    monkeypatch.setattr(importer.os, "link", failed_link)
    assert importer.main(args(paths)) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"status": "blocked", "reason": "snapshot_io_failed"}
    assert "private" not in captured.err and not captured.out
    assert not paths[2].exists()
    assert not list(tmp_path.glob(".ghcn-snapshot-*"))
