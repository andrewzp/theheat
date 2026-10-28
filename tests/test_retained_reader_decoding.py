"""Connection/pass-local pure JSON calculations, never retained approval reuse."""
from contextlib import nullcontext
from copy import deepcopy
import json
from threading import Thread

import pytest

from src.storage import postgres_projection as p
from tests.test_delivery_begin_passes import reviewed as reviewed, begin_reviewed, Stop


@pytest.fixture
def calls(monkeypatch):
    trace = []
    original = p._decode_with_canonical
    def counted(raw):
        trace.append(raw)
        return original(raw)
    monkeypatch.setattr(p, "_decode_with_canonical", counted)
    return trace


def raw(value=None):
    return json.dumps(value if value is not None else {"retained": ["invented" * 1000]},
                      separators=(",", ":")).encode()


def test_actual_readers_reduce_decodes_without_changing_sql_roles_or_outputs(reviewed, calls, monkeypatch):
    r = reviewed
    sql_trace = []
    execute = r.sql.execute
    def traced(query, args=()):
        sql_trace.append((query, deepcopy(args)))
        return execute(query, args)
    monkeypatch.setattr(r.sql, "execute", traced)
    with monkeypatch.context() as patch:
        patch.setattr(p, "_reader_decoding_scope", nullcontext)
        with pytest.raises(Stop):
            begin_reviewed(r)
    baseline = dict(sql=deepcopy(sql_trace), calls=deepcopy(r.control["calls"]),
        roles=deepcopy(r.control["roles"]), leases=deepcopy(r.control["leases"]),
        large=sum(len(v) >= 4096 for v in calls), packages=r.sql.package_reads)
    calls.clear()
    sql_trace.clear()
    r.control.update(calls=[], roles=[], leases=[])
    r.sql.package_reads = 0
    with pytest.raises(Stop):
        begin_reviewed(r)
    assert sql_trace == baseline["sql"] and r.control["calls"] == baseline["calls"]
    assert r.control["roles"] == baseline["roles"] and len(baseline["roles"]) == 12
    assert r.control["leases"] == baseline["leases"] and len(baseline["leases"]) == 1
    assert r.sql.package_reads == baseline["packages"] == 6
    assert baseline["large"] == 38
    assert sum(len(v) >= 4096 for v in calls) == 10  # 5 exact payloads per independent pass


def test_fresh_reader_values_are_detached_and_canonical_bytes_identical(calls):
    c, payload = object(), raw()
    expected = p._decode_with_canonical(payload)
    calls.clear()
    with p._reader_decoding_scope(c):
        first = p._reader_decode_with_canonical(c, payload)
        first[0]["retained"][0] = "Changed return"
        second = p._reader_decode_with_canonical(c, payload)
        assert second == expected and second[0] is not expected[0]
        second[0]["retained"].append("Another changed return")
        assert p._reader_decode_with_canonical(c, payload) == expected and len(calls) == 1
    assert p._READER_DECODING.get() is None
    assert p._reader_decode_with_canonical(c, payload) == expected and len(calls) == 2


def test_other_connection_nested_pass_and_later_pass_start_empty(calls):
    first, other, payload = object(), object(), raw()
    with p._reader_decoding_scope(first):
        expected = p._reader_decode_with_canonical(first, payload)
        assert p._reader_decode_with_canonical(other, payload) == expected
        assert p._reader_decode_with_canonical(other, payload) == expected
        assert len(calls) == 3
        with p._reader_decoding_scope(first):
            assert p._reader_decode_with_canonical(first, payload) == expected and len(calls) == 4
        assert p._reader_decode_with_canonical(first, payload) == expected and len(calls) == 4
    with p._reader_decoding_scope(first):
        assert p._reader_decode_with_canonical(first, payload) == expected and len(calls) == 5


@pytest.mark.parametrize("changed", [b'{"n":1,"padding":"' + b'x' * 4096 + b'"}',
    b'{"n":1.0,"padding":"' + b'x' * 4096 + b'"}',
    b'{"n":true,"padding":"' + b'x' * 4096 + b'"}'], ids=["integer", "float", "bool"])
