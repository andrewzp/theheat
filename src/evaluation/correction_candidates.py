"""Correction candidates from supplied, source-complete discrepancies (W15.6).

A candidate needs one of our confirmed posts, the exact claim quoted from its
delivered text, the source evidence that contradicts it (artifact hash,
retrieval time and the statement) and the stated uncertainty. Anything missing
is reported as the evidence still needed, never filled in. Reader "incorrect"
feedback is a prompt to look, not evidence. Nothing here corrects, deletes,
posts or messages anyone; a candidate is for the editor's review only.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "theheat.correction-candidates/v1"
MAX_DISCREPANCIES = 50
_SHA = re.compile(r"[a-f0-9]{64}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
KINDS = {"value", "place", "time", "attribution", "category", "consequence"}


def _confirmed(state: dict) -> dict[str, dict]:
    posts: dict[str, dict] = {}
    raw = state.get("publish_ledger")
    ledger: dict[str, Any] = raw if isinstance(raw, dict) else {}
    drafts = {d.get("event_id") or d.get("id"): d for d in state.get("drafts", []) if isinstance(d, dict)}
    for event_id, row in ledger.items():
        if isinstance(row, dict) and row.get("phase") == "confirmed" and row.get("tweet_id") and isinstance(row.get("text"), str):
            draft = drafts.get(event_id) or {}
            posts[str(row["tweet_id"])] = {"text": row["text"], "text_sha256": row.get("text_sha256"),
                                           "posted_at": draft.get("posted_at") or row.get("confirmed_at"),
                                           "publication_class": draft.get("type")}
    return posts


def prepare(state: dict, discrepancies: Any, *, reader_flags: list[dict] | None = None) -> dict:
    if not isinstance(discrepancies, list) or len(discrepancies) > MAX_DISCREPANCIES:
        raise ValueError("discrepancy_count")
    posts = _confirmed(state)
    candidates: list[dict] = []
    incomplete: list[dict] = []
    for row in discrepancies:
        if not isinstance(row, dict):
            incomplete.append({"needed": ["discrepancy_record"]})
            continue
        tweet_id = str(row.get("tweet_id") or "")
        raw_evidence = row.get("source_evidence")
        evidence: dict[str, Any] = raw_evidence if isinstance(raw_evidence, dict) else {}
        needed = []
        post = posts.get(tweet_id)
        if post is None:
            needed.append("confirmed_post_receipt")
        claim = row.get("claim")
        if not isinstance(claim, str) or not claim.strip() or (post is not None and claim not in post["text"]):
            needed.append("exact_claim_quoted_from_delivered_text")
        if not _SHA.fullmatch(str(evidence.get("artifact_sha256") or "")):
            needed.append("source_artifact_sha256")
        if not _TIME.fullmatch(str(evidence.get("retrieved_at") or "")):
            needed.append("source_retrieved_at")
        if not isinstance(evidence.get("statement"), str) or not evidence["statement"].strip():
            needed.append("source_statement")
        if row.get("kind") not in KINDS:
            needed.append("discrepancy_kind")
        if not isinstance(row.get("uncertainty"), str) or not row["uncertainty"].strip():
            needed.append("stated_uncertainty")
        if needed:
            incomplete.append({"tweet_id": tweet_id or None, "needed": needed})
            continue
        assert post is not None
        candidates.append({
            "tweet_id": tweet_id, "published_text_sha256": post["text_sha256"], "posted_at": post["posted_at"],
            "publication_class": post["publication_class"], "claim": claim, "kind": row["kind"],
            "source_evidence": {k: evidence[k] for k in ("artifact_sha256", "retrieved_at", "statement")},
            "uncertainty": row["uncertainty"][:500], "action": "editor_review_only",
            "automatic_correction": False, "deletion": False})
    flags = [{"tweet_id": str(f.get("tweet_id")), "status": "evidence_needed",
              "note": "Reader feedback marked this incorrect; a source-complete discrepancy is needed first."}
             for f in (reader_flags or []) if isinstance(f, dict) and str(f.get("tweet_id")) in posts
             and not any(c["tweet_id"] == str(f.get("tweet_id")) for c in candidates)]
    return {"schema": SCHEMA, "candidates": candidates, "incomplete": incomplete, "reader_flags": flags,
            "note": "No correction, deletion, reply or message is prepared or sent automatically."}


# P15/P00d join: a retained affected-claim finding (src/data/temperature_history.py)
# whose current source contradicts a confirmed post becomes a discrepancy input.
# The statement is assembled only from the finding's retained fields; nothing is
# fetched or inferred, and the historical timing limits travel as uncertainty.
CONTRADICTION_REASONS = {
    "current_source_qc_or_value_revision": "reported_value_c",
    "current_archive_comparator_changed": "reported_previous_c",
}
_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?=\s?\u00b0?\s?[CF]\b)")


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _quoted_claim(text: str, value: Any) -> str | None:
    """The single delivered sentence stating ``value`` in °C or its °F form, else None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    wanted = {round(float(value), 1), round(float(value) * 9 / 5 + 32, 1), round(float(value) * 9 / 5 + 32)}
    hits = [sentence for sentence in _sentences(text)
            if any(round(float(m.group(0)), 1) in wanted for m in _NUMBER.finditer(sentence))]
    return hits[0].strip() if len(hits) == 1 else None


