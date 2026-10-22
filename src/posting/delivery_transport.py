"""Credentialless real SDK serialization through one fixed local HTTP listener.

The owned session freezes exact SDK-prepared bytes before the barrier callback.
A short-lived credentialless child owns the socket, with an absolute lifetime
including cleanup. The response callback retains raw bytes before SDK parsing.
No live client factory can select this adapter or override a production URL.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import version
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
import requests

from src.posting import delivery_receipts as receipts
from src.posting.local_delivery import configuration, clean_environment, require, MAX_REQUEST, MAX_RESPONSE, PHASE_SECONDS, strict_json

_quiet = ContextVar("local_delivery_wire_logs", default=False)


class _WireFilter(logging.Filter):
    def filter(self, record):
        return not _quiet.get()


@contextmanager
def no_wire_logging():
    # Filter only this synchronous local operation; other threads and the
    # legacy sender keep their own logging behavior and levels.
    targets = [logging.getLogger(name) for name in ("tweepy.api", "tweepy.client", "httpx")]
    guard = _WireFilter()
    token = _quiet.set(True)
    for logger in targets:
        logger.addFilter(guard)
    try:
        yield
    finally:
        for logger in targets:
            logger.removeFilter(guard)
        _quiet.reset(token)


def bounded_http(config, *, method, path, body, content_type, attempt_id, request_sha256, deadline):
    configuration(config)
    require(type(body) is bytes and len(body) <= MAX_REQUEST, "delivery_request_bound")
    require(type(deadline) is float and math.isfinite(deadline), "delivery_deadline_required")
    failure = dict(raw=b"", http_status=None, complete=False, reason="time_exceeded")
    if time.monotonic() >= deadline:
        return failure
    request = dict(config=config, method=method, path=path, body_base64=base64.b64encode(body).decode(),
                   content_type=content_type, attempt_id=attempt_id, request_sha256=request_sha256, deadline=deadline)
    encoded = json.dumps(request, separators=(",", ":")).encode()
    require(len(encoded) <= 13 * 1024 * 1024, "delivery_child_input_bound")
    child = subprocess.Popen([sys.executable, "-m", __name__, "--http-child"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        cwd=Path(__file__).resolve().parents[2], env={"PATH":"/usr/bin:/bin", "LANG":"en_US.UTF-8", "PYTHONDONTWRITEBYTECODE":"1"})
    failure = dict(raw=b"", http_status=None, complete=False, reason="transport_unavailable")
    try:
        stdout, stderr = child.communicate(input=encoded, timeout=max(0.01, deadline-time.monotonic()-2))
        require(child.returncode == 0 and not stderr and len(stdout) <= 180000, "delivery_child_failed")
        result = strict_json(stdout)
        require(set(result) == {"raw_base64", "http_status", "complete", "reason"}, "delivery_child_shape")
        raw = base64.b64decode(result.pop("raw_base64"), validate=True)
        # A parent resumed after expiry may still retain the completed original
        # response. That passive evidence never grants a subsequent mutation.
        require(len(raw) <= MAX_RESPONSE, "delivery_child_response_bound")
        return dict(result, raw=raw)
    except subprocess.TimeoutExpired:
        failure["reason"] = "time_exceeded"
    except (ValueError, OSError, KeyError):
        pass
    finally:
        if child.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    child.communicate(timeout=max(0.01, min(0.5, deadline-time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if child.poll() is None:
                failure["reason"] = "cleanup_failed"
    return failure


class _Boundary:
    def __init__(self, value, platform, stage, prepared, begin, observe, check):
        self.value, self.platform, self.stage = value, platform, stage
        self.prepared, self.begin, self.observe = prepared, begin, observe
        self.check = check
        require(type(prepared["eligibility_deadline"]) is float and math.isfinite(prepared["eligibility_deadline"]), "delivery_deadline_required")
        self.deadline = min(prepared["eligibility_deadline"], time.monotonic()+PHASE_SECONDS)
        self.used = False
        self.binding = None

    def exchange(self, method, url, headers, body):
        require(not self.used, "delivery_second_request_refused")
        self.used = True
        expected = receipts.HOSTS.get((self.platform, self.stage), self.value["fixture"]["origin"]) + receipts.ROUTES[self.platform, self.stage]
        require(method == "POST" and url == expected, "delivery_sdk_destination_changed")
        allowed = {"host", "user-agent", "accept", "accept-encoding", "connection", "content-type", "content-length", "authorization"}
        require(all(name.lower() in allowed for name in headers), "delivery_sdk_headers_refused")
        host = headers.get("Host") or headers.get("host")
        require(host is None or host == urlsplit(expected).netloc, "delivery_sdk_destination_changed")
        auth = headers.get("Authorization") or headers.get("authorization")
        require(auth is None or (self.platform == "x" and self.stage == "create" and auth == "Bearer None"),
                "delivery_sdk_credentials_refused")
        if type(body) is str:
            body = body.encode("utf-8")
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        request = receipts.descriptor(self.platform, self.stage, content_type, body)
        receipts.verify_request(self.value, self.platform, self.stage, self.prepared, request, body)
        grant = self.begin(request, body)
        require(grant.get("dispatch_granted") is True, "delivery_dispatch_not_granted")
        self.binding = grant["binding"]
        try:
            self.check(self.binding)
            require(time.monotonic() < self.deadline, "delivery_window_expired")
        except Exception:
            self.observe(self.binding, dict(raw=b"", http_status=None, complete=False, reason="currentness_refused"), "no_call")
            raise ValueError("delivery_final_currentness_refused") from None
        result = bounded_http(self.value["fixture"], method="POST", path=request["path"], body=body,
            content_type=content_type, attempt_id=self.binding["attempt_id"], request_sha256=self.binding["request_sha256"], deadline=self.deadline)
        self.observe(self.binding, result)
        require(result["complete"], "delivery_response_incomplete")
        return result


class _RequestsSession(requests.Session):
    def __init__(self, boundary):
        super().__init__()
        self.trust_env = False
        self.boundary = boundary

    def send(self, request, **kwargs):
        require(not self.cookies and self.auth is None and not kwargs.get("proxies"), "delivery_sdk_credentials_refused")
        result = self.boundary.exchange(request.method, request.url, request.headers, request.body)
        response = requests.Response()
        response.status_code = result["http_status"]
        response._content = result["raw"]
        setattr(response, "_content_consumed", True)
        response.headers["Content-Type"] = "application/json"
        response.url, response.request = request.url, request
        return response


class _HttpxClient(httpx.Client):
    def __init__(self, boundary):
        super().__init__(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(5, connect=2))
        self.boundary = boundary

    def send(self, request, **kwargs):
        require(not self.cookies, "delivery_sdk_credentials_refused")
        result = self.boundary.exchange(request.method, str(request.url), request.headers, request.read())
        return httpx.Response(result["http_status"], content=result["raw"], headers={"content-type":"application/json"}, request=request)


def execute(value, platform, stage, prepared, *, begin, observe, check):
    """One real SDK stage. Never use the legacy wrappers/credential factories."""
    clean_environment()
    from src.media.platform_description import preflight, profiles
    require(value.get("schema_version") == 2, "platform_description_required")
    wire = preflight(value["platform_description"], raw_alt=prepared.get("raw_alt", prepared["alt"].encode("utf-8", errors="strict")),
        png=prepared["png"], expected_profiles=profiles(value["fixture"]), graphic_spec=prepared.get("graphic_spec"))
    require(wire == prepared["alt"], "delivery_request_content_changed")
    require(version("tweepy") == "4.17.0" and version("atproto") == "0.0.72", "delivery_sdk_profile_changed")
    boundary = _Boundary(value, platform, stage, prepared, begin, observe, check)
    session: _RequestsSession | _HttpxClient | None = None
    try:
        with no_wire_logging():
            if platform == "x":
                import tweepy
                from src.posting import twitter
                session = _RequestsSession(boundary)
                if stage in ("upload", "alt"):
                    api = tweepy.API(auth=None, retry_count=0, wait_on_rate_limit=False, timeout=5)
                    api.session.close()
                    api.session = session
                    if stage == "upload":
                        twitter.upload_png(api, prepared["png"], require_auth=False, chunked=False)
                    else:
                        twitter.set_alt_text(api, prepared["prior"]["upload"]["media_id"], prepared["alt"], require_auth=False)
                else:
                    client = tweepy.Client(wait_on_rate_limit=False)
                    client.session.close()
                    client.session = session
                    twitter.create_post(client, value["text"], [prepared["prior"]["upload"]["media_id"]], user_auth=False)
            else:
                from atproto import Client
                from atproto_client.models.blob_ref import BlobRef
                from atproto_client.request import Request
                from src.posting import bluesky
                request = Request()
                request._client.close()
                session = _HttpxClient(boundary)
                request._client = session
                client = Client(base_url=value["fixture"]["origin"], request=request)
                if stage == "upload":
                    bluesky.upload_png(client, prepared["png"])
                else:
                    blob = BlobRef.model_validate(prepared["prior"]["upload"]["blob"])
                    record = bluesky.image_record(value["text"], prepared["alt"], blob, value["created_at"])
                    bluesky.create_post(client, value["text"], record=record, actor=value["fixture"]["actor"])
        return dict(sdk_completed=True, binding=boundary.binding)
    except Exception as exc:
        # Raw evidence, if any, is already retained. No SDK error text leaves this
        # adapter; a missing response/commit acknowledgement remains unresolved.
        code = str(exc) if type(exc) is ValueError else ""
        safe = code if code in {"delivery_final_currentness_refused", "delivery_sdk_destination_changed",
            "delivery_sdk_headers_refused", "delivery_sdk_credentials_refused", "delivery_request_content_changed",
            "delivery_upload_bytes_changed", "delivery_response_incomplete", "delivery_dispatch_not_granted",
            "delivery_second_request_refused"} else "delivery_sdk_unavailable"
        return dict(sdk_completed=False, binding=boundary.binding, reason=safe)
    finally:
        if session is not None:
            session.close()


def http_child():
    """Fixed no-auth HTTP engine, one request; launched only by bounded_http."""
    import http.client
    import socket
    raw = sys.stdin.buffer.read(13 * 1024 * 1024 + 1)
    require(len(raw) <= 13 * 1024 * 1024, "delivery_child_input_bound")
    value = strict_json(raw)
    require(set(value) == {"config", "method", "path", "body_base64", "content_type", "attempt_id", "request_sha256", "deadline"}, "delivery_child_shape")
    deadline = value["deadline"]
    require(type(deadline) is float and math.isfinite(deadline) and 0 < deadline-time.monotonic() <= PHASE_SECONDS,
            "delivery_child_deadline")
    config = configuration(value["config"])
    require(all(type(value[key]) is str and re.fullmatch(r"[0-9a-f]{64}", value[key]) for key in ("attempt_id", "request_sha256")),
            "delivery_child_identity")
    body = base64.b64decode(value["body_base64"], validate=True)
    require(len(body) <= MAX_REQUEST, "delivery_child_input_bound")
    path, method = value["path"], value["method"]
    require((method == "POST" and path in receipts.ROUTES.values() and 0 < len(body) <= MAX_REQUEST)
            or (method == "GET" and path == "/__fixture/receipts/" + value["attempt_id"] and body == b""),
            "delivery_child_route")
    require(type(value["content_type"]) is str and len(value["content_type"]) <= 256
            and "\n" not in value["content_type"] and "\r" not in value["content_type"], "delivery_child_header")
    port = urlsplit(config["origin"]).port
    original_connect = socket.socket.connect

    def connect(sock, address):
        require(time.monotonic() < deadline, "delivery_window_expired")
        require(sock.family == socket.AF_INET and address == ("127.0.0.1", port), "delivery_socket_destination_refused")
        return original_connect(sock, address)

    setattr(socket.socket, "connect", connect)
    setattr(http.client, "_MAXLINE", 2048)
    setattr(http.client, "_MAXHEADERS", 16)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    result: dict = dict(raw_base64="", http_status=None, complete=False, reason="transport_unavailable")
    received = bytearray()
    try:
        headers = {"Content-Type":value["content_type"], "Accept-Encoding":"identity",
                   "X-TheHeat-Fixture":config["instance_id"], "X-TheHeat-Attempt":value["attempt_id"],
                   "X-TheHeat-Request":value["request_sha256"]}
        connection.connect()
        transport_socket = connection.sock
        transport_socket.settimeout(5)
        require(time.monotonic() < deadline, "delivery_window_expired")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result["http_status"] = response.status
        require(sum(len(k)+len(v)+4 for k,v in response.getheaders()) <= 16384, "delivery_response_header_bound")
        require(response.getheader("Content-Encoding", "identity").lower() == "identity", "delivery_response_encoding")
        # read1 returns every available prefix before another blocking read.
        # read(n) can bury partial bytes inside an IncompleteRead exception,
        # or discard the prefix altogether when a later socket read times out.
        while len(received) <= MAX_RESPONSE:
            if response.isclosed() or (not response.chunked and response.length == 0):
                break
            remaining = deadline-time.monotonic()-2.5
            require(remaining > 0, "delivery_window_expired")
            transport_socket.settimeout(min(5, remaining))
            chunk = response.read1(min(16384, MAX_RESPONSE+1-len(received)))
            if not chunk:
                break
            received.extend(chunk)
        if len(received) > MAX_RESPONSE:
            result["reason"] = "size_exceeded"
        else:
            require(response.length in (None, 0), "delivery_truncated_response")
            result.update(complete=True, reason="received")
    except Exception:
        pass
    finally:
        result["raw_base64"] = base64.b64encode(received[:MAX_RESPONSE]).decode()
        connection.close()
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    try:
        require(sys.argv[1:] == ["--http-child"], "explicit_delivery_child_required")
        http_child()
    except Exception:
        raise SystemExit(1) from None
