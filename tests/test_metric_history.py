from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import permutations

import pytest

from src.data.metric_history import append_sample, merge_metric_rows, parse_public_metrics, publication_reference


NOW = datetime(2026, 9, 9, 0, tzinfo=UTC)
POST = "2026-09-08T00:00:00Z"
STATE = {"publish_ledger": {"event": {"tweet_id": "123", "at": POST}}, "drafts": []}


def sample(previous=None, *, counts=None, at=NOW, state=None):
    values = {"created_at": POST, **(counts if counts is not None else {"likes": 0, "impressions": 10})}
    return append_sample(previous, tweet_id="123", counts=values,
                         sampled_at=at, state=STATE if state is None else state)


def test_missing_public_fields_remain_unknown_and_zero_is_observed():
    metrics = parse_public_metrics({"like_count": 0, "retweet_count": 2})
    assert metrics == {"likes": 0, "retweets": 2, "replies": None, "quotes": None,
                       "impressions": None, "bookmarks": None}


@pytest.mark.parametrize("value", [True, "12", -1, 1.5, float("nan"), float("inf"), 2**53])
def test_invalid_counts_are_never_observed_zero(value):
    assert parse_public_metrics({"like_count": value})["likes"] is None


def test_exact_post_age_and_original_samples_survive_later_poll():
    first = sample()
    snapshot = deepcopy(first)
    second = sample(first, counts={"likes": 5}, at=NOW + timedelta(days=1))
    assert first == snapshot
    assert len(second["samples"]) == 2
    ages = sorted(row["post_age_seconds"] for row in second["samples"].values())
    assert ages == [86400, 172800]
    assert second["likes"] == 5 and second["impressions"] is None
    assert second["latest_sample_conflict"] is False


def test_duplicate_sample_is_idempotent_and_merge_order_does_not_lose_rows():
    first = sample()
    second = sample(at=NOW + timedelta(days=1))
    assert sample(first) == first
    a = merge_metric_rows(first, second)
    b = merge_metric_rows(second, first)
    assert a == b
    assert len(a["samples"]) == 2
    assert merge_metric_rows(a, first) == a


def test_conflicting_values_at_same_time_are_both_retained_and_flagged():
    a = sample(counts={"likes": 1})
    b = sample(counts={"likes": 2})
    merged = merge_metric_rows(a, b)
    assert merged == merge_metric_rows(b, a)
    assert len(merged["samples"]) == 2
    assert merged["latest_sample_conflict"] is True
    # Even a corrupt/reused caller key cannot overwrite an observation.
    b["samples"] = {next(iter(a["samples"])): next(iter(b["samples"].values()))}
    assert merge_metric_rows(a, b) == merged


def test_legacy_latest_row_is_not_fabricated_as_new_history():
    legacy = {"at": POST, "likes": 10, "retweets": 0, "replies": 1}
    assert merge_metric_rows(legacy, None) == legacy
    result = sample(legacy)
    assert len(result["samples"]) == 1
    assert list(result["legacy_rows"].values()) == [legacy]
    assert result["at"] != POST


def test_flat_legacy_rows_survive_merges_before_first_new_sample():
    a = {"at": POST, "likes": 1}
    b = {"at": "2026-09-08T12:00:00Z", "likes": 2}
    merged = merge_metric_rows(a, b)
    assert sorted(row["likes"] for row in merged["legacy_rows"].values()) == [1, 2]
    result = sample(merged)
    assert result["legacy_rows"] == merged["legacy_rows"]
    assert merge_metric_rows(merged, a) == merged


def test_conflicting_three_way_merge_is_associative_and_commutative():
    for rows in permutations([sample(counts={"likes": None}), sample(counts={"likes": 0}), sample(counts={"likes": 1})]):
        a, b, c = rows
        left = merge_metric_rows(merge_metric_rows(a, b), c)
        right = merge_metric_rows(a, merge_metric_rows(b, c))
        assert left == right
        assert len(left["samples"]) == 3
        assert left["latest_sample_conflict"] is True
        assert merge_metric_rows(left, a) == left


@pytest.mark.parametrize("second_at", [POST, "2026-09-08T00:00:00+00:00", "2026-09-07T20:00:00-04:00"])
def test_legacy_conflicts_use_the_observed_instant_without_inventing_samples(second_at):
    a = {"at": POST, "likes": 1}
    b = {"at": second_at, "likes": 2}
    merged = merge_metric_rows(a, b)
    assert merged == merge_metric_rows(b, a)
    assert "samples" not in merged
    assert len(merged["legacy_rows"]) == 2
    assert merged["latest_sample_conflict"] is True
    assert merge_metric_rows(merged, a) == merged
    assert sample(merged)["latest_sample_conflict"] is False


