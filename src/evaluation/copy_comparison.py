"""Pure, offline contracts for human comparison of supplied weather copy.

Factual qualification is an explicit caller assertion with provenance, not a
certification by this module. No generation, provider call, inferred preference,
automatic grade or publication decision occurs here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from typing import Any

from src.editorial.revisions import fingerprint

MAX_BYTES = 2_000_000
MAX_PAIRS = 100
MAX_RATINGS = 1_000
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
_DISPOSITIONS = {"qualified", "rejected", "unverified"}
_SCORES = {"punch", "clarity", "unnecessary_words"}
_PREFERENCES = ("A", "B", "tie", "abstain")


class CopyComparisonError(ValueError):
    """Bounded diagnostics; caller text never appears in errors."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CopyComparisonError(message)


def _clone(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        _require(len(encoded) <= MAX_BYTES, "Comparison input exceeds the byte bound")
        fingerprint(value)  # also rejects non-JSON values and non-string object keys
        return deepcopy(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise CopyComparisonError("Comparison input must be bounded finite JSON") from None


def _shape(value: Any, fields: set[str]) -> None:
    _require(isinstance(value, dict) and set(value) == fields, "Unexpected comparison fields")


def _identifier(value: Any) -> None:
    _require(
        isinstance(value, str) and _ID.fullmatch(value) is not None, "Invalid stable identifier"
    )


def _sha(value: Any) -> None:
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None, "Invalid SHA256")


def _text(value: Any, maximum: int) -> None:
    _require(
        isinstance(value, str) and bool(value.strip()) and len(value) <= maximum,
        "Invalid bounded text",
    )


def _text_list(value: Any, limit: int, width: int) -> None:
    _require(isinstance(value, list) and len(value) <= limit, "Invalid annotation list")
    for item in value:
        _text(item, width)
    _require(len(set(value)) == len(value), "Duplicate annotations")


def _qualification(value: Any) -> None:
    _shape(value, {"status", "adjudicator", "reference", "method"})
    _require(
        isinstance(value["status"], str) and value["status"] in _DISPOSITIONS,
        "Invalid evidence qualification",
    )
    _text(value["adjudicator"], 200)
    _text(value["reference"], 500)
    _require(
        value["method"] in ("human_evidence_review", "source_audit", "not_reviewed"),
        "Qualification must name evidence review, not an old prose grade",
    )
    _require(
        value["status"] != "qualified" or value["method"] != "not_reviewed",
        "Unreviewed evidence cannot be qualified",
    )


def _candidate(value: Any) -> None:
    _shape(
        value,
        {
            "candidate_id",
            "text",
            "text_sha256",
            "origin",
            "factual_status",
            "rejection_reasons",
            "material_claims",
        },
    )
    _identifier(value["candidate_id"])
    _text(value["text"], 280)
    _text(value["origin"], 200)
    _sha(value["text_sha256"])
    _require(
        value["text_sha256"] == hashlib.sha256(value["text"].encode("utf-8")).hexdigest(),
        "Candidate text hash changed",
    )
    _require(
        isinstance(value["factual_status"], str) and value["factual_status"] in _DISPOSITIONS,
        "Invalid candidate factual disposition",
    )
    _text_list(value["rejection_reasons"], 20, 500)
    _text_list(value["material_claims"], 20, 500)
    _require(
        value["factual_status"] != "qualified" or not value["rejection_reasons"],
        "Qualified candidate has rejection reasons",
    )
    _require(
        value["factual_status"] != "rejected" or bool(value["rejection_reasons"]),
        "Rejected candidate requires a reason",
    )


def _prepare(pairs: Any, side_assignments: Any) -> dict:
    pairs, assignments = _clone(pairs), _clone(side_assignments)
    _require(isinstance(pairs, list) and len(pairs) <= MAX_PAIRS, "Supply at most 100 pairs")
    _require(isinstance(assignments, dict), "Supply explicit A/B assignments")
    seen_pairs: set[str] = set()
    seen_candidates: set[str] = set()
    display = []
    private = {}
    for pair in pairs:
        _shape(
            pair, {"pair_id", "evidence_sha256", "qualification", "source_context", "candidates"}
        )
        _identifier(pair["pair_id"])
        pair_id = pair["pair_id"]
        _require(pair_id not in seen_pairs, "Duplicate pair identifier")
        seen_pairs.add(pair_id)
        _sha(pair["evidence_sha256"])
        _qualification(pair["qualification"])
        _text(pair["source_context"], 10_000)
        _require(
            isinstance(pair["candidates"], list) and len(pair["candidates"]) == 2,
            "Each pair needs exactly two candidates",
        )
        by_id = {}
        for candidate in pair["candidates"]:
            _candidate(candidate)
            cid = candidate["candidate_id"]
            _require(cid not in seen_candidates, "Duplicate candidate identifier")
            seen_candidates.add(cid)
            by_id[cid] = candidate
        sides = assignments.get(pair_id)
        _shape(sides, {"A", "B"})
        _require(
            all(isinstance(value, str) for value in sides.values())
            and set(sides.values()) == set(by_id),
            "Side assignment must use each candidate exactly once",
        )
        pair_sha = fingerprint({"pair": pair, "sides": sides})
        binding = {
            "pair_id": pair_id,
            "pair_sha256": pair_sha,
            "evidence_sha256": pair["evidence_sha256"],
            "candidates": {
                side: {"candidate_id": cid, "text_sha256": by_id[cid]["text_sha256"]}
                for side, cid in sides.items()
            },
        }
        eligible = pair["qualification"]["status"] == "qualified" and all(
            c["factual_status"] == "qualified" for c in by_id.values()
        )
        display.append(
            {
                "pair_id": pair_id,
                "pair_sha256": pair_sha,
                "evidence_sha256": pair["evidence_sha256"],
                "source_context": pair["source_context"],
                "qualification": deepcopy(pair["qualification"]),
                "eligible_for_quality_comparison": eligible,
                "sides": {
                    side: {
                        "text": by_id[cid]["text"],
                        "text_sha256": by_id[cid]["text_sha256"],
                        "factual_status": by_id[cid]["factual_status"],
                        "rejection_reasons": by_id[cid]["rejection_reasons"],
                        "characters": len(by_id[cid]["text"]),
                        "words": len(by_id[cid]["text"].split()),
                        "material_claim_count": len(by_id[cid]["material_claims"]),
                    }
                    for side, cid in sides.items()
                },
            }
        )
        private[pair_id] = {
            "rating_binding": binding,
            "origins": {
                side: {"candidate_id": cid, "origin": by_id[cid]["origin"]}
                for side, cid in sides.items()
            },
        }
    _require(set(assignments) == seen_pairs, "Assignments contain missing or unknown pairs")
    return {
        "schema_version": 1,
        "display_pairs": display,
        "private_mapping": private,
        "qualification_is_caller_assertion": True,
        "publication_approved": False,
    }


def prepare_copy_comparison(pairs: list[dict], *, side_assignments: dict) -> dict:
    """Show only A/B copy; retain explicit origin and binding metadata separately.

    The caller must keep private_mapping off the rating screen and choose opaque
    pair IDs/context. Hiding explicit origin labels alone cannot guarantee blind
    or representative evaluation. Whitespace word counts and Python character
    counts are descriptive, not platform-weighted length or semantic claim counts.
    """
    try:
        return _prepare(pairs, side_assignments)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise CopyComparisonError("Invalid copy comparison inputs or bindings") from None


def _rating(value: Any, expected_binding: dict) -> None:
    _shape(value, {"binding", "rater_id", "rated_at", "scores", "preference", "notes"})
    _require(
        value["binding"] == expected_binding
        and fingerprint(value["binding"]) == fingerprint(expected_binding),
        "Rating belongs to different text, evidence, qualification or side assignment",
    )
    _identifier(value["rater_id"])
    _text(value["rated_at"], 64)
    stamp = datetime.fromisoformat(value["rated_at"].replace("Z", "+00:00"))
    _require(
        stamp.tzinfo is not None and stamp.utcoffset() is not None,
        "Rating timestamp must include timezone",
    )
    _require(value["preference"] in _PREFERENCES, "Invalid explicit preference")
    _require(
        isinstance(value["notes"], str) and len(value["notes"]) <= 2_000, "Invalid rating notes"
    )
    _shape(value["scores"], {"A", "B"})
    for score in value["scores"].values():
        if score is None:
            _require(value["preference"] == "abstain", "Only abstention permits absent scores")
        else:
            _shape(score, _SCORES)
            _require(
                all(type(n) is int and 1 <= n <= 5 for n in score.values()),
                "Ratings must be integer scores from 1 to 5",
            )


def summarize_copy_comparison(
    pairs: list[dict], *, side_assignments: dict, ratings: list[dict]
) -> dict:
    """Rebuild against current inputs; count human ballots, never infer a winner.

    Both candidates and their shared evidence must be qualified for a pair to
    enter quality counts. Ineligible ratings stay auditable, but never contribute
    a quality preference. One rater/pair is one ballot; identical retries dedupe,
    conflicting revisions are rejected. Higher unnecessary_words means more excess.
    """
    try:
        comparison = _prepare(pairs, side_assignments)
        return _summarize(comparison, _clone(ratings))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise CopyComparisonError("Invalid, stale or conflicting comparison ratings") from None


def _summarize(comparison: dict, ratings: Any) -> dict:
    _require(
        isinstance(ratings, list) and len(ratings) <= MAX_RATINGS, "Supply at most 1000 ratings"
    )
    by_pair = {pair["pair_id"]: pair for pair in comparison["display_pairs"]}
    seen: dict[tuple[str, str], dict] = {}
    duplicates = 0
    for rating in ratings:
        _require(
            isinstance(rating, dict) and isinstance(rating.get("binding"), dict),
            "Missing rating binding",
        )
        pair_id = rating["binding"].get("pair_id")
        _require(isinstance(pair_id, str) and pair_id in by_pair, "Rating names an unknown pair")
        _rating(rating, comparison["private_mapping"][pair_id]["rating_binding"])
        key = pair_id, rating["rater_id"]
        if key in seen:
            _require(fingerprint(rating) == fingerprint(seen[key]), "Conflicting duplicate rating")
            duplicates += 1
        else:
            seen[key] = rating
    preferences = dict.fromkeys(_PREFERENCES, 0)
    rows = []
    eligible_deltas = []
    for pair_id, pair in by_pair.items():
        ballots = [value for key, value in seen.items() if key[0] == pair_id]
        counts = dict.fromkeys(_PREFERENCES, 0)
        eligible = pair["eligible_for_quality_comparison"]
        for ballot in ballots:
            if eligible:
                counts[ballot["preference"]] += 1
                preferences[ballot["preference"]] += 1
        sides = pair["sides"]
        delta = {
            metric: sides["B"][metric] - sides["A"][metric]
            for metric in ("characters", "words", "material_claim_count")
        }
        if eligible:
            eligible_deltas.append(delta)
        rows.append(
            {
                "pair_id": pair_id,
                "eligible": eligible,
                "rating_count": len(ballots),
                "eligible_preferences_by_display_side": counts,
                "length_delta_b_minus_a": delta,
                "ratings": ballots,
            }
        )
    eligible_count = len(eligible_deltas)
    return {
        "schema_version": 1,
        "pair_count": len(rows),
        "eligible_pair_count": eligible_count,
        "rated_pair_count": sum(bool(row["rating_count"]) for row in rows),
        "eligible_rated_pair_count": sum(
            bool(row["rating_count"]) and row["eligible"] for row in rows
        ),
        "unrated_pair_count": sum(not row["rating_count"] for row in rows),
        "unique_rating_count": len(seen),
        "identical_retries_ignored": duplicates,
        "eligible_rating_count": sum(preferences.values()),
        "ineligible_rating_count": len(seen) - sum(preferences.values()),
        "eligible_preferences_by_display_side": preferences,
        "preference_result": "recorded_human_ballots"
        if sum(preferences.values())
        else "no_eligible_ratings",
        "mean_length_delta_b_minus_a": {
            metric: sum(delta[metric] for delta in eligible_deltas) / eligible_count
            if eligible_count
            else None
            for metric in ("characters", "words", "material_claim_count")
        },
        "length_denominator": "all eligible pairs, including unrated pairs",
        "rows": rows,
        "publication_approved": False,
        "limits": [
            "Qualification is a supplied assertion, not certified here.",
            "A/B sides are not models; aggregate side counts do not identify a winning method.",
            "Length and supplied annotation counts are descriptive, not a quality score.",
            "Human records and timestamps are assertions; this module does not authenticate raters.",
            "No generation, representative sampling, engagement measurement or viral-lift inference.",
        ],
    }
