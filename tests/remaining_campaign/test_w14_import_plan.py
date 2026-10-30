"""W14.1/14.2: lossless import plan and resumable idempotent import on disposable stores.

Invented fictional places and identities; never production history or Gist.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from src.commands import import_plan, local_cli
from src.commands.schema import CommandError
from src.commands.sqlite_authority import SQLiteAuthority

# Exact spellings a canonical writer would change; kept byte-for-byte.
FIRST = (b'{"drafts":[{"id":"w14-a","status":"posted","text":"Invented Vale reached 41C.","tweet_id":"1900000000000000001",'
         b'"score":{"total":500.0,"ratio":1e2,"delta":-0.0,"big":9007199254740993}}],'
         b'"publish_ledger":{"ev-1":{"phase":"unknown","tweet_id":null},"ev-2":{"phase":"confirmed","tweet_id":"1900000000000000001"},'
         b'"ev-3":{"phase":"submitted"}},"posted_events":["ev-2"],"memory":{"seen":[]}}')
SECOND = b'{"drafts":[{"id":"w14-b","status":"pending","text":"Invented Harbor saw 30mm.","score":{"total":12.50}}]}'


@pytest.fixture
def target(tmp_path):
    store = SQLiteAuthority(tmp_path / "import-target.sqlite")
    store.initialize({"drafts": []})
    return store


def test_plan_states_findings_protected_fields_and_collisions_before_any_mutation(target, tmp_path):
    before = target.domain_status(verify=True)
    value = import_plan.plan([("hist-1", FIRST), ("hist-2", SECOND)], authority=target,
                             sidecars={"hist-2": (str(tmp_path / "absent-sidecar.json"),)})
    assert target.domain_status(verify=True) == before and value["mutation"] == "none"
    first, second = value["items"]
    classes = {(f["pointer"], f["class"]) for f in first["numeric_findings"]}
    assert ("/drafts/0/score/total", "integral_float") in classes
    assert ("/drafts/0/score/ratio", "noncanonical_spelling") in classes
    assert ("/drafts/0/score/delta", "negative_zero") in classes
    assert ("/drafts/0/score/big", "unsafe_integer") in classes
    assert all(f["disposition"] == "preserved_as_original_bytes" for f in first["numeric_findings"])
    assert first["protected"]["ledger_phases"] == {"confirmed": 1, "submitted": 1, "unknown": 1}
    assert first["protected"]["unknown_deliveries_preserved"] == 2
    assert first["protected"]["draft_fields"]["tweet_id"] == 1 and "posted_events" in first["protected"]["top_level"]
    assert first["unprojected_top_level_fields"] == ["posted_events"]
    assert second["missing"] == [{"sidecar": "absent-sidecar.json", "code": "source_sidecar_unavailable"}]
    assert {"pointer": "/drafts/0/score/total", "token": "12.50", "class": "noncanonical_spelling",
            "disposition": "preserved_as_original_bytes"} in second["numeric_findings"]
    assert value["executable"] is False and value["migration_claim"] == "partial_history_only"
    with pytest.raises(CommandError) as refused:
        import_plan.execute(target, value, [("hist-1", FIRST), ("hist-2", SECOND)])
    assert refused.value.code == "import_plan_not_executable"


def test_interrupted_import_resumes_without_duplicates_and_keeps_original_bytes(target):
    items = [("hist-1", FIRST), ("hist-2", SECOND)]
    value = import_plan.plan(items, authority=target)
    assert value["executable"] is True

    def crash(import_id):
        if import_id == "hist-1":
            raise RuntimeError("worker interrupted after its first durable item")

    with pytest.raises(RuntimeError):
        import_plan.execute(target, value, items, between_items=crash)
    resumed = import_plan.execute(target, value, items)
    assert [row["status"] for row in resumed["items"]] == ["already_imported", "imported"]
    after = target.domain_status(verify=True)
    again = import_plan.execute(target, value, items)
    assert [row["status"] for row in again["items"]] == ["already_imported", "already_imported"]
    assert target.domain_status(verify=True) == after
    assert again["migration_complete"] is False and again["publication_authorized"] is False
    import hashlib
    assert target.read_artifact(hashlib.sha256(FIRST).hexdigest()) == FIRST  # 500.0, 1e2, -0.0 intact
    assert target.read()[1] == {"drafts": []}  # passive evidence; current state untouched


def test_changed_source_altered_plan_or_reused_identity_refuse(target):
    items = [("hist-1", FIRST)]
    value = import_plan.plan(items, authority=target)
    for changed_items, plan_value, code in (
        ([("hist-1", FIRST.replace(b"41C", b"42C"))], value, "import_source_changed"),
        (items, {**value, "executable": True, "migration_claim": "complete"}, "import_plan_changed"),
        ([("hist-1", FIRST), ("hist-9", SECOND)], value, "import_items_changed"),
    ):
        with pytest.raises(CommandError) as refused:
            import_plan.execute(target, plan_value, changed_items)
        assert refused.value.code == code
    import_plan.execute(target, value, items)
    collision = import_plan.plan([("hist-1", SECOND)], authority=target)
    assert collision["items"][0]["collision"] == "identity_collision_refused" and collision["executable"] is False


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


def test_local_cli_plans_then_runs_the_reviewed_plan(target, tmp_path):
    source = tmp_path / "first.json"
    source.write_bytes(FIRST)
    code, value = cli("--database", target.path, "import-plan", "--item", f"hist-1={source}")
    assert code == 0 and value["executable"] is True
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(value))
    code, ran = cli("--database", target.path, "import-run", "--plan", str(plan_file), "--item", f"hist-1={source}")
    assert code == 0 and ran["items"][0]["status"] == "imported"
    source.write_bytes(SECOND)
    code, refused = cli("--database", target.path, "import-run", "--plan", str(plan_file), "--item", f"hist-1={source}")
    assert code == 2 and refused["error"] == "import_source_changed"
