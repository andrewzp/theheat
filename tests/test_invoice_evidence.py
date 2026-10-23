"""Operator-supplied billing evidence: strict contract and conservative matching.

All documents, accounts, IDs and amounts are INVENTED. Nothing here parses a
real provider export or establishes an invoice, account total or saving.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.evaluation import invoice_evidence as evidence

FIXTURES = Path(__file__).parent / "fixtures/private_workflow"
ITEMIZED = (FIXTURES / "billing-anthropic-itemized-invented.json").read_bytes()
ORIGINAL = (FIXTURES / "original-document-invented.txt").read_bytes()


def parsed(raw: dict | bytes, **kwargs) -> dict:
    data = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
    return evidence.parse_billing_evidence(data, **kwargs)


def edited(change) -> dict:
    raw = json.loads(ITEMIZED)
    change(raw)
    return raw


def test_itemized_fixture_parses_with_decimal_money_and_explicit_document_hash():
    document = parsed(ITEMIZED, original_document=ORIGINAL)
    assert document["document_check"] == "matched_explicit_file"
    assert document["totals"] == {"charges": "0.010825", "credits": "-0.001", "net": "0.009825"}
    assert document["coverage"] == {"assertion": "asserted_partial", "authority": "operator_assertion_only"}
    assert parsed(ITEMIZED)["document_check"] == "not_supplied"
    with pytest.raises(evidence.BillingEvidenceInvalid, match="document_sha256_mismatch"):
        parsed(ITEMIZED, original_document=ORIGINAL + b"changed")


def test_decimal_arithmetic_has_no_binary_float_drift():
    raw = edited(lambda r: r.update(items=[{"item_id": "a", "kind": "charge", "amount": "0.1"},
                                           {"item_id": "b", "kind": "charge", "amount": "0.2"}]))
    assert parsed(raw)["totals"]["net"] == "0.3" and Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


INVALID_CASES = [
    ("nan", ITEMIZED.replace(b'"0.004125"', b"NaN"), "billing_json_invalid"),
    ("float", ITEMIZED.replace(b'"0.004125"', b"0.004125"), "billing_json_invalid"),
    ("duplicate_key", ITEMIZED.replace(b'"currency": "USD"', b'"currency": "USD", "currency": "EUR"'),
     "billing_json_invalid"),
    ("integer_amount", ITEMIZED.replace(b'"0.004125"', b"4"), "item_amount"),
    ("bool_quantity", ITEMIZED.replace(b'"quantity": "1100"', b'"quantity": true'), "item_quantity"),
    ("numeric_string_exponent", ITEMIZED.replace(b'"0.004125"', b'"4e-3"'), "item_amount"),
    ("negative_quantity", ITEMIZED.replace(b'"quantity": "1100"', b'"quantity": "-1"'), "item_quantity"),
    ("lowercase_currency", ITEMIZED.replace(b'"currency": "USD"', b'"currency": "usd"'), "currency_unknown"),
    ("missing_currency", ITEMIZED.replace(b'"currency": "USD",', b""), "billing_shape"),
    ("naive_period", ITEMIZED.replace(b"2026-01-01T00:00:00+00:00", b"2026-01-01T00:00:00"), "time_not_aware"),
    ("unordered_period", ITEMIZED.replace(b"2036-01-01T00:00:00+00:00", b"2025-01-01T00:00:00+00:00"),
     "period_not_ordered"),
    ("path_field", ITEMIZED.replace(b'"statement": "itemized",', b'"statement": "itemized", "path": "/x",'),
     "billing_shape"),
    ("positive_credit", ITEMIZED.replace(b'"-0.001"', b'"0.001"'), "credit_must_not_be_positive"),
    ("schema", ITEMIZED.replace(b"billing-evidence/v1", b"billing-evidence/v2"), "billing_schema_version"),
    ("coverage_by", ITEMIZED.replace(b'"asserted_by": "operator"', b'"asserted_by": "provider"'),
     "coverage_assertion"),
]


@pytest.mark.parametrize("label,raw_bytes,code", [pytest.param(*case, id=case[0]) for case in INVALID_CASES])
def test_invalid_evidence_is_refused_with_fixed_codes(label, raw_bytes, code):
    with pytest.raises(evidence.BillingEvidenceInvalid, match=code) as raised:
        parsed(raw_bytes)
    assert "0.004125" not in str(raised.value) and "acct-invented" not in str(raised.value)


def test_item_conflicts_and_outside_period_are_refused_inside_one_document():
    with pytest.raises(evidence.BillingEvidenceInvalid, match="item_id_conflict_within_document"):
        parsed(edited(lambda r: r["items"].append({**r["items"][0], "amount": "0.5"})))
    same = parsed(edited(lambda r: r["items"].append(deepcopy(r["items"][0]))))
    assert len(same["items"]) == 6  # Exact repeat inside the document is deduplicated.
    with pytest.raises(evidence.BillingEvidenceInvalid, match="item_outside_period"):
        parsed(edited(lambda r: r["items"][0].update(occurred_at="2040-01-01T00:00:00+00:00")))
    with pytest.raises(evidence.BillingEvidenceInvalid, match="document_supplied_without_declared_sha256"):
        parsed(edited(lambda r: r["document"].pop("sha256")), original_document=ORIGINAL)


def test_aggregate_statement_totals_must_be_consistent():
    aggregate = (FIXTURES / "billing-google-aggregate-invented.json").read_bytes()
    document = parsed(aggregate)
    assert document["statement"] == "aggregate" and document["items"] == []
    assert document["totals"] == {"charges": "0.013000", "credits": "-0.000500", "net": "0.012500"}
    with pytest.raises(evidence.BillingEvidenceInvalid, match="aggregate_totals_inconsistent"):
        parsed(aggregate.replace(b'"net": "0.012500"', b'"net": "0.012400"'))


def test_documents_dedupe_exact_repeats_and_quarantine_conflicts():
    first = parsed(ITEMIZED)
    conflicting = parsed((FIXTURES / "billing-anthropic-conflicting-invented.json").read_bytes())
    other = parsed((FIXTURES / "billing-anthropic-other-account-invented.json").read_bytes())
    collected = evidence.collect_documents([first, deepcopy(first), other])
    assert collected["exact_duplicate_documents"] == 1 and len(collected["documents"]) == 2
    # Same item ID in a different account is a different item, never a duplicate or match.
    assert sorted(i["account"] for i in collected["items"] if i["item_id"] == "inv-item-accepted-writer") == [
        "acct-invented-0001", "acct-invented-OTHER"]
    quarantined = evidence.collect_documents([first, conflicting])
    assert quarantined["documents"] == [] and quarantined["quarantined"][0]["reason"] == "conflicting_document_identity"
    renamed = edited(lambda r: (r["document"].update(id="INVENTED-second-statement"),
                                r["items"][0].update(amount="0.777")))
    split = evidence.collect_documents([first, parsed(renamed)])
    assert [q["reason"] for q in split["quarantined"]] == ["conflicting_item_identity"]
    assert "inv-item-accepted-writer" not in {i["item_id"] for i in split["items"]}
    assert split["exact_duplicate_items"] == 5


def _usage(rows):
    return {"attempts": rows, "sources": [], "denominators": {}, "calls": [], "token_totals": []}


def _row(call, ids, *, at="2026-10-23T12:00:00.000Z", provider="anthropic", conflict=False, scope="scope-x"):
    return {"scope_id": scope, "call": call, "attempt": 1, "stage": "writer", "provider": provider,
            "provider_ids": ids, "provider_id_conflict": conflict, "response_recorded_at": at, "sent_at": at,
            "send_outcome": "response_received", "usage_status": "present"}


BINDING = evidence.parse_account_binding("anthropic:acct-invented-0001:proj-invented-0001")


def test_matching_uses_only_stable_ids_inside_the_bound_scope():
    usage = _usage([_row(1, {"request_id_header": "req_invented_d2_accepted_writer"}),
                    _row(2, {"response_body_id": "msg_invented_d2_rejected_writer"}),
                    _row(3, {"response_body_id": "msg_with_same_tokens_and_text"})])
    collected = evidence.collect_documents([parsed(ITEMIZED)])
    result = evidence.reconcile(usage, collected, [BINDING])
    assert [(m["item_id"], m["call"], m["matched_on"]) for m in result["matches"]] == [
        ("inv-item-accepted-writer", 1, ["provider_request_id"]),
        ("inv-item-rejected-writer", 2, ["provider_response_id"])]
    reasons = {u["item_id"]: u["reason"] for u in result["unmatched_billing_items"]}
    assert reasons == {"inv-item-not-archived": "identifier_not_in_supplied_archives",
                       "inv-item-no-identifier": "no_provider_identifier_supplied",
                       "inv-item-credit": "no_provider_identifier_supplied",
                       "inv-item-tax": "no_provider_identifier_supplied"}
    assert [a["call"] for a in result["attempts_without_billing_item"]] == [3]
    assert result["interpretation"]["unmatched_item"] == "not_evidence_of_an_unpaid_call"
    unbound = evidence.reconcile(usage, collected, [])
    assert unbound["matches"] == [] and {u["reason"] for u in unbound["unmatched_billing_items"]} >= {
        "archive_account_scope_not_bound"}


def test_identical_ids_in_other_accounts_periods_or_duplicates_never_match():
    other = parsed((FIXTURES / "billing-anthropic-other-account-invented.json").read_bytes())
    usage = _usage([_row(1, {"request_id_header": "req_invented_d2_accepted_writer"})])
    result = evidence.reconcile(usage, evidence.collect_documents([other]), [BINDING])
    assert result["matches"] == [] and result["unmatched_billing_items"][0]["reason"] == "archive_account_scope_not_bound"
    late = _usage([_row(1, {"request_id_header": "req_invented_d2_accepted_writer"}, at="2040-01-01T00:00:00.000Z")])
    outside = evidence.reconcile(late, evidence.collect_documents([parsed(ITEMIZED)]), [BINDING])
    assert "response_outside_billing_period" in {u["reason"] for u in outside["unmatched_billing_items"]}
    duplicated = _usage([_row(1, {"request_id_header": "req_invented_d2_accepted_writer"}, conflict=True),
                         _row(2, {"request_id_header": "req_invented_d2_accepted_writer"}, conflict=True,
                              scope="scope-y")])
    conflict = evidence.reconcile(duplicated, evidence.collect_documents([parsed(ITEMIZED)]), [BINDING])
    assert conflict["matches"] == [] and conflict["conflicting_matches"][0]["reason"] == \
        "identifier_matches_multiple_responses"


def test_aggregate_money_is_compared_never_allocated_and_currencies_never_convert():
    aggregate = parsed((FIXTURES / "billing-google-aggregate-invented.json").read_bytes())
    euro = parsed(edited(lambda r: r.update(currency="EUR", document={"id": "INVENTED-eur-0001"})))
    usage = _usage([_row(1, {"response_body_responseId": "g1"}, provider="google"),
                    _row(2, {}, provider="google")])
    usage["attempts"][1]["send_outcome"] = "unknown"
    result = evidence.reconcile(usage, evidence.collect_documents([aggregate, parsed(ITEMIZED), euro]), [])
    [comparison] = result["aggregate_comparisons"]
    assert comparison["billed"]["net"] == "0.012500" and comparison["archive_physical_attempts_in_period"] == 2
    assert comparison["archive_unknown_outcomes_in_period"] == 1
    assert comparison["allocation"] == "none_aggregate_money_is_never_distributed_over_calls"
    assert comparison["archive_account_binding"] == "unbound_counts_may_include_other_accounts"
    assert {(t["currency"], t["net"]) for t in result["billed_totals_by_scope"]} == {
        ("USD", "0.012500"), ("USD", "0.009825"), ("EUR", "0.009825")}
    assert all("allocated" not in json.dumps(m) for m in result["matches"])


def test_account_binding_is_an_explicit_bounded_assertion():
    assert BINDING == {"provider": "anthropic", "account": "acct-invented-0001", "project": "proj-invented-0001",
                       "authority": "operator_assertion_only"}
    for bad in ("openai:acct", "anthropic", "anthropic:", "anthropic:a:b:c", "google:bad account"):
        with pytest.raises(evidence.BillingEvidenceInvalid):
            evidence.parse_account_binding(bad)


def test_markdown_cells_escape_tables_and_never_shorten_silently():
    assert evidence._cell("a|b\nc") == "a\\|b c"
    shortened = evidence._cell("x" * 400)
    assert len(shortened) == 160 and shortened.endswith("…")
    assert evidence._cell(None) == "—" and evidence._cell(0) == "0"


def test_unique_item_totals_exclude_duplicates_and_quarantined_money():
    raw = edited(lambda r: r.update(items=[{"item_id": "i", "kind": "charge", "amount": "0.10"},
                                           {"item_id": "credit", "kind": "credit", "amount": "-0.01"}]))
    second = deepcopy(raw)
    second["document"]["id"] = "second"
    collected = evidence.collect_documents([parsed(raw), parsed(second)])
    [total] = evidence._billed_totals(collected)
    assert total["net"] == "0.09" and total["charges"] == "0.10" and total["credits"] == "-0.01"
    assert collected["exact_duplicate_items"] == 2
    second["items"][0]["amount"] = "0.20"
    collected = evidence.collect_documents([parsed(raw), parsed(second)])
    [total] = evidence._billed_totals(collected)
    assert total["net"] is None and total["charges"] is None and total["credits"] is None
    assert total["incomplete"] is True and total["quarantined_item_count"] == 1
    assert total["accepted_item_subtotal"]["net"] == "-0.01"
    from datetime import datetime, timezone
    report = evidence.build_report(as_of=datetime(2026, 10, 23, tzinfo=timezone.utc), usage=_usage([]),
                                   documents=[parsed(raw), parsed(second)], rejected_billing=[], bindings=[],
                                   scenario=None, state_summary=None, input_files=[])
    assert report["supplied_billing"]["billed_totals_by_scope"][0]["net"] is None
    assert "total unknown" in evidence.render_markdown(report)


@pytest.mark.parametrize("ids,request_id,response_id,reason", [
    ({"request_id_header": "req-1", "response_body_id": "msg-1"}, "msg-1", None,
     "identifier_not_in_supplied_archives"),
    ({"request_id_header": "req-1", "response_body_id": "msg-1"}, "req-1", "msg-WRONG",
     "contradictory_provider_identifiers"),
])
def test_identifiers_preserve_roles_and_known_values_must_agree(ids, request_id, response_id, reason):
    raw = edited(lambda r: r.update(items=[{"item_id": "i", "kind": "charge", "amount": "0.10",
                                           "provider_request_id": request_id,
                                           "provider_response_id": response_id}]))
    result = evidence.reconcile(_usage([_row(1, ids)]), evidence.collect_documents([parsed(raw)]), [BINDING])
    assert result["matches"] == []
    assert reason in {item["reason"] for item in result["unmatched_billing_items"] + result["conflicting_matches"]}


def test_both_identifiers_must_resolve_the_same_attempt_and_multiple_scopes_are_ambiguous():
    raw = edited(lambda r: r.update(items=[{"item_id": "i", "kind": "charge", "amount": "0.10",
                                           "provider_request_id": "req-1", "provider_response_id": "msg-2"}]))
    usage = _usage([_row(1, {"request_id_header": "req-1", "response_body_id": "msg-1"}),
                    _row(2, {"request_id_header": "req-2", "response_body_id": "msg-2"}, scope="scope-b")])
    result = evidence.reconcile(usage, evidence.collect_documents([parsed(raw)]), [BINDING])
    assert not result["matches"] and result["conflicting_matches"][0]["reason"] == "identifier_matches_multiple_responses"
    raw["items"][0]["provider_request_id"] = "req-2"
    for other in ("anthropic:account-B:project-B", "anthropic:acct-invented-0001:other-project"):
        result = evidence.reconcile(usage, evidence.collect_documents([parsed(raw)]),
                                    [BINDING, evidence.parse_account_binding(other)])
        assert not result["matches"]
        assert result["unmatched_billing_items"][0]["reason"] == "archive_account_scope_ambiguous"


def test_aggregate_components_remain_unknown_and_overlapping_documents_are_not_added():
    raw = json.loads((FIXTURES / "billing-google-aggregate-invented.json").read_bytes())
    raw["totals"] = {"net": "12.50"}
    second = deepcopy(raw)
    second["document"]["id"] = "another-statement"
    documents = [parsed(raw), parsed(second)]
    totals = evidence._billed_totals(evidence.collect_documents(documents))
    assert len(totals) == 2
    assert all(row["net"] == "12.50" and row["charges"] is None and row["credits"] is None for row in totals)
    result = evidence.reconcile(_usage([_row(1, {}, provider="google")]), evidence.collect_documents(documents),
                                [evidence.parse_account_binding("google:acct-invented-google-0001"),
                                 evidence.parse_account_binding("google:other-account")])
    assert all(row["archive_account_binding"] == "ambiguous_bindings_counts_may_include_other_accounts"
               for row in result["aggregate_comparisons"])


def test_money_sums_stay_exact_across_accepted_range_and_cancellation():
    from decimal import getcontext, localcontext
    original_precision = getcontext().prec
    amount = "9999999999999999.999999999999"
    raw = edited(lambda r: r.update(items=[{"item_id": "a", "kind": "charge", "amount": amount},
                                           {"item_id": "b", "kind": "charge", "amount": amount},
                                           {"item_id": "c", "kind": "credit", "amount": "-0.000000000001"}]))
    with localcontext() as context:
        context.prec = 6  # A caller's unrelated context must not change recorded money.
        assert parsed(raw)["totals"] == {"charges": "19999999999999999.999999999998",
                                         "credits": "-1E-12", "net": "19999999999999999.999999999997"}
        assert evidence._sum_money([amount] * evidence.MAX_ITEMS) == Decimal("999999999999999999999.999999900000")
    assert getcontext().prec == original_precision


@pytest.mark.parametrize("statement", ["itemized", "aggregate"])
def test_absent_and_explicit_project_have_a_total_order(statement):
    raw = json.loads(ITEMIZED if statement == "itemized" else
                     (FIXTURES / "billing-google-aggregate-invented.json").read_bytes())
    raw["scope"].pop("project", None)
    second = deepcopy(raw)
    second["document"]["id"] = "other-project-statement"
    second["scope"]["project"] = "p"
    collected = evidence.collect_documents([parsed(raw), parsed(second)])
    assert {row["project"] for row in evidence._billed_totals(collected)} == {None, "p"}


def test_equivalent_aware_period_offsets_do_not_duplicate_stable_item_money():
    first = parsed(ITEMIZED)
    raw = edited(lambda r: r["document"].update(id="equivalent-period-statement"))
    raw["period"] = {"start": "2025-12-31T19:00:00-05:00", "end": "2035-12-31T19:00:00-05:00"}
    second = parsed(raw)
    assert first["period"] == second["period"]
    collected = evidence.collect_documents([first, second])
    assert collected["exact_duplicate_items"] == len(first["items"])
    assert evidence._billed_totals(collected)[0]["net"] == first["totals"]["net"]
