"""Cost-input register: what each spend route needs before its charge is known.

Every declared call stage (``call_inventory.DECLARATIONS``) and every hosting
service the bot runs on is listed per provider with three distinct kinds of
evidence, which are never added together:

* ``estimate`` — a retained price table applied to observed usage
  (``usage_ledger`` Anthropic table, ``usage_cost_scenario`` Gemini scenario);
* ``observation`` — provider-reported usage or a counted physical request;
* ``invoice`` — an authentic provider export imported by
  ``scripts/reconcile_request_archive.py import-export`` (Anthropic/Google) or,
  for providers without an import path, the exact owner statement named here.

``actual_charge_known`` is always False here: this register states inputs, it
does not price anything. A missing price is ``missing_price`` with the exact
input that would supply it, never zero. Watches, alerts and candidate caps are
not monthly provider ceilings (``ceilings`` repeats ``CEILING_KINDS``).
Mirrored by ``dashboard/lib/cost-inputs.js`` (parity-tested).
"""
from __future__ import annotations

from typing import Any

from src.two_bot.call_inventory import CEILING_KINDS, DECLARATIONS
from src.two_bot.usage_cost_scenario import _RATES as GEMINI_SCENARIO_RATES
from src.two_bot.usage_ledger import _PRICES_PER_MTOK as ANTHROPIC_PRICE_TABLE

SCHEMA_VERSION = 1
INVOICE_IMPORT_PROVIDERS = ("anthropic", "google")
BILLING_EXPORT_INPUT = {
    "kind": "billing_export_import",
    "command": "scripts/reconcile_request_archive.py import-export",
    "files": ["provider billing export CSV for one period",
              "theheat.billing-export-profile/v1 JSON profile"],
    "profile_required_fields": ["schema", "provider", "scope", "currency", "period", "coverage", "columns"],
    "profile_columns": {"required": ["amount"],
                        "optional": ["item_id", "currency", "kind", "quantity", "quantity_unit", "model",
                                     "provider_request_id", "provider_response_id", "occurred_at"]},
}
# Providers without an import path: the exact owner statement that would close the gap.
STATEMENT_INPUTS: dict[str, str] = {
    "x": "X developer account plan statement for the period: plan name, period start/end, amount and currency "
         "(or the provider's written no-charge tier for that account and period)",
    "bluesky": "Owner statement that the account incurs no API charge for the period, or the charge document",
    "github": "GitHub billing usage report for the account and period (Actions minutes, storage, API), with "
              "amount and currency, or the plan statement showing the included allowance",
    "vercel": "Vercel usage/invoice for the dashboard project and period, with amount and currency",
    "publisher": "No provider bill is expected for public page reads; owner confirmation for the period that "
                 "no paid access, proxy or egress plan is used",
    "source": "Per-source data plan or terms statement for the period (public feeds: owner confirmation that "
              "no paid plan is used; paid feeds: the plan invoice)",
    "noaa": "Owner confirmation that NOAA bulk downloads use public no-charge access for the period, plus the "
            "runner-minutes statement (github) for the job",
}
# Hosting the bot runs on that is not a per-call declaration.
HOSTING_SERVICES: tuple[dict, ...] = (
    {"service": "github_actions_runner_minutes", "provider": "github", "spend_class": "hosting",
     "observed_by": "workflow run history (not retained in state)"},
    {"service": "vercel_dashboard_hosting", "provider": "vercel", "spend_class": "hosting",
     "observed_by": "not observed by the bot"},
)


def _estimate(stage: str, provider: str, physical_call: str, unpriced: tuple[str, ...]) -> dict:
    if provider == "anthropic" and physical_call == "sdk_generate":
        return {"basis": "anthropic_price_table", "models": sorted(ANTHROPIC_PRICE_TABLE),
                "unpriced": sorted(set(unpriced) | {"other_models"})}
    if provider == "google" and physical_call == "sdk_generate":
        return {"basis": "gemini_token_scenario", "models": sorted(GEMINI_SCENARIO_RATES),
                "unpriced": sorted(set(unpriced) | {"tool_and_grounding_charges", "other_models"})}
    # Batch never borrows synchronous rates; platforms, data and hosting have no table.
    return {"basis": "missing_price", "models": [], "unpriced": sorted(set(unpriced) | {"all_charges"})}


