"""Per-stage X delivery outcome: proven not-sent versus ambiguous delivery.

The X adapter sends at most three ordered phases: ``upload`` (PNG), ``alt``
(media metadata) and ``create`` (the post). Only ``create`` can publish. The
adapter records each phase it starts into the active :func:`recording`; the
publisher classifies that record once, after transport returns or raises.

Rules (no inference from timing or from the absence of an error):

* no phase started (credentials absent, refused before egress) -> ``not_sent``;
* a complete HTTP rejection of ``upload`` or ``alt`` -> ``not_sent``: the
  platform answered and ``create`` never started;
* a lost/unreadable ``upload`` or ``alt`` response -> ``unknown`` (the accepted
  sender contract: an uncertain phase is never resent or downgraded to text);
* a complete HTTP 429 response to ``create`` -> ``not_sent`` (rate limited);
* any other ``create`` failure, including complete 4xx/5xx responses, lost
  responses and SDK exceptions -> ``unknown`` (a 403 can mean an earlier
  identical post exists, so it never proves absence);
* a ``create`` response with a post ID -> ``confirmed``.

Without a stage record (an injected or legacy sender), the previous contract is
kept exactly: ``rate_limited`` -> not sent, an ID -> confirmed, else unknown.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from typing import Any, Iterator

STAGES = ("upload", "alt", "create")
_ACTIVE: ContextVar[dict | None] = ContextVar("theheat_outbox_stage_report", default=None)


def sha256(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    raw = value.encode("utf-8", errors="strict") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def delivery_identity(text: str, png: bytes | None, alt: str | None) -> dict:
    """The exact bytes a send will carry; bound on the ledger row before egress."""
    return {"text_sha256": sha256(text), "png_sha256": sha256(png),
            "alt_sha256": sha256(alt) if png is not None and alt else None}


@contextmanager
def recording() -> Iterator[dict]:
    report: dict = {"stages": [], "refused_before_egress": None}
    token = _ACTIVE.set(report)
    try:
        yield report
    finally:
        _ACTIVE.reset(token)


def refuse_before_egress(reason: str) -> None:
    report = _ACTIVE.get()
    if report is not None and not report["stages"]:
        report["refused_before_egress"] = reason


def begin(stage: str) -> dict | None:
    if stage not in STAGES:
        raise ValueError("unknown_delivery_stage")
    report = _ACTIVE.get()
    if report is None:
        return None
    entry = {"stage": stage, "result": "started", "http_status": None, "complete": False}
    report["stages"].append(entry)
    return entry


def finish(entry: dict | None, error: BaseException | None = None) -> None:
    """Record a phase result; a complete response only when one was received."""
    if entry is None:
        return
    if error is None:
        entry.update(result="returned", complete=True)
        return
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        entry.update(result="rejected", http_status=status, complete=True)
    else:
        entry.update(result="no_response", complete=False)


def classify(report: dict | None, result: Any) -> dict:
    """Return ``{status, stage, reason, rate_limited, media_state, proof}``."""
    post_id = str(result.get("id") or "") if isinstance(result, dict) else ""
    stages = list((report or {}).get("stages") or [])
    if report is None or (not stages and not report.get("refused_before_egress")):
        if post_id:
            return _outcome("confirmed", "create", "post_id_returned", proof="legacy_sender_post_id")
        if isinstance(result, dict) and result.get("error") == "rate_limited":
            return _outcome("not_sent", None, "rate_limited", rate_limited=True, proof="legacy_rate_limited_contract")
        return _outcome("unknown", None, "no_stage_evidence")
    if not stages:
        return _outcome("not_sent", None, str(report["refused_before_egress"]), proof="no_egress")
    last = stages[-1]
    media = _media_state(stages)
    if last["stage"] != "create":
        if last["result"] == "rejected":
            return _outcome("not_sent", last["stage"], f"{last['stage']}_rejected",
                            rate_limited=last["http_status"] == 429, media_state=media,
                            proof="complete_pre_create_rejection")
        return _outcome("unknown", last["stage"], f"{last['stage']}_response_missing", media_state=media)
    if post_id and last["result"] == "returned":
        return _outcome("confirmed", "create", "post_id_returned", media_state=media, proof="create_response_post_id")
    if last["complete"] and last["http_status"] == 429:
        return _outcome("not_sent", "create", "create_rate_limited", rate_limited=True, media_state=media,
                        proof="complete_create_rate_limit_response")
    reason = "create_rejected_unproven" if last["complete"] else "create_response_missing"
    return _outcome("unknown", "create", reason, media_state=media)


def _media_state(stages: list[dict]) -> str | None:
    upload = next((row for row in stages if row["stage"] == "upload"), None)
    if upload is None:
        return None
    if upload["result"] == "returned":
        return "uploaded_unattached" if stages[-1]["stage"] != "create" else "uploaded"
    return "upload_rejected" if upload["complete"] else "upload_unresolved"


def _outcome(status: str, stage: str | None, reason: str, *, rate_limited: bool = False,
             media_state: str | None = None, proof: str | None = None) -> dict:
    return {"status": status, "stage": stage, "reason": reason, "rate_limited": rate_limited,
            "media_state": media_state, "proof": proof if status == "not_sent" else None,
            "retry_permitted": status == "not_sent"}


def retry_permitted(row: Any) -> bool:
    """The explicit retry path is open only for a row that proves nothing was sent.

    Legacy, submitted, unknown and confirmed rows, rows carrying conflicts, and
    operator-cancelled intents are never retryable.
    """
    if not isinstance(row, dict) or row.get("tweet_id") or row.get("attempt_conflicts"):
        return False
    if row.get("operator_cancellation"):
        return False
    return row.get("phase") == "not_sent"
