"""Real cross-runtime persistence checks; no provider calls or production state."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from scripts.gen_state_contract import OUTPUT, render
from src.state import DEFAULT_STATE, StateReadError, _configured_backend, _merge_drafts, read_state
from src.storage import sqlite_store

REPO = Path(__file__).resolve().parents[1]
CASES = json.loads((REPO / "tests/fixtures/draft_retention_contract.json").read_text())
NOW = datetime(2026, 9, 8, tzinfo=UTC)


def expand_groups(case):
    rows = []
    for group in case["groups"]:
        for index in range(group["count"]):
            row = {"id": f'{group["prefix"]}-{index}', "text": "Saved exact text", **deepcopy(group["draft"])}
            if group.get("stepSeconds"):
                start = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                row["created_at"] = (start + timedelta(seconds=index * group["stepSeconds"])).isoformat()
            rows.append(row)
    return rows


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_retention_contract(case):
    rows = expand_groups(case)
    before = deepcopy(rows)
    expected = [f'{group["prefix"]}-{index}' for group in case["keep"] for index in range(group["start"], group["end"])]
    out = _merge_drafts(rows[::2], rows[1::2], now=NOW)
    assert sorted(row["id"] for row in out) == sorted(expected)
    assert rows == before


def test_dashboard_generated_contract_is_current_and_complete():
    assert OUTPUT.read_text() == render(), "Run python scripts/gen_state_contract.py after an intentional contract change"
    dedicated = {"last_hot10", "streaks", "posted_events", "daily_tweet_count", "drafts", "run_history", "errors"}
    assert set(DEFAULT_STATE) == dedicated | set(sqlite_store._METADATA_JSON_KEYS)


def populated_state():
    state = deepcopy(DEFAULT_STATE)
    for key in sqlite_store._METADATA_JSON_KEYS:
        default = state[key]
        if isinstance(default, dict):
            state[key] = {"sentinel": {"field": key, "value": "53°C — untouched", "count": 3}}
        elif isinstance(default, list):
            state[key] = [{"id": f"sentinel-{key}", "ts": "2099-09-08T12:00:00Z", "value": key}]
        elif key == "_state_rev":
            state[key] = 7
        else:
            state[key] = f"sentinel-{key}"
    state.update(
        publication_control={"retired_epochs": ["fixture-pause-epoch", "retired-release-fixture"],
                             "observed_at": "2099-09-08T12:00:00Z", "epoch": "fixture-pause-epoch",
                             "enabled": False, "reason": "Offline paused fixture"},
        last_hot10={"date": "2099-09-08", "cities": [{"city": "Test", "anomaly_c": 2.5}]},
        streaks={"place": {"consecutive_days": 3, "last_seen": "2099-09-08"}},
        posted_events=["sent-event"], daily_tweet_count={"2099-09-08": 2},
        drafts=[{"id": "draft-1", "text": "53°C — original", "status": "pending", "content_revision": 2,
                 "created_at": "2099-09-08T12:00:00Z", "revision_history": [{"text": "old", "content_revision": 1}],
                 "revision_conflicts": [{"text": "alternate", "content_revision": 2}],
                 "approval_binding": {"content_revision": 2, "operator": "fixture"}, "publish_outcome": "unknown"}],
        run_history=[{"id": "run-1", "started_at": "2099-09-08T12:00:00Z", "runtime": {"flags": {"auto": False}},
                      "sources": [{"source": "fixture", "status": "ok", "provenance": {"url": "https://example.invalid"}}]}],
        errors=[{"source": "fixture", "ts": "2099-09-08T12:00:00Z", "msg": "synthetic"}],
    )
    return state


def node_store(db_path, operation, payload=None):
    # Execute this checkout's module explicitly; dependency symlinks must never
    # redirect imports into another working tree or require a real Gist token.
    script = '''
      import { readStateStore, writeStateStore, updateDraftStore } from "./dashboard/lib/state-store.js";
      import { readFileSync } from "node:fs";
      const input = JSON.parse(readFileSync(0, "utf8"));
      globalThis.fetch = () => { throw new Error("Network forbidden in persistence test") };
      if (input.operation === "edit") await updateDraftStore("draft-1", row => ({...row, text: "53°C — locally edited", content_revision: 3}));
      if (input.operation === "write") await writeStateStore(input.payload);
      console.log(JSON.stringify(await readStateStore()));
    '''
    env = {**os.environ, "THEHEAT_STATE_BACKEND": "sqlite", "THEHEAT_DB_PATH": str(db_path), "GIST_ID": "", "GITHUB_TOKEN": ""}
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO, env=env,
                            input=json.dumps({"operation": operation, "payload": payload}), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_every_python_field_survives_real_dashboard_sqlite_read_and_command(tmp_path):
    db = tmp_path / "state.sqlite"
    source = populated_state()
    assert sqlite_store.write_state(str(db), source)
    loaded = node_store(db, "read")
    for key in source:
        assert loaded[key] == source[key], key
    node_store(db, "edit")
    result = sqlite_store.read_state(str(db), DEFAULT_STATE)
    assert result["drafts"][0]["text"] == "53°C — locally edited"
    for key in source:
        if key != "drafts":
            assert result[key] == source[key], key
    for key in ("revision_history", "revision_conflicts", "approval_binding", "publish_outcome"):
        assert result["drafts"][0][key] == source["drafts"][0][key]


def test_dashboard_full_and_partial_writes_preserve_all_current_python_fields(tmp_path):
    db = tmp_path / "state.sqlite"
    source = populated_state()
    node_store(db, "write", source)
    node_store(db, "write", {"drafts": []})
    result = sqlite_store.read_state(str(db), DEFAULT_STATE)
    assert result == source


def test_python_suppression_metadata_supersedes_old_dashboard_table(tmp_path):
    db = tmp_path / "state.sqlite"
    source = populated_state()
    node_store(db, "write", source)
    source["suppressions"] = []
    assert sqlite_store.write_state(str(db), source)
    assert node_store(db, "read")["suppressions"] == []


def test_unknown_backend_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("THEHEAT_STATE_BACKEND", "postgres-typo")
    with pytest.raises(StateReadError, match="Unsupported state backend"):
        _configured_backend()


def test_sqlite_bootstrap_write_failure_cannot_return_empty_state(tmp_path):
    with patch.dict(os.environ, {"THEHEAT_STATE_BACKEND": "sqlite"}), patch.multiple(
        "src.state", DB_PATH=str(tmp_path / "state.sqlite"), GIST_ID="fixture", GITHUB_TOKEN="fixture"
    ), patch("src.state._read_gist_state", return_value=populated_state()), patch.object(sqlite_store, "write_state", return_value=False):
        with pytest.raises(StateReadError, match="Failed to bootstrap"):
            read_state()


def test_incomplete_gist_credentials_cannot_bootstrap_empty_sqlite(tmp_path):
    with patch.dict(os.environ, {"THEHEAT_STATE_BACKEND": "sqlite"}), patch.multiple(
        "src.state", DB_PATH=str(tmp_path / "state.sqlite"), GIST_ID="fixture", GITHUB_TOKEN=""
    ):
        with pytest.raises(StateReadError, match="requires both GIST_ID and GITHUB_TOKEN"):
            read_state()


def test_python_write_also_refuses_failed_configured_bootstrap(tmp_path):
    from src.state import write_state
    with patch.dict(os.environ, {"THEHEAT_STATE_BACKEND": "sqlite"}), patch.multiple(
        "src.state", DB_PATH=str(tmp_path / "state.sqlite"), GIST_ID="fixture", GITHUB_TOKEN="fixture"
    ), patch("src.state._read_gist_state", side_effect=StateReadError("synthetic unavailable")):
        assert write_state({"drafts": []}) is False
    assert sqlite_store.is_empty(str(tmp_path / "state.sqlite"))


def test_future_sqlite_metadata_fails_closed_in_both_runtimes(tmp_path):
    import sqlite3
    from src.state import write_state
    db_path = tmp_path / "state.sqlite"
    assert sqlite_store.write_state(str(db_path), populated_state())
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO metadata (key, value_json) VALUES (?, ?)", ("future_field", '{"receipt":"do not erase"}'))
    with pytest.raises(ValueError, match="Unsupported SQLite metadata.*future_field"):
        sqlite_store.read_state(str(db_path), DEFAULT_STATE)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        node_store(db_path, "write", {"drafts": []})
    assert "Unsupported SQLite metadata fields: future_field" in exc.value.stderr
    with patch.dict(os.environ, {"THEHEAT_STATE_BACKEND": "sqlite"}), patch.multiple(
        "src.state", DB_PATH=str(db_path), GIST_ID="", GITHUB_TOKEN=""
    ):
        assert write_state({"drafts": []}) is False
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT value_json FROM metadata WHERE key='future_field'").fetchone()[0] == '{"receipt":"do not erase"}'
