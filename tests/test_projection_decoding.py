"""Fresh decode identities and refusal order using invented stored rows only."""
from datetime import UTC, datetime
import json
import math

import pytest

from src.storage import postgres_projection as p


@pytest.mark.parametrize(("raw", "expected"), [
    (b"null", None), (b"true", True), (b"false", False), (b"0", 0),
    (b"-0", 0), (b"-0.0", -0.0), (b"1", 1), (b"1.0", 1.0),
    (b"1e0", 1.0), (b"5e-324", 5e-324),
    (b"9007199254740991", p.MAX_INTEGER),
    (b'"\\u00e9\\ud83c\\udf21\\n\\u0000"', "é🌡\n\x00"),
    (b'{ "z": [false, -0.0], "a": {} }', {"z": [False, -0.0], "a": {}}),
    (b"[]", []), (b"{}", {}),
])
def test_decode_returns_exact_numeric_types_and_canonical_bytes(raw, expected):
    value, canonical = p._decode_with_canonical(raw)
    assert type(value) is type(expected) and value == expected
    assert canonical == json.dumps(expected, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode()
    original_api = p._decode(raw)
    assert type(original_api) is type(expected) and original_api == expected
    if type(expected) is float and expected == 0:
        assert math.copysign(1, value) == math.copysign(1, original_api) == -1


@pytest.mark.parametrize(("raw", "code"), [
    (bytearray(b"{}"), "invalid_payload_bytes"),
    (memoryview(b"{}"), "invalid_payload_bytes"),
    ("{}", "invalid_payload_bytes"), (None, "invalid_payload_bytes"),
    (b"", "invalid_stored_json"), (b"\xff", "invalid_stored_json"),
    (b"{", "invalid_stored_json"), (b"{} {}", "invalid_stored_json"),
    (b'{"a":0,"a":1}', "invalid_stored_json"),
    (b"NaN", "invalid_stored_json"), (b"Infinity", "invalid_stored_json"),
    (b"-Infinity", "invalid_stored_json"), (b"1e999", "invalid_stored_json"),
    (b"9007199254740992", "invalid_stored_json"),
    (b'"\\ud800"', "invalid_stored_json"),
    (b'"\\udfff"', "invalid_stored_json"),
    (b'{"\\ud800":1}', "invalid_stored_json"),
])
def test_decode_preserves_original_error_boundary(raw, code):
    for decode in (p._decode, p._decode_with_canonical):
        with pytest.raises(p.ProjectionError) as caught:
            decode(raw)
        assert type(caught.value) is p.ProjectionError and str(caught.value) == code
        if code == "invalid_stored_json":
            assert caught.value.__suppress_context__ is True


def test_decode_preserves_size_depth_node_and_string_bounds(monkeypatch):
    for decode in (p._decode, p._decode_with_canonical):
        with monkeypatch.context() as patch:
            patch.setattr(p, "MAX_BYTES", 8)
            with pytest.raises(p.ProjectionError, match="^invalid_payload_bytes$"):
                decode(b'"1234567"')
            assert p._decode(b'"123456"') == "123456"
        with monkeypatch.context() as patch:
            patch.setattr(p, "MAX_DEPTH", 2)
            assert p._decode(b"[[0]]") == [[0]]
            with pytest.raises(p.ProjectionError, match="^invalid_stored_json$"):
                decode(b"[[[0]]]")
        with monkeypatch.context() as patch:
            patch.setattr(p, "MAX_NODES", 3)
            assert p._decode(b"[0,0]") == [0, 0]
            with pytest.raises(p.ProjectionError, match="^invalid_stored_json$"):
                decode(b"[0,0,0]")


class StoredRows:
    """Only scripted SELECT responses; no PostgreSQL or provider execution."""

    def __init__(self, fields, *, restored=None, final_sha=None):
        self.fields = fields
        self.queries = []
        self.values = {p._sha(value): value for _, value in fields}
        size = 2 + sum(len(name) + 1 + len(value) for name, value in fields) + max(0, len(fields) - 1)
        if restored is None:
            restored = {json.loads(name): json.loads(value) for name, value in fields}
        self.row = (final_sha or p._sha(p._canonical(restored)), size, len(fields), datetime(2026, 1, 1, tzinfo=UTC))
        self.refs = [(name, p._sha(value), len(value)) for name, value in fields]
        self.payloads = list(self.values.items())

    def execute(self, sql, parameters):
        self.queries.append((sql, parameters))
        assert len(self.queries) <= 3
        owner = self
        index = len(self.queries)
        class Cursor:
            def fetchone(self):
                assert index == 1
                return owner.row
            def fetchall(self):
                return owner.refs if index == 2 else owner.payloads
        return Cursor()


@pytest.mark.parametrize("count", [0, 1, 18, 512])
def test_real_reader_uses_one_canonicalization_per_decoded_field_part(monkeypatch, count):
    state = {f"field-{index}": {"invented": [None, -0.0, 1.0, "é🌡"]} for index in range(count)}
    fields = [(p._canonical(name), p._canonical(value)) for name, value in state.items()]
    connection = StoredRows(fields, restored=state)
    original = p._canonical
    private = p._canonical_private_decoded
    snapshot = p._bounded_snapshot
    check = p._check_structure
    loads = p.json.loads
    calls = []
    private_calls = []
    snapshots = []
    checks = []
    parses = []
    def counted(value):
        calls.append(value)
        return original(value)
    def counted_private(value):
        private_calls.append(value)
        return private(value)
    def counted_snapshot(value):
        snapshots.append(value)
        return snapshot(value)
    def counted_check(value, **kwargs):
        checks.append(kwargs)
        return check(value, **kwargs)
    def counted_loads(*args, **kwargs):
        value = loads(*args, **kwargs)
        parses.append(value)
        return value
    with monkeypatch.context() as patch:
        patch.setattr(p, "_canonical", counted)
        patch.setattr(p, "_canonical_private_decoded", counted_private)
        patch.setattr(p, "_bounded_snapshot", counted_snapshot)
        patch.setattr(p, "_check_structure", counted_check)
        patch.setattr(p.json, "loads", counted_loads)
        receipt, actual = p.PostgresProjectionRepository._read(connection, "invented", "read")
    # Every name/value is still independently parsed and validated. Only the
    # final caller-owned reconstruction uses the general serializer/snapshot.
    assert len(calls) == len(snapshots) == 1
    assert len(private_calls) == len(parses) == 2 * count
    assert all(value is parsed for value, parsed in zip(private_calls, parses, strict=True))
    assert checks == [{"_with_bound": True}] * (2 * count) + [{}]
    assert len(connection.queries) == (3 if count else 2)
    assert receipt.field_count == count and original(actual) == original(state)
    if count > 1:
        actual["field-0"]["invented"].append("changed")
        assert actual["field-1"] == state["field-1"]


def test_private_decode_encodes_its_fresh_tree_without_snapshot(monkeypatch):
    encode = json.JSONEncoder.encode
    check = p._check_structure
    seen = []
    checks = []

    def observe_encode(encoder, value):
        seen.append(value)
        return encode(encoder, value)

    def observe_check(value, **kwargs):
        checks.append((value, kwargs))
        return check(value, **kwargs)

    def forbidden_snapshot(value):
        raise AssertionError("A fresh private parse must not be cloned")

    monkeypatch.setattr(json.JSONEncoder, "encode", observe_encode)
    monkeypatch.setattr(p, "_check_structure", observe_check)
    monkeypatch.setattr(p, "_bounded_snapshot", forbidden_snapshot)
    raw = b'{"a":[{"x":1}],"b":[{"x":1}]}'
    first, canonical = p._decode_with_canonical(raw)
    second, again = p._decode_with_canonical(raw)
    assert canonical == again == raw
    assert seen[0] is first and seen[1] is second and first is not second
    assert checks == [(first, {"_with_bound": True}), (second, {"_with_bound": True})]
    assert first["a"] is not first["b"] and first["a"] is not second["a"]
    first["a"][0]["x"] = 2
    assert first["b"][0]["x"] == second["a"][0]["x"] == 1


def test_private_decode_loose_bound_keeps_incremental_path(monkeypatch):
    monkeypatch.setattr(p, "MAX_BYTES", 64)
    def forbidden(*args, **kwargs):
        raise AssertionError("A loose bound must not reach the whole encoder")
    monkeypatch.setattr(json.JSONEncoder, "encode", forbidden)
    monkeypatch.setattr(p, "_bounded_snapshot", forbidden)
    assert p._decode_with_canonical(b'"' + b"x" * 20 + b'"') == ("x" * 20, b'"' + b"x" * 20 + b'"')
    # Valid short wire spellings can expand beyond the unchanged output cap.
    with pytest.raises(p.ProjectionError, match="^invalid_stored_json$") as caught:
        p._decode(b"[1e9,1e9,1e9,1e9,1e9,1e9]")
    assert str(caught.value.__context__) == "projection_byte_bound"


@pytest.mark.parametrize(("raw", "inner"), [
    (b'{"a":[1e9,1e9,1e9,1e9,1e9,1e9],"z":"\\ud800"}', "projection_byte_bound"),
    (b'{"a":"\\ud800","z":[1e9,1e9,1e9,1e9,1e9,1e9]}', "invalid_json"),
    (b'{"a":1e999,"z":"xxxxxxxxxxxxxxxxxxxx"}', "nonfinite_json_number"),
    (b'{"a":9007199254740992,"z":"xxxxxxxxxxxxxxxxxxxx"}', "unsafe_json_integer"),
])
def test_private_decode_completes_validation_and_preserves_encoding_precedence(monkeypatch, raw, inner):
    monkeypatch.setattr(p, "MAX_BYTES", 64)
    assert len(raw) <= p.MAX_BYTES
    with pytest.raises(p.ProjectionError, match="^invalid_stored_json$") as caught:
        p._decode(raw)
    assert str(caught.value.__context__) == inner
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


@pytest.mark.parametrize(("fields", "code"), [
    ([(b'"a" ', b"1")], "corrupt_projection_field"),
    ([(b'"\\u0061"', b"1")], "corrupt_projection_field"),
    ([(b"0", b"{")], "corrupt_projection_field"),
    ([(b'"a" ', b"{")], "corrupt_projection_field"),
    ([(b"{", b"{")], "invalid_stored_json"),
    ([(b'"a"', b"1"), (b'"a"', b"{")], "corrupt_projection_field"),
    ([(b'"a"', b"1 ")], "noncanonical_projection_artifact"),
    ([(b'"a"', b"1e0")], "noncanonical_projection_artifact"),
    ([(b'"a"', b'"\\u0061"')], "noncanonical_projection_artifact"),
    ([(b'"a"', b'{"z":0,"a":1}')], "noncanonical_projection_artifact"),
    ([(b'"a"', b'{"a":0,"a":1}')], "invalid_stored_json"),
    ([(b'"a"', b"{")], "invalid_stored_json"),
])
def test_reader_refuses_in_original_name_then_value_order(fields, code):
    connection = StoredRows(fields, restored={})
    with pytest.raises(p.ProjectionError) as caught:
        p.PostgresProjectionRepository._read(connection, "invented", "read")
    assert str(caught.value) == code and len(connection.queries) == 3


def test_payload_integrity_precedes_decoding_and_final_identity_follows_fields():
    connection = StoredRows([(b"{", b"{")], restored={})
    connection.payloads[0] = (connection.payloads[0][0], b"!")
    with pytest.raises(p.ProjectionError, match="^corrupt_projection_artifact$"):
        p.PostgresProjectionRepository._read(connection, "invented", "read")
    connection = StoredRows([(b'"a"', b"1")], final_sha="0" * 64)
    with pytest.raises(p.ProjectionError, match="^corrupt_projection_identity$"):
        p.PostgresProjectionRepository._read(connection, "invented", "read")
