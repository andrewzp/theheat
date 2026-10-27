"""Command-check request/response evidence through the installed google-genai SDK.

The check transport's own bounded reader is exercised with INVENTED offline
MockTransport responses; grants use the real local SQLite authority. These
fixtures prove mechanical capture and unchanged check behavior, never a
factual, safety or critic verdict, provider truth or billing.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from src.commands import check_execution_journal as observations
from src.two_bot import check_executor as executor, check_transport, request_archive as archive
from src.two_bot import request_archive_replay as replay
from tests.test_check_executor import case, envelope, inputs, run, saved, store

__all__ = ["case", "inputs", "store"]
MODEL = "gemini-test"
KEY = "canary-check-key-T5W1-never-archive"
SECRET = "canary-check-error-P8N2-never-archive"


def private_root(base: Path, name: str = "private-archive") -> Path:
    root = base / name
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    return root


def records(scope, kind) -> list[dict]:
    raw = archive.read_private_file(scope.directory / archive.MANIFEST, 1 << 22)
    return [row["data"] for line in raw.split(b"\n") if line for row in [archive.strict_json_loads(line)]
            if row["type"] == kind]


def all_bytes(scope) -> bytes:
    data = archive.read_private_file(scope.directory / archive.MANIFEST, 1 << 22)
    for name in os.listdir(scope.directory / archive.ARTIFACTS):
        data += archive.read_private_file(scope.directory / archive.ARTIFACTS / name, 1 << 22)
    return data


class Provider:
    def __init__(self, reply):
        self.reply = reply
        self.sent: list = []

    def __call__(self, request):
        assert request.url.host == "generativelanguage.googleapis.com", "external network trapped"
        self.sent.append(request)
        return self.reply(request)


def stream(raw, *, status=200, headers=None):
    return lambda request: httpx.Response(status, request=request, headers=headers or {},
                                          stream=httpx.ByteStream(raw))


REPLIES = {
    "complete200": stream(envelope("NO")),
    "provider_error": stream(json.dumps({"error": {"message": SECRET}}).encode(), status=500),
    "malformed_model_result": stream(envelope("not a verdict")),
    "sdk_parse_failure": stream(b"not json at all"),
    "empty": stream(b""),
    "oversize": stream(b"x" * (observations.MAX_RESPONSE_BYTES + 1)),
    "encoded": stream(b"compressed", headers={"content-encoding": "gzip"}),
}


def execute(reply, *, scope=None, model=MODEL, expected_model=MODEL):
    provider = Provider(reply)
    transport = check_transport.GoogleCheckTransport(api_key=KEY, model=model,
                                                     http_transport=httpx.MockTransport(provider))
    route = None
    try:
        if scope is not None:
            route = scope.begin_route("command_check", client=transport._http,
                                      expected_path=f"/v1beta/models/{expected_model}:generateContent",
                                      binding={}, logical={"model": expected_model, "contents": "invented"})
        observed = transport.execute(dict(model=model, contents="invented"))
    finally:
        if route is not None:
            route.finish("returned")
        transport.close()
    return observed, provider


@pytest.mark.parametrize("kind", sorted(REPLIES))
def test_capture_on_and_off_keep_identical_observations_and_send_counts(tmp_path, kind):
    off, off_provider = execute(REPLIES[kind])
    with archive.capture(private_root(tmp_path), operation=f"check {kind}", routes=True) as scope:
        on, on_provider = execute(REPLIES[kind], scope=scope)
    assert on == off and len(on_provider.sent) == len(off_provider.sent) == 1
    assert on_provider.sent[0].content == off_provider.sent[0].content
    wire, = records(scope, "route_wire_request")
    assert wire["path"] == f"/v1beta/models/{MODEL}:generateContent" and wire["method"] == "POST"
    assert archive.read_private_file(scope.directory / archive.ARTIFACTS / wire["body"]["artifact"], 1 << 22) \
        == on_provider.sent[0].content
    response, = records(scope, "route_response")
    kept = archive.read_private_file(scope.directory / archive.ARTIFACTS / response["body"]["artifact"], 1 << 22)
    assert kept == on.raw and response["complete"] is on.complete and response["reason"] == on.reason
    assert response["status"] == on.http_status
    assert response["body"]["form"] == "raw_http_entity_identity" + ("" if on.complete else "_bounded_prefix")
    loaded = replay.load_archive(scope.directory)
    assert loaded.status == "complete" and loaded.routes[0].family == "command_check"
    traced, = replay.route_lineage(loaded)["routes"]
    assert traced["family"] == "command_check" and "predecessor" not in traced
    # The exact bounded entity (even an error body) is private evidence; credentials never are.
    assert KEY.encode() not in all_bytes(scope) and b"x-goog-api-key" not in all_bytes(scope).lower()


def test_encoded_response_is_refused_not_decompressed_and_headers_say_so(tmp_path):
    with archive.capture(private_root(tmp_path), operation="encoded", routes=True) as scope:
        observed, _ = execute(REPLIES["encoded"], scope=scope)
    assert observed.raw == b"" and not observed.complete
    response, = records(scope, "route_response")
    assert response["headers"]["content-encoding"] == "gzip" and response["body"]["bytes"] == 0


def test_cleanup_failure_is_retained_as_incomplete(tmp_path, monkeypatch):
    original = httpx.Response.close

    def close(self):
        # The stream's own end-of-read close succeeds; the transport's finally close fails.
        if getattr(self, "_invented_closed_once", False):
            raise RuntimeError(SECRET)
        self._invented_closed_once = True
        return original(self)
    monkeypatch.setattr(httpx.Response, "close", close)
    off, _ = execute(REPLIES["complete200"])
    with archive.capture(private_root(tmp_path), operation="cleanup", routes=True) as scope:
        observed, _ = execute(REPLIES["complete200"], scope=scope)
    assert observed == off and observed.reason == "cleanup_failed" and not observed.complete
    response, = records(scope, "route_response")
    assert response["reason"] == "cleanup_failed" and SECRET.encode() not in all_bytes(scope)


def test_wrong_model_url_never_sends_and_records_no_send(tmp_path):
    with archive.capture(private_root(tmp_path), operation="wrong model", routes=True) as scope:
        observed, provider = execute(REPLIES["complete200"], scope=scope, expected_model="gemini-other")
    assert provider.sent == [] and observed.reason == "transport_unavailable"
    result, = records(scope, "route_result")
    assert result["physical_send_observed"] is False and result["provider_outcome"] == "not_sent"
    assert result["refusal"] == "archive_unsupported_endpoint"


def test_second_post_is_refused_before_any_send(tmp_path):
    provider = Provider(REPLIES["complete200"])
    with archive.capture(private_root(tmp_path), operation="second post", routes=True) as scope:
        transport = check_transport.GoogleCheckTransport(api_key=KEY, model=MODEL,
                                                         http_transport=httpx.MockTransport(provider))
        try:
            route = scope.begin_route("command_check", client=transport._http,
                                      expected_path=f"/v1beta/models/{MODEL}:generateContent", binding={})
            transport.execute(dict(model=MODEL, contents="invented"))
            with pytest.raises(ValueError, match="already_used"):
                transport.execute(dict(model=MODEL, contents="again"))
            route.finish("returned")
        finally:
            transport.close()
    assert len(provider.sent) == 1 and len(records(scope, "route_wire_request")) == 1


def test_synchronous_only_scope_refuses_the_check_transport(tmp_path):
    with archive.capture(private_root(tmp_path), operation="v1"):
        with pytest.raises(ValueError, match="check_client_unavailable"):
            check_transport.GoogleCheckTransport(api_key=KEY, model=MODEL,
                                                 http_transport=httpx.MockTransport(Provider(REPLIES["empty"])))


def options(reply):
    provider = Provider(reply)
    return provider, {"api_key": KEY, "http_transport": httpx.MockTransport(provider)}


def test_executor_binds_the_actual_check_identities_and_one_send(case, tmp_path):
    assert run(case)["outcome"] == "completed"  # deterministic stage: local, no provider route
    provider, transport_options = options(REPLIES["complete200"])
    with archive.capture(private_root(tmp_path), operation="safety check", routes=True) as scope:
        result = run(case, "safety", transport_options=transport_options)
    assert result["checks"]["stages"]["safety"] == "passed" and len(provider.sent) == 1
    attempt = saved(case)["attempts"]["safety"]
    intent, = records(scope, "route_intent")
    binding = intent["binding"]
    assert binding["check_set_id"] == {"value": case["identity"], "source": "invoking_request"}
    assert binding["stage"]["value"] == "safety" and binding["request_sha256"]["value"] == attempt["binding"]["request_sha256"]
    assert binding["policy_sha256"]["source"] == "verified_current_context"
    bound, = records(scope, "route_bound")
    assert bound["binding"]["grant_id"] == {"value": attempt["grant_id"], "source": "check_grant"}
    response, = records(scope, "route_response")
    assert response["body"]["artifact"] == attempt["observation"]["raw_sha256"]
    result_record, = records(scope, "route_result")
    assert result_record["disposition"]["observation_complete"] is True
    assert result_record["disposition"]["stage"] == "safety" and result_record["billing"] == "unknown"
    assert KEY.encode() not in all_bytes(scope)


@pytest.mark.parametrize("kind", ["oversize", "provider_error", "sdk_parse_failure"])
def test_incomplete_or_failed_responses_never_pass_a_check(case, tmp_path, kind):
    assert run(case)["outcome"] == "completed"
    provider, transport_options = options(REPLIES[kind])
    with archive.capture(private_root(tmp_path), operation=f"failed {kind}", routes=True) as scope:
        result = run(case, "safety", transport_options=transport_options)
    assert result["checks"]["stages"]["safety"] != "passed" and len(provider.sent) == 1
    result_record, = records(scope, "route_result")
    assert result_record["archival"] == "complete" and KEY.encode() not in all_bytes(scope)
    assert SECRET.encode() not in archive.read_private_file(scope.directory / archive.MANIFEST, 1 << 22)


@pytest.mark.parametrize("failing", ["route_intent", "route_bound", "route_response"])
def test_archive_failure_refuses_before_send_and_holds_after(case, tmp_path, monkeypatch, failing):
    assert run(case)["outcome"] == "completed"
    provider, transport_options = options(REPLIES["complete200"])
    original = archive._write_all

    def fail(fd, data):
        if f'"type":"{failing}"'.encode() in data:
            raise OSError("invented disk failure")
        return original(fd, data)
    monkeypatch.setattr(archive, "_write_all", fail)
    with archive.capture(private_root(tmp_path), operation=f"io {failing}", routes=True) as scope:
        result = run(case, "safety", transport_options=transport_options)
    if failing == "route_intent":
        assert result["reason"] == "archive_refused_before_grant" and provider.sent == []
        assert "safety" not in saved(case)["attempts"] or not saved(case)["attempts"]["safety"]
    elif failing == "route_bound":
        assert result["reason"] == "archive_refused_before_send" and provider.sent == []
        # The grant is unresolved; recovery never sends it again.
        monkeypatch.setattr(archive, "_write_all", original)
        again, again_options = options(REPLIES["complete200"])
        recovered = run(case, "safety", transport_options=again_options)
        assert again.sent == [] and recovered["outcome"] != "completed"
    else:
        # Lost observation after a real send: the check outcome is the transport's own.
        assert result["checks"]["stages"]["safety"] == "passed" and len(provider.sent) == 1
        assert scope.held is not None


def test_disabled_executor_stays_disabled_inside_a_route_scope(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("I/O while disabled")
    monkeypatch.setattr(executor, "GoogleCheckTransport", forbidden)
    with archive.capture(private_root(tmp_path), operation="disabled check", routes=True) as scope:
        invalid: Any = dict(current_context=None, checker_state=None, owner="", clock=forbidden)
        result = executor.execute_check_once(cast(Any, None), "invalid", **invalid)
    assert result["outcome"] == "disabled" and records(scope, "route_intent") == []
