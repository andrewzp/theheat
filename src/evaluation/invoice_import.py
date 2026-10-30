"""Bounded local import of an owner-supplied billing export into billing-evidence v1.

The owner holds a provider export (CSV) and writes a small profile
(``theheat.billing-export-profile/v1``) naming its columns, the provider,
account/project, currency, account period and the operator's coverage
assertion. This module never reads a path from the profile, logs in, scrapes,
fetches, converts currencies or infers a column: an unmapped dimension stays
absent. The original export bytes are bound by sha256 (``document.sha256``) so
the existing reconciler re-verifies them (``document_check``).

Rows are kept separate by class: charges, credits/refunds (negative amounts),
zero-charge lines, rows outside the account period (excluded, counted) and
identical rows without a provider line id (kept, flagged as possible duplicate
exports). The same line id with different content is refused, never merged.
A future authentic export needs only a profile, not another integration.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import io
import re
from typing import Any

from src.evaluation.invoice_evidence import (
    COVERAGE, MAX_FILE_BYTES, MAX_ITEMS, PROVIDERS, SCHEMA, BillingEvidenceInvalid, _aware, _ident, _money,
    parse_billing_evidence,
)
from src.two_bot.request_archive import canonical_json, sha256_hex, strict_json_loads

PROFILE_SCHEMA = "theheat.billing-export-profile/v1"
MAX_PROFILE_BYTES = 64 * 1024
FIELDS = ("item_id", "amount", "currency", "kind", "quantity", "quantity_unit", "model", "provider_request_id",
          "provider_response_id", "occurred_at")
_PROFILE = {"schema", "provider", "scope", "currency", "period", "coverage", "columns", "kind_values", "delimiter"}
_HEADER = re.compile(r"\A[^\x00-\x1f]{1,120}\Z")


def _profile(data: bytes) -> dict:
    if type(data) is not bytes or len(data) > MAX_PROFILE_BYTES:
        raise BillingEvidenceInvalid("export_profile_over_limit")
    try:
        raw = strict_json_loads(data)
    except (ValueError, UnicodeError):
        raise BillingEvidenceInvalid("export_profile_json_invalid") from None
    if type(raw) is not dict or set(raw) - _PROFILE or not {"schema", "provider", "scope", "currency", "period",
                                                             "coverage", "columns"} <= set(raw):
        raise BillingEvidenceInvalid("export_profile_shape")
    if raw["schema"] != PROFILE_SCHEMA:
        raise BillingEvidenceInvalid("export_profile_schema")
    if raw["provider"] not in PROVIDERS or raw["coverage"] not in COVERAGE:
        raise BillingEvidenceInvalid("export_profile_provider_or_coverage")
    columns = raw["columns"]
    if (type(columns) is not dict or set(columns) - set(FIELDS) or "amount" not in columns
            or not all(type(v) is str and _HEADER.fullmatch(v) for v in columns.values())
            or len(set(columns.values())) != len(columns)):
        raise BillingEvidenceInvalid("export_profile_columns")
    kinds = raw.get("kind_values", {})
    if (type(kinds) is not dict or set(kinds) - {"charge", "credit", "tax", "adjustment"}
            or not all(type(v) is list and all(type(x) is str and 0 < len(x) <= 80 for x in v) for v in kinds.values())
            or ("kind" in columns) != bool(kinds)):
        raise BillingEvidenceInvalid("export_profile_kind_values")
    labels = [label for values in kinds.values() for label in values]
    if len(labels) != len(set(labels)):
        raise BillingEvidenceInvalid("export_profile_kind_values")
    delimiter = raw.get("delimiter", ",")
    if delimiter not in (",", ";", "\t"):
        raise BillingEvidenceInvalid("export_profile_delimiter")
    return {**raw, "kind_values": kinds, "delimiter": delimiter}


def import_export(export: bytes, profile_bytes: bytes, *, document_id: str) -> tuple[bytes, dict]:
    """Return (billing-evidence v1 JSON bytes, content-free import report)."""
    if type(export) is not bytes or len(export) > MAX_FILE_BYTES:
        raise BillingEvidenceInvalid("export_over_limit")
    profile = _profile(profile_bytes)
    _ident(document_id, "document_id")
    start, end = _aware(profile["period"].get("start")), _aware(profile["period"].get("end"))
    try:
        text = export.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BillingEvidenceInvalid("export_not_utf8") from None
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=profile["delimiter"], strict=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        raise BillingEvidenceInvalid("export_header_missing") from None
    if len(header) != len(set(header)):
        raise BillingEvidenceInvalid("export_header_duplicate")
    columns = profile["columns"]
    missing = [name for name in columns.values() if name not in header]
    if missing:
        raise BillingEvidenceInvalid("export_header_unmapped_column")
    index = {field: header.index(name) for field, name in columns.items()}
    by_label = {label: kind for kind, labels in profile["kind_values"].items() for label in labels}
    report: dict[str, Any] = {"rows": 0, "items": 0, "charges": 0, "credits_or_refunds": 0, "zero_charge_items": 0,
              "rows_outside_period": 0, "possible_duplicate_rows": 0, "derived_item_ids": 0,
              "mapped_dimensions": sorted(columns), "unmapped_dimensions": sorted(set(FIELDS) - set(columns)),
              "currency_conversion": False, "export_sha256": sha256_hex(export)}
    items: dict[str, dict] = {}
    seen_rows: set[bytes] = set()
    try:
        for ordinal, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            report["rows"] += 1
            if report["rows"] > MAX_ITEMS:
                raise BillingEvidenceInvalid("export_rows_over_limit")
            if len(row) != len(header):
                raise BillingEvidenceInvalid("export_row_width")
            cell = {field: row[i].strip() for field, i in index.items()}
            if "currency" in cell and cell["currency"] != profile["currency"]:
                raise BillingEvidenceInvalid("export_row_currency_differs")  # Never converted.
            amount = _money(cell["amount"], "export_row_amount")
            if "occurred_at" in cell and cell["occurred_at"]:
                moment = _aware(cell["occurred_at"])
                if not start <= moment < end:
                    report["rows_outside_period"] += 1
                    continue
            kind = by_label.get(cell.get("kind", "")) if "kind" in cell else ("credit" if amount < 0 else "charge")
            if kind is None:
                raise BillingEvidenceInvalid("export_row_kind_unmapped")
            signature = canonical_json({k: v for k, v in cell.items() if k != "item_id"})
            if not cell.get("item_id"):
                # No provider line id: keep each row, flag identical rows (possible duplicate export).
                report["possible_duplicate_rows"] += signature in seen_rows
                cell["item_id"] = f"row-{ordinal}-{sha256_hex(signature)[:24]}"
                report["derived_item_ids"] += 1
            seen_rows.add(signature)
            item: dict[str, Any] = {"item_id": cell["item_id"], "kind": kind, "amount": str(amount)}
            for field in ("quantity", "quantity_unit", "model", "provider_request_id", "provider_response_id",
                          "occurred_at"):
                if cell.get(field):
                    item[field] = cell[field]
            if ("quantity" in item) != ("quantity_unit" in item):
                item.pop("quantity", None)
                item.pop("quantity_unit", None)
            previous = items.get(item["item_id"])
            if previous is not None:
                if previous != item:
                    raise BillingEvidenceInvalid("export_item_id_conflict")
                report["possible_duplicate_rows"] += 1
                continue
            items[item["item_id"]] = item
            report["charges"] += amount > 0
            report["credits_or_refunds"] += amount < 0
            report["zero_charge_items"] += amount == Decimal(0)
    except csv.Error:
        raise BillingEvidenceInvalid("export_csv_invalid") from None
    report["items"] = len(items)
    document = {"schema": SCHEMA, "document": {"id": document_id, "sha256": report["export_sha256"]},
                "provider": profile["provider"], "scope": profile["scope"], "currency": profile["currency"],
                "period": profile["period"],
                "coverage": {"assertion": profile["coverage"], "asserted_by": "operator"},
                "statement": "itemized", "items": list(items.values())}
    data = canonical_json(document)
    parsed = parse_billing_evidence(data, original_document=export)  # The existing contract decides validity.
    report["evidence_sha256"] = parsed["evidence_sha256"]
    report["document_check"] = parsed["document_check"]
    report["totals"] = parsed["totals"]
    return data, report


__all__ = ["PROFILE_SCHEMA", "import_export"]
