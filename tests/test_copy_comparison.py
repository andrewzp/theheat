from copy import deepcopy
import hashlib

import pytest

from src.evaluation.copy_comparison import (
    MAX_BYTES,
    CopyComparisonError,
    prepare_copy_comparison,
    summarize_copy_comparison,
)


def candidate(cid, text, status="qualified"):
    return {
        "candidate_id": cid,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "origin": "private-source-" + cid,
        "factual_status": status,
        "rejection_reasons": ["synthetic unsupported claim"] if status == "rejected" else [],
        "material_claims": ["synthetic measurement"],
    }


@pytest.fixture
def inputs():
    return {
        "pairs": [
            {
                "pair_id": "p1",
                "evidence_sha256": "a" * 64,
                "qualification": {
                    "status": "qualified",
                    "adjudicator": "fixture-reviewer",
                    "reference": "synthetic source fixture",
                    "method": "source_audit",
                },
                "source_context": "Synthetic example only: a station reports 42 C.",
                "candidates": [
                    candidate(
                        "c1",
                        "The synthetic station reports 42 C, an observed reading in this fixture.",
                    ),
                    candidate("c2", "Synthetic station: 42 C observed."),
                ],
            }
        ],
        "side_assignments": {"p1": {"A": "c1", "B": "c2"}},
    }


def rating(inputs, *, preference="B", rater="rater-1"):
    prepared = prepare_copy_comparison(**inputs)
    return {
        "binding": prepared["private_mapping"]["p1"]["rating_binding"],
        "rater_id": rater,
        "rated_at": "2026-09-29T16:00:00Z",
        "preference": preference,
        "notes": "",
        "scores": {side: {"punch": 4, "clarity": 4, "unnecessary_words": 2} for side in ("A", "B")},
    }


def test_blind_display_and_explicit_origin_mapping_detached(inputs):
    before = deepcopy(inputs)
    prepared = prepare_copy_comparison(**inputs)
    assert prepared == prepare_copy_comparison(**inputs)
    assert "private-source" not in str(prepared["display_pairs"])
    assert prepared["private_mapping"]["p1"]["origins"]["A"]["candidate_id"] == "c1"
    display = prepared["display_pairs"][0]
    assert display["eligible_for_quality_comparison"] is True
    assert display["sides"]["B"]["words"] == 5
    assert display["sides"]["B"]["material_claim_count"] == 1
    prepared["display_pairs"][0]["sides"]["A"]["rejection_reasons"].append("edit")
    assert inputs == before


def test_no_ratings_never_invents_a_quality_result(inputs):
    result = summarize_copy_comparison(**inputs, ratings=[])
    assert result["eligible_pair_count"] == 1 and result["rated_pair_count"] == 0
    assert (
        result["unrated_pair_count"] == 1 and result["preference_result"] == "no_eligible_ratings"
    )
    assert result["mean_length_delta_b_minus_a"]["characters"] < 0
    assert sum(result["eligible_preferences_by_display_side"].values()) == 0
    assert result["publication_approved"] is False


def test_ties_abstentions_missingness_and_identical_retries_are_distinct(inputs):
    records = [
        rating(inputs, preference=p, rater="r" + str(i))
        for i, p in enumerate(("A", "B", "tie", "abstain"))
    ]
    records[-1]["scores"] = {"A": None, "B": None}
    before = deepcopy(records)
    result = summarize_copy_comparison(**inputs, ratings=records + [records[0]])
    assert result["unique_rating_count"] == 4 and result["identical_retries_ignored"] == 1
    assert result["eligible_preferences_by_display_side"] == {
        "A": 1,
        "B": 1,
        "tie": 1,
        "abstain": 1,
    }
    assert result["rated_pair_count"] == 1 and result["unrated_pair_count"] == 0
    assert records == before


@pytest.mark.parametrize("status", ["unverified", "rejected"])
@pytest.mark.parametrize("target", ["source", "A", "B"])
def test_unqualified_pair_cannot_contribute_a_quality_winner(inputs, status, target):
    pair = inputs["pairs"][0]
    if target == "source":
        pair["qualification"]["status"] = status
    else:
        c = pair["candidates"][0 if target == "A" else 1]
        c["factual_status"] = status
        c["rejection_reasons"] = ["unqualified synthetic fixture"]
    record = rating(inputs)
    result = summarize_copy_comparison(**inputs, ratings=[record])
    assert result["eligible_pair_count"] == result["eligible_rating_count"] == 0
    assert result["ineligible_rating_count"] == result["rated_pair_count"] == 1
    assert result["rows"][0]["ratings"] == [record]
    assert result["mean_length_delta_b_minus_a"]["characters"] is None


