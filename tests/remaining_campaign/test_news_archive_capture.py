"""News requests use the same real pinned SDK capture seam as writer checks."""
from datetime import UTC, datetime

import pytest

from src.data import newsworthiness as news
from src.two_bot import call_inventory, request_archive, request_archive_replay
from tests.test_request_archive_sdk import OfflineProviders, journey_env, offline_transport, private_root

__all__ = ["journey_env"]


def calls():
    return (lambda: news._call_grounded_search(datetime(2026, 10, 30, tzinfo=UTC)),
            lambda: news._call_verify_flash("Invented claim", 1, "Invented retained article"))


def providers(*, timeout=False):
    # Both routes use the actual configured cheap Google model. The inherited
    # offline SDK fixture calls that model's transport bucket "fact_check".
    output = OfflineProviders()
    output.queue("fact_check", *([{"raise": True}] if timeout else [{"text": "[]"}, {"text": '{"supported":true}'}]))
    return output


def test_capture_on_and_off_send_identical_news_requests_with_exact_once_joins(journey_env, tmp_path):
    plain = providers()
    with offline_transport(plain):
        expected = [call() for call in calls()]
    archived = providers()
    before = call_inventory.runtime_counts()
    with offline_transport(archived), request_archive.capture(private_root(tmp_path), operation="invented news capture") as scope:
        actual = [call() for call in calls()]
    assert actual == expected
    assert archived.physical == plain.physical and len(archived.physical) == 2
    loaded = request_archive_replay.load_archive(scope.directory)
    assert [call.stage for call in loaded.calls] == ["newsworthiness_search", "newsworthiness_verify"]
    for call in loaded.calls:
        assert len(call.attempts) == 1 and call.outcome == "returned"
        attempt = call.attempts[0]
        assert attempt.response.availability == "captured"
        assert loaded.artifact(attempt.response.artifact)
    after = call_inventory.runtime_counts()
    for stage in ("newsworthiness_search", "newsworthiness_verify"):
        assert after.get(stage, 0) - before.get(stage, 0) == 1
        assert call_inventory.archive_coverage()[stage] == "provider_call_seam"


def test_news_transport_timeout_is_retained_unknown_without_resend(journey_env, tmp_path):
    sent = providers(timeout=True)
    with offline_transport(sent), request_archive.capture(private_root(tmp_path), operation="invented news timeout") as scope:
        with pytest.raises(Exception):
            calls()[1]()
    loaded = request_archive_replay.load_archive(scope.directory)
    assert len(sent.physical) == len(loaded.calls) == 1
    assert loaded.calls[0].stage == "newsworthiness_verify"
    assert loaded.calls[0].outcome == "raised_after_send"