def test_complete_bytes_keep_changed_numeric_types_and_values_distinct(calls, changed):
    c, a = object(), raw()
    with p._reader_decoding_scope(c):
        expected = p._reader_decode_with_canonical(c, a)
        actual = p._reader_decode_with_canonical(c, changed)
        assert actual[0] == json.loads(changed) and len(calls) == 2
        assert type(actual[0]["n"]) is type(json.loads(changed)["n"])
        assert p._reader_decode_with_canonical(c, a) == expected and len(calls) == 2


@pytest.mark.parametrize("invalid", [b'{"a":1,"a":2,"padding":"' + b'x' * 4096 + b'"}',
    b'{"a":NaN,"padding":"' + b'x' * 4096 + b'"}', b'x' * 5000],
    ids=["duplicate", "nonfinite", "malformed"])
def test_no_failure_is_cached_and_original_refusal_is_exact(calls, invalid):
    c = object()
    with pytest.raises(p.ProjectionError) as original:
        p._decode_with_canonical(invalid)
    calls.clear()
    with p._reader_decoding_scope(c):
        for count in (1, 2):
            with pytest.raises(p.ProjectionError) as actual:
                p._reader_decode_with_canonical(c, invalid)
            assert str(actual.value) == str(original.value) and len(calls) == count


@pytest.mark.parametrize("change", ["depth", "bytes", "nodes", "decoder"])
def test_live_calculation_limits_or_implementation_changes_never_reuse_a_result(calls, monkeypatch, change):
    c, payload = object(), raw()
    with p._reader_decoding_scope(c):
        expected = p._reader_decode_with_canonical(c, payload)
        if change == "decoder":
            original = p._canonical_private_decoded
            monkeypatch.setattr(p, "_canonical_private_decoded", lambda value: original(value))
            assert p._reader_decode_with_canonical(c, payload) == expected and len(calls) == 2
        else:
            monkeypatch.setattr(p, {"depth": "MAX_DEPTH", "bytes": "MAX_BYTES", "nodes": "MAX_NODES"}[change], 1)
            with pytest.raises(p.ProjectionError) as original:
                p._decode_with_canonical(payload)
            with pytest.raises(p.ProjectionError) as actual:
                p._reader_decode_with_canonical(c, payload)
            assert str(actual.value) == str(original.value)


def test_entry_and_byte_bounds_fall_back_to_original_calculation(calls):
    c = object()
    with p._reader_decoding_scope(c):
        calculation = p._READER_DECODING.get()
        for i in range(12):
            value = raw({"index": i, "padding": "x" * 150_000})
            assert p._reader_decode_with_canonical(c, value) == p._decode_with_canonical(value)
        assert calculation is not None
        assert len(calculation.entries) <= 8 and calculation.byte_count <= 2_000_000
        assert calculation.entries


def test_exception_close_and_foreign_thread_cannot_inherit_a_decoded_result(calls):
    c, payload, errors = object(), raw(), []
    with pytest.raises(RuntimeError, match="invented stop"):
        with p._reader_decoding_scope(c):
            calculation = p._READER_DECODING.get()
            expected = p._reader_decode_with_canonical(c, payload)
            def other():
                token = p._READER_DECODING.set(calculation)
                try:
                    assert p._reader_decode_with_canonical(c, payload) == expected
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    p._READER_DECODING.reset(token)
            thread = Thread(target=other)
            thread.start()
            thread.join(5)
            assert not thread.is_alive() and not errors and len(calls) == 2
            raise RuntimeError("invented stop")
    assert calculation is not None and not calculation.open and not calculation.entries
    assert p._READER_DECODING.get() is None
    token = p._READER_DECODING.set(calculation)
    try:
        assert p._reader_decode_with_canonical(c, payload) == expected and len(calls) == 3
    finally:
        p._READER_DECODING.reset(token)
