"""Owned invented HTTP listener; records accepted bytes before responding."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from uuid import uuid4

from src.posting.delivery_receipts import ROUTES, digest
from src.posting.local_delivery import SCOPE
from src.commands.schema import canonical_json


def cid(raw):
    return "b" + base64.b32encode(bytes([1, 0x55, 0x12, 0x20]) + hashlib.sha256(raw).digest()).decode().lower().rstrip("=")


@contextmanager
def fixture_server(png, text, *, mode="normal", after_accept=None):
    instance = str(uuid4())
    trace = []
    class Witnesses(dict):
        pass
    accepted = Witnesses()
    retained = tempfile.TemporaryDirectory(prefix="theheat-delivery-http-")
    accepted.journal_path = Path(retained.name) / "accepted.jsonl"
    descriptor = os.open(accepted.journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    actor = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def response(self, status, raw):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            identity = self.path.removeprefix("/__fixture/receipts/")
            trace.append(dict(method="GET", path=self.path))
            # Read the independent append-only server journal, not a caller
            # receipt or the in-memory convenience map used by assertions.
            rows = [json.loads(line) for line in accepted.journal_path.read_bytes().splitlines()]
            assert len(rows) <= 64
            proofs = [row["proof"] for row in rows if row["proof"]["attempt_id"] == identity]
            proof = proofs[0] if len(proofs) == 1 else None
            self.response(200 if proof else 404, json.dumps(proof or {}).encode())

        def do_POST(self):
            assert self.headers.get("Authorization") is None
            assert self.headers.get("Cookie") is None
            assert self.headers["X-TheHeat-Fixture"] == instance
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            identity, request_sha = self.headers["X-TheHeat-Attempt"], self.headers["X-TheHeat-Request"]
            trace.append(dict(method="POST", path=self.path, body=raw, attempt_id=identity,
                              request_sha256=request_sha, content_type=self.headers["Content-Type"]))
            stage = next(key for key, path in ROUTES.items() if path == self.path)
            from src.posting.delivery_receipts import descriptor
            wire = descriptor(*stage, self.headers["Content-Type"], raw)
            assert digest(canonical_json(wire).encode()) == request_sha
            behavior = mode.get(stage, "normal") if isinstance(mode, dict) else mode
            if stage == ("x", "upload"):
                value = dict(media_id=100, media_id_string="100", size=len(png), expires_after_secs=86400,
                             image=dict(image_type="image/png", w=1, h=1))
            elif stage == ("x", "alt"):
                value = None
            elif stage == ("x", "create"):
                value = dict(data=dict(id="200", text=text))
            elif stage == ("bluesky", "upload"):
                value = dict(blob={"$type":"blob", "ref":{"$link":cid(png)}, "mimeType":"image/png", "size":len(png)})
            else:
                value = dict(uri="at://" + actor + "/app.bsky.feed.post/invented", cid=cid(raw))
            result = b"" if value is None else json.dumps(value).encode()
            status = 204 if value is None else 200
            if behavior == "rejected":
                self.response(429, canonical_json(dict(fixture_rejection=dict(instance_id=instance, attempt_id=identity,
                    request_sha256=request_sha, accepted=False))).encode())
                return
            if behavior in {"error-401", "error-429", "error-500"}:
                status, result = int(behavior[-3:]), b'{"error":"invented provider error"}'
            elif behavior == "malformed":
                result = b'{"unfinished":'
            elif behavior == "wrong-id":
                result = b'{"media_id":101,"media_id_string":"100"}'
            accepted[identity] = dict(kind="accepted", instance_id=instance, attempt_id=identity,
                request_sha256=request_sha, status=status, body_base64=base64.b64encode(result).decode())
            with accepted.journal_path.open("ab") as journal:
                journal.write(canonical_json(dict(request=wire, body_base64=base64.b64encode(raw).decode(), proof=accepted[identity])).encode()+b"\n")
                journal.flush()
                os.fsync(journal.fileno())
            if after_accept:
                after_accept()
                self.close_connection = True
                return
            if behavior == "drop":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if behavior == "truncated":
                self.send_response(status)
                self.send_header("Content-Length", str(len(result) + 100))
                self.end_headers()
                self.wfile.write(result)
                self.close_connection = True
                return
            if behavior in {"chunked_truncated", "slow_prefix"}:
                self.send_response(status)
                if behavior == "chunked_truncated":
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write((b"20\r\n" if behavior == "chunked_truncated" else b"") + b"invented-prefix")
                self.wfile.flush()
                if behavior == "slow_prefix":
                    time.sleep(5.5)
                self.close_connection = True
                return
            if behavior == "redirect":
                self.send_response(307)
                self.send_header("Location", "https://example.invalid/do-not-follow")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if behavior == "oversized":
                result = b"x" * (128 * 1024 + 1)
            self.response(status, result)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = dict(schema_version=1, scope=SCOPE, invented=True, instance_id=instance,
                  origin="http://127.0.0.1:" + str(server.server_port), routes_version=1, actor=actor)
    try:
        yield config, trace, accepted
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()
        retained.cleanup()


def value(config, png, text="An invented region recorded extreme heat.", alt="Invented graphic."):
    return dict(fixture=config, configuration_sha256="c" * 64, text=text, png_sha256=digest(png),
                png_byte_count=len(png), alt_sha256=digest(alt.encode()), created_at="2026-06-08T12:00:00Z")
