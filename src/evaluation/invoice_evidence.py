"""Operator-supplied billing evidence and conservative identifier-only reconciliation.

``theheat.billing-evidence/v1`` is a bounded local JSON contract that a person
fills from documents they hold. It is NOT a parser for any live provider export.
Authenticity and coverage are the operator's assertions. An optional original
document is hashed only when explicitly supplied on the command line; a path
inside the JSON is never followed (paths are not even a field).

Matching uses only stable identifiers within a compatible provider, account,
project and period. Similar token totals, text, model or time never match;
aggregate money is never distributed over calls; currencies are never
converted; an unmatched item is not evidence of an unpaid call, and a response
without a billing item is not evidence of a free one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Any, Iterable

from src.two_bot.request_archive import canonical_json, sha256_hex, strict_json_loads

SCHEMA = "theheat.billing-evidence/v1"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 100_000
_DECIMAL = re.compile(r"\A-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,12})?\Z")
_QUANTITY = re.compile(r"\A(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,12})?\Z")
_ID = re.compile(r"\A[A-Za-z0-9_.:/@-]{1,200}\Z")
_CURRENCY = re.compile(r"\A[A-Z]{3}\Z")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
PROVIDERS = ("anthropic", "google")
COVERAGE = ("asserted_complete_for_scope_and_period", "asserted_partial", "unknown")
KINDS = ("charge", "credit", "tax", "adjustment")
_TOP = {"schema", "document", "provider", "scope", "currency", "period", "coverage", "statement", "items", "totals"}
_ITEM = {"item_id", "kind", "amount", "quantity", "quantity_unit", "model", "provider_request_id",
         "provider_response_id", "occurred_at"}


class BillingEvidenceInvalid(ValueError):
    """Fixed code; never echoes supplied values."""


def _aware(value: Any) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise BillingEvidenceInvalid("time_not_string")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise BillingEvidenceInvalid("time_unparseable") from None
    if moment.utcoffset() is None:
        raise BillingEvidenceInvalid("time_not_aware")
    return moment.astimezone(timezone.utc)


def _ident(value: Any, code: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not _ID.fullmatch(value):
        raise BillingEvidenceInvalid(code)
    return value


def _money(value: Any, code: str) -> Decimal:
    if type(value) is not str or not _DECIMAL.fullmatch(value):
        raise BillingEvidenceInvalid(code)
    try:
        return Decimal(value)
    except InvalidOperation:  # pragma: no cover - regex guards this
        raise BillingEvidenceInvalid(code) from None


def _sum_money(values: Iterable[str | Decimal]) -> Decimal:
    """Exact bounded decimal addition without depending on the ambient context."""
    numbers = [Decimal(value) for value in values]
    if not numbers:
        return Decimal(0)
    integer_digits = max(max(1, number.adjusted() + 1) for number in numbers)
    fractional_digits = max(max(0, -int(number.as_tuple().exponent)) for number in numbers)
    with localcontext() as context:
        context.prec = max(28, integer_digits + fractional_digits + len(str(len(numbers))) + 2)
        return sum(numbers, Decimal(0))


def parse_billing_evidence(data: bytes, *, original_document: bytes | None = None) -> dict:
    """Validate one supplied document; return a normalized, content-hashed view."""
    if type(data) is not bytes or len(data) > MAX_FILE_BYTES:
        raise BillingEvidenceInvalid("billing_file_over_limit")
    try:
        raw = strict_json_loads(data)  # Floats/NaN/duplicates refused: money is decimal text.
    except (ValueError, UnicodeError):
        raise BillingEvidenceInvalid("billing_json_invalid") from None
    if type(raw) is not dict or set(raw) - _TOP or not {"schema", "document", "provider", "scope", "currency",
                                                        "period", "coverage", "statement"} <= set(raw):
        raise BillingEvidenceInvalid("billing_shape")
    if raw["schema"] != SCHEMA:
        raise BillingEvidenceInvalid("billing_schema_version")
    document = raw["document"]
    if type(document) is not dict or set(document) - {"id", "sha256"} or "id" not in document:
        raise BillingEvidenceInvalid("document_shape")
    document_id = _ident(document["id"], "document_id")
    declared = document.get("sha256")
    if declared is not None and (type(declared) is not str or not _HEX64.fullmatch(declared)):
        raise BillingEvidenceInvalid("document_sha256_shape")
    document_check = "not_supplied"
    if original_document is not None:
        if declared is None:
            raise BillingEvidenceInvalid("document_supplied_without_declared_sha256")
        if sha256_hex(original_document) != declared:
            raise BillingEvidenceInvalid("document_sha256_mismatch")
        document_check = "matched_explicit_file"
    if raw["provider"] not in PROVIDERS:
        raise BillingEvidenceInvalid("provider_unsupported")
    scope = raw["scope"]
    if type(scope) is not dict or set(scope) - {"account", "project"} or "account" not in scope:
        raise BillingEvidenceInvalid("scope_shape")
    account = _ident(scope["account"], "scope_account")
    project = _ident(scope.get("project"), "scope_project", optional=True)
    if type(raw["currency"]) is not str or not _CURRENCY.fullmatch(raw["currency"]):
        raise BillingEvidenceInvalid("currency_unknown")
    period = raw["period"]
    if type(period) is not dict or set(period) != {"start", "end"}:
        raise BillingEvidenceInvalid("period_shape")
    start, end = _aware(period["start"]), _aware(period["end"])
    if not start < end:
        raise BillingEvidenceInvalid("period_not_ordered")
    coverage = raw["coverage"]
    if (type(coverage) is not dict or set(coverage) != {"assertion", "asserted_by"}
            or coverage["assertion"] not in COVERAGE or coverage["asserted_by"] != "operator"):
        raise BillingEvidenceInvalid("coverage_assertion")
    statement = raw["statement"]
    if statement not in ("itemized", "aggregate"):
        raise BillingEvidenceInvalid("statement_type")
    items: list[dict] = []
    if statement == "itemized":
        if "totals" in raw or type(raw.get("items")) is not list or len(raw["items"]) > MAX_ITEMS:
            raise BillingEvidenceInvalid("itemized_shape")
        seen: dict[str, bytes] = {}
        for item in raw["items"]:
            normalized = _item(item, start, end)
            encoded = canonical_json(normalized)
            previous = seen.get(normalized["item_id"])
            if previous is not None and previous != encoded:
                raise BillingEvidenceInvalid("item_id_conflict_within_document")
            if previous is None:
                seen[normalized["item_id"]] = encoded
                items.append(normalized)
    else:
        if "items" in raw or type(raw.get("totals")) is not dict:
            raise BillingEvidenceInvalid("aggregate_shape")
        totals = raw["totals"]
        if set(totals) - {"charges", "credits", "net"} or "net" not in totals:
            raise BillingEvidenceInvalid("aggregate_totals_shape")
        parsed = {key: _money(value, "aggregate_amount") for key, value in totals.items()}
        if "credits" in parsed and parsed["credits"] > 0:
            raise BillingEvidenceInvalid("credit_must_not_be_positive")
        if {"charges", "credits"} <= set(parsed) and _sum_money([parsed["charges"], parsed["credits"]]) != parsed["net"]:
            raise BillingEvidenceInvalid("aggregate_totals_inconsistent")
    body = {"schema": SCHEMA, "document_id": document_id, "declared_document_sha256": declared,
            "document_check": document_check, "provider": raw["provider"],
            "scope": {"account": account, "project": project}, "currency": raw["currency"],
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "coverage": {"assertion": coverage["assertion"], "authority": "operator_assertion_only"},
            "statement": statement, "items": items,
            "totals": ({k: str(_money(v, "aggregate_amount")) for k, v in sorted(raw["totals"].items())}
                       if statement == "aggregate" else _item_totals(items))}
    return {**body, "evidence_sha256": sha256_hex(canonical_json(body)), "file_sha256": sha256_hex(data)}


def _item(item: Any, start: datetime, end: datetime) -> dict:
    if type(item) is not dict or set(item) - _ITEM or not {"item_id", "kind", "amount"} <= set(item):
        raise BillingEvidenceInvalid("item_shape")
    kind = item["kind"]
    if kind not in KINDS:
        raise BillingEvidenceInvalid("item_kind")
    amount = _money(item["amount"], "item_amount")
    if kind == "credit" and amount > 0:
        raise BillingEvidenceInvalid("credit_must_not_be_positive")
    quantity = item.get("quantity")
    if quantity is not None and (type(quantity) is not str or not _QUANTITY.fullmatch(quantity)):
        raise BillingEvidenceInvalid("item_quantity")
    unit = item.get("quantity_unit")
    if (quantity is None) != (unit is None):
        raise BillingEvidenceInvalid("item_quantity_unit")
    occurred = item.get("occurred_at")
    if occurred is not None:
        moment = _aware(occurred)
        if not start <= moment < end:
            raise BillingEvidenceInvalid("item_outside_period")
        occurred = moment.isoformat()
    return {"item_id": _ident(item["item_id"], "item_id"), "kind": kind, "amount": str(amount),
            "quantity": quantity, "quantity_unit": _ident(unit, "item_quantity_unit", optional=True),
            "model": _ident(item.get("model"), "item_model", optional=True),
            "provider_request_id": _ident(item.get("provider_request_id"), "item_request_id", optional=True),
            "provider_response_id": _ident(item.get("provider_response_id"), "item_response_id", optional=True),
            "occurred_at": occurred}


def _item_totals(items: list[dict]) -> dict:
    charges = _sum_money(i["amount"] for i in items if Decimal(i["amount"]) > 0)
    credits = _sum_money(i["amount"] for i in items if Decimal(i["amount"]) < 0)
    return {"charges": str(charges), "credits": str(credits), "net": str(_sum_money([charges, credits]))}


def parse_account_binding(value: str) -> dict:
    """``provider:account[:project]`` — the operator's assertion of where archived calls ran."""
    parts = value.split(":") if type(value) is str else []
    if len(parts) not in (2, 3) or parts[0] not in PROVIDERS:
        raise BillingEvidenceInvalid("account_binding_shape")
    return {"provider": parts[0], "account": _ident(parts[1], "account_binding_account"),
            "project": _ident(parts[2], "account_binding_project") if len(parts) == 3 else None,
            "authority": "operator_assertion_only"}


