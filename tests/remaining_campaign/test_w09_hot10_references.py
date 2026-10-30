"""W09.1: operator quote references for a qualified Hot10 bulletin (invented catalogue rows).

The bulletin's ``ranking`` fact is a list of flat rows. Each ranked row is offered as one
exact list element (the PM2.5 element pattern), bound by the whole fact's fingerprint,
the index and the row; the whole list, nested rows and an empty list stay unreferenceable.
Real consumers: ``invalidate_text`` (edit), the local command reducer and ``project_draft``.
"""
from copy import deepcopy

import pytest

from src.commands.reducer import reduce_command
from src.editorial import operator_claim_references as refs
from src.editorial.revisions import draft_identity, fingerprint, invalidate_text, project_draft
from tests.gist_hazard_helpers import saved_state
from tests.test_command_authority import EDITOR, NOW, command


def hot10_draft():
    return deepcopy(saved_state("hot10")["drafts"][0])


def fact_index(bundle, label):
    return next(i for i, row in enumerate(bundle["current_facts"]) if row["label"] == label)


def quote(text, words=2):
    end = len(" ".join(text.split(" ")[:words]))
    return {"start": 0, "end": end, "text": text[:end]}


def test_hot10_facts_are_referenceable_and_each_ranked_row_is_one_exact_element():
    draft = hot10_draft()
    bundle = draft["review_context"]["two_bot"]["bundle"]
    facts = refs.retained_claim_facts(bundle)  # Previously refused whole (rows + empty rank_changes).
    ranking, changes = fact_index(bundle, "ranking"), fact_index(bundle, "rank_changes")
    assert len(facts[ranking]["value"]) == 10 and facts[changes]["value"] == []
    view, bound = refs.resolve_reference(facts, f"/current_facts/{ranking}/value/2")
    assert view == {"label": "ranking[2]", "value": facts[ranking]["value"][2], "unit": None}
    assert bound == {"fact_sha256": fingerprint(facts[ranking]), "element": 2, "value": facts[ranking]["value"][2]}
    for pointer in (f"/current_facts/{ranking}", f"/current_facts/{ranking}/value/10",
                    f"/current_facts/{changes}", f"/current_facts/{changes}/value/0"):
        with pytest.raises(ValueError):
            refs.resolve_reference(facts, pointer)


@pytest.mark.parametrize("row", [
    {"rank": 1, "nested": {"city": "Invented"}},          # nested object
    {"rank": 1, "cities": ["Invented"]},                  # list field
    {"Rank": 1},                                           # unsupported field name
    {},                                                    # empty record
    {f"field_{i}": i for i in range(17)},                  # more than 16 fields
    {"rank": float("inf")},                                # non-finite number
])
def test_nested_or_unbounded_rows_keep_the_bundle_unreferenceable(row):
    bundle = deepcopy(hot10_draft()["review_context"]["two_bot"]["bundle"])
    bundle["current_facts"][fact_index(bundle, "ranking")]["value"][0] = row
    with pytest.raises(ValueError, match="Saved source facts are unavailable"):
        refs.retained_claim_facts(bundle)


def test_edit_saves_a_ranked_row_reference_and_a_changed_row_makes_it_unavailable():
    draft = hot10_draft()
    bundle = draft["review_context"]["two_bot"]["bundle"]
    ranking = fact_index(bundle, "ranking")
    items = [{"claim": quote(draft["text"]), "sources": [
        {"pointer": f"/current_facts/{fact_index(bundle, 'leader_city')}"},
        {"pointer": f"/current_facts/{ranking}/value/0"}]}]
    before = deepcopy(draft)
    invalidate_text(draft, draft["text"], operator_claim_references=items)
    assert draft["content_revision"] == before["content_revision"] + 1  # Reference-only edit is a revision.
    assert draft["review_context"]["two_bot"] == before["review_context"]["two_bot"]  # Source untouched.
    view = project_draft(draft)["operator_claim_reference_view"]
    assert view["status"] == "saved"
    row = view["items"][0]["sources"][1]["fact"]
    assert row["label"] == "ranking[0]" and row["value"]["rank"] == 1 and row["value"] == bundle["current_facts"][ranking]["value"][0]
    # Any change to the bound row (or the whole ranking) never keeps the saved connection current.
    changed = deepcopy(draft)
    changed["review_context"]["two_bot"]["bundle"]["current_facts"][ranking]["value"][0]["departure_c"] += 0.1
    assert project_draft(changed)["operator_claim_reference_view"]["status"] == "unavailable"
    reordered = deepcopy(draft)
    rows = reordered["review_context"]["two_bot"]["bundle"]["current_facts"][ranking]["value"]
    rows[0], rows[1] = rows[1], rows[0]
    assert project_draft(reordered)["operator_claim_reference_view"]["status"] == "unavailable"


def test_local_command_reducer_accepts_the_row_reference_without_changing_text_or_source():
    draft = hot10_draft()
    bundle = draft["review_context"]["two_bot"]["bundle"]
    ranking = fact_index(bundle, "ranking")
    items = [{"claim": quote(draft["text"]), "sources": [{"pointer": f"/current_facts/{ranking}/value/1"}]}]
    original = deepcopy(draft)
    state: dict = {"drafts": [draft], "publish_ledger": {}}
    before_identity = draft_identity(draft)
    reduced = reduce_command(state, command(draft, payload={"text": draft["text"], "operator_claim_references": items}), EDITOR, now=NOW)
    assert state["drafts"][0] == original  # Caller-owned state is unchanged; the reduction carries the edit.
    saved = reduced.state["drafts"][0]
    assert saved["text"] == original["text"]
    assert fingerprint(saved["review_context"]["two_bot"]["bundle"]) == fingerprint(original["review_context"]["two_bot"]["bundle"])
    assert draft_identity(saved)["content_revision"] == before_identity["content_revision"] + 1
    assert project_draft(saved)["operator_claim_reference_view"]["status"] == "saved"
    # The whole ranking list is still never a scalar source.
    whole = [{"claim": quote(saved["text"]), "sources": [{"pointer": f"/current_facts/{ranking}"}]}]
    with pytest.raises(ValueError, match="one exact element"):
        refs.build_operator_claim_references(saved["text"], saved["review_context"]["two_bot"]["bundle"], whole)
