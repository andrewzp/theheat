"""Real local source/check/native/approval history; no external transport or model."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from src.commands import postgres_delivery as delivery, postgres_media as media, preview_ingress
from src.commands.schema import CommandError
from tests.test_postgres_preview_command_ingress import clean_environment
from src.storage import postgres_projection as p
from tests import test_postgres_delivery as existing, test_postgres_editor_media as editor
from tests.test_postgres_delivery import (
    admitted as admitted, offline_connections as offline_connections, cluster as cluster,
    database as database, core as core, make_authority as make_authority,
    spend_store as spend_store, worker_store as worker_store, base_store as base_store,
    store as store, inputs as inputs, native_dependencies as native_dependencies,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def approved(case, core, tmp_path, monkeypatch, *, rereview=False):
    prepared, png = editor.prepare_and_attach(case)
    if rereview:
        changed = case["text"].replace("an invented region", "this invented region")
        assert changed != case["text"]
        assert editor.action(case, "edit_revision", {"text":changed})[1]["status"] == "applied"
        case["text"] = changed
        current = editor.view(case)
        assert editor.action(case, "review_media_revision", dict(
            proposal_sha256=prepared["preparation"]["proposal_sha256"],
            expected_policy_sha256=current["expected_policy_sha256"], expected_packet_sha256=current["packet"]["packet_sha256"],
            review=dict(decision="accept", confirmations={k:True for k in editor.CONFIRMATIONS}, reason="Invented changed text reviewed with original PNG."),
        ))[1]["status"] == "applied"
    editor.complete_revision(case, monkeypatch)
    core[2].initialize_delivery(now=editor.AT)
    with existing.fixture_server(png, case["text"]) as (config, trace, _):
        existing.configure(case["store"], tmp_path, config)
        command, result = existing.park(case)
        assert result["status"] == "applied", result
        yield prepared, png, command, result["delivery"]["intent_id"], trace


def detail(case, intent):
    return case["store"].delivery_content(case["draft_id"], intent)


def edited(case):
    assert editor.action(case, "edit_revision", {"text":"A later edited statement in this invented local test."})[1]["status"] == "applied"
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert "approval_binding" not in draft and "publish_intent_id" not in draft
    return draft


@pytest.mark.parametrize("admitted", ["modis", "pm25"], indirect=True)
def test_actual_delivery_edit_history_and_authenticated_http_are_passive(admitted, core, tmp_path, monkeypatch):
    case = admitted
    with approved(case, core, tmp_path, monkeypatch) as (prepared, png, _, intent, trace):
        for key in tuple(os.environ):
            if key.startswith("PG") or any(word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
                monkeypatch.delenv(key)
        original = delivery.observe

        def lose_ack(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Invented rollback after platform receipt")

        with monkeypatch.context() as patch:
            patch.setattr(delivery, "observe", lose_ack)
            assert existing.run(case, intent, "x", "upload")["outcome"] == "unknown"
        assert len(trace) == 1
        current = edited(case)
        before = editor.all_application_rows(core[3])
        old = detail(case, intent)
        assert old["text"] == case["text"] != current["text"]
        assert old["target"] == editor._identity(current)
        assert old["media"]["alt_text"].endswith("\n")
        assert p._sha(old["media"]["alt_text"].encode()) == old["media"]["alt_text_sha256"]
        assert old["media"]["png_sha256"] == p._sha(png)
        assert editor.view(case, png=old["proposal_sha256"]) == png
        assert old["preparation_packet_sha256"] == prepared["packet"]["packet_sha256"]
        summary = case["store"].delivery_projection(case["draft_id"], editor.candidate.resolve, now=editor.AT)
        assert summary["intents"][0]["stages"]["x"]["upload"]["status"] == "unknown"
        assert summary["intents"][0]["current"] is False
        operators = tmp_path / "operators.json"
        operators.write_text(json.dumps({"operators":[dict(username=role, password="invented-"+role,
            subject="invented-"+role, role=role) for role in ("viewer", "editor", "publisher")]}))
        operators.chmod(0o600)
        origin = "http://127.0.0.1:3133"
        server = preview_ingress.PreviewServer(case["store"], preview_ingress.Operators(operators), port=0, origin=origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = tmp_path / "history-http.json"
        config.write_text(json.dumps(dict(endpoint=f"http://127.0.0.1:{server.server_port}", origin=origin,
            draft_id=case["draft_id"], intent_id=intent, expected=old, operators=str(operators),
            other_draft=next(d["id"] for d in case["store"].read()[1]["drafts"] if d["id"] != case["draft_id"]))))
        try:
            result = subprocess.run([os.environ.get("THEHEAT_NODE24", "node"), "--test", "--test-name-pattern=actual authenticated history", "tests/delivery-history.test.js"],
                cwd=ROOT / "dashboard", env={**clean_environment(), "THEHEAT_DELIVERY_HISTORY_CONFIG":str(config)},
                capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        assert editor.all_application_rows(core[3]) == before and len(trace) == 1
        assert len(case["provider_requests"]) == 3


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_rereviewed_original_png_keeps_delivery_text_through_current_resource_outage(admitted, core, tmp_path, monkeypatch):
    case = admitted
    with approved(case, core, tmp_path, monkeypatch, rereview=True) as (prepared, png, _, intent, trace):
        expected = detail(case, intent)
        assert expected["text"] == case["text"] != prepared["text"]
        assert expected["packet_sha256"] != expected["preparation_packet_sha256"]
        edited(case)
        current = editor.view(case)
        assert editor.action(case, "remove_media_revision", dict(expected_policy_sha256=current["expected_policy_sha256"],
            expected_proposal_sha256=current["removal"]["expected_proposal_sha256"], confirmed=True, reason="Invented removal after edit."))[1]["status"] == "applied"
        before = editor.all_application_rows(core[3])
        del case["store"].editor_media_configuration
        case["config"]["current_inputs"] = []
        from src.commands import preview_media_worker
        from src.media import fire_map_graphic_adapter
        for target, name in ((delivery, "context"), (media, "_read"), (preview_media_worker, "run_native"), (fire_map_graphic_adapter, "resource")):
            monkeypatch.setattr(target, name, lambda *a, **k: pytest.fail("Historical read invoked current mutation work"))
        actual = detail(case, intent)
        assert actual["text"] == expected["text"] and actual["media"] == expected["media"]
        assert editor.view(case, png=actual["proposal_sha256"]) == png
        assert editor.all_application_rows(core[3]) == before and not trace


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_history_refuses_corrupt_joins_and_missing_assets_without_mutating_evidence(admitted, core, tmp_path, monkeypatch):
    case = admitted
    with approved(case, core, tmp_path, monkeypatch) as (_, _, command, intent, trace):
        expected = detail(case, intent)
        before = editor.all_application_rows(core[3])
        driver = p._driver()
        with driver.connect(**dict(core[3], autocommit=False)) as c:
            original_sha = c.execute("SELECT artifact_sha FROM theheat_delivery.intents WHERE intent_id=%s", (intent,)).fetchone()[0]
            original = p._decode(c.execute("SELECT payload FROM theheat_delivery.artifacts WHERE sha=%s", (original_sha,)).fetchone()[0])
        for key in ("text", "event_id", "png_sha256", "alt_sha256", "package", "approval_binding", "missing_text", "invalid_binding"):
            changed = deepcopy(original)
            if key == "missing_text":
                changed.pop("text")
            elif key == "invalid_binding":
                changed["approval_binding"] = None
            elif key == "package":
                changed[key]["package_sha256"] = "f" * 64
            elif key == "approval_binding":
                changed[key]["decision_revision"] += 1
            else:
                changed[key] = "f" * 64
            raw = p._canonical(changed)
            digest = p._sha(raw)
            try:
                with driver.connect(**dict(core[3], autocommit=False)) as c:
                    c.execute("SET LOCAL session_replication_role = replica")
                    c.execute("INSERT INTO theheat_delivery.artifacts VALUES(%s,%s,%s)", (digest, raw, len(raw)))
                    c.execute("UPDATE theheat_delivery.intents SET artifact_sha=%s WHERE intent_id=%s", (digest, intent))
                with pytest.raises((CommandError, p.ProjectionError, ValueError)):
                    detail(case, intent)
            finally:
                with driver.connect(**dict(core[3], autocommit=False)) as c:
                    c.execute("SET LOCAL session_replication_role = replica")
                    c.execute("UPDATE theheat_delivery.intents SET artifact_sha=%s WHERE intent_id=%s", (original_sha, intent))
                    c.execute("DELETE FROM theheat_delivery.artifacts WHERE sha=%s", (digest,))
        # A missing separately verified command result or PNG cannot be replaced by the intent JSON.
        for table, column, identity in (("theheat_commands.results", "command_id", command.command_id),
                                        ("theheat_media.artifacts", "sha", expected["media"]["png_sha256"])):
            with driver.connect(**dict(core[3], autocommit=False)) as c:
                saved = c.execute(f"SELECT * FROM {table} WHERE {column}=%s", (identity,)).fetchone()
            try:
                with driver.connect(**dict(core[3], autocommit=False)) as c:
                    c.execute("SET LOCAL session_replication_role = replica")
                    c.execute(f"DELETE FROM {table} WHERE {column}=%s", (identity,))
                with pytest.raises((CommandError, p.ProjectionError, ValueError)):
                    detail(case, intent)
            finally:
                with driver.connect(**dict(core[3], autocommit=False)) as c:
                    c.execute(f"INSERT INTO {table} VALUES({','.join(['%s'] * len(saved))})", saved)
        assert detail(case, intent) == expected
        assert editor.all_application_rows(core[3]) == before and not trace
