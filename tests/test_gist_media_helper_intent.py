"""The invented X transport checks the requested durable intent, regardless of order."""
from copy import deepcopy
from io import BytesIO

import pytest

from src.posting import twitter
from tests.gist_media_helpers import install_fake_x


@pytest.mark.parametrize("requested_first", [False, True])
def test_fake_upload_uses_the_conditionally_saved_draft_not_list_position(monkeypatch, requested_first):
    fake = install_fake_x(monkeypatch)
    requested = {"id": "requested", "event_id": "requested-event"}
    unrelated = {"id": "unrelated", "event_id": "unrelated-event"}
    drafts = [requested, unrelated] if requested_first else [unrelated, requested]
    saved = {"drafts": drafts, "publish_ledger": {"requested-event": {"phase": "submitted"}}}
    before = deepcopy(saved)
    assert fake.storage.write_state(saved, expected_draft=requested, expected_publish_ledger=None)
    uploaded = twitter._get_upload_api().media_upload(filename="invented.png", file=BytesIO(b"invented"))
    assert uploaded.media_id == 98765
    assert fake.calls == [("upload", b"invented", "invented.png")]
    assert saved == before


def test_fake_upload_still_refuses_an_unsubmitted_requested_intent(monkeypatch):
    fake = install_fake_x(monkeypatch)
    requested = {"id": "requested", "event_id": "requested-event"}
    saved = {"drafts": [requested], "publish_ledger": {"requested-event": {"phase": "not_sent"}}}
    assert fake.storage.write_state(saved, expected_draft=requested, expected_publish_ledger=None)
    with pytest.raises(AssertionError):
        twitter._get_upload_api().media_upload(filename="invented.png", file=BytesIO(b"invented"))
    assert fake.calls == []