@pytest.mark.parametrize(
    "change",
    ["text", "evidence", "order", "candidate_id", "adjudication", "claims", "context", "origin"],
)
def test_old_rating_invalidated_by_changed_bound_inputs(inputs, change):
    old = rating(inputs)
    pair = inputs["pairs"][0]
    if change == "text":
        pair["candidates"][1] = candidate("c2", "A changed qualified fixture.")
    elif change == "evidence":
        pair["evidence_sha256"] = "b" * 64
    elif change == "order":
        inputs["side_assignments"]["p1"] = {"A": "c2", "B": "c1"}
    elif change == "candidate_id":
        pair["candidates"][1]["candidate_id"] = "c3"
        inputs["side_assignments"]["p1"]["B"] = "c3"
    elif change == "adjudication":
        pair["qualification"]["reference"] = "new adjudication"
    elif change == "context":
        pair["source_context"] = "Changed source context"
    elif change == "origin":
        pair["candidates"][1]["origin"] = "different source"
    else:
        pair["candidates"][1]["material_claims"].append("new claim annotation")
    with pytest.raises(CopyComparisonError):
        summarize_copy_comparison(**inputs, ratings=[old])


@pytest.mark.parametrize(
    "field,value",
    [
        ("punch", True),
        ("clarity", 1.0),
        ("unnecessary_words", 0),
        ("punch", 6),
        ("punch", float("nan")),
    ],
)
def test_invalid_scores(inputs, field, value):
    record = rating(inputs)
    record["scores"]["A"][field] = value
    with pytest.raises(CopyComparisonError):
        summarize_copy_comparison(**inputs, ratings=[record])


@pytest.mark.parametrize(
    "change",
    [
        "conflict",
        "unknown_pair",
        "bad_hash",
        "missing_score",
        "naive_time",
        "missing_rater",
        "oversized_notes",
        "preference",
        "extra",
    ],
)
def test_invalid_or_conflicting_ratings(inputs, change):
    first, second = rating(inputs), rating(inputs)
    if change == "conflict":
        second["preference"] = "A"
    elif change == "unknown_pair":
        second["binding"]["pair_id"] = "p2"
    elif change == "bad_hash":
        second["binding"]["candidates"]["A"]["text_sha256"] = "b" * 64
    elif change == "missing_score":
        second["scores"]["A"] = None
    elif change == "naive_time":
        second["rated_at"] = "2026-09-29T12:00:00"
    elif change == "missing_rater":
        second["rater_id"] = ""
    elif change == "oversized_notes":
        second["notes"] = "x" * 2001
    elif change == "preference":
        second["preference"] = "shortest"
    else:
        second["automatic_grade"] = "A"
    with pytest.raises(CopyComparisonError):
        summarize_copy_comparison(**inputs, ratings=[first, second])


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_pair",
        "duplicate_candidate",
        "too_many",
        "bad_hash",
        "blank",
        "long",
        "nonfinite",
        "oversized",
        "same_side",
        "unknown_side",
        "prose_grade",
        "unreviewed",
        "no_reason",
        "qualified_reason",
        "extra",
    ],
)
def test_invalid_pair_contracts(inputs, change):
    pair = inputs["pairs"][0]
    c = pair["candidates"][0]
    if change == "duplicate_pair":
        inputs["pairs"].append(deepcopy(pair))
    elif change == "duplicate_candidate":
        pair["candidates"][1]["candidate_id"] = "c1"
    elif change == "too_many":
        inputs["pairs"] *= 101
    elif change == "bad_hash":
        c["text_sha256"] = "b" * 64
    elif change in {"blank", "long"}:
        pair["candidates"][0] = candidate("c1", " " if change == "blank" else "x" * 281)
    elif change == "nonfinite":
        pair["source_context"] = float("nan")
    elif change == "oversized":
        pair["source_context"] = "x" * (MAX_BYTES + 1)
    elif change == "same_side":
        inputs["side_assignments"]["p1"]["B"] = "c1"
    elif change == "unknown_side":
        inputs["side_assignments"]["p2"] = {"A": "c1", "B": "c2"}
    elif change == "prose_grade":
        pair["qualification"]["method"] = "old_ai_A_grade"
    elif change == "unreviewed":
        pair["qualification"]["method"] = "not_reviewed"
    elif change == "no_reason":
        c["factual_status"] = "rejected"
    elif change == "qualified_reason":
        c["rejection_reasons"] = ["false number"]
    else:
        pair["automatic_winner"] = "A"
    with pytest.raises(CopyComparisonError):
        prepare_copy_comparison(**inputs)


def test_zero_pairs_and_single_sentence_have_no_minimum_length(inputs):
    empty = summarize_copy_comparison([], side_assignments={}, ratings=[])
    assert empty["pair_count"] == 0 and empty["preference_result"] == "no_eligible_ratings"
    inputs["pairs"][0]["candidates"][1] = candidate("c2", "42 C.")
    assert (
        prepare_copy_comparison(**inputs)["display_pairs"][0]["eligible_for_quality_comparison"]
        is True
    )


def test_multiple_pairs_keep_distinct_denominators(inputs):
    second = deepcopy(inputs["pairs"][0])
    second["pair_id"] = "p2"
    second["candidates"] = [
        candidate("c3", "Longer synthetic text."),
        candidate("c4", "Short synthetic text."),
    ]
    inputs["pairs"].append(second)
    inputs["side_assignments"]["p2"] = {"A": "c3", "B": "c4"}
    result = summarize_copy_comparison(**inputs, ratings=[rating(inputs)])
    assert result["eligible_pair_count"] == 2 and result["eligible_rated_pair_count"] == 1
    assert result["unrated_pair_count"] == 1 and result["eligible_rating_count"] == 1