def _scope_key(document: dict) -> tuple:
    return (document["provider"], document["scope"]["account"], document["scope"]["project"],
            document["period"]["start"], document["period"]["end"], document["currency"])


def collect_documents(documents: list[dict]) -> dict:
    """Dedupe exact repeats; quarantine conflicting same-identity evidence."""
    by_document: dict[tuple, list[dict]] = {}
    for document in documents:
        by_document.setdefault((document["provider"], document["scope"]["account"], document["document_id"]),
                               []).append(document)
    accepted, quarantined, duplicates = [], [], 0
    for key, group in sorted(by_document.items()):
        hashes = {d["evidence_sha256"] for d in group}
        if len(hashes) > 1:
            quarantined.append({"reason": "conflicting_document_identity", "document_id": key[2],
                                "provider": key[0], "evidence_sha256": sorted(hashes)})
            continue
        duplicates += len(group) - 1
        accepted.append(group[0])
    items: dict[tuple, list[tuple[dict, dict]]] = {}
    for document in accepted:
        for item in document["items"]:
            items.setdefault((*_scope_key(document), item["item_id"]), []).append((document, item))
    item_rows, item_duplicates = [], 0
    for item_key, entries in sorted(items.items(), key=lambda pair: tuple("" if v is None else v for v in pair[0])):
        encodings = {canonical_json(item) for _, item in entries}
        if len(encodings) > 1:
            quarantined.append({"reason": "conflicting_item_identity", "item_id": item_key[-1],
                                "provider": item_key[0], "account": item_key[1], "project": item_key[2],
                                "period": {"start": item_key[3], "end": item_key[4]}, "currency": item_key[5],
                                "documents": sorted({d["document_id"] for d, _ in entries})})
            continue
        item_duplicates += len(entries) - 1
        document, item = entries[0]
        item_rows.append({"document_id": document["document_id"], "provider": document["provider"],
                          "account": document["scope"]["account"], "project": document["scope"]["project"],
                          "currency": document["currency"], "period": document["period"], **item})
    return {"documents": accepted, "items": item_rows, "quarantined": quarantined,
            "exact_duplicate_documents": duplicates, "exact_duplicate_items": item_duplicates}


