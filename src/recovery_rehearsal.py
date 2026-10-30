"""Readable Operations status for the owned local recovery rehearsal (W16.5).

Each row is produced from the output of the real consumer that handled one
invented situation: an unavailable source, a missing baseline, a stale review,
an interrupted unstarted job, an unknown delivery and a refused restore plan.
The board refuses a row that claims a send, a mutation of production data or a
missing consumer, and it always says that fiction is not production recovery.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "theheat.recovery-rehearsal/v1"
STEPS = ("unavailable_source", "missing_baseline", "stale_review", "interrupted_unstarted_job",
         "unknown_delivery", "restore_plan_refusal")
TITLES = {
    "unavailable_source": "A source product is unavailable",
    "missing_baseline": "A required baseline is missing",
    "stale_review": "A review no longer matches the draft",
    "interrupted_unstarted_job": "A job was interrupted before it started",
    "unknown_delivery": "A delivery outcome is unknown",
    "restore_plan_refusal": "A restore input is incomplete",
}
_FIELDS = ("step", "consumer", "observed", "operator_sees", "safe_action", "sent", "production_mutated")


class RehearsalError(ValueError):
    pass


def status_row(step: str, *, consumer: str, observed: str, operator_sees: str, safe_action: str,
               sent: bool = False, production_mutated: bool = False) -> dict[str, Any]:
    if step not in STEPS:
        raise RehearsalError("unknown_step")
    for value in (consumer, observed, operator_sees, safe_action):
        if not isinstance(value, str) or not value.strip() or len(value) > 400:
            raise RehearsalError("unreadable_row")
    if sent or production_mutated:
        # A rehearsal step that sent or changed production data is a failed rehearsal.
        raise RehearsalError("rehearsal_side_effect")
    return {"step": step, "consumer": consumer, "observed": observed, "operator_sees": operator_sees,
            "safe_action": safe_action, "sent": False, "production_mutated": False}


def board(rows: list[dict[str, Any]], *, as_of: str) -> dict[str, Any]:
    seen = [str(row.get("step")) for row in rows]
    if sorted(seen) != sorted(STEPS) or len(set(seen)) != len(STEPS):
        raise RehearsalError("incomplete_rehearsal")
    if any(set(row) != set(_FIELDS) or row["sent"] or row["production_mutated"] for row in rows):
        raise RehearsalError("rehearsal_side_effect")
    ordered = sorted(rows, key=lambda row: STEPS.index(row["step"]))
    return {"schema": SCHEMA, "as_of": as_of, "rows": ordered, "sent": 0, "production_mutated": 0,
            "evidence_class": "invented_local_rehearsal",
            "limit": "Invented state exercised through real local consumers; this is not production recovery evidence."}


def render_markdown(document: dict[str, Any]) -> str:
    lines = [f"# Operations recovery rehearsal — {document['as_of']}", "",
             "| Situation | What Operations shows | Safe next action | Handled by |", "|---|---|---|---|"]
    for row in document["rows"]:
        cells = (TITLES[row["step"]], f"{row['operator_sees']} (`{row['observed']}`)", row["safe_action"], row["consumer"])
        lines.append("| " + " | ".join(cell.replace("|", "/").replace("\n", " ") for cell in cells) + " |")
    lines += ["", f"Nothing was sent and no production data changed. {document['limit']}"]
    return "\n".join(lines) + "\n"


__all__ = ["RehearsalError", "SCHEMA", "STEPS", "board", "render_markdown", "status_row"]
