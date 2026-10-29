"""Invented operator connections; no factual approval is fabricated."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.editorial.operator_claim_references import (
    build_operator_claim_references, read_operator_claim_references,
)

FIXTURE = json.loads((Path(__file__).parent / "fixtures/operator_claim_references.json").read_text())


def test_exact_shared_unicode_round_trip_and_immutable_inputs():
    before = deepcopy(FIXTURE)
    result = build_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], FIXTURE["items"])
    assert result == FIXTURE["saved"]
    assert read_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], result) == result
    result["items"][0]["claim"]["text"] = "changed returned object"
    assert FIXTURE == before


@pytest.mark.parametrize("pointer", ["/current_facts/00", "/current_facts/-1", "/current_facts/1.0",
                                     "/current_facts/64", "/current_facts/0/value", "/current_facts/0~1",
                                     "https://invalid.example/", "__proto__", "/current_facts/999999999999"])
def test_pointer_is_a_bounded_exact_array_row(pointer):
    items = deepcopy(FIXTURE["items"])
    items[0]["sources"][0]["pointer"] = pointer
    with pytest.raises(ValueError):
        build_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], items)


@pytest.mark.parametrize("change", [
    lambda i: i[0]["claim"].update(start=True),
    lambda i: i[0]["claim"].update(end=999999999999999999999),
    lambda i: i[0]["claim"].update(text="different quote"),
    lambda i: i[0]["claim"].update(end=i[0]["claim"]["start"]),
    lambda i: i[0]["claim"].update(text_sha256="a" * 64),
    lambda i: i[0]["sources"][0].update(value_sha256="a" * 64),
    lambda i: i[0].update(sources=[]),
    lambda i: i[0]["sources"].append(deepcopy(i[0]["sources"][0])),
    lambda i: i.append(deepcopy(i[0])),
    lambda i: i[0].update(origin="verified"),
])
def test_malformed_ambiguous_or_supplied_digests_fail_without_mutation(change):
    items = deepcopy(FIXTURE["items"])
    change(items)
    before = deepcopy(items)
    with pytest.raises(ValueError):
        build_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], items)
    assert items == before


def test_saved_hashes_are_rederived_for_text_source_quote_and_values():
    for key in ("text_sha256", "bundle_sha256"):
        saved = deepcopy(FIXTURE["saved"])
        saved[key] = "f" * 64
        assert read_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], saved) is None
    saved = deepcopy(FIXTURE["saved"])
    saved["items"][0]["sources"][0]["value_sha256"] = "f" * 64
    assert read_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], saved) is None
    bundle = deepcopy(FIXTURE["bundle"])
    bundle["current_facts"][0]["unit"] = "invented other unit"
    assert read_operator_claim_references(FIXTURE["text"], bundle, FIXTURE["saved"]) is None
    bundle = deepcopy(FIXTURE["bundle"])
    bundle["where"] = "Another invented place"
    assert read_operator_claim_references(FIXTURE["text"], bundle, FIXTURE["saved"]) is None
    assert read_operator_claim_references(FIXTURE["text"] + ".", FIXTURE["bundle"], FIXTURE["saved"]) is None
    for saved in (None, [], {}, {**FIXTURE["saved"], "schema_version": True}, {**FIXTURE["saved"], "items": []}):
        assert read_operator_claim_references(FIXTURE["text"], FIXTURE["bundle"], saved) is None


def test_exact_limits_never_truncate():
    bundle = {"current_facts": [{"label": "invented", "value": n} for n in range(64)]}
    text = "x" * 280
    item = {"claim": {"start": 0, "end": 280, "text": text},
            "sources": [{"pointer": f"/current_facts/{n}"} for n in range(64)]}
    assert len(build_operator_claim_references(text, bundle, [item])["items"][0]["sources"]) == 64
    items = [{"claim": {"start": n, "end": n + 1, "text": "x"}, "sources": [{"pointer": "/current_facts/0"}]} for n in range(32)]
    assert len(build_operator_claim_references(text, bundle, items)["items"]) == 32
    with pytest.raises(ValueError, match="32"):
        build_operator_claim_references(text, bundle, items + [{"claim": {"start": 32, "end": 33, "text": "x"}, "sources": [{"pointer": "/current_facts/0"}]}])
    with pytest.raises(ValueError, match="64"):
        build_operator_claim_references(text, bundle, [item, items[1]])
    oversized = [{"claim": {"start": n, "end": 280, "text": text[n:]}, "sources": [{"pointer": "/current_facts/0"}, {"pointer": "/current_facts/1"}]} for n in range(32)]
    with pytest.raises(ValueError, match="16 KiB"):
        build_operator_claim_references("🌡" * 280, bundle, [{**row, "claim": {**row["claim"], "text": "🌡" * (280 - n)}} for n, row in enumerate(oversized)])
    with pytest.raises(ValueError):
        build_operator_claim_references("x" * 281, bundle, [item])
    assert build_operator_claim_references(text, None, []) is None


@pytest.mark.parametrize("facts", [None, [None], [{"label": "x", "value": {}}], [{"label": "x", "value": float("inf")}],
                                   [{"label": "x", "value": 1}] * 65, [{"label": "\ud800", "value": 1}]])
def test_unusable_fact_packet_is_not_partially_retained(facts):
    with pytest.raises((ValueError, UnicodeError)):
        build_operator_claim_references(FIXTURE["text"], {"current_facts": facts}, FIXTURE["items"])
