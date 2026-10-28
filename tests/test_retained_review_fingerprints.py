"""Pure digest identities inside one retained read; no approval reuse or timing."""
from contextlib import nullcontext
from copy import deepcopy
import json
from threading import Thread

import pytest

from src.editorial import revisions as r
from src.storage import postgres_projection as p
from tests.test_delivery_begin_passes import reviewed as reviewed, begin_reviewed, Stop
from tests.test_projection_decoding import StoredRows


@pytest.fixture
def calls(monkeypatch):
    found = []
    original = r._fingerprint_value
    def counted(value):
        found.append(1)
        return original(value)
    monkeypatch.setattr(r, "_fingerprint_value", counted)
    return found


def value():
    return {"input_binding": {"invented": ["unchanged" * 700]}, "number": 1, "nested": {"n": -0.0}}


def test_actual_retained_readers_keep_every_sql_role_and_proof_with_fewer_digest_calculations(reviewed, calls, monkeypatch):
    sql, trace = reviewed.sql.execute, []
    def traced(query, args=()):
        trace.append((query, deepcopy(args)))
        return sql(query, args)
    monkeypatch.setattr(reviewed.sql, "execute", traced)
    with monkeypatch.context() as patch:
        patch.setattr(r, "_retained_fingerprint_scope", nullcontext)
        with pytest.raises(Stop):
            begin_reviewed(reviewed)
    baseline = dict(trace=deepcopy(trace), roles=deepcopy(reviewed.control["roles"]),
        calls=deepcopy(reviewed.control["calls"]), leases=deepcopy(reviewed.control["leases"]),
        calculations=len(calls))
    trace.clear()
    calls.clear()
    reviewed.control.update(roles=[], calls=[], leases=[])
    with pytest.raises(Stop):
        begin_reviewed(reviewed)
    assert trace == baseline["trace"] and reviewed.control["roles"] == baseline["roles"]
    assert len(baseline["roles"]) == 12
    assert reviewed.control["calls"] == baseline["calls"] and reviewed.control["leases"] == baseline["leases"]
    assert baseline["calculations"] - len(calls) >= 12


def test_exact_original_digest_and_no_cross_read_inheritance(calls):
    data = value()
    expected = r._fingerprint_value(data)
    calls.clear()
    with r._retained_fingerprint_scope():
        assert r.fingerprint(data) == r.fingerprint(deepcopy(data)) == expected and len(calls) == 1
    with r._retained_fingerprint_scope():
        assert r.fingerprint(data) == expected and len(calls) == 2
    assert r.fingerprint(data) == expected and len(calls) == 3


@pytest.mark.parametrize("number", [1.0, True, -0.0], ids=["float", "bool", "negative-zero"])
def test_mutations_and_numeric_types_keep_complete_exact_keys(calls, number):
    data = value()
    with r._retained_fingerprint_scope():
        original = r.fingerprint(data)
        data["number"] = number
        expected = r._fingerprint_value(data)
        assert r.fingerprint(data) == expected and len(calls) == 3
        data["number"] = 1
        assert r.fingerprint(data) == original and len(calls) == 3


@pytest.mark.parametrize("bad", [float("nan"), {"unsupported"}, (1, 2), object()],
    ids=["nonfinite", "set", "tuple", "object"])
def test_original_failures_are_not_replaced_or_cached(calls, bad):
    data = dict(value(), bad=bad)
    with pytest.raises((ValueError, TypeError)) as expected:
        r._fingerprint_value(data)
    calls.clear()
    with r._retained_fingerprint_scope():
        for count in (1, 2):
            with pytest.raises(type(expected.value)) as actual:
                r.fingerprint(data)
            assert str(actual.value) == str(expected.value) and len(calls) == count


