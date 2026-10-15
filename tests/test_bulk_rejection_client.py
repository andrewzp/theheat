"""Fixed-request client boundaries; no live maintenance operation or providers."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.commands import bulk_rejection_client as client
from src.commands.schema import canonical_json, utc_datetime, utc_text
from tests.test_command_authority import story, target
from tests.test_postgres_preview_command_ingress import operator_file

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bulk(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("PG") or any(token in key for token in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "GIST_ID", "DATABASE_URL")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("THEHEAT_ENVIRONMENT", raising=False)
    return client.BulkRejectionClient("http://127.0.0.1:3034", "http://127.0.0.1:3035",
        operator_file(tmp_path / "operators.json"), "local-editor", tmp_path / "request.json")


def state(drafts):
    return dict(state={"drafts": drafts}, local_preview=True, publication_enabled=False, operator_subject="local-editor")


def script_module():
    spec = importlib.util.spec_from_file_location("bulk_script_fixture", ROOT / "scripts/reject_all_drafts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ["empty", "success", "retry", "exhausted"])
def test_default_legacy_retry_semantics_unchanged(monkeypatch, mode):
    script = script_module()
    reads = Mock(side_effect=lambda: {"drafts": [] if mode == "empty" else [deepcopy(story())]})
    writes = Mock(side_effect=[False] * 4 + [mode != "exhausted"] if mode in {"retry", "exhausted"} else [True])
    monkeypatch.setattr(script, "read_state", reads)
    monkeypatch.setattr(script, "write_state", writes)
    if mode == "exhausted":
        with pytest.raises(SystemExit) as error:
            script.main([])
        assert error.value.code == 1
    else:
        assert script.main([]) == 0
    assert reads.call_count == (5 if mode in {"retry", "exhausted"} else 1)
    assert writes.call_count == (0 if mode == "empty" else 5 if mode in {"retry", "exhausted"} else 1)


def test_incomplete_mode_never_calls_legacy(monkeypatch):
    script = script_module()
    reads = Mock(side_effect=AssertionError("legacy called"))
    monkeypatch.setattr(script, "read_state", reads)
    with pytest.raises(SystemExit) as error:
        script.main(["--subject", "local-editor"])
    assert error.value.code == 2 and reads.call_count == 0


@pytest.mark.parametrize("mode", ["empty", "many", "duplicate", "unknown", "bad_revision", "large"])
def test_selection_bounds_and_noop(bulk, monkeypatch, mode):
    drafts = [story()]
    if mode == "empty":
        drafts = []
    elif mode in {"many", "large"}:
        drafts = [story(str(i) if mode == "many" else str(i) + "x" * 190) for i in range(501 if mode == "many" else 500)]
    elif mode == "duplicate":
        drafts *= 2
    elif mode == "unknown":
        drafts[0].pop("decision_revision")
    elif mode == "bad_revision":
        drafts[0]["content_revision"] = True
    transport = Mock(return_value=(200, state(drafts)))
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    outcome = bulk.run()
    assert outcome["status"] == ("noop" if mode == "empty" else "refused")
    assert transport.call_count == 1 and not bulk.request_file.exists()


@pytest.mark.parametrize("endpoint", ["https://127.0.0.1:3034", "http://localhost:3034", "http://127.0.0.1:3034/", "http://user@127.0.0.1:3034", "http://127.0.0.1:3034?x=y", "http://127.0.0.1:0"])
def test_nonliteral_endpoints_refuse_before_io(bulk, monkeypatch, endpoint):
    transport = Mock(side_effect=AssertionError("HTTP called"))
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    assert replace(bulk, endpoint=endpoint).run()["status"] == "refused"
    transport.assert_not_called()


def test_racing_creators_keep_winner_and_sync_before_post(bulk, monkeypatch):
    first = bulk.select(state([story("first")]))
    loser = bulk.select(state([story("loser")]))
    real_link = os.link
    def competing_link(source, destination):
        # Another creator wins after this invocation's selection.
        Path(destination).write_bytes(canonical_json(first).encode())
        Path(destination).chmod(0o600)
        real_link(source, destination)
    monkeypatch.setattr(client.os, "link", competing_link)
    assert bulk.retain(loser) == first
    assert bulk.load() == first
    assert list(bulk.request_file.parent.glob(".bulk-request-*")) == []
    assert b"Example City" not in bulk.request_file.read_bytes()


def test_sync_failure_never_posts_and_does_not_reselect(bulk, monkeypatch):
    envelope = bulk.select(state([story()]))
    bulk.retain(envelope)
    original = bulk.request_file.read_bytes()
    transport = Mock(side_effect=AssertionError("HTTP called"))
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    monkeypatch.setattr(client.os, "fsync", Mock(side_effect=OSError("invented disk failure")))
    assert bulk.run()["status"] == "refused"
    transport.assert_not_called()
    assert bulk.request_file.read_bytes() == original


@pytest.mark.parametrize("change", ["subject", "endpoint", "origin", "mode", "symlink", "hash", "truncated", "oversize"])
def test_recovery_binding_and_private_file_fail_closed(bulk, monkeypatch, change):
    envelope = bulk.select(state([story()]))
    bulk.retain(envelope)
    if change in {"subject", "endpoint", "origin"}:
        bulk = replace(bulk, **{change: "local-publisher" if change == "subject" else "http://127.0.0.1:3036"})
    elif change == "mode":
        bulk.request_file.chmod(0o644)
    elif change == "symlink":
        saved = bulk.request_file.with_suffix(".saved")
        bulk.request_file.rename(saved)
        bulk.request_file.symlink_to(saved)
    elif change == "hash":
        envelope["request"]["targets"][0]["decision_revision"] += 1
        bulk.request_file.write_bytes(canonical_json(envelope).encode())
    elif change == "truncated":
        bulk.request_file.write_bytes(b'{"request":')
    else:
        bulk.request_file.write_bytes(b"x" * (client.MAX_ENVELOPE_BYTES + 1))
    transport = Mock(side_effect=AssertionError("HTTP called"))
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    assert bulk.run()["status"] == "refused"
    transport.assert_not_called()


def test_retry_only_resends_exact_expired_request_never_new_state(bulk, monkeypatch):
    envelope = bulk.select(state([story()]))
    request = envelope["request"]
    requested = utc_datetime(request["requested_at"]) - timedelta(minutes=10)
    request.update(requested_at=utc_text(requested), expires_at=utc_text(requested + timedelta(minutes=5)))
    envelope["request_sha256"] = hashlib.sha256(canonical_json(request).encode()).hexdigest()
    bulk.retain(envelope)
    before = bulk.request_file.read_bytes()
    transport = Mock(side_effect=[(404, {"code": "command_not_found"}), (409, {"code": "command_expired"})])
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    outcome = bulk.run()
    assert outcome["status"] == "unknown" and outcome["code"] == "command_expired"
    assert transport.call_args_list[0].args == ("/commands/" + request["command_id"],)
    assert transport.call_args_list[1].args == ("/commands", canonical_json(request).encode())
    assert bulk.request_file.read_bytes() == before


def test_unknown_response_never_prints_body_or_credentials(bulk, monkeypatch):
    envelope = bulk.select(state([story()]))
    bulk.retain(envelope)
    transport = Mock(return_value=(200, {"secret": "invented-editor", "text": "not for output"}))
    monkeypatch.setattr(client.BulkRejectionClient, "http", transport)
    outcome = bulk.run()
    assert outcome["status"] == "unknown" and "invented-editor" not in json.dumps(outcome)
    assert "not for output" not in json.dumps(outcome) and transport.call_count == 1


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_absolute_transport_deadline_survives_trickled_response(bulk, monkeypatch, phase):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import time

    stop = threading.Event()
    class Trickle(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if phase == "body":
                    self.send_response(200)
                    self.send_header("Content-Length", "10000")
                    self.end_headers()
                else:
                    self.wfile.write(b"HTTP/1.0 200 OK\r\nX-Invented: ")
                    self.wfile.flush()
                while not stop.wait(0.04):
                    self.wfile.write(b"x")
                    self.wfile.flush()
            except OSError:
                pass

    server = HTTPServer(("127.0.0.1", 0), Trickle)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bulk = replace(bulk, endpoint=f"http://127.0.0.1:{server.server_port}")
    envelope = bulk.select(state([story()]))
    bulk.retain(envelope)
    before = bulk.request_file.read_bytes()
    monkeypatch.setattr(client, "HTTP_DEADLINE_SECONDS", 0.3)
    started = time.monotonic()
    try:
        outcome = bulk.run()
        assert outcome["status"] == "unknown" and outcome["command_id"] == envelope["request"]["command_id"]
        assert 0.25 <= time.monotonic() - started < 1.0
        assert bulk.request_file.read_bytes() == before
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_recovery_never_selects_new_pending_draft(bulk, monkeypatch):
    from src.commands.preview_ingress import AUTH_CONTEXT
    from src.commands.schema import Command, Principal

    first = story("selected")
    envelope = bulk.select(state([first]))
    bulk.retain(envelope)
    # New pending content exists now; only a forbidden fresh /state read could
    # add it. The response for that route is a trap, not an authority mutation.
    later = state([first, story("arrived-later")])
    requests = []
    command = Command.from_request(envelope["request"], Principal(bulk.subject, "editor", AUTH_CONTEXT),
        environment="local", now=utc_datetime(envelope["request"]["requested_at"]))
    def http(path, raw=None):
        requests.append((path, raw))
        assert path != "/state", later
        if raw is None:
            return 404, {"code": "command_not_found"}
        return 202, {"status": "pending", "local_preview": True,
                     "receipt": {"command_id": command.command_id, "digest": command.digest}}
    monkeypatch.setattr(client.BulkRejectionClient, "http", lambda self, path, raw=None: http(path, raw))
    result = bulk.run()
    assert result["status"] == "pending" and "rejected_count" not in result
    assert json.loads(requests[1][1])["targets"] == [target(first)]
    assert bulk.load() == envelope
