"""Small private copy review packs and descriptive copy comparisons (B4).

A review pack lists up to ``limit`` recent drafts from an owner-only saved-state
copy with their exact text, the free copy notes, length, sentence count and the
exact revision binding that ordinary dashboard revision feedback uses. By default
it covers posted and rejected copy only; pending drafts (including any held for
Andrew's direct discussion) need an explicit opt-in and can be excluded by id.

A comparison reports descriptive copy shape for groups (supplied incumbent texts,
drafts reviewed under one editorial policy, other drafts): counts, lengths,
sentence counts and copy-note rates. It echoes no incumbent text. Neither output
is a quality score, preference, model evaluation, factual check or publication
decision; fixtures and scripted models measure plumbing only.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median
from typing import Any, Iterable

from src.editorial.revisions import draft_identity, fingerprint
from src.two_bot.copy_gates import ADVISORY, BLOCKING, COPY_GATES_VERSION, copy_notes, sentences

SCHEMA = "theheat.copy-review/v1"
MAX_PACK = 25
MAX_TEXTS = 2_000
DEFAULT_STATUSES = ("posted", "rejected")
LIMITS = [
    "Descriptive copy shape only; not quality, preference, truth or audience effect.",
    "Copy notes are the free bundle-blind rules; danger wording is advisory without source evidence.",
    "Groups are whatever was supplied or retained; they are not matched on evidence or randomized.",
]


def _at(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.utcoffset() is not None else None


def _when(draft: dict) -> datetime | None:
    for key in ("posted_at", "updated_at", "created_at"):
        at = _at(draft.get(key))
        if at is not None:
            return at
    return None


def _policy(draft: dict) -> str | None:
    two_bot = ((draft.get("review_context") or {}).get("two_bot") or {}) if isinstance(draft.get("review_context"), dict) else {}
    value = two_bot.get("reviewed_policy_sha256") if isinstance(two_bot, dict) else None
    return value if isinstance(value, str) and len(value) == 64 else None


def _target(draft: dict) -> dict | None:
    """The same exact revision fields dashboard revision feedback binds; None if unbindable."""
    try:
        identity = draft_identity(draft)
    except ValueError:
        return None
    media = draft.get("media_attachment")
    return {"draft_id": draft["id"], "status": draft.get("status"), "tweet_id": draft.get("tweet_id"),
            **identity, "graphic_sha256": fingerprint(media) if isinstance(media, dict) else None}


def review_pack(state: dict, *, since: datetime, until: datetime, limit: int = 12,
                statuses: Iterable[str] = DEFAULT_STATUSES, exclude_ids: Iterable[str] = ()) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("drafts"), list):
        raise ValueError("state_drafts_required")
    if not 1 <= limit <= MAX_PACK or since >= until:
        raise ValueError("invalid_pack_bounds")
    wanted, excluded = set(statuses), set(exclude_ids)
    rows: list[tuple[datetime, dict]] = []
    skipped: Counter[str] = Counter()
    for draft in state["drafts"]:
        if not isinstance(draft, dict) or not isinstance(draft.get("id"), str) or not isinstance(draft.get("text"), str):
            skipped["invalid_draft"] += 1
            continue
        if draft["id"] in excluded:
            skipped["excluded_by_id"] += 1
            continue
        if draft.get("status") not in wanted:
            continue
        at = _when(draft)
        if at is None or not since <= at < until:
            continue
        rows.append((at, draft))
    rows.sort(key=lambda row: (row[0], row[1]["id"]), reverse=True)
    items = []
    for at, draft in rows[:limit]:
        notes = copy_notes(draft["text"])
        items.append({
            "draft_id": draft["id"], "status": draft.get("status"), "type": draft.get("type"),
            "at": at.isoformat(), "text": draft["text"], "characters": len(draft["text"]),
            "sentences": len(sentences(draft["text"])),
            "copy_notes": [{"code": n.code, "blocking": n.blocking, "excerpt": n.excerpt} for n in notes],
            "reviewed_policy_sha256": _policy(draft), "feedback_target": _target(draft),
            "feedback": {"tags": [], "note": "", "allowed_tags": ["concise", "useful", "confusing", "incorrect"]},
        })
    return {"schema": SCHEMA, "kind": "copy_review_pack", "copy_gates_version": COPY_GATES_VERSION,
            "window": {"since": since.isoformat(), "until": until.isoformat()}, "statuses": sorted(wanted),
            "items": items, "eligible": len(rows), "skipped": dict(skipped), "limits": LIMITS,
            "use": "Save feedback through the dashboard's revision feedback on the same draft; a stale target refuses."}


def _shape(texts: list[str]) -> dict:
    if not texts:
        return {"count": 0, "status": "unavailable"}
    notes = [copy_notes(text) for text in texts]
    codes = Counter(note.code for row in notes for note in row)
    lengths = [len(text) for text in texts]
    counts = [len(sentences(text)) for text in texts]
    return {"count": len(texts), "status": "descriptive",
            "median_characters": median(lengths), "over_200_characters": sum(n > 200 for n in lengths),
            "median_sentences": median(counts), "single_sentence": sum(n == 1 for n in counts),
            "with_blocking_note": sum(any(n.blocking for n in row) for row in notes),
            "note_counts": {code: codes.get(code, 0) for code in (*BLOCKING, *ADVISORY)}}


def compare(state: dict, *, since: datetime, until: datetime, policy_sha256: str | None = None,
            incumbent_texts: list[str] | None = None) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("drafts"), list) or since >= until:
        raise ValueError("invalid_comparison_input")
    if incumbent_texts is not None and (not isinstance(incumbent_texts, list) or len(incumbent_texts) > MAX_TEXTS
                                        or not all(isinstance(t, str) and 0 < len(t) <= 280 for t in incumbent_texts)):
        raise ValueError("invalid_incumbent_texts")
    current: list[str] = []
    other: list[str] = []
    for draft in state["drafts"]:
        if not isinstance(draft, dict) or not isinstance(draft.get("text"), str) or not draft["text"].strip():
            continue
        at = _when(draft)
        if at is None or not since <= at < until:
            continue
        (current if policy_sha256 is not None and _policy(draft) == policy_sha256 else other).append(draft["text"])
    return {"schema": SCHEMA, "kind": "copy_shape_comparison", "copy_gates_version": COPY_GATES_VERSION,
            "window": {"since": since.isoformat(), "until": until.isoformat()},
            "groups": {"incumbent_supplied": _shape(incumbent_texts or []) if incumbent_texts is not None
                       else {"count": None, "status": "not_supplied"},
                       "drafts_current_policy": _shape(current) if policy_sha256 else {"count": None, "status": "policy_not_named"},
                       "drafts_other_or_unbound": _shape(other)},
            "texts_echoed": False, "limits": LIMITS, "quality_result": None, "preference_result": None}


__all__ = ["SCHEMA", "compare", "review_pack"]
