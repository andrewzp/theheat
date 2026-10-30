"""D3 — every declared route and hosting service states its estimate, observation
and invoice input; missing prices name the exact input; the reconciliation
consumer lists them first; the Operations mirror is identical.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from src.evaluation import reconciled_cost
from src.two_bot import call_inventory as inv
from src.two_bot import cost_inputs

ROOT = Path(__file__).resolve().parents[2]


def test_every_declared_stage_and_provider_has_exactly_one_input_row():
    rows = cost_inputs.register()["rows"]
    keys = [(row["stage"], row["provider"]) for row in rows]
    declared = [(stage, provider) for stage, found in inv.DECLARATIONS.items() for provider in found.providers]
    assert len(keys) == len(set(keys)) and set(declared) <= set(keys)
    assert {"github_actions_runner_minutes", "vercel_dashboard_hosting"} <= {row["stage"] for row in rows}
    for row in rows:
        assert row["actual_charge_known"] is False
        assert row["estimate"]["basis"] in ("anthropic_price_table", "gemini_token_scenario", "missing_price")
        if row["invoice"]["path"] == "supplied_statement_required":
            assert len(row["invoice"]["required_input"]) > 40  # An exact statement, not a placeholder.
    register = cost_inputs.register()
    assert register["monthly_provider_ceiling_enforced"] is False and register["evidence_added_together"] is False
    assert register["ceilings"]["monthly_budget_watch"] == {"financial_cap": False, "enforced": False}
    assert register["ceilings"]["candidate_attempts"]["financial_cap"] is False


def test_batch_never_borrows_synchronous_prices_and_platform_data_hosting_are_missing():
    rows = {(row["stage"], row["provider"]): row for row in cost_inputs.register()["rows"]}
    assert rows[("batch_writer", "anthropic")]["estimate"]["basis"] == "missing_price"
    for key in (("x_publish", "x"), ("gist_state", "github"), ("source_http_get", "source"),
                ("news_verification_page", "publisher"), ("vercel_dashboard_hosting", "vercel")):
        assert rows[key]["estimate"]["basis"] == "missing_price"
        assert rows[key]["invoice"]["path"] == "supplied_statement_required"
    assert rows[("writer", "anthropic")]["invoice"]["path"] == "billing_export_import"


def test_reconciliation_lists_missing_price_inputs_and_late_requests_before_any_total():
    state = {"run_history": [{"operation_costs": [
        {"schema_version": 1, "spend_class": "selection", "requests": {
            "total": 3, "interrupted": 0, "by_outcome": {"returned": 3}, "late_after_close": 1,
            "late_by_stage": {"writer": 1},
            "by_stage": {"writer": {"requests": 1}, "x_publish": {"requests": 2}, "Bearer invented": {"requests": 9}}},
         "unpriced_requests": 2, "estimate_only_requests": 1}]}]}
    observed = reconciled_cost.operation_observations(state)
    assert observed["by_stage"] == {"writer": 1, "x_publish": 2} and observed["late_after_close"] == 1
    assert observed["missing_price_inputs"] == [{"stage": "x_publish", "providers": ["x"], "requests": 2,
                                                 "required_inputs": [cost_inputs.STATEMENT_INPUTS["x"]]}]
    report = {"inputs": {"archives": [], "identity_reconciliation": {"status": "consistent"}, "rejected_billing_files": []},
              "supplied_billing": {"quarantined": [], "exact_duplicate_documents": 0, "exact_duplicate_items": 0,
                                   "documents": []},
              "reconciliation": {"unmatched_billing_items": [], "attempts_without_billing_item": [],
                                 "conflicting_matches": []},
              "observed": {"token_totals_status": "complete_for_retained_rows"},
              "retained_state_summary": {"operation_observations": observed}}
    codes = {row["code"]: row["count"] for row in reconciled_cost.discrepancies(report)}
    assert codes["production_requests_missing_price_input"] == 2
    assert codes["production_requests_after_operation_closed"] == 1
    assert codes["no_billing_evidence"] == 1


def test_operations_mirror_is_identical_and_renders_the_exact_inputs():
    script = '''
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { COST_INPUTS } from "./lib/cost-inputs.js";
      import { CostInputs } from "./app/components/CostPanel.js";
      const html = renderToStaticMarkup(React.createElement(CostInputs, {register: COST_INPUTS}));
      console.log(JSON.stringify({register: COST_INPUTS, html}));
    '''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT / "dashboard",
                            text=True, capture_output=True, check=True)
    value = json.loads(result.stdout)
    assert value["register"] == json.loads(json.dumps(cost_inputs.register()))
    html = value["html"]
    assert "No monthly provider ceiling is enforced" in html and "never added together" in html
    assert "theheat.billing-export-profile/v1 JSON profile" in html
    assert "X developer account plan statement" in html and "Vercel usage/invoice" in html
