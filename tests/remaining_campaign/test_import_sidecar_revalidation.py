"""Required sidecar bytes remain preconditions when a passive import executes."""
import hashlib

import pytest

from src.commands import import_plan
from src.commands.schema import CommandError

RAW = b'{"drafts":[]}'


class History:
    def __init__(self):
        self.imported = {}

    def import_snapshot(self, raw, *, import_id, now=None):
        self.imported[import_id] = {"artifact_sha256": hashlib.sha256(raw).hexdigest()}
        return {"snapshot_id": import_id}


@pytest.fixture
def history(monkeypatch):
    target = History()
    monkeypatch.setattr(import_plan, "_existing", lambda authority, identity: target.imported.get(identity))
    return target


@pytest.mark.parametrize("change", ["remove", "replace", "symlink"])
def test_sidecar_change_after_planning_refuses_before_any_write(tmp_path, history, change):
    source = tmp_path.resolve() / "source.json"
    source.write_bytes(b"invented retained source")
    items = [("first", RAW)]
    plan = import_plan.plan(items, sidecars={"first": (str(source),)})
    assert plan["executable"]
    source.unlink()
    if change == "replace":
        source.write_bytes(b"different retained bytes")
    elif change == "symlink":
        target = tmp_path.resolve() / "other.json"
        target.write_bytes(b"invented retained source")
        source.symlink_to(target)
    with pytest.raises(CommandError) as refused:
        import_plan.execute(history, plan, items)
    assert refused.value.code == "import_sidecar_changed"
    assert history.imported == {}


def test_change_between_items_preserves_completed_history_and_resumes_only_with_exact_bytes(tmp_path, history):
    source = tmp_path.resolve() / "source.json"
    original = b"invented retained source"
    source.write_bytes(original)
    items = [("first", RAW), ("second", RAW)]
    plan = import_plan.plan(items, sidecars={"first": (str(source),), "second": (str(source),)})
    with pytest.raises(CommandError) as refused:
        import_plan.execute(history, plan, items, between_items=lambda identity: source.write_bytes(b"changed"))
    assert refused.value.code == "import_sidecar_changed"
    assert list(history.imported) == ["first"]
    source.write_bytes(original)
    result = import_plan.execute(history, plan, items)
    assert [row["status"] for row in result["items"]] == ["already_imported", "imported"]
    assert result["migration_complete"] is False and result["publication_authorized"] is False
