"""Imported malformed references must refuse durably, then release local edits."""

from copy import deepcopy

import pytest

from src.commands import postgres_editor_media, preview_media_worker
from src.commands.reducer import _target_drafts
from src.storage import ghcn_runtime_inputs
from src.storage import postgres_projection as projection
from src.two_bot import ghcn_claim_contract as passive
from tests.ghcn_claim_contract_helpers import pair
from tests.test_command_authority import EDITOR, NOW, command, resolver
from tests.test_postgres_command_authority import make_authority as make_authority
from tests.test_postgres_projection import cluster as cluster, database as database


@pytest.mark.parametrize("bad_date", ["not-a-date", 123], ids=["invalid-string", "integer"])
def test_imported_bad_date_refuses_media_then_following_edit_applies(make_authority, tmp_path, monkeypatch, bad_date):
    make, _, _ = make_authority
    _, _, view, _ = pair(passive)
    view["raw_signal_dump"]["ghcn_claim_view"]["selection"]["signal_date"] = bad_date
    draft = dict(id="invented-imported-claim", event_id=view["event_id"],
        text="An invented station report.", status="pending", content_revision=1,
        decision_revision=1, review_context={"two_bot": {"bundle": view}})
    initial = dict(drafts=[draft], publish_ledger={})
    assert projection._decode(projection._snapshot(initial)[0]) == initial
    store = make(initial)
    # The typed capability is present, but these never-opened paths grant no
    # source qualification. Structural refusal must precede any reconstruction.
    store.ghcn_baseline = ghcn_runtime_inputs.Baseline(tmp_path / "unopened.sqlite",
        tmp_path / "unopened.json", "a" * 64, "b" * 64)

    def no_native(*args, **kwargs):
        pytest.fail("A malformed reference must not reach native work")

    monkeypatch.setattr(preview_media_worker, "run_native", no_native)
    media = command(draft, "prepare_media_revision", dict(expected_policy_sha256="a" * 64,
        expected_renderer_profile_sha256="b" * 64))
    edit = command(draft, "edit_revision", dict(text="A following valid invented edit."))
    assert _target_drafts(initial, media) == [draft]
    store.accept(media, EDITOR, now=NOW)
    store.accept(edit, EDITOR, now=NOW)
    before = deepcopy(store.read())
    result = preview_media_worker.consume_media_once(store, resolver, command_id=media.command_id, now=NOW)
    assert result["status"] == "rejected" and result["code"] == "ghcn_claim_view_shape"
    assert store.result(media.command_id) == result and store.read() == before
    assert store.consume(resolver, command_id=media.command_id, now=NOW) == result
    passive_view = postgres_editor_media.view_claim(store, draft["id"])
    assert passive_view.code == "ghcn_claim_view_shape"
    following = store.consume(resolver, command_id=edit.command_id, now=NOW)
    assert following["status"] == "applied" and store.result(edit.command_id) == following
    version, saved = store.read()
    assert version == before[0] + 1 and saved["drafts"][0]["text"] == edit.payload["text"]
    assert not saved["drafts"][0].get("publication_approved")
    assert saved["publish_ledger"] == {} and not store.ghcn_baseline.database.exists()
