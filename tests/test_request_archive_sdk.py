"""Actual pinned SDK send boundaries with explicit INVENTED offline transports.

The real Anthropic (httpx2) and Google (httpx) clients serialize and send; only
``HTTPTransport.handle_request`` is replaced, and any other host fails the test.
These fixtures prove mechanical capture, never provider behavior or quality.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

from src.two_bot import request_archive, request_archive_replay as replay, retry, trial_budget

FIXTURE = json.loads((Path(__file__).parent / "fixtures/request_archive/invented_provider_responses.json")
                     .read_text())
CANARIES = {"anthropic": "canary-anthropic-key-ZQ7X-never-archive",
            "google": "canary-google-key-W4PL-never-archive",
            "header": "canary-header-value-9KD2-never-archive"}
GOOGLE_STAGES = {"gemini-flash-latest": "safety", "gemini-2.5-flash": "fact_check", "gemini-2.5-pro": "critic"}


def private_root(base: Path, name: str = "private-archive") -> Path:
    root = base / name
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    return root


def writer_json(tweet: str | None, kill: str | None = None) -> str:
    return json.dumps({"tweet": tweet, "kill_reason": kill, "angle_chosen": "number", "era_anchor_used": None,
                       "peer_comparison_used": None, "reasoning": "invented fixture"})


def fact_json(passed: bool, claims=None, failures=None) -> str:
    return json.dumps({"passed": passed, "extracted_claims": claims if claims is not None
                       else FIXTURE["accepted_claims"], "failures": failures or []})


def critic_json(verdict: str, **extra) -> str:
    return json.dumps({"verdict": verdict, "kill_reason": extra.pop("kill_reason", None), **extra})


class OfflineProviders:
    """Scripted invented responses keyed by the stage each real request targets."""

    def __init__(self):
        self.script: dict[str, list] = defaultdict(list)
        self.physical: list[tuple[str, bytes]] = []
        self.observers: list = []
        self.counter = 0

    def queue(self, stage: str, *items) -> OfflineProviders:
        self.script[stage].extend(items)
        return self

    @staticmethod
    def stage_of(request) -> str:
        host = request.url.host
        if host == "api.anthropic.com":
            return "writer"
        if host != "generativelanguage.googleapis.com":
            raise AssertionError("external network trapped")
        from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT
        text = json.loads(request.content)["contents"][0]["parts"][0]["text"]
        if text.startswith(WRITER_SYSTEM_PROMPT[:200]):
            return "writer"
        return GOOGLE_STAGES[request.url.path.split("/models/")[1].split(":")[0]]

    def handle(self, family, request):
        request.read()  # A followed redirect carries a re-readable byte stream.
        stage = self.stage_of(request)
        self.physical.append((stage, bytes(request.content)))
        for observer in self.observers:
            observer(stage, request)
        if not self.script[stage]:
            raise AssertionError(f"unscripted {stage} request")
        item = self.script[stage].pop(0)
        self.counter += 1
        if callable(item):
            return item(family, request)
        if "raise" in item:
            raise family.ReadTimeout("invented offline timeout", request=request)
        if "read_error" in item:
            base: Any = family.SyncByteStream

            class Failing(base):
                def __iter__(self):
                    raise family.ReadError("invented offline read failure", request=request)
            return family.Response(200, headers={"content-type": "application/json"}, stream=Failing())
        if "status" in item:
            return family.Response(item["status"], json={"error": {"message": "invented", "type": "invented"}},
                                   headers=item.get("headers", {}))
        if "body" in item:
            return family.Response(200, content=item["body"], headers={"content-type": "application/json"})
        text = item["text"]
        if request.url.host == "api.anthropic.com":
            body = {"id": f"{FIXTURE['anthropic_message_id']}-{self.counter}", "type": "message",
                    "role": "assistant", "model": "claude-sonnet-4-6",
                    "content": [] if text is None else [{"type": "text", "text": text}],
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 17, "output_tokens": 9}}
            headers = {"request-id": f"{FIXTURE['anthropic_request_id']}-{self.counter}",
                       "set-cookie": "invented-cookie-never-archive=1"}
        else:
            body = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                                    "finishReason": item.get("finish", "STOP")}],
                    "usageMetadata": {"promptTokenCount": 17, "candidatesTokenCount": 3, "totalTokenCount": 20},
                    "responseId": f"{FIXTURE['google_response_id']}-{self.counter}"}
            headers = {}
        return family.Response(200, json=body, headers=headers)


@contextmanager
def offline_transport(providers: OfflineProviders):
    import httpx
    import httpx2

    def modern(self, request):
        return providers.handle(httpx2, request)

    def legacy(self, request):
        return providers.handle(httpx, request)

    with patch.object(httpx2.HTTPTransport, "handle_request", modern), \
            patch.object(httpx.HTTPTransport, "handle_request", legacy):
        yield providers


@pytest.fixture
def journey_env(monkeypatch):
    """Invented canary credentials and existing default flags; no provider access."""
    from src.voice import safety
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES["anthropic"])
    monkeypatch.setenv("GEMINI_API_KEY", CANARIES["google"])
    monkeypatch.setattr(safety, "GEMINI_API_KEY", CANARIES["google"])
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    sleeps: list[float] = []
    monkeypatch.setattr(retry, "time", SimpleNamespace(sleep=sleeps.append))
    return SimpleNamespace(sleeps=sleeps)


def run_journey(script: dict, *, root: Path | None = None, bundle=None, state=None, **kwargs):
    """Run the actual generate_draft once, capture OFF (root None) or ON."""
    from src.two_bot import pipeline
    from src.voice import safety
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders()
    for stage, items in script.items():
        providers.queue(stage, *deepcopy(items))
    bundle = bundle if bundle is not None else _bundle()
    state = state if state is not None else _state_with_memory()
    out: dict = {}
    stdout = io.StringIO()
    archive = None
    with patch.object(safety, "_SAFETY_CACHE", OrderedDict()), offline_transport(providers), redirect_stdout(stdout):
        if root is None:
            draft = pipeline.generate_draft(bundle, state, result_out=out, **kwargs)
        else:
            with request_archive.capture(root, operation="invented offline rehearsal") as scope:
                draft, out = scope.run_generation(bundle, state, **kwargs)
            archive = scope.directory
    return SimpleNamespace(draft=draft, out=out, stdout=stdout.getvalue(), providers=providers,
                           state=state, archive=archive)


def accepted_script(writer=None):
    return {"writer": writer or [{"text": writer_json(FIXTURE["accepted_tweet"])}],
            "safety": [{"text": "NO"}], "fact_check": [{"text": fact_json(True)}],
            "critic": [{"text": critic_json("PASS")}]}


def result(call: replay.CallRecord) -> dict:
    assert call.result is not None
    return call.result


def archive_bytes(directory: Path) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(directory.rglob("*")) if path.is_file())


# ------------------------------------------------------------------ tests

def test_inactive_scope_preserves_options_objects_and_sdk_behavior():
    from unittest.mock import MagicMock
    original = {"model": "other-production-model", "config": object(), "contents": "unchanged"}
    send = MagicMock(return_value="returned")
    assert request_archive.active_scope() is None
    assert trial_budget.provider_call("unknown", "google", original, send) == "returned"
    assert send.call_args.kwargs == original and send.call_args.kwargs["config"] is original["config"]
    assert trial_budget.google_trial_options() == {} and trial_budget.anthropic_trial_options() == {}


@pytest.mark.parametrize("writer_provider", ["anthropic", "google"])
def test_capture_off_and_on_send_identical_bytes_and_return_identical_results(journey_env, tmp_path, monkeypatch,
                                                                              writer_provider):
    from src.two_bot import writer
    if writer_provider == "google":
        monkeypatch.setattr(writer, "WRITER_PROVIDER", "google")
        monkeypatch.setattr(writer, "WRITER_MODEL", "gemini-2.5-pro")
    off = run_journey(accepted_script())
    on = run_journey(accepted_script(), root=private_root(tmp_path))
    assert off.draft is not None and on.draft == off.draft and on.out == off.out
    assert on.providers.physical == off.providers.physical
    assert on.stdout == off.stdout and on.state == off.state
    archive = replay.load_archive(on.archive)
    assert archive.status == "complete" and [c.stage for c in archive.calls] == [
        "writer", "safety", "fact_check", "critic"]
    expected_family = "httpx2" if writer_provider == "anthropic" else "httpx"
    assert archive.calls[0].attempts[0].transport_family == expected_family
    for call, (stage, sent) in zip(archive.calls, on.providers.physical):
        assert call.stage == stage and len(call.attempts) == 1
        attempt = call.attempts[0]
        assert archive.artifact(attempt.request.artifact) == sent  # exact bytes that reached transport
        assert attempt.request.form == "exact_request_entity" and attempt.response.form == "decoded_http_entity"
        logical = archive.artifact(call.logical_request.artifact)
        assert logical != sent and json.loads(logical)["kwargs"]["model"] == call.model
        assert result(call)["billing"] == "unknown" and result(call)["archival"] == "complete"


def test_durable_intent_and_wire_record_exist_before_each_physical_send(journey_env, tmp_path):
    root = private_root(tmp_path)
    seen = []

    def at_send(stage, request):
        scope = next(root.iterdir())
        lines = (scope / "manifest.jsonl").read_bytes().splitlines()
        records = [json.loads(line) for line in lines]
        intent = [r for r in records if r["type"] == "call_intent"][-1]
        wire = records[-1]
        assert wire["type"] == "wire_request" and wire["data"]["call"] == intent["data"]["call"]
        assert (scope / "artifacts" / wire["data"]["body"]["artifact"]).read_bytes() == request.content
        assert (scope / "artifacts" / intent["data"]["logical_request"]["artifact"]).exists()
        seen.append(stage)

    from src.two_bot import pipeline
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders()
    for stage, items in accepted_script().items():
        providers.queue(stage, *items)
    providers.observers.append(at_send)
    from src.voice import safety
    # This probe specifically verifies all four uncached physical sends. A valid
    # safety result from an earlier test must not change the fixture's premise.
    with patch.object(safety, "_SAFETY_CACHE", OrderedDict()), offline_transport(providers), redirect_stdout(io.StringIO()):
        with request_archive.capture(root, operation="durability probe") as scope:
            draft, _ = scope.run_generation(_bundle(), _state_with_memory())
    assert draft is not None and seen == ["writer", "safety", "fact_check", "critic"]
    del pipeline


def test_canary_credentials_headers_and_cookies_never_enter_archive_or_output(tmp_path, capsys):
    import anthropic
    from google import genai
    from google.genai import types
    root = private_root(tmp_path)
    providers = OfflineProviders().queue("writer", {"text": "invented"}).queue("safety", {"text": "NO"})
    with offline_transport(providers), request_archive.capture(root, operation="canary probe") as scope:
        client = anthropic.Anthropic(api_key=CANARIES["anthropic"], max_retries=0,
                                     default_headers={"x-invented-canary": CANARIES["header"]},
                                     **trial_budget.anthropic_trial_options())
        trial_budget.provider_call("writer", "anthropic", {
            "model": "claude-sonnet-4-6", "max_tokens": 16,
            "messages": [{"role": "user", "content": "Invented canary prompt"}]}, client.messages.create)
        options = trial_budget.google_trial_options()
        with genai.Client(api_key=CANARIES["google"], http_options=types.HttpOptions(
                headers={"x-invented-canary": CANARIES["header"]}, **options)) as gclient:
            trial_budget.provider_call("safety", "google", {"model": "gemini-flash-latest",
                                       "contents": "Invented canary prompt"}, gclient.models.generate_content)
        client.close()
    content = archive_bytes(scope.directory)
    printed = capsys.readouterr()
    for secret in (*CANARIES.values(), "invented-cookie-never-archive"):
        assert secret.encode() not in content and secret not in printed.out + printed.err
    archive = replay.load_archive(scope.directory)
    assert archive.status == "complete"
    assert archive.calls[0].attempts[0].provider_ids == {
        "request_id_header": f"{FIXTURE['anthropic_request_id']}-1",
        "response_body_id": f"{FIXTURE['anthropic_message_id']}-1"}
    assert set(archive.calls[0].attempts[0].response_headers) <= {"content-type", "content-length", "request-id"}


def _trial(tmp_path):
    rows: list[dict] = []
    budget = trial_budget.TrialBudget(rows.append, tmp_path / "STOP")
    budget.begin_candidate("invented-candidate")
    return budget, rows


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_trial_guard_runs_first_and_both_records_bind_the_same_wire_bytes(tmp_path, provider):
    import anthropic
    from google import genai
    from google.genai import types
    stage = "writer" if provider == "anthropic" else "safety"
    request = ({"model": trial_budget.MODELS["writer"][1], "messages": [{"role": "user", "content": "Invented"}]}
               if provider == "anthropic" else {"model": trial_budget.MODELS["safety"][1], "contents": "Invented"})
    budget, rows = _trial(tmp_path)
    providers = OfflineProviders()
    # Routing label only: the trial's priced safety model shares the fixture checker's model name.
    providers.queue("writer" if provider == "anthropic" else "fact_check",
                    {"text": "NO" if provider == "google" else "invented"})
    root = private_root(tmp_path)
    with offline_transport(providers), trial_budget.trial_scope(budget), \
            request_archive.capture(root, operation="trial composition") as scope:
        if provider == "anthropic":
            client = anthropic.Anthropic(api_key="invented-offline", max_retries=0,
                                         **trial_budget.anthropic_trial_options())
            assert client._client.follow_redirects is False
            trial_budget.provider_call(stage, provider, request, client.messages.create)
            client.close()
        else:
            options = trial_budget.google_trial_options()
            assert options["retry_options"].attempts == 1
            assert options["client_args"]["follow_redirects"] is False
            with genai.Client(api_key="invented-offline", http_options=types.HttpOptions(**options)) as c:
                trial_budget.provider_call(stage, provider, request, c.models.generate_content)
    archive = replay.load_archive(scope.directory)
    wire = [row for row in rows if row["outcome"] == "wire_reserved_before_dispatch"]
    assert [row["outcome"] for row in rows] == ["reserved_before_dispatch", "wire_reserved_before_dispatch",
                                                "response_returned"]
    assert archive.calls[0].attempts[0].request.artifact == wire[0]["wire_request_sha256"]
    assert len(budget.calls) == 1 and budget.estimated_reserved > 0 and budget.stopped is None


def test_trial_refusal_at_wire_sends_nothing_and_records_no_wire_bytes(tmp_path, monkeypatch):
    import anthropic
    budget, rows = _trial(tmp_path)
    providers = OfflineProviders()
    root = private_root(tmp_path)
    request = {"model": trial_budget.MODELS["writer"][1], "messages": [{"role": "user", "content": "Invented"}]}
    with offline_transport(providers), trial_budget.trial_scope(budget), \
            request_archive.capture(root, operation="trial refusal") as scope:
        client = anthropic.Anthropic(api_key="invented-offline", max_retries=0, **trial_budget.anthropic_trial_options())

        reserve = budget.reserve

        def stop_after_reservation(*args):
            bounded = reserve(*args)
            (tmp_path / "STOP").write_text("stop")  # Reserved, then stopped before the wire.
            return bounded

        monkeypatch.setattr(budget, "reserve", stop_after_reservation)
        with pytest.raises(Exception):
            trial_budget.provider_call("writer", "anthropic", request, client.messages.create)
        client.close()
    archive = replay.load_archive(scope.directory)
    assert providers.physical == [] and archive.calls[0].attempts == ()
    assert result(archive.calls[0])["outcome"] == "raised_before_send"
    # The recorder did not observe the earlier budget guard; it must not infer a send outcome.
    assert result(archive.calls[0])["provider_outcome"] == "unknown"
    assert budget.stopped and len(budget.calls) == 1  # The reservation is kept, never refunded.


def test_streaming_and_unsupported_endpoints_refuse_before_any_send(tmp_path):
    import anthropic
    from google import genai
    from google.genai import types
    root = private_root(tmp_path)
    providers = OfflineProviders()
    with offline_transport(providers), request_archive.capture(root, operation="streaming refusal") as scope:
        client = anthropic.Anthropic(api_key="invented-offline", max_retries=0, **trial_budget.anthropic_trial_options())
        with pytest.raises(request_archive.RequestArchiveRefused, match="streaming"):
            trial_budget.provider_call("writer", "anthropic", {"model": "claude-sonnet-4-6", "max_tokens": 8,
                                       "stream": True, "messages": [{"role": "user", "content": "x"}]},
                                       client.messages.create)
        client.close()
        with genai.Client(api_key="invented-offline", http_options=types.HttpOptions(
                **trial_budget.google_trial_options())) as gclient:
            with pytest.raises(request_archive.RequestArchiveRefused, match="unobserved_transport"):
                trial_budget.provider_call("safety", "google", {"model": "gemini-flash-latest", "contents": "x"},
                                           lambda **kw: list(gclient.models.generate_content_stream(**kw)))
    assert providers.physical == []
    archive = replay.load_archive(scope.directory)
    assert archive.status == "complete" and archive.calls == ()
    assert {row["reason"] for row in archive.refusals} == {
        "archive_streaming_unsupported", "archive_unobserved_transport"}


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_timeout_after_send_is_unknown_and_keeps_existing_retry_count(journey_env, tmp_path, provider, monkeypatch):
    from src.two_bot import writer
    if provider == "google":
        monkeypatch.setattr(writer, "WRITER_PROVIDER", "google")
        monkeypatch.setattr(writer, "WRITER_MODEL", "gemini-2.5-pro")
    script = {"writer": [{"raise": "timeout"}] * 3}
    off = run_journey(script)
    on = run_journey(script, root=private_root(tmp_path))
    assert off.draft is on.draft is None and on.out == off.out and on.out["kill_stage"] == "pipeline_error"
    assert len(on.providers.physical) == len(off.providers.physical) == 3
    assert on.stdout == off.stdout
    archive = replay.load_archive(on.archive)
    assert archive.status == "complete" and archive.held is None
    assert [result(c)["outcome"] for c in archive.calls] == ["raised_after_send"] * 3
    assert all(result(c)["provider_outcome"] == "unknown" and result(c)["billing"] == "unknown"
               and c.attempts[0].response.availability == "not_observed" for c in archive.calls)


def test_failure_while_reading_response_is_labeled_without_changing_retries(journey_env, tmp_path):
    script = {"writer": [{"read_error": True}] * 3}
    off = run_journey(script)
    on = run_journey(script, root=private_root(tmp_path))
    assert len(on.providers.physical) == len(off.providers.physical) == 3 and on.out == off.out
    archive = replay.load_archive(on.archive)
    assert [a.response.availability for c in archive.calls for a in c.attempts] == ["read_failed"] * 3
    assert archive.held is None and all(result(c)["provider_outcome"] == "unknown" for c in archive.calls)


def test_failure_while_retaining_response_holds_and_never_buys_a_replacement(journey_env, tmp_path):
    root = private_root(tmp_path)
    holder = {}

    def lock_artifacts(stage, request):
        scope = next(root.iterdir())
        holder["dir"] = scope / "artifacts"
        os.chmod(holder["dir"], 0o500)  # Real filesystem failure for the next artifact write.

    script = accepted_script()
    from src.two_bot import pipeline
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders()
    for stage, items in script.items():
        providers.queue(stage, *items)
    providers.observers.append(lock_artifacts)
    out: dict = {}
    try:
        with offline_transport(providers), redirect_stdout(io.StringIO()):
            with request_archive.capture(root, operation="retention failure") as scope:
                draft = pipeline.generate_draft(_bundle(), cast(Any, _state_with_memory()), result_out=out)
    finally:
        os.chmod(holder["dir"], 0o700)
    assert draft is None and out["kill_stage"] == "pipeline_error"
    # The held call raises; the existing outer retries are then refused before any send.
    assert out["kill_reason"] == "RequestArchiveRefused: archive_scope_held"
    assert [stage for stage, _ in providers.physical] == ["writer"]  # Outer retries refused pre-send.
    archive = replay.load_archive(scope.directory)
    assert archive.status == "incomplete" and archive.held is not None
    assert result(archive.calls[0])["archival"] == "incomplete" and len(archive.calls) == 1


def test_oversize_response_is_unknown_and_never_an_approved_result(journey_env, tmp_path):
    big = b'{"invented":"' + b"x" * (request_archive.MAX_RESPONSE_BYTES + 1) + b'"}'
    root = private_root(tmp_path)
    from src.two_bot import pipeline
    from tests.two_bot.conftest import _bundle, _state_with_memory
    providers = OfflineProviders().queue("writer", {"body": big})
    out: dict = {}
    with offline_transport(providers), redirect_stdout(io.StringIO()):
        with request_archive.capture(root, operation="oversize response") as scope:
            draft = pipeline.generate_draft(_bundle(), cast(Any, _state_with_memory()), result_out=out)
    assert draft is None and len(providers.physical) == 1 and out["kill_stage"] == "pipeline_error"
    archive = replay.load_archive(scope.directory)
    response = archive.calls[0].attempts[0].response
    assert response.availability == "not_retained_over_limit" and response.size == len(big)
    assert archive.status == "incomplete" and archive.held == "archive_response_over_limit"
    assert result(archive.calls[0])["billing"] == "unknown"


def test_redirect_attempts_are_each_recorded_like_the_uncaptured_client(tmp_path):
    from google import genai
    from google.genai import types

    def redirect(family, request):
        return family.Response(307, headers={"location": str(request.url)})

    def run(root):
        providers = OfflineProviders()
        providers.queue("safety", redirect, {"text": "NO"})
        with offline_transport(providers):
            if root is None:
                with genai.Client(api_key="invented-offline", http_options=types.HttpOptions(
                        **trial_budget.google_trial_options())) as client:
                    trial_budget.provider_call("safety", "google", {"model": "gemini-flash-latest",
                                               "contents": "Invented"}, client.models.generate_content)
                return providers, None
            with request_archive.capture(root, operation="redirect") as scope:
                with genai.Client(api_key="invented-offline", http_options=types.HttpOptions(
                        **trial_budget.google_trial_options())) as client:
                    trial_budget.provider_call("safety", "google", {"model": "gemini-flash-latest",
                                               "contents": "Invented"}, client.models.generate_content)
            return providers, scope.directory

    off, _ = run(None)
    on, directory = run(private_root(tmp_path))
    assert on.physical == off.physical and len(on.physical) == 2
    archive = replay.load_archive(directory)
    assert [a.status for a in archive.calls[0].attempts] == [307, 200] and archive.status == "complete"
