"""Real dashboard handler -> authenticated loopback HTTP -> retained PG receipts."""
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import subprocess
import threading

from src.commands import preview_ingress
from src.commands.preview_ingress import Operators, PreviewServer
from tests import test_postgres_editor_media as editor
from tests import test_postgres_candidate_admission as candidate
from tests.test_postgres_preview_command_ingress import clean_environment


def verify(case, tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return editor.AT

    monkeypatch.setattr(preview_ingress, "datetime", Clock)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
    operators = tmp_path / "delivery-operators.json"
    operators.write_text(json.dumps({"operators":[dict(username=role, password="invented-"+role,
        subject="invented-"+role, role=role) for role in ("editor", "publisher", "viewer")]}))
    operators.chmod(0o600)
    server = PreviewServer(case["store"], Operators(operators), port=0, origin=origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    config = tmp_path / "delivery-readback.json"
    config.write_text(json.dumps(dict(origin=origin, endpoint=f"http://127.0.0.1:{server.server_port}",
        draft_id=case["draft_id"], expected=case["store"].delivery_projection(case["draft_id"], candidate.resolve, now=editor.AT))))
    config.chmod(0o600)
    thread.start()
    try:
        result = subprocess.run([os.environ.get("THEHEAT_NODE24", "node"), "--test", "--test-reporter=tap", "tests/delivery-http.test.js"],
            cwd=Path(__file__).resolve().parents[1] / "dashboard", env={**clean_environment(), "THEHEAT_DELIVERY_HTTP_CONFIG":str(config)},
            capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "# pass 1" in result.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
