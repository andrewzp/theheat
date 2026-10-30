"""W12.3 / W12.4 — owner-supplied export intake and coverage-first reconciliation.

A FICTIONAL export proves mechanics only; no billing page, login or provider
access. Archives come from the actual pipeline with invented offline providers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.evaluation.invoice_evidence import BillingEvidenceInvalid, parse_billing_evidence
from src.evaluation.invoice_import import import_export
from src.evaluation.reconciled_cost import operation_observations
from tests.test_archive_reconciliation_cli import cli
from tests.test_request_archive_sdk import accepted_script, journey_env, private_root, run_journey

__all__ = ["journey_env"]

PROFILE: dict[str, Any] = {"schema": "theheat.billing-export-profile/v1", "provider": "anthropic",
           "scope": {"account": "acct-invented-0001", "project": "proj-invented-0001"}, "currency": "USD",
           "period": {"start": "2026-10-01T00:00:00+00:00", "end": "2026-11-01T00:00:00+00:00"},
           "coverage": "asserted_partial",
           "columns": {"item_id": "Line ID", "amount": "Cost (USD)", "currency": "Currency", "model": "Model",
                       "occurred_at": "Usage time", "quantity": "Tokens", "quantity_unit": "Unit",
                       "provider_request_id": "Request ID"}}
HEADER = "Line ID,Cost (USD),Currency,Model,Usage time,Tokens,Unit,Request ID\n"


def _profile(**overrides) -> bytes:
    return json.dumps({**PROFILE, **overrides}).encode()


def _csv(*rows: str) -> bytes:
    return (HEADER + "".join(row + "\n" for row in rows)).encode()


def test_fictional_export_becomes_bound_billing_evidence_with_classes_kept_apart():
    export = _csv("line-1,0.012000,USD,invented-model,2026-10-02T10:00:00+00:00,1200,tokens,req_invented_1",
                  "line-2,-0.004000,USD,invented-model,2026-10-03T10:00:00+00:00,,,",
                  "line-3,0,USD,invented-model,2026-10-04T10:00:00+00:00,10,tokens,",
                  "line-4,0.500000,USD,invented-model,2026-09-30T23:00:00+00:00,10,tokens,",
                  ",0.001000,USD,invented-model,2026-10-05T10:00:00+00:00,5,tokens,",
                  ",0.001000,USD,invented-model,2026-10-05T10:00:00+00:00,5,tokens,",
                  "line-1,0.012000,USD,invented-model,2026-10-02T10:00:00+00:00,1200,tokens,req_invented_1")
    data, report = import_export(export, _profile(), document_id="invented-export-2026-10")
    parsed = parse_billing_evidence(data, original_document=export)
    assert parsed["document_check"] == "matched_explicit_file" and report["document_check"] == "matched_explicit_file"
    assert report["rows"] == 7 and report["rows_outside_period"] == 1
    assert report["items"] == 5 and report["charges"] == 3 and report["credits_or_refunds"] == 1
    assert report["zero_charge_items"] == 1 and report["derived_item_ids"] == 2
    assert report["possible_duplicate_rows"] == 2  # Identical id-less row + repeated exact line.
    assert report["currency_conversion"] is False and "provider_response_id" in report["unmapped_dimensions"]
    kinds = {item["item_id"]: item["kind"] for item in parsed["items"]}
    assert kinds["line-2"] == "credit" and kinds["line-3"] == "charge"
    assert parsed["provider"] == "anthropic" and parsed["currency"] == "USD"


@pytest.mark.parametrize("rows,code", [
    (("line-1,0.01,EUR,m,2026-10-02T10:00:00+00:00,1,tokens,",), "export_row_currency_differs"),
    (("line-1,0.01,USD,m,2026-10-02T10:00:00+00:00,1,tokens,", "line-1,0.02,USD,m,2026-10-02T10:00:00+00:00,1,tokens,"),
     "export_item_id_conflict"),
    (("line-1,1e-3,USD,m,2026-10-02T10:00:00+00:00,1,tokens,",), "export_row_amount"),
    (("line-1,0.01,USD,m,2026-10-02T10:00:00,1,tokens,",), "time_not_aware"),
    (("line-1,0.01,USD",), "export_row_width"),
])
def test_ambiguous_rows_are_refused_never_repaired(rows, code):
    with pytest.raises(BillingEvidenceInvalid, match=code):
        import_export(_csv(*rows), _profile(), document_id="invented-export")


def test_profile_must_map_every_named_column_and_never_guess_kinds():
    with pytest.raises(BillingEvidenceInvalid, match="export_header_unmapped_column"):
        import_export(b"Line ID,Amount\nx,1\n", _profile(), document_id="invented-export")
    with pytest.raises(BillingEvidenceInvalid, match="export_profile_kind_values"):
        import_export(_csv(), _profile(columns={"item_id": "Line ID", "amount": "Cost (USD)", "kind": "Unit"}),
                      document_id="d")
    with pytest.raises(BillingEvidenceInvalid, match="export_profile_columns"):  # One header, two dimensions.
        import_export(_csv(), _profile(columns={**PROFILE["columns"], "kind": "Unit"}, kind_values={"charge": ["x"]}),
                      document_id="d")
    labelled = _profile(columns={"item_id": "Line ID", "amount": "Cost (USD)", "kind": "Unit"},
                        kind_values={"charge": ["tokens"]})
    with pytest.raises(BillingEvidenceInvalid, match="export_row_kind_unmapped"):
        import_export(_csv("line-9,0.01,USD,m,2026-10-02T10:00:00+00:00,1,refund,"), labelled, document_id="d")
    with pytest.raises(BillingEvidenceInvalid, match="export_profile_schema"):
        import_export(_csv(), _profile(schema="invented/v9"), document_id="d")


def _state_with_interrupted_request() -> dict:
    row = {"schema_version": 1, "operation": "alerts", "path": "ordinary", "spend_class": "selection",
           "requests": {"total": 3, "by_outcome": {"dispatched": 1, "returned": 1, "unknown": 1, "malformed": 0},
                        "interrupted": 1, "truncated": False},
           "unpriced_requests": 0, "estimate_only_requests": 3}
    return {"run_history": [{"started_at": "2026-10-20T09:00:00Z", "operation_costs": [row, {"schema_version": 7}]}],
            "llm_usage": {}}


def test_operation_observations_aggregate_without_trusting_free_rows():
    observed = operation_observations(_state_with_interrupted_request())
    assert observed["operations"] == 1 and observed["invalid_rows"] == 1
    assert observed["interrupted"] == 1 and observed["unknown_or_malformed"] == 1
    assert observed["by_spend_class"] == {"selection": 3}


def test_cli_import_then_reconcile_lists_discrepancies_before_any_total(journey_env, tmp_path):
    archive = run_journey(accepted_script(), root=private_root(tmp_path, "accepted")).archive
    inputs, out = private_root(tmp_path, "inputs"), private_root(tmp_path, "out")
    export, profile, state = inputs / "export.csv", inputs / "profile.json", inputs / "state.json"
    export.write_bytes(_csv("line-1,0.012000,USD,invented-model,2026-10-02T10:00:00+00:00,1200,tokens,req_invented_1"))
    profile.write_bytes(_profile())
    state.write_text(json.dumps(_state_with_interrupted_request()))
    for path in (export, profile, state):
        os.chmod(path, 0o600)
    evidence = inputs / "evidence.json"
    code, summary, raw = cli("import-export", str(export), "--profile", str(profile), "--document-id",
                             "invented-export-2026-10", "--output", str(evidence))
    assert code == 0, raw
    assert summary["status"] == "written" and summary["items"] == 1 and summary["document_check"] == "matched_explicit_file"
    code, summary, raw = cli("reconcile", "--archive", str(archive), "--billing-with-document", str(evidence), str(export),
                             "--account-binding", "anthropic:acct-invented-0001:proj-invented-0001",
                             "--state", str(state), "--as-of", "2026-10-23T12:00:00+00:00", "--output-dir", str(out))
    assert code in (0, 1), raw
    report = json.loads((out / "reconciliation.json").read_text())
    codes = {gap["code"]: gap["count"] for gap in report["discrepancies"]}
    assert codes["billing_item_unmatched"] == 1 and codes["production_interrupted_requests"] == 1
    assert codes["production_unknown_or_malformed_requests"] == 1 and report["totals_reliable"] is False
    assert report["coverage"]["actual_cost_known"] is False
    markdown = (out / "reconciliation.md").read_text()
    assert markdown.index("Coverage and discrepancies") < markdown.index("## Inputs") < markdown.index("## Reconciliation")
    assert "not reliable" in markdown


def test_operator_diagnosis_spend_reads_discrepancies_first():
    source = (Path(__file__).resolve().parents[2] / "src/evaluation/operator_diagnosis.py").read_text()
    spend = source[source.index('spend = {"status": "verified"'):]
    assert spend.index('"discrepancies"') < spend.index('"billing_matches"')