def _in_period(moment: str | None, period: dict) -> bool:
    if moment is None:
        return False
    at = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return datetime.fromisoformat(period["start"]) <= at < datetime.fromisoformat(period["end"])


def reconcile(usage: dict, collected: dict, bindings: list[dict], scenario: dict | None = None) -> dict:
    """Join billing items to archived responses ONLY by actual stable identifiers."""
    bound = {(b["provider"], b["account"], b["project"]) for b in bindings}
    index: dict[tuple[str, str, str], list[dict]] = {}
    for row in usage["attempts"]:
        for role, value in _typed_ids(row).items():
            index.setdefault((row["provider"], role, value), []).append(row)
    matches, unmatched, conflicts = [], [], []
    matched_attempts: set[tuple] = set()
    for item in collected["items"]:
        identifiers = {role: item[role] for role in ("provider_request_id", "provider_response_id") if item[role]}
        if not identifiers:
            unmatched.append({**_item_ref(item), "reason": "no_provider_identifier_supplied"})
            continue
        if (item["provider"], item["account"], item["project"]) not in bound:
            unmatched.append({**_item_ref(item), "reason": "archive_account_scope_not_bound"})
            continue
        if len({scope for scope in bound if scope[0] == item["provider"]}) != 1:
            unmatched.append({**_item_ref(item), "reason": "archive_account_scope_ambiguous"})
            continue
        found = {(r["scope_id"], r["call"], r["attempt"]): r
                 for role, value in identifiers.items() for r in index.get((item["provider"], role, value), [])}
        if not found:
            unmatched.append({**_item_ref(item), "reason": "identifier_not_in_supplied_archives"})
            continue
        if len(found) > 1 or any(r["provider_id_conflict"] for r in found.values()):
            conflicts.append({**_item_ref(item), "reason": "identifier_matches_multiple_responses",
                              "attempts": [list(key) for key in sorted(found)]})
            continue
        key, row = next(iter(found.items()))
        actual = _typed_ids(row)
        if any(role in actual and actual[role] != value for role, value in identifiers.items()):
            conflicts.append({**_item_ref(item), "reason": "contradictory_provider_identifiers", "attempts": [list(key)]})
            continue
        if not _in_period(row["response_recorded_at"] or row["sent_at"], item["period"]):
            unmatched.append({**_item_ref(item), "reason": "response_outside_billing_period"})
            continue
        if key in matched_attempts:
            conflicts.append({**_item_ref(item), "reason": "response_already_matched_by_another_item",
                              "attempts": [list(key)]})
            continue
        matched_attempts.add(key)
        matches.append({**_item_ref(item), "scope_id": key[0], "call": key[1], "attempt": key[2],
                        "stage": row["stage"], "matched_on": sorted(
                            name for name, value in (("provider_request_id", item["provider_request_id"]),
                                                     ("provider_response_id", item["provider_response_id"]))
                            if value and actual.get(name) == value),
                        "usage_status": row["usage_status"], "billed_amount": item["amount"],
                        "currency": item["currency"]})
    without_item = [{"scope_id": r["scope_id"], "call": r["call"], "attempt": r["attempt"], "stage": r["stage"],
                     "provider": r["provider"], "send_outcome": r["send_outcome"],
                     "interpretation": "no_supplied_billing_item_is_not_evidence_of_free_usage"}
                    for r in usage["attempts"] if (r["scope_id"], r["call"], r["attempt"]) not in matched_attempts]
    return {"matches": matches, "unmatched_billing_items": unmatched, "conflicting_matches": conflicts,
            "attempts_without_billing_item": without_item,
            "aggregate_comparisons": _aggregates(usage, collected, scenario, bound),
            "billed_totals_by_scope": _billed_totals(collected),
            "interpretation": {"unmatched_item": "not_evidence_of_an_unpaid_call",
                               "attempt_without_item": "not_evidence_of_a_free_call",
                               "matching": "stable_provider_identifiers_and_bound_scope_only"}}


