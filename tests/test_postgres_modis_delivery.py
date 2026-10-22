"""Invented saved MODIS -> authenticated native review -> exact SDK -> owned restore."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from uuid import uuid4

import pytest

from src.commands import postgres_delivery as delivery, preview_ingress
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.media import platform_description as descriptions
from src.storage import postgres_projection as p
from tests import test_postgres_editor_media as editor, test_postgres_delivery as existing
from tests.test_postgres_preview_editor_media import CHILD
from tests.test_postgres_preview_command_ingress import clean_environment
from tests.test_postgres_editor_media import admitted as admitted, offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority, options
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies

ROOT = Path(__file__).resolve().parents[1]


def clean(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("PG") or any(word in name for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            monkeypatch.delenv(name)


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_actual_modis_authenticated_native_sdk_unknown_receipt_and_owned_restore(admitted, core, cluster, tmp_path, monkeypatch):
    case, store = admitted, admitted["store"]
    # Native bytes are produced by the authenticated HTTP command journey below,
    # not a seeded final attachment. The fixture listener does not need them to
    # retain exact accepted X request bytes.
    core[2].initialize_delivery(now=editor.AT)
    with existing.fixture_server(b"unused-x-only-fixture-image", case["text"], mode={("x", "create"):"drop"}) as (config, trace, accepted):
        config_path = existing.configure(store, tmp_path, config)
        clean(monkeypatch)
        monkeypatch.delenv("NODE_ENV", raising=False)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return editor.AT
        monkeypatch.setattr(preview_ingress, "datetime", Clock)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
        operators = tmp_path / "operators.json"
        operators.write_text(json.dumps({"operators":[dict(username=role, password="invented-"+role,
            subject="invented-"+role, role=role) for role in ("editor", "publisher", "viewer")]}))
        operators.chmod(0o600)
        server = preview_ingress.PreviewServer(store, preview_ingress.Operators(operators), port=0, origin=origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        child = tmp_path / "modis-worker.py"
        child.write_text(CHILD.replace('authority.configure_editor_media(**config["native"])',
            'authority.configure_editor_media(**config["native"])\nauthority.configure_delivery(config["delivery"])'))
        from src.two_bot import writer
        settings = dict(endpoint=f"http://127.0.0.1:{server.server_port}", origin=origin, root=str(ROOT),
            python=sys.executable, child=str(child), authority=options(core[3]), operators=str(operators),
            generation=case["config"], native=store.editor_media_configuration, delivery=str(config_path),
            requests=str(tmp_path / "requests.txt"), policy_sha256=fingerprint(current_editorial_policy()),
            draft_id=case["draft_id"], at=utc_text(editor.AT), writer_provider=writer.WRITER_PROVIDER,
            writer_model=writer.WRITER_MODEL, expect_modis_projection=True, retain_parked=True,
            prepared_fixture=str(tmp_path / "actual-modis-prepared.json"))
        path = tmp_path / "modis-http.json"
        path.write_text(json.dumps(settings))
        path.chmod(0o600)
        try:
            http = subprocess.run([os.environ.get("THEHEAT_NODE24", "node"), "--test", "tests/editor-media-http.test.js"],
                cwd=ROOT / "dashboard", env={**clean_environment(), "THEHEAT_MEDIA_HTTP_CONFIG":str(path)},
                capture_output=True, text=True, timeout=180)
            assert http.returncode == 0, http.stdout + http.stderr
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
        assert not thread.is_alive()
        assert Path(settings["requests"]).read_text().splitlines() == ["safety", "fact_check", "critic"]
        current = editor.view(case)
        assert current["parked"] and current["review_current"]
        record = current["platform_description"]["record"]
        assert record["schema_version"] == 2 and record["derivation"] == descriptions.MODIS_DERIVATION
        png = editor.view(case, png=current["preparation"]["proposal_sha256"])
        projection = store.delivery_projection(case["draft_id"], editor.candidate.resolve, now=editor.AT)
        assert len(projection["intents"]) == 1 and set(projection["intents"][0]["stages"]) == {"x", "bluesky"}
        intent = projection["intents"][0]["intent_id"]
        with store.projections._connection() as c:
            retained = delivery.read(c, intent)
            assert retained["platform_description"] == record
            full = delivery.media.read(c, retained["proposal_sha256"], store.environment)["assets"]["alt.txt"]
        fixture = json.loads(Path(settings["prepared_fixture"]).read_text())
        assert fixture["prepared"]["platform_description"]["record"] == record
        assert len(full) > 1000 and full.endswith(b"\n")
        wire = record["wire_text"].encode()
        assert len(wire) <= 1000 and hashlib.sha256(wire).hexdigest() == record["wire"]["sha256"]
        assert retained["alt_sha256"] == hashlib.sha256(full).hexdigest() != record["wire"]["sha256"]
        state = store.read()
        for stage in ("upload", "alt"):
            assert existing.run(case, intent, "x", stage)["outcome"] == "confirmed"
        alt_body = json.loads(trace[1]["body"])
        assert alt_body["alt_text"]["text"].encode() == wire
        with store.projections._connection() as c:
            saved = delivery.attempt(c, retained, "x", "alt")
            request = delivery.document(c, saved["request_sha256"])
            assert delivery.raw(c, request["body_sha256"]) == trace[1]["body"]
            receipt = delivery.outcome(c, saved)
            assert receipt["result"] == dict(schema_version=2, media_id="100", raw_alt_sha256=retained["alt_sha256"],
                wire_alt_sha256=record["wire"]["sha256"], platform_description_sha256=record["description_sha256"])
        assert existing.run(case, intent, "x", "create")["outcome"] == "unknown"
        assert len(trace) == len(accepted) == 3
        assert existing.run(case, intent, "x", "create")["outcome"] == "unknown" and len(trace) == 3
        before_rows = editor.all_application_rows(core[3])
        params, binaries, folder = cluster
        archive = folder / ("modis-" + uuid4().hex + ".dump")
        common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
        binaries("pg_dump", *common, "-Fc", "-f", str(archive), core[3]["dbname"])
        import psycopg
        name = "restore_" + uuid4().hex
        admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
        restored_params = dict(core[3], dbname=name)
        try:
            binaries("pg_restore", *common, "--single-transaction", "-d", name, str(archive))
            authority = PostgresCommandAuthority(**options(restored_params))
            authority.configure_sourced_generation(lambda:case["config"])
            authority.configure_editor_media(**store.editor_media_configuration)
            authority.configure_delivery(config_path)
            restored = dict(case, store=authority)
            assert authority.read() == state and editor.all_application_rows(restored_params) == before_rows
            assert editor.view(restored)["platform_description"]["record"] == record
            assert existing.run(restored, intent, "x", "create")["outcome"] == "unknown" and len(trace) == 3
            assert existing.run(restored, intent, "x", "create", reconcile=True)["outcome"] == "confirmed"
            assert len(trace) == 4 and trace[-1]["method"] == "GET"
            # No obligation is silently removed after confirming X; Bluesky stays
            # unresolved in the fixed set, and duplicate X creation is barred.
            summary = authority.delivery_projection(case["draft_id"], editor.candidate.resolve, now=editor.AT)
            assert summary["intents"][0]["stages"]["bluesky"]["create"]["status"] == "pending"
            assert existing.run(restored, intent, "x", "create")["outcome"] == "confirmed" and len(trace) == 4
            history = authority.delivery_content(case["draft_id"], intent)
            assert history["schema_version"] == 2
            assert history["platform_description"]["description_sha256"] == record["description_sha256"]
            assert history["platform_description"]["wire_text"].encode() == wire
            assert history["media"]["alt_text"].encode() == full
            assert editor.view(restored, png=history["proposal_sha256"]) == png
            original_read = delivery.read
            historical_rows = editor.all_application_rows(restored_params)
            for corrupted in ("wire_text", "raw_alt_sha256", "description_sha256"):
                with monkeypatch.context() as patch:
                    def changed_read(c, identity):
                        value = deepcopy(original_read(c, identity))
                        value["platform_description"][corrupted] = "changed" if corrupted == "wire_text" else "f" * 64
                        return value
                    patch.setattr(delivery, "read", changed_read)
                    with pytest.raises(delivery.CommandError):
                        authority.delivery_content(case["draft_id"], intent)
                assert editor.all_application_rows(restored_params) == historical_rows
            assert editor.action(restored, "edit_revision", {"text":"An edited invented thermal statement."})[1]["status"] == "applied"
            assert not editor.view(restored)["review_current"] and not editor.view(restored)["parked"]
            assert authority.delivery_content(case["draft_id"], intent)["media"]["alt_text"].encode() == full
            assert existing.run(restored, intent, "x", "create")["outcome"] == "confirmed" and len(trace) == 4
            rereview = editor.view(restored)
            next_description = rereview["platform_description"]["record"]
            assert next_description["description_sha256"] != record["description_sha256"]
            from src.media.joint_review import CONFIRMATIONS
            _, reviewed = editor.action(restored, "review_media_revision", dict(
                proposal_sha256=rereview["preparation"]["proposal_sha256"],
                expected_policy_sha256=rereview["expected_policy_sha256"], expected_packet_sha256=rereview["packet"]["packet_sha256"],
                review=dict(decision="accept", confirmations={key:True for key in CONFIRMATIONS | {descriptions.CONFIRMATION}},
                    expected_platform_description_sha256=next_description["description_sha256"],
                    reason="Genuine new review of the edited invented statement and complete source projection.")))
            assert reviewed["status"] == "applied", reviewed
            rereviewed = editor.view(restored)
            assert rereviewed["review_current"] and not rereviewed["parked"]
            assert rereviewed["platform_description"]["record"] == next_description
            assert rereviewed["checks_status"] != "passed"
            assert authority.delivery_content(case["draft_id"], intent)["platform_description"]["description_sha256"] == record["description_sha256"]
            # Original retained history remains readable without current source
            # or native availability, under its own original raw-alt semantics.
            del authority.editor_media_configuration
            restored["config"]["current_inputs"] = []
            assert authority.delivery_content(case["draft_id"], intent)["media"]["alt_text"].encode() == full
            assert editor.view(restored, png=history["proposal_sha256"]) == png
            (tmp_path / "modis-acceptance.json").write_text(json.dumps(dict(
                description=record, png_sha256=p._sha(png), png_byte_count=len(png),
                raw_alt_sha256=p._sha(full), raw_alt_byte_count=len(full), wire_byte_count=len(wire),
                request_body_sha256=hashlib.sha256(trace[1]["body"]).hexdigest(),
                platform_requests=[dict(method=row["method"], path=row["path"]) for row in trace],
                description_equal_at_prepare_attach_checks_park_restore=True,
                genuine_rereview_description_sha256=next_description["description_sha256"],
                historical_description_sha256=record["description_sha256"],
                historical_wire_sha256=history["platform_description"]["wire_sha256"],
                native_profile=store.editor_media_configuration,
                scientific_or_live_platform_qualification=False), indent=2))
        finally:
            admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
