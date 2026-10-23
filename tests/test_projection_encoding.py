"""Exact canonical identities and bounded whole encoding over invented JSON."""

import json
import math
import random
from typing import Any

import pytest

from src.storage import postgres_projection as p


@pytest.mark.parametrize(("value", "expected"), [
    ({"z": None, "a": [True, False, -0.0, 1e-6, 1e308, 5e-324]},
     b'{"a":[true,false,-0.0,1e-06,1e+308,5e-324],"z":null}'),
    ({"\u03a9": "\U0001f321\ufe0f\n\t\x00\\\"", "a": "\u00e9"},
     '{"a":"\u00e9","\u03a9":"\U0001f321\ufe0f\\n\\t\\u0000\\\\\\\""}'.encode()),
    ({"max": p.MAX_INTEGER, "min": -p.MAX_INTEGER, "empty": [{}, []]},
     b'{"empty":[{},[]],"max":9007199254740991,"min":-9007199254740991}'),
], ids=["ordered-scalars", "unicode-escapes", "safe-integers"])
def test_exact_canonical_bytes(value, expected):
    assert p._canonical(value) == expected
    bounded = p._bounded_snapshot(value)
    assert bounded is not None and len(expected) <= bounded[1] <= p.MAX_BYTES


class StringSubclass(str):
    pass


class IntegerSubclass(int):
    pass


class FloatSubclass(float):
    pass


class ListSubclass(list):
    pass


class DictSubclass(dict):
    pass


@pytest.mark.parametrize(("value", "code"), [
    ((1, 2), "unsupported_json_value"),
    ({"set": {1}}, "unsupported_json_value"),
    (b"bytes", "unsupported_json_value"),
    (StringSubclass("a"), "unsupported_json_value"),
    (IntegerSubclass(1), "unsupported_json_value"),
    (FloatSubclass(1.0), "unsupported_json_value"),
    (ListSubclass([1]), "unsupported_json_value"),
    (DictSubclass(a=1), "unsupported_json_value"),
    ({1: "a"}, "invalid_json_key"),
    ({StringSubclass("a"): 1}, "invalid_json_key"),
    (p.MAX_INTEGER + 1, "unsafe_json_integer"),
    (-p.MAX_INTEGER - 1, "unsafe_json_integer"),
    (math.nan, "nonfinite_json_number"),
    (math.inf, "nonfinite_json_number"),
    (-math.inf, "nonfinite_json_number"),
    ("\ud800", "invalid_json"),
    ("\udfff", "invalid_json"),
    ("\ud800\udfff", "invalid_json"),
    ({"\ud800": 0}, "invalid_json"),
], ids=["tuple", "set", "bytes", "str-subclass", "int-subclass", "float-subclass",
        "list-subclass", "dict-subclass", "integer-key", "key-subclass",
        "large-positive", "large-negative", "nan", "positive-inf", "negative-inf",
        "high-surrogate", "low-surrogate", "surrogate-pair", "surrogate-key"])
def test_exact_refusal_classes_and_codes(value, code):
    with pytest.raises(p.ProjectionError) as caught:
        p._canonical(value)
    assert type(caught.value) is p.ProjectionError
    assert str(caught.value) == code


def test_original_structure_depth_nodes_and_cycles(monkeypatch):
    nested: Any = 0
    for _ in range(p.MAX_DEPTH):
        nested = [nested]
    assert p._canonical(nested) == b"[" * p.MAX_DEPTH + b"0" + b"]" * p.MAX_DEPTH
    cycle: list[Any] = []
    cycle.append(cycle)
    for value in ([nested], cycle):
        with pytest.raises(p.ProjectionError, match="^projection_structure_bound$"):
            p._canonical(value)
    monkeypatch.setattr(p, "MAX_NODES", 4)
    assert p._canonical([0, 0, 0]) == b"[0,0,0]"
    with pytest.raises(p.ProjectionError, match="^projection_structure_bound$"):
        p._canonical([0, 0, 0, 0])