def _item_ref(item: dict) -> dict:
    return {"document_id": item["document_id"], "item_id": item["item_id"], "provider": item["provider"],
            "account": item["account"], "project": item["project"]}


def _typed_ids(row: dict) -> dict:
    ids = row["provider_ids"]
    result = {}
    if row["provider"] == "anthropic" and ids.get("request_id_header"):
        result["provider_request_id"] = ids["request_id_header"]
    body_key = "response_body_id" if row["provider"] == "anthropic" else "response_body_responseId"
    if ids.get(body_key):
        result["provider_response_id"] = ids[body_key]
    return result


def _billed_totals(collected: dict) -> list[dict]:
    itemized: dict[tuple, list[dict]] = {}
    aggregates = []
    for document in collected["documents"]:
        key = _scope_key(document)
        if document["statement"] == "itemized":
            itemized.setdefault(key, [])
        else:
            # Different aggregate documents may overlap. Never add their assertions together.
            aggregates.append({"provider": key[0], "account": key[1], "project": key[2],
                               "period": document["period"], "currency": key[5], "statement": "aggregate",
                               "document_id": document["document_id"], "basis": "individual_supplied_statement",
                               **{name: document["totals"].get(name) for name in ("charges", "credits", "net")}})
    for item in collected["items"]:
        key = (item["provider"], item["account"], item["project"], item["period"]["start"],
               item["period"]["end"], item["currency"])
        itemized[key].append(item)
    rows = []
    for key, items in sorted(itemized.items(), key=lambda pair: tuple("" if v is None else v for v in pair[0])):
        conflicts = sum(q["reason"] == "conflicting_item_identity" and
                        (q["provider"], q["account"], q["project"], q["period"]["start"], q["period"]["end"],
                         q["currency"]) == key for q in collected["quarantined"])
        subtotal = _item_totals(items)
        rows.append({"provider": key[0], "account": key[1], "project": key[2],
                     "period": {"start": key[3], "end": key[4]}, "currency": key[5], "statement": "itemized",
                     "basis": "deduplicated_nonconflicting_items", "incomplete": bool(conflicts),
                     "quarantined_item_count": conflicts,
                     **({name: None for name in subtotal} if conflicts else subtotal),
                     "accepted_item_subtotal": subtotal if conflicts else None})
    return rows + sorted(aggregates, key=lambda row: (row["provider"], row["account"], row["project"] or "",
                                                     row["document_id"]))


