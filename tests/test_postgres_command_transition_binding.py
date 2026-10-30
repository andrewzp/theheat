"""Linux/PostgreSQL CI only: the role/command transition binding inside the real
PostgreSQL command transaction (W13.1). A reduction that escapes its binding is
an implementation fault: every effect rolls back and the intent stays pending."""
import sys

import pytest

from src.commands import postgres_authority as authority_module
from src.commands import reducer as reducer_module
from tests.test_command_authority import EDITOR, NOW, command, resolver, story
from tests.test_postgres_command_authority import make_authority as make_authority  # noqa: F401
from tests.test_postgres_projection import cluster as cluster, database as database  # noqa: F401

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Real PostgreSQL acceptance runs on Root's Linux CI")


def test_escaping_reduction_rolls_back_and_leaves_the_intent_pending(make_authority, monkeypatch):
    make, _, _ = make_authority
    first, second = story("w13-pg-a"), story("w13-pg-b")
    store = make({"drafts": [first, second]})
    original = reducer_module.reduce_command

    def escaping(state, cmd, principal, **kwargs):
        reduction = original(state, cmd, principal, **kwargs)
        for draft in reduction.state["drafts"]:
            if draft["id"] == "w13-pg-b":
                draft["status"] = "approved"
        return reduction

    monkeypatch.setattr(authority_module, "reduce_command", escaping)
    edit = command(first)
    store.accept(edit, EDITOR, now=NOW)
    before = store.read()
    with pytest.raises(RuntimeError, match="transition_not_allowed"):
        store.consume(resolver, command_id=edit.command_id, now=NOW)
    assert store.read() == before and store.result(edit.command_id) is None
    monkeypatch.setattr(authority_module, "reduce_command", original)
    assert store.consume(resolver, command_id=edit.command_id, now=NOW)["status"] == "applied"
