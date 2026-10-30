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


__all__ = ["SCHEMA", "prepare"]
