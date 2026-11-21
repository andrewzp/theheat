"""Review counterexamples: source recognition is diagnostic, never eligibility."""
import gzip
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from src.data import ghcn, ghcn_format
from tests.ghcn_intake_cases import DATES, NOW, SID, TODAY, Replies, csv, payloads
from tests.test_ghcn_format import _make_diff_tar


@pytest.mark.parametrize("body", [b"", b" \n\t", gzip.compress(b" \n\t")])
def test_empty_http_response_cannot_claim_completed_intake(body):
    replies = Replies({DATES[-1]: body})
    metrics: dict = {"diff_intake": {"old": True}}
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
        values = ghcn._fetch_recent_obs(
            frozenset({SID}), today=TODAY, metrics_out=metrics, revisions_out=[],
        )
    assert values == {}
    assert metrics["diff_dates_fetched"] == 1
    assert "diff_intake" not in metrics


@pytest.mark.parametrize("position", [0, 1, 2])
def test_any_unrecognized_fetched_date_withholds_diagnostic_without_changing_science(position):
    data = payloads()
    data[DATES[position]] = b" \n\t"

    def fetch(with_metrics):
        replies = Replies(data)
        metrics: dict = {}
        revisions: list = []
        with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
            values = ghcn._fetch_recent_obs(
                frozenset({SID}), today=TODAY, revisions_out=revisions,
                tracked_keys={(SID, TODAY, "TMAX")}, metrics_out=metrics if with_metrics else None,
            )
        return values, revisions, replies.calls, metrics

    values, revisions, calls, metrics = fetch(True)
    plain_values, plain_revisions, plain_calls, _ = fetch(False)
    assert (values, revisions, calls) == (plain_values, plain_revisions, plain_calls)
    assert metrics["diff_dates_fetched"] == 3 and len(calls) == 3
    assert "diff_intake" not in metrics


@pytest.mark.parametrize("raw", [csv("20261118").encode(), gzip.compress(csv("20261118").encode())])
def test_fixture_text_fallback_still_returns_observations_but_not_archive_evidence(raw):
    replies = Replies({DATES[-1]: raw})
    metrics: dict = {}
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
        values = ghcn._fetch_recent_obs(frozenset({SID}), today=TODAY, revisions_out=[], metrics_out=metrics)
    assert len(values) == 1
    assert "diff_intake" not in metrics


@pytest.mark.parametrize("raw,recognized", [
    (b"", False), (b" \n\t", False), (gzip.compress(b" \n\t"), False),
    (csv("20261118").encode(), False),
    (_make_diff_tar({"insert.csv": ""}), True),
    (_make_diff_tar({"insert.csv": csv("20261118", "PRCP")}), True),
])
def test_archive_recognition_comes_from_the_existing_single_parser_pass(raw, recognized):
    diagnostics = {"recognized_archive": True}
    with patch.object(ghcn_format, "_parse_superghcnd_diff_tar_bytes", wraps=ghcn_format._parse_superghcnd_diff_tar_bytes) as parser:
        records = ghcn_format.parse_superghcnd_diff_records_bytes(raw, diagnostics_out=diagnostics)
    assert parser.call_count == (1 if raw else 0)
    assert (diagnostics.get("recognized_archive") is True) == recognized
    assert records == ghcn_format.parse_superghcnd_diff_records_bytes(raw)


def test_failed_parse_cannot_reuse_archive_recognition():
    diagnostics = {"recognized_archive": True}
    with pytest.raises(ValueError):
        ghcn_format.parse_superghcnd_diff_records_bytes(
            _make_diff_tar({"insert.csv": "broken"}), diagnostics_out=diagnostics,
        )
    assert "recognized_archive" not in diagnostics