def test_function_change_input_change_during_calculation_and_nested_scope(calls, monkeypatch):
    data = value()
    with r._retained_fingerprint_scope():
        expected = r.fingerprint(data)
        original = r._canonical
        monkeypatch.setattr(r, "_canonical", lambda obj: original(obj))
        assert r.fingerprint(data) == expected and len(calls) == 2
        with r._retained_fingerprint_scope():
            assert r.fingerprint(data) == expected and len(calls) == 3
        assert r.fingerprint(data) == expected and len(calls) == 3
    original_value = r._fingerprint_value
    def mutate(obj):
        result = original_value(obj)
        obj["new"] = True
        return result
    monkeypatch.setattr(r, "_fingerprint_value", mutate)
    with r._retained_fingerprint_scope():
        r.fingerprint(data)
        calculation = r._RETAINED_FINGERPRINTS.get()
        assert calculation is not None and not calculation.entries


def test_foreign_thread_closed_scope_and_exception_cleanup(calls):
    data, errors = value(), []
    with pytest.raises(RuntimeError, match="invented stop"):
        with r._retained_fingerprint_scope():
            calculation = r._RETAINED_FINGERPRINTS.get()
            expected = r.fingerprint(data)
            def other():
                token = r._RETAINED_FINGERPRINTS.set(calculation)
                try:
                    assert r.fingerprint(data) == expected
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    r._RETAINED_FINGERPRINTS.reset(token)
            thread = Thread(target=other)
            thread.start()
            thread.join(5)
            assert not thread.is_alive() and not errors and len(calls) == 2
            raise RuntimeError("invented stop")
    assert calculation is not None and not calculation.open and not calculation.entries
    assert r._RETAINED_FINGERPRINTS.get() is None
    token = r._RETAINED_FINGERPRINTS.set(calculation)
    try:
        assert r.fingerprint(data) == expected and len(calls) == 3
    finally:
        r._RETAINED_FINGERPRINTS.reset(token)


def test_entry_byte_and_type_bounds_keep_original_fallback(calls):
    with r._retained_fingerprint_scope():
        for i in range(20):
            data = {"index": i, "input_binding": {"padding": "x" * 150000}}
            assert r.fingerprint(data) == r._fingerprint_value(data)
        calculation = r._RETAINED_FINGERPRINTS.get()
        assert calculation is not None and len(calculation.entries) <= 16 and calculation.byte_count <= 2000000
        class Custom(dict):
            pass
        assert r._fingerprint_key(Custom(value())) is None
        assert r._fingerprint_key({1: "x" * 5000}) is None
        assert r._fingerprint_key({"small": 1}) is None
        assert r._fingerprint_key({"large": "x" * 1000001}) is None


@pytest.mark.parametrize("limit", ["depth", "nodes"])
def test_private_reconstructed_projection_retains_whole_tree_bounds(monkeypatch, limit):
    fields = [(b'"a"', b"[0,0]"), (b'"b"', b"[0,0]")]
    first, second = StoredRows(fields), StoredRows(fields)
    monkeypatch.setattr(p, "MAX_DEPTH" if limit == "depth" else "MAX_NODES", 1 if limit == "depth" else 4)
    with pytest.raises(p.ProjectionError) as old:
        p.PostgresProjectionRepository._read(first, "invented", "tree")
    with p._reader_decoding_scope(second):
        with pytest.raises(p.ProjectionError) as actual:
            p.PostgresProjectionRepository._read(second, "invented", "tree")
    assert str(actual.value) == str(old.value) == "projection_structure_bound"
    assert first.queries == second.queries


def test_reconstructed_private_tree_keeps_bytes_without_another_copy(monkeypatch):
    state = {"a": {"large": "x" * 5000}, "b": {"large": "x" * 5000}}
    fields = [(p._canonical(k), p._canonical(v)) for k, v in state.items()]
    connection = StoredRows(fields)
    expected = p._canonical(state)
    def forbidden(value):
        raise AssertionError("Fresh private restored containers must not be cloned again")
    with p._reader_decoding_scope(connection):
        monkeypatch.setattr(p, "_bounded_snapshot", forbidden)
        receipt, restored = p.PostgresProjectionRepository._read(connection, "invented", "private")
    assert receipt.canonical_sha256 == p._sha(expected) and restored == state
    restored["a"]["large"] = "Changed return"
    assert restored["b"] == state["b"]
