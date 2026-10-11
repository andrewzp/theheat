"""Invented byte envelopes only; retained private history is never a fixture."""
from dataclasses import replace

import pytest

from src.storage import historical_import as h
from src.storage import postgres_projection as p


def plan(raw=b'{"synthetic":9007199254740993}\n', ident="invented-import"):
    value = h.raw_envelope(raw)
    return h.prepare(ident, [("history.artifacts.v1", value["raw_sha256"], value),
                            ("history.sources.v1", "invented-source", {"sha256": value["raw_sha256"]})])


@pytest.mark.parametrize("raw", [b"", b"\xff\x00", b'{"id":9007199254740993}\n',
    b'{"missing":null,"zero":0,"float":-0.0,"text":"invented"}   ', '☀'.encode()])
def test_original_bytes_not_canonicalized(raw):
    value = h.raw_envelope(raw)
    assert h.original_bytes(p._decode(p._canonical(value))) == raw


@pytest.mark.parametrize("change,code", [
    ({"extra": True}, "invalid_history_envelope"),
    ({"schema_version": True}, "invalid_history_envelope"),
    ({"byte_count": True}, "invalid_history_envelope"),
    ({"byte_count": -1}, "invalid_history_envelope"),
    ({"raw_sha256": "0" * 64}, "history_artifact_mismatch"),
    ({"payload_base64": "====private-data"}, "invalid_history_encoding"),
    ({"payload_base64": "Zg==\n"}, "invalid_history_encoding"),
])
def test_envelope_refuses_corruption_without_private_error_text(change, code):
    value = h.raw_envelope(b"invented-private-value")
    value.update(change)
    with pytest.raises(p.ProjectionError, match=f"^{code}$"):
        h.original_bytes(value)


def test_plan_detaches_and_binds_complete_set():
    rows = [("history.sources.v1", "one", {"untrusted": {"approved": True}})]
    value = h.prepare("import", rows)
    rows[0][2]["untrusted"]["approved"] = False
    assert p._decode(value.records[0][2])["untrusted"]["approved"] is True
    completion = p._decode(value.completion)
    assert completion["publication_authorized"] is False
    assert completion["historical_jobs_runnable"] is False
    assert completion["external_job_coverage"] == "unestablished"
    assert h._validated(value) == value
    with pytest.raises(p.ProjectionError, match="history_plan_mismatch"):
        h._validated(replace(value, completion=value.completion + b" "))


@pytest.mark.parametrize("rows,code", [
    ([], "history_record_bound"),
    ([("command-core-v1", "state", {})], "history_namespace_refused"),
    ([("history.sources.v1", "x", {}), ("history.sources.v1", "x", {})], "duplicate_history_record"),
    ([("history.artifacts.v1", "wrong", h.raw_envelope(b"x"))], "history_artifact_identity_mismatch"),
])
def test_invalid_plans(rows, code):
    with pytest.raises(p.ProjectionError, match=f"^{code}$"):
        h.prepare("invented", rows)


def test_plan_and_envelope_bounds(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(h, "MAX_IMPORT_BYTES", 10)
        with pytest.raises(p.ProjectionError, match="history_import_byte_bound"):
            plan()
    monkeypatch.setattr(p, "MAX_BYTES", 30)
    with pytest.raises(p.ProjectionError, match="projection_byte_bound"):
        h.raw_envelope(b"a" * 30)


def test_hosted_and_preview_refused_without_connection(tmp_path):
    repository = p.PostgresProjectionRepository(socket_directory=tmp_path, database="invented",
                                                user="invented", environment="preview")
    for operation in (h.record_import, h.verify_import):
        with pytest.raises(p.ProjectionError, match="local_history_repository_required"):
            operation(repository, plan())
    repository.environment = "local"
    repository._hosted_config = object()
    with pytest.raises(p.ProjectionError, match="local_history_repository_required"):
        h.record_import(repository, plan())


@pytest.mark.parametrize("case,code", [("count", "history_record_bound"),
    ("aggregate", "history_import_byte_bound"), ("shape", "invalid_history_plan"),
    ("raw_size", "invalid_history_plan"), ("completion", "invalid_history_plan")])
def test_supplied_plan_bounds_checked_before_decode(monkeypatch, case, code):
    value = plan()
    def forbidden(_):
        pytest.fail("unbounded supplied plan reached decoding")
    monkeypatch.setattr(p, "_decode", forbidden)
    if case == "count":
        monkeypatch.setattr(h, "MAX_RECORDS", 1)
    elif case == "aggregate":
        monkeypatch.setattr(h, "MAX_IMPORT_BYTES", 1)
    elif case == "shape":
        value = replace(value, records=(["history.sources.v1", "x", b"{}"],))
    elif case == "completion":
        value = replace(value, completion="untrusted-string")
    else:
        value = replace(value, records=(("history.sources.v1", "x", b"x" * (p.MAX_BYTES + 1)),))
    with pytest.raises(p.ProjectionError, match=f"^{code}$"):
        h._validated(value)