def _aggregates(usage: dict, collected: dict, scenario: dict | None, bound: set) -> list[dict]:
    """Side by side only: billed money vs archive counts/scenario in that period."""
    rows = []
    for document in collected["documents"]:
        if document["statement"] != "aggregate":
            continue
        period = document["period"]
        inside = [r for r in usage["attempts"] if r["provider"] == document["provider"]
                  and _in_period(r["response_recorded_at"] or r["sent_at"], period)]
        scenario_rows = []
        if scenario is not None and document["currency"] == scenario["currency"]:
            keys = {(r["scope_id"], r["call"], r["attempt"]) for r in inside}
            scenario_rows = [s for s in scenario["rows"] if (s["scope_id"], s["call"], s["attempt"]) in keys
                             and s["disposition"] == "eligible"]
        rows.append({"document_id": document["document_id"], "provider": document["provider"],
                     "account": document["scope"]["account"], "currency": document["currency"],
                     "period": period, "billed": document["totals"],
                     "archive_physical_attempts_in_period": len(inside),
                     "archive_responses_in_period": sum(1 for r in inside if r["send_outcome"] == "response_received"),
                     "archive_unknown_outcomes_in_period": sum(1 for r in inside if r["send_outcome"] == "unknown"),
                     "named_scenario": scenario["scenario"] if scenario is not None and scenario_rows else None,
                     "scenario_token_component_usd": ({
                         "min": str(_sum_money(s["token_component_usd"]["min"] for s in scenario_rows)),
                         "max": str(_sum_money(s["token_component_usd"]["max"] for s in scenario_rows))}
                         if scenario_rows else None),
                     "allocation": "none_aggregate_money_is_never_distributed_over_calls",
                     "archive_account_binding": (
                         "ambiguous_bindings_counts_may_include_other_accounts" if len(
                             {scope for scope in bound if scope[0] == document["provider"]}) > 1 else
                         "operator_asserted" if (document["provider"], document["scope"]["account"],
                                                 document["scope"]["project"]) in bound
                         else "unbound_counts_may_include_other_accounts")})
    return rows


# ------------------------------------------------------------------ reports

REPORT_SCHEMA = "theheat.archive-reconciliation/v1"
REPORT_LIMITS = [
    "Only calls retained in the supplied private archives; never an account, monthly or invoice total.",
    "Billing documents are operator-supplied evidence; authenticity and coverage are operator assertions.",
    "Matching uses stable provider identifiers within an operator-asserted account binding only.",
    "Aggregate statements are compared side by side; money is never allocated to individual calls.",
    "Price scenarios are fixed named token scenarios, not billed amounts, allowances or savings.",
    "Missing usage, missing responses and unknown send outcomes are never zero cost.",
    "No result settles a reservation, enforces a ceiling, changes configuration or grants approval.",
]