def _invoice(provider: str) -> dict:
    if provider in INVOICE_IMPORT_PROVIDERS:
        return {"path": "billing_export_import", "required_input": BILLING_EXPORT_INPUT["kind"]}
    return {"path": "supplied_statement_required", "required_input": STATEMENT_INPUTS[provider]}


def register() -> dict:
    """Stable, content-free statement of inputs; no prices are fetched or invented."""
    rows: list[dict[str, Any]] = []
    for stage, found in DECLARATIONS.items():
        for provider in found.providers:
            sdk = found.physical_call.startswith("sdk_") and provider in INVOICE_IMPORT_PROVIDERS
            rows.append({"stage": stage, "provider": provider, "spend_class": found.spend_class,
                         "pricing": found.pricing,
                         "estimate": _estimate(stage, provider, found.physical_call, found.unpriced_dimensions),
                         "observation": "provider_reported_usage" if sdk else "counted_physical_request",
                         "invoice": _invoice(provider), "actual_charge_known": False})
    for service in HOSTING_SERVICES:
        rows.append({"stage": service["service"], "provider": service["provider"],
                     "spend_class": service["spend_class"], "pricing": "unknown",
                     "estimate": {"basis": "missing_price", "models": [], "unpriced": ["all_charges"]},
                     "observation": service["observed_by"], "invoice": _invoice(service["provider"]),
                     "actual_charge_known": False})
    missing = sorted({(row["provider"], row["invoice"]["path"]) for row in rows
                      if row["invoice"]["path"] != "billing_export_import"})
    return {"schema_version": SCHEMA_VERSION, "actual_charge_known": False,
            "evidence_kinds": ["estimate", "observation", "invoice"], "evidence_added_together": False,
            "billing_export_input": BILLING_EXPORT_INPUT, "rows": rows,
            "statement_required_providers": [provider for provider, _ in missing],
            "ceilings": {name: {"financial_cap": bool(kind.get("financial_cap")), "enforced": bool(kind.get("enforced"))}
                         for name, kind in CEILING_KINDS.items()},
            "monthly_provider_ceiling_enforced": False}


def missing_price_inputs(observed_stages: dict[str, int]) -> list[dict]:
    """One row per observed stage with no price table: its requests and exact missing inputs.

    Requests are per stage (a joined row does not name every provider), so a
    stage is listed once and its count is never repeated per provider.
    """
    grouped: dict[str, dict] = {}
    for row in register()["rows"]:
        count = observed_stages.get(row["stage"], 0)
        if count and row["estimate"]["basis"] == "missing_price":
            entry = grouped.setdefault(row["stage"], {"stage": row["stage"], "providers": [], "requests": count,
                                                      "required_inputs": []})
            entry["providers"].append(row["provider"])
            entry["required_inputs"].append(row["invoice"]["required_input"])
    return [grouped[stage] for stage in sorted(grouped)]


MIRROR = "dashboard/lib/cost-inputs.js"


def render_mirror() -> str:
    import json
    return ("// Mirror of src/two_bot/cost_inputs.register(); parity-tested by\n"
            "// tests/final_closure/test_cost_inputs.py. States inputs only: no price, no total.\n"
            "export const COST_INPUTS = " + json.dumps(register(), indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    """``python -m src.two_bot.cost_inputs --check|--write`` (after a declaration change)."""
    import sys
    from pathlib import Path
    args = sys.argv[1:] if argv is None else argv
    target = Path(__file__).resolve().parents[2] / MIRROR
    if args == ["--write"]:
        target.write_text(render_mirror())
        return 0
    if args == ["--check"]:
        current = target.read_text() if target.exists() else ""
        if current != render_mirror():
            print(f"{MIRROR} is stale; run python -m src.two_bot.cost_inputs --write")
            return 1
        return 0
    print("usage: python -m src.two_bot.cost_inputs --check|--write")
    return 2


__all__ = ["BILLING_EXPORT_INPUT", "HOSTING_SERVICES", "INVOICE_IMPORT_PROVIDERS", "MIRROR", "STATEMENT_INPUTS",
           "main", "missing_price_inputs", "register", "render_mirror"]


if __name__ == "__main__":
    raise SystemExit(main())