def test_equivalent_instant_legacy_and_modern_sample_conflict():
    modern = sample(counts={"likes": 1})
    legacy = {"at": "2026-09-09T00:00:00+00:00", "likes": 2}
    merged = merge_metric_rows(modern, legacy)
    assert merged == merge_metric_rows(legacy, modern)
    assert merged["latest_sample_conflict"] is True


def test_mixed_legacy_and_modern_conflict_merge_is_associative():
    values = [{"at": "2026-09-09T00:00:00+00:00", "likes": 1},
              {"at": "2026-09-08T20:00:00-04:00", "likes": 2},
              sample(counts={"likes": 3})]
    for a, b, c in permutations(values):
        left = merge_metric_rows(merge_metric_rows(a, b), c)
        right = merge_metric_rows(a, merge_metric_rows(b, c))
        assert left == right
        assert len(left["legacy_rows"]) == 2
        assert left["latest_sample_conflict"] is True


def test_generation_or_attempt_timestamps_cannot_establish_post_age():
    source = {"drafts": [{"tweet_id": "123", "created_at": POST, "last_publish_attempt_at": POST}],
              "memory": {"shipped_tweets": [{"tweet_id": "123", "shipped_at": POST}]}, "publish_ledger": {}}
    reference = publication_reference(source, "123", NOW)
    assert reference["post_age_seconds"] is None
    assert reference["post_time_status"] == "unknown"


def test_conflicting_receipt_dates_and_future_times_remain_unknown():
    source = {"publish_ledger": {"a": {"tweet_id": "123", "at": POST},
                                 "b": {"tweet_id": "123", "at": "2026-09-07T00:00:00Z"}}}
    assert publication_reference(source, "123", NOW)["receipt_time_status"] == "conflict"
    source["publish_ledger"] = {"a": {"tweet_id": "123", "at": "2026-09-10T00:00:00Z"}}
    assert publication_reference(source, "123", NOW)["post_age_seconds"] is None


def test_confirmed_receipt_takes_precedence_and_fingerprint_is_not_invented():
    source = {"publish_ledger": {"event": {"tweet_id": "123", "at": POST,
              "confirmed_at": "2026-09-08T00:01:00Z", "text_sha256": "a" * 64}},
              "drafts": [{"tweet_id": "123", "posted_at": POST, "text": "later edited text"}]}
    reference = publication_reference(source, "123", NOW)
    assert reference["post_age_seconds"] is None
    assert reference["receipt_age_seconds"] == 86340
    assert reference["receipt_time_status"] == "proxy"
    assert reference["published_text_sha256"] == "a" * 64
    del source["publish_ledger"]["event"]["text_sha256"]
    assert publication_reference(source, "123", NOW)["published_text_sha256"] is None


def test_receipt_conflict_branches_retain_their_own_reference():
    source = {"publish_ledger": {"event": {"phase": "unknown", "tweet_id": None,
              "attempt_conflicts": [{"tweet_id": "123", "at": POST, "text_sha256": "b" * 64}]}}}
    reference = publication_reference(source, "123", NOW)
    assert reference["post_age_seconds"] is None
    assert reference["receipt_age_seconds"] == 86400
    assert reference["published_text_sha256"] == "b" * 64


def test_sample_requires_aware_clock():
    with pytest.raises(ValueError):
        sample(at=NOW.replace(tzinfo=None))


def test_modern_intent_time_cannot_establish_either_age():
    source = {"publish_ledger": {"event": {"tweet_id": "123", "phase": "confirmed", "at": POST}}}
    reference = publication_reference(source, "123", NOW)
    assert reference["post_age_seconds"] is None
    assert reference["receipt_age_seconds"] is None
    assert reference["receipt_time_status"] == "unknown"


def test_platform_created_at_is_required_for_true_post_age():
    reference = publication_reference(STATE, "123", NOW, POST)
    assert reference["post_age_seconds"] == 86400
    assert reference["post_time_basis"] == "x_api.created_at"
    assert reference["post_time_status"] == "recorded"
    for invalid in (None, "bad", "2026-09-10T00:00:00Z", "2026-02-31T00:00:00Z"):
        assert publication_reference(STATE, "123", NOW, invalid)["post_age_seconds"] is None