def report_bytes(report: dict) -> bytes:
    import json
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")


def _report_identity(report: dict) -> str:
    import json
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    return sha256_hex(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                 allow_nan=False).encode("utf-8"))


def build_report(*, as_of: datetime, usage: dict, documents: list[dict], rejected_billing: list[dict],
                 bindings: list[dict], scenario: dict | None, state_summary: dict | None,
                 input_files: list[dict]) -> dict:
    collected = collect_documents(documents)
    joined = reconcile(usage, collected, bindings, scenario)
    report = {
        "schema": REPORT_SCHEMA, "as_of": as_of.isoformat(),
        "inputs": {"files": sorted(input_files, key=lambda f: (f["role"], f["sha256"])),
                   "archives": usage["sources"], "account_bindings": bindings,
                   "rejected_billing_files": rejected_billing},
        "observed": {"denominators": usage["denominators"], "calls": usage["calls"],
                     "token_totals": usage["token_totals"]},
        "usage_attempts": [{key: value for key, value in row.items() if key != "observation"}
                           for row in usage["attempts"]],
        "priced_scenario": scenario,
        "supplied_billing": {"documents": [{key: value for key, value in d.items() if key != "items"}
                                           for d in collected["documents"]],
                             "items": collected["items"], "quarantined": collected["quarantined"],
                             "exact_duplicate_documents": collected["exact_duplicate_documents"],
                             "exact_duplicate_items": collected["exact_duplicate_items"],
                             "billed_totals_by_scope": joined["billed_totals_by_scope"]},
        "reconciliation": {key: joined[key] for key in ("matches", "unmatched_billing_items",
                                                        "conflicting_matches", "attempts_without_billing_item",
                                                        "aggregate_comparisons", "interpretation")},
        "retained_state_summary": state_summary,
        "coverage": {"archive_statuses": sorted({s["status"] for s in usage["sources"]}),
                     "billing_coverage_assertions": sorted({d["coverage"]["assertion"]
                                                            for d in collected["documents"]}),
                     "complete_account_coverage": False, "actual_cost_known": False},
        "authority": {"settles_reservations": False, "enforces_ceiling": False, "changes_configuration": False,
                      "grants_approval": False, "billing_truth": "operator_supplied_assertion"},
        "limitations": list(REPORT_LIMITS),
    }
    report["report_sha256"] = _report_identity(report)
    return report


def verify_report(report: Any) -> dict:
    if type(report) is not dict or report.get("schema") != REPORT_SCHEMA:
        raise BillingEvidenceInvalid("report_schema")
    if report.get("report_sha256") != _report_identity(report):
        raise BillingEvidenceInvalid("report_identity_mismatch")
    return report


