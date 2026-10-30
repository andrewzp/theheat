"""W14.6 provenance channel: import journal -> local preview ``GET /state`` -> dashboard.

The real importer writes the journal, the real reader decides currentness by exact
revision identity, and the real preview handler carries the map. Node
(remaining-campaign-w14-recovery.test.js) feeds the same reply to /api/dashboard.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import sqlite3

import pytest

from src.commands import recovery_provenance
from src.commands.schema import canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from tests.live_content_harness import trap_network
from tests.remaining_campaign import w14_provenance_child as child


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    trap_network(monkeypatch.setattr)


def _import(journal, snapshot, import_id, hour):
    from src.commands import import_plan
    raw = canonical_json(snapshot).encode()
    import_plan.execute(journal, import_plan.plan([(import_id, raw)], authority=journal), [(import_id, raw)],
                        now=datetime(2026, 10, 30, hour, tzinfo=UTC))
    return hashlib.sha256(raw).hexdigest()


def _journal(tmp_path, snapshot, *, import_id="w14p-import", environment="local"):
    journal = SQLiteAuthority(tmp_path / f"{import_id}.sqlite3", environment=environment)
    journal.initialize({"drafts": [], "publish_ledger": {}})
    return journal, _import(journal, snapshot, import_id, 8)


def test_state_reply_marks_exact_imported_identities_read_only(tmp_path):
    result = child.run(str(tmp_path))
    assert result["import"] == ["imported"] and result["status"] == 200 and result["journal_unchanged"]
    entry = {"origin": "import", "import_id": "w14p-import", "source_sha256": result["source_sha256"]}
    # Changed bytes do not establish a supported current transition; fresh was never imported.
    assert result["reply"]["recovery_provenance"] == {"w14p-held": entry, "w14p-posted": entry, "w14p-edited": entry}
    assert {d["id"] for d in result["reply"]["state"]["drafts"]} == {"w14p-held", "w14p-posted", "w14p-edited", "w14p-fresh"}
    assert result["unconfigured_status"] == 200 and result["unconfigured_provenance"] == {}


def test_reader_never_infers_currentness_and_prefers_the_matching_import(tmp_path):
    snapshot, current = child.fixture()
    journal, sha = _journal(tmp_path, snapshot)
    # A later import holding the edited revision binds that draft to the later import only;
    # unchanged drafts keep the earliest import that holds their exact identity.
    second = _import(journal, current, "w14p-second", 9)
    found = recovery_provenance.provenance(journal.path, current)
    assert found["w14p-held"] == {"origin": "import", "import_id": "w14p-import", "source_sha256": sha}
    assert found["w14p-edited"] == {"origin": "import", "import_id": "w14p-second", "source_sha256": second}
    assert found["w14p-fresh"]["import_id"] == "w14p-second"
    # Unavailable identity on either side, or an ambiguous current id, stays read-only.
    broken = deepcopy(current)
    broken["drafts"][2]["content_revision"] = "two"
    assert "w14p-edited" in recovery_provenance.provenance(journal.path, {"drafts": broken["drafts"][:3]})
    duplicated = {"drafts": [current["drafts"][2], deepcopy(current["drafts"][2])]}
    alone, _ = _journal(tmp_path, snapshot, import_id="w14p-alone")
    assert "w14p-edited" in recovery_provenance.provenance(alone.path, duplicated)
    assert "w14p-edited" in recovery_provenance.provenance(alone.path, {"drafts": [current["drafts"][2]]})
    assert recovery_provenance.provenance(None, current) == {}


def test_unusable_journal_refuses_at_start_and_at_request(tmp_path):
    snapshot, current = child.fixture()
    operators = child.operators_file(tmp_path)
    good, _ = _journal(tmp_path, snapshot)
    preview, _ = _journal(tmp_path, snapshot, import_id="w14p-preview", environment="preview")
    plain = tmp_path / "plain.sqlite3"
    with sqlite3.connect(plain) as connection:
        connection.execute("CREATE TABLE authority_metadata (singleton INTEGER, environment TEXT)")
        connection.execute("INSERT INTO authority_metadata VALUES (1, 'local')")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(good.path)
    target = child.server(current, operators, None)
    for bad in ("relative.sqlite3", str(tmp_path / "missing.sqlite3"), str(tmp_path), str(link), str(plain), preview.path):
        with pytest.raises(recovery_provenance.ProvenanceUnavailable):
            # Refused before any socket is bound.
            target._initialize(child.LocalAuthority(current), target.operators, port=child.PORT, origin=child.ORIGIN,
                               candidate_inputs=(), recovery_journal=bad)
    configured = child.server(current, operators, good.path)
    assert child.get_state(configured)[0] == 200
    Path(good.path).rename(tmp_path / "moved.sqlite3")
    status, reply = child.get_state(configured)
    assert status == 503 and reply["code"] == "authority_unavailable" and "state" not in reply


def test_reader_opens_read_only(tmp_path):
    snapshot, current = child.fixture()
    journal, _ = _journal(tmp_path, snapshot)
    before = hashlib.sha256(open(journal.path, "rb").read()).hexdigest()
    recovery_provenance.provenance(journal.path, current)
    connection = recovery_provenance._connect(journal.path, "local")
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO authority_metadata(singleton, environment) VALUES(2, 'local')")
    finally:
        connection.close()
    assert hashlib.sha256(open(journal.path, "rb").read()).hexdigest() == before
    assert child.server(current, child.operators_file(tmp_path), None).recovery_provenance(current) == {}
