"""Actual PG edit transaction regression; run only by required CI PG profile."""
from copy import deepcopy

from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_command_authority import make_authority as make_authority
from tests.test_command_authority import EDITOR, NOW, command, resolver
from tests.test_operator_claim_reference_edits import reference_draft
from tests.test_operator_claim_references import FIXTURE


def test_postgres_persists_reference_only_edits_and_refuses_bad_or_stale_followup(make_authority):
    make, _, _ = make_authority
    draft = reference_draft()
    initial = {"drafts": [draft], "publish_ledger": {}}
    store = make(initial)
    cmd = command(draft, payload={"text": draft["text"], "operator_claim_references": FIXTURE["items"]})
    store.accept(cmd, EDITOR, now=NOW)
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW)["status"] == "applied"
    version, saved = store.read()
    assert version == 1
    current = saved["drafts"][0]
    assert current["text"] == draft["text"]
    assert current["content_revision"] == draft["content_revision"] + 1
    assert current["review_context"]["operator_claim_references"] == FIXTURE["saved"]
    assert current["review_context"]["two_bot"]["bundle"] == draft["review_context"]["two_bot"]["bundle"]
    malformed = deepcopy(FIXTURE["items"])
    malformed[0]["sources"][0]["pointer"] = "/current_facts/64"
    for target, references in ((current, malformed), (draft, [])):
        rejected = command(target, payload={"text": target["text"], "operator_claim_references": references})
        store.accept(rejected, EDITOR, now=NOW)
        assert store.consume(resolver, command_id=rejected.command_id, now=NOW)["status"] == "rejected"
        assert store.read() == (version, saved)