def _cell(value: Any, limit: int = 160) -> str:
    text = ("—" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")
    # A view cell may be shortened, but never silently: the JSON report is complete.
    return text if len(text) <= limit else text[:limit - 1] + "…"



def render_markdown(report: dict) -> str:
    """Bounded, content-free private Markdown view of a verified report."""
    verify_report(report)
    observed = report["observed"]["denominators"]
    lines = [f"# Private archive reconciliation ({report['report_sha256'][:12]})", "",
             f"As of `{report['as_of']}`. Report sha256 `{report['report_sha256']}`.", "",
             "Evidence classes stay separate: observed attempts, parsed usage, a named price scenario, "
             "operator-supplied billing and identifier matches. None certifies another.", "",
             "## Inputs", "", "| role | sha256 | bytes |", "|---|---|---|"]
    lines += [f"| {_cell(f['role'])} | `{f['sha256']}` | {f['bytes']} |" for f in report["inputs"]["files"]]
    lines += ["", "| archive scope | status | problems |", "|---|---|---|"]
    lines += [f"| {_cell(a['scope_id'])} | {a['status']} | {_cell(', '.join(a['problems']) or 'none')} |"
              for a in report["inputs"]["archives"]]
    lines += ["", "## Observed (separate denominators)", "", "| measure | count |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in sorted(observed.items())]
    lines += ["", "## Provider-reported usage (present, valid, non-conflicting only)", "",
              "Counts sum reported values (zero is reported zero); `missing` counts responses lacking the field. "
              "Cells ending in … are shortened views; the JSON report is complete.", "",
              "| provider | stage | model | responses | counts | missing |", "|---|---|---|---|---|---|"]
    for group in report["observed"]["token_totals"]:
        # Sorted: the view must not depend on dict insertion order (JSON round trips sort keys).
        counts = ", ".join(f"{k}={v}" for k, v in sorted(group["counts"].items())
                           if group["missing_counts"][k] < group["responses"])
        missing = ", ".join(f"{k}:{v}" for k, v in sorted(group["missing_counts"].items()) if v)
        lines.append(f"| {group['provider']} | {group['stage']} | {_cell(group['model'])} | {group['responses']} | "
                     f"{_cell(counts or 'none')} | {_cell(missing or 'none')} |")
    scenario = report["priced_scenario"]
    lines += ["", "## Named price scenario (not billed)", ""]
    if scenario is None:
        lines.append("No scenario was requested.")
    else:
        amount = scenario["token_component_usd"]
        lines.append(f"Scenario `{scenario['scenario']}`: {scenario['eligible_rows']} eligible, "
                     f"{scenario['excluded_rows']} excluded; token component "
                     + (f"{amount['min']}–{amount['max']} USD." if amount else "unavailable."))
    billing = report["supplied_billing"]
    lines += ["", "## Operator-supplied billing (assertions)", "",
              "| provider | account | period | currency | statement | charges | credits | net |",
              "|---|---|---|---|---|---|---|---|"]
    for row in billing["billed_totals_by_scope"]:
        lines.append(f"| {row['provider']} | {_cell(row['account'])} | {row['period']['start']} → "
                     f"{row['period']['end']} | {row['currency']} | {row['statement']} | {_cell(row['charges'])} | "
                     f"{_cell(row['credits'])} | {_cell(row['net'])} |")
        if row.get("incomplete"):
            lines.append(f"\nScope has {row['quarantined_item_count']} quarantined item identities; total unknown. "
                         f"Accepted unique-item subtotal: {row['accepted_item_subtotal']['net']} {row['currency']}.\n")
    rec = report["reconciliation"]
    lines += ["", "## Reconciliation", "",
              f"- Identifier matches: {len(rec['matches'])}",
              f"- Unmatched billing items: {len(rec['unmatched_billing_items'])} (not evidence of unpaid calls)",
              f"- Conflicting matches: {len(rec['conflicting_matches'])}",
              f"- Quarantined billing evidence: {len(billing['quarantined'])}",
              f"- Attempts without a billing item: {len(rec['attempts_without_billing_item'])} "
              "(not evidence of free calls)", ""]
    if rec["matches"]:
        lines += ["| document | item | call | attempt | stage | billed | usage |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {_cell(m['document_id'])} | {_cell(m['item_id'])} | {m['call']} | {m['attempt']} | "
                  f"{m['stage']} | {m['billed_amount']} {m['currency']} | {m['usage_status']} |"
                  for m in rec["matches"]]
    if rec["unmatched_billing_items"] or rec["conflicting_matches"] or billing["quarantined"]:
        lines += ["", "| kind | document | item | reason |", "|---|---|---|---|"]
        lines += [f"| unmatched | {_cell(u['document_id'])} | {_cell(u['item_id'])} | {u['reason']} |"
                  for u in rec["unmatched_billing_items"]]
        lines += [f"| conflict | {_cell(c['document_id'])} | {_cell(c['item_id'])} | {c['reason']} |"
                  for c in rec["conflicting_matches"]]
        lines += [f"| quarantined | {_cell(q.get('document_id') or ', '.join(q.get('documents', [])))} | "
                  f"{_cell(q.get('item_id'))} | {q['reason']} |" for q in billing["quarantined"]]
    for comparison in rec["aggregate_comparisons"]:
        lines += ["", f"Aggregate document `{_cell(comparison['document_id'])}`: billed net "
                  f"{comparison['billed']['net']} {comparison['currency']}; archive attempts in period "
                  f"{comparison['archive_physical_attempts_in_period']} "
                  f"({comparison['archive_unknown_outcomes_in_period']} unknown); "
                  f"binding {comparison['archive_account_binding']}; no allocation."]
    lines += ["", "## Coverage and limits", ""] + [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"