def _statement(finding: dict) -> str:
    claim, details = finding.get("claim") or {}, finding.get("details") or {}
    where = f"{claim.get('station_id')} {claim.get('valid_date')} {claim.get('element')}"
    if finding.get("reason") == "current_source_qc_or_value_revision":
        return (f"Current GHCN-Daily record for {where}: value {details.get('current_value_c')} C, "
                f"QFLAG '{details.get('current_qflag') or ''}', source accepted {details.get('source_accepted')}; "
                f"the post used {claim.get('reported_value_c')} C.")
    return (f"Current accepted GHCN-Daily comparator for {where} before {details.get('comparison_before')}: "
            f"{details.get('current_accepted_comparator_c')} C; the post used {details.get('retained_comparator_c')} C.")


def _uncertainty(finding: dict) -> str:
    details = finding.get("details") or {}
    parts = ["A current source revision does not establish that the post was wrong when published."]
    if not finding.get("publication_time_qc_known") or details.get("publication_time_flag_timing") == "unknown":
        parts.append("Publication-time QC status is unknown; when the flag was added is not established.")
    if details.get("historical_revision_timing") == "not_established":
        parts.append("When the comparator changed is not established.")
    return " ".join(parts)


def source_findings(state: dict) -> dict:
    """Discrepancy inputs from retained contradicting findings on confirmed posts."""
    raw_history = state.get("temperature_history")
    history: dict[str, Any] = raw_history if isinstance(raw_history, dict) else {}
    posts = _confirmed(state)
    discrepancies: list[dict] = []
    review_only: list[dict] = []
    for finding_id, finding in sorted(history.items()):
        if not isinstance(finding, dict) or finding.get("kind") != "affected_claim":
            continue
        raw_claim = finding.get("claim")
        claim: dict[str, Any] = raw_claim if isinstance(raw_claim, dict) else {}
        tweet_id = str(claim.get("tweet_id") or "")
        post = posts.get(tweet_id)
        field = CONTRADICTION_REASONS.get(str(finding.get("reason")))
        if post is None or field is None:
            if tweet_id:
                review_only.append({"finding_id": finding_id, "tweet_id": tweet_id, "reason": finding.get("reason"),
                                    "status": "review_only_not_a_contradiction" if post else "no_confirmed_post"})
            continue
        if claim.get("text_sha256") not in (None, post.get("text_sha256")):
            review_only.append({"finding_id": finding_id, "tweet_id": tweet_id, "reason": finding.get("reason"),
                                "status": "claim_text_differs_from_delivered_text"})
            continue
        discrepancies.append({
            "tweet_id": tweet_id, "kind": "value", "claim": _quoted_claim(post["text"], claim.get(field)),
            "source_evidence": {"artifact_sha256": finding.get("source_revision"),
                                "retrieved_at": finding.get("retrieved_at"), "statement": _statement(finding)},
            "uncertainty": _uncertainty(finding), "source_finding_id": finding_id,
        })
    return {"discrepancies": discrepancies[:MAX_DISCREPANCIES], "review_only_findings": review_only,
            "truncated": max(0, len(discrepancies) - MAX_DISCREPANCIES)}


def prepare_from_state(state: dict, supplied: Any = None, *, reader_flags: list[dict] | None = None) -> dict:
    """Supplied discrepancies plus retained source findings, then the unchanged rules."""
    derived = source_findings(state)
    rows = list(supplied or []) if isinstance(supplied, list) or supplied is None else supplied
    if not isinstance(rows, list):
        raise ValueError("discrepancy_count")
    combined = (rows + derived["discrepancies"])[:MAX_DISCREPANCIES]
    result = prepare(state, combined, reader_flags=reader_flags)
    return {**result, "source_findings": {"derived": len(derived["discrepancies"]),
                                          "review_only": derived["review_only_findings"],
                                          "truncated": derived["truncated"] + max(0, len(rows) + len(derived["discrepancies"]) - MAX_DISCREPANCIES)}}


__all__ = ["SCHEMA", "prepare", "prepare_from_state", "source_findings"]