def forbid_whole_encoding(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Loose bounds must use incremental encoding")
    monkeypatch.setattr(json.JSONEncoder, "encode", forbidden)


def test_loose_bound_uses_original_path_without_false_refusal(monkeypatch):
    monkeypatch.setattr(p, "MAX_BYTES", 64)
    shared = ["x" * 20]
    value = {"a": shared, "b": shared}
    assert p._bounded_snapshot(value) is None
    forbid_whole_encoding(monkeypatch)
    assert p._canonical(value) == b'{"a":["xxxxxxxxxxxxxxxxxxxx"],"b":["xxxxxxxxxxxxxxxxxxxx"]}'


@pytest.mark.parametrize("kind", ["ascii", "escaped", "non-bmp", "key"])
def test_actual_sixteen_mib_boundary_uses_incremental_fallback(monkeypatch, kind):
    limit = p.MAX_BYTES
    value: Any
    over: Any
    if kind == "ascii":
        text = "a" * (limit - 2)
        value, over = text, text + "a"
        expected = b'"' + b"a" * (limit - 2) + b'"'
    elif kind == "escaped":
        count, remainder = divmod(limit - 2, 6)
        text = "\x00" * count + "a" * remainder
        value, over = text, text + "a"
        expected = b'"' + b"\\u0000" * count + b"a" * remainder + b'"'
    elif kind == "non-bmp":
        count, remainder = divmod(limit - 2, 4)
        text = "\U0001f321" * count + "a" * remainder
        value, over = text, text + "a"
        expected = b'"' + "\U0001f321".encode() * count + b"a" * remainder + b'"'
    else:
        text = "a" * (limit - 6)
        value, over = {text: 0}, {text + "a": 0}
        expected = b'{"' + b"a" * (limit - 6) + b'":0}'
    assert len(expected) == limit
    assert p._bounded_snapshot(value) is None
    forbid_whole_encoding(monkeypatch)
    assert p._canonical(value) == expected
    with pytest.raises(p.ProjectionError, match="^projection_byte_bound$"):
        p._canonical(over)


def test_repeated_huge_shared_string_never_reaches_whole_encoder(monkeypatch):
    shared = "x" * (p.MAX_BYTES // 2)
    value = [shared] * 1000
    assert p._bounded_snapshot(value) is None
    forbid_whole_encoding(monkeypatch)
    with pytest.raises(p.ProjectionError, match="^projection_byte_bound$"):
        p._canonical(value)


def test_incremental_error_order_is_unchanged(monkeypatch):
    huge = "x" * p.MAX_BYTES
    forbid_whole_encoding(monkeypatch)
    for value, code in (({"a": huge, "z": "\ud800"}, "projection_byte_bound"),
                        ({"a": "\ud800", "z": huge}, "invalid_json")):
        with pytest.raises(p.ProjectionError) as caught:
            p._canonical(value)
        assert str(caught.value) == code


def test_whole_encoder_only_sees_detached_bounded_graph(monkeypatch):
    child = ["before"]
    original: dict[str, Any] = {"a": child, "b": child}
    encode = json.JSONEncoder.encode
    seen = []

    def mutate_then_encode(encoder, value):
        assert value is not original
        assert value["a"] is not child and value["b"] is not child
        assert value["a"] is not value["b"]  # Repeated references count independently.
        child[:] = ["x" * (p.MAX_BYTES // 2)] * 1000
        original["new"] = original
        seen.append(value)
        return encode(encoder, value)

    monkeypatch.setattr(json.JSONEncoder, "encode", mutate_then_encode)
    assert p._canonical(original) == b'{"a":["before"],"b":["before"]}'
    assert seen == [{"a": ["before"], "b": ["before"]}]


@pytest.mark.parametrize(("replacement", "code"), [
    ((1,), "unsupported_json_value"),
    (p.MAX_INTEGER + 1, "unsafe_json_integer"),
    (math.inf, "nonfinite_json_number"),
    ({1: 0}, "invalid_json_key"),
], ids=["unsupported", "unsafe-integer", "nonfinite", "invalid-key"])
def test_snapshot_rechecks_values_mutated_after_first_structure_check(monkeypatch, replacement, code):
    original = [0]
    check = p._check_structure

    def mutate_after_check(value):
        check(value)
        value[0] = replacement

    monkeypatch.setattr(p, "_check_structure", mutate_after_check)
    forbid_whole_encoding(monkeypatch)
    with pytest.raises(p.ProjectionError, match=f"^{code}$"):
        p._canonical(original)


@pytest.mark.parametrize("kind", ["list", "dict"])
def test_snapshot_counts_actual_members_added_after_length_check(monkeypatch, kind):
    original: Any = [0, 0] if kind == "list" else {"a": 0, "b": 0}
    monkeypatch.setattr(p, "MAX_NODES", 5)
    p._check_structure(original)
    require = p._require
    calls = 0

    def mutate_after_length_check(condition, code):
        nonlocal calls
        require(condition, code)
        calls += 1
        # The snapshot's length condition has already evaluated to true. The
        # following iteration must account for each member it actually copies.
        if calls == 2:
            if kind == "list":
                original.extend([0] * 5)
            else:
                original.update({str(index): 0 for index in range(5)})

    monkeypatch.setattr(p, "_require", mutate_after_length_check)
    forbid_whole_encoding(monkeypatch)
    with pytest.raises(p.ProjectionError, match="^projection_structure_bound$"):
        p._bounded_snapshot(original)


def test_varied_json_preserves_stdlib_bytes_and_conservative_bounds():
    randomizer = random.Random(7381)
    scalars = [None, True, False, -0.0, 1e308, 5e-324, -p.MAX_INTEGER,
               "a\x00\n\\\"\u00e9\U0001f321"]
    for index in range(100):
        value = {f"key-{index}": [randomizer.choice(scalars) for _ in range(index % 17)],
                 "nested": {"value": randomizer.choice(scalars)}}
        expected = json.dumps(value, sort_keys=True, ensure_ascii=False,
                              allow_nan=False, separators=(",", ":")).encode("utf-8")
        bounded = p._bounded_snapshot(value)
        assert bounded is not None and len(expected) <= bounded[1]
        assert p._canonical(value) == expected
