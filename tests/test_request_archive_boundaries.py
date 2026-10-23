"""Review counterexamples, invented data and offline SDK transports only."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.two_bot import request_archive as archive
from src.two_bot import request_archive_replay as replay
from src.two_bot.trial_budget import provider_call, anthropic_trial_options, google_trial_options
from tests.test_request_archive_replay import _rechain, copy_archive
from tests.test_request_archive_sdk import (
    OfflineProviders, accepted_script, journey_env, offline_transport, private_root, run_journey,
    fact_json,
)

__all__ = ["journey_env"]
CANARY = "INVENTED-transport-secret-never-retain"


@pytest.mark.parametrize("kind,key,value", [
    ("generation_input", "bundle_sha256", "0" * 64),
    ("generation_input", "memory_sha256", "0" * 64),
    ("generation_input", "event_id", "different-invented-event"),
    ("candidate", "characters", 1),
    ("candidate", "attempt", True),
    ("terminal", "draft_text_sha256", "0" * 64),
    ("terminal", "reviewed_bundle_sha256", "0" * 64),
    ("terminal", "reviewed_policy_sha256", "0" * 64),
    ("terminal", "accepted", "yes"),
])
def test_rechained_but_contradictory_identities_are_invalid(journey_env, tmp_path, kind, key, value):
    run = run_journey(accepted_script(), root=private_root(tmp_path))
    copied = copy_archive(run.archive, tmp_path, "changed")
    records = [json.loads(line) for line in (copied / archive.MANIFEST).read_bytes().splitlines()]
    next(row for row in records if row["type"] == kind)["data"][key] = value
    (copied / archive.MANIFEST).write_bytes(b"\n".join(_rechain(records)) + b"\n")
    loaded = replay.load_archive(copied)
    assert loaded.status == "invalid" and loaded.problems


@pytest.mark.parametrize("kind,key", [
    ("call_intent", "bundle_sha256"), ("call_intent", "memory_sha256"),
    ("call_intent", "candidate_text_sha256"), ("stage_outcome", "candidate_text_sha256"),
    ("stage_outcome", "event_id"),
])
def test_call_and_stage_bindings_cannot_borrow_another_identity(journey_env, tmp_path, kind, key):
    run = run_journey(accepted_script(), root=private_root(tmp_path))
    copied = copy_archive(run.archive, tmp_path, "changed")
    records = [json.loads(line) for line in (copied / archive.MANIFEST).read_bytes().splitlines()]
    next(row for row in records if row["type"] == kind)["data"]["binding"][key] = "0" * 64
    (copied / archive.MANIFEST).write_bytes(b"\n".join(_rechain(records)) + b"\n")
    assert replay.load_archive(copied).status == "invalid"


@pytest.mark.parametrize("accepted,key,value", [
    (True, "kill_stage", "fact_check"),
    (True, "kill_reason_artifact", "existing-artifact"),
    (True, "stage_outcomes", {"fact_check": "kill"}),
    (False, "stage_outcomes", {"fact_check": "pass"}),
    (False, "kill_stage", "critic"),
    (False, "kill_reason_artifact", "existing-artifact"),
])
def test_terminal_summary_cannot_contradict_observed_stages(journey_env, tmp_path, accepted, key, value):
    script = accepted_script()
    if not accepted:
        script["fact_check"] = [{"text": fact_json(False, failures=["Invented failed claim"])}]
        del script["critic"]
    run = run_journey(script, root=private_root(tmp_path))
    assert replay.load_archive(run.archive).status == "complete"
    copied = copy_archive(run.archive, tmp_path, "changed")
    records = [json.loads(line) for line in (copied / archive.MANIFEST).read_bytes().splitlines()]
    if value == "existing-artifact":
        value = next(row for row in records if row["type"] == "candidate")["data"]["text_artifact"]
    next(row for row in records if row["type"] == "terminal")["data"][key] = value
    (copied / archive.MANIFEST).write_bytes(b"\n".join(_rechain(records)) + b"\n")
    loaded = replay.load_archive(copied)
    assert loaded.status == "invalid" and loaded.problems[0].startswith("terminal_binding:")


@pytest.mark.parametrize("option", ["extra_headers", "extra_query", "extra_body"])
def test_anthropic_request_transport_overrides_refuse_before_retention(tmp_path, option):
    import anthropic
    providers = OfflineProviders()
    with offline_transport(providers), archive.capture(private_root(tmp_path), operation="transport canary") as scope:
        with anthropic.Anthropic(api_key="invented", **anthropic_trial_options()) as client:
            with pytest.raises(archive.RequestArchiveRefused, match="transport_override"):
                provider_call("writer", "anthropic", {"model": "claude-sonnet-4-6", "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Invented"}], option: {"Authorization": CANARY}},
                    client.messages.create)
    assert providers.physical == []
    assert not list((scope.directory / archive.ARTIFACTS).iterdir())
    assert CANARY.encode() not in (scope.directory / archive.MANIFEST).read_bytes()


@pytest.mark.parametrize("config_kind", ["dict", "model", "alias", "both_aliases"])
def test_google_request_http_options_never_retain_credentials(tmp_path, config_kind):
    from google import genai
    from google.genai import types
    config: Any = {"http_options": {"headers": {"Authorization": CANARY}}}
    if config_kind == "model":
        config = types.GenerateContentConfig(http_options=types.HttpOptions(headers={"Authorization": CANARY}))
    elif config_kind == "alias":
        config = {"httpOptions": {"headers": {"Authorization": CANARY}}}
    elif config_kind == "both_aliases":
        config = {"http_options": None, "httpOptions": {"headers": {"Authorization": CANARY}}}
    providers = OfflineProviders()
    with offline_transport(providers), archive.capture(private_root(tmp_path), operation="transport canary") as scope:
        with genai.Client(api_key="invented", http_options=types.HttpOptions(**google_trial_options())) as client:
            with pytest.raises(archive.RequestArchiveRefused, match="transport_override"):
                provider_call("safety", "google", {"model": "gemini-flash-latest", "contents": "Invented",
                                                    "config": config}, client.models.generate_content)
    assert providers.physical == [] and not list((scope.directory / archive.ARTIFACTS).iterdir())
    assert CANARY.encode() not in (scope.directory / archive.MANIFEST).read_bytes()


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_client_created_before_capture_is_refused_without_physical_send(tmp_path, provider):
    import anthropic
    from google import genai
    providers = OfflineProviders()
    with offline_transport(providers):
        client: Any = (anthropic.Anthropic(api_key="invented") if provider == "anthropic"
                  else genai.Client(api_key="invented"))
        with client, archive.capture(private_root(tmp_path), operation="unhooked client") as scope:
            send = client.messages.create if provider == "anthropic" else client.models.generate_content
            request = ({"model": "claude-sonnet-4-6", "max_tokens": 16, "messages": []}
                       if provider == "anthropic" else {"model": "gemini-flash-latest", "contents": "Invented"})
            with pytest.raises(archive.RequestArchiveRefused, match="unobserved_transport"):
                provider_call("writer" if provider == "anthropic" else "safety", provider, request, send)
    loaded = replay.load_archive(scope.directory)
    assert providers.physical == [] and loaded.calls == ()
    assert loaded.refusals[0]["before_dispatch"] is True


def test_unobserved_exception_never_becomes_not_sent_or_complete(tmp_path):
    with archive.capture(private_root(tmp_path), operation="unobserved result") as scope:
        recorder = scope.begin_call("safety", "google", {"model": "invented", "contents": "Invented"})
        assert recorder.raised(TimeoutError()) is None
    loaded = replay.load_archive(scope.directory)
    assert loaded.status == "incomplete"
    assert loaded.calls[0].result is not None
    assert loaded.calls[0].result["provider_outcome"] == "unknown"


@pytest.mark.parametrize("provider", ["anthropic", "google"])
def test_removed_response_hook_is_refused_before_execution(tmp_path, provider):
    import anthropic
    from google import genai
    from google.genai import types
    providers = OfflineProviders()
    with offline_transport(providers), archive.capture(private_root(tmp_path), operation="removed hook"):
        client: Any = (anthropic.Anthropic(api_key="invented", **anthropic_trial_options()) if provider == "anthropic"
                  else genai.Client(api_key="invented", http_options=types.HttpOptions(**google_trial_options())))
        with client:
            transport = client._client if provider == "anthropic" else client._api_client._httpx_client
            transport.event_hooks["response"].clear()
            send = client.messages.create if provider == "anthropic" else client.models.generate_content
            with pytest.raises(archive.RequestArchiveRefused, match="unobserved_transport"):
                provider_call("writer" if provider == "anthropic" else "safety", provider,
                              {"model": "invented"}, send)
    assert providers.physical == []


def test_artifact_directory_replacement_cannot_redirect_capture(tmp_path):
    outside = private_root(tmp_path, "outside")
    with archive.capture(private_root(tmp_path), operation="directory substitution") as scope:
        intended = scope.directory / archive.ARTIFACTS
        retained = scope.directory / "renamed-artifacts"
        intended.rename(retained)
        intended.symlink_to(outside, target_is_directory=True)
        digest = scope._artifact(b"INVENTED private artifact")
        assert (retained / digest).read_bytes() == b"INVENTED private artifact"
        assert not list(outside.iterdir())
        intended.unlink()
        retained.rename(intended)
    # This storage-only probe did not append a record referencing its artifact.
    assert replay.load_archive(scope.directory).problems == ("unreferenced_artifact_in_sealed_scope",)


def test_export_replacement_mid_write_uses_pinned_directory(tmp_path, monkeypatch):
    selected = private_root(tmp_path, "selected")
    outside = private_root(tmp_path, "outside")
    retained = tmp_path / "original-selected"
    original_write = archive._write_all

    def replacing(fd, data):
        selected.rename(retained)
        selected.symlink_to(outside, target_is_directory=True)
        original_write(fd, data)

    monkeypatch.setattr(archive, "_write_all", replacing)
    assert archive.write_private_file_exclusive(selected, "report.json", b"INVENTED private export")
    assert (retained / "report.json").read_bytes() == b"INVENTED private export"
    assert not list(outside.iterdir())
    with pytest.raises(OSError):
        archive.read_private_file(selected / "report.json", 100)
    assert stat_mode(retained / "report.json") == 0o600


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def test_durability_probe_is_isolated_from_a_warm_callers_safety_cache(journey_env, tmp_path):
    from collections import OrderedDict
    from unittest.mock import patch
    from src.voice import safety
    from tests.test_request_archive_sdk import FIXTURE, test_durable_intent_and_wire_record_exist_before_each_physical_send
    warm_cache: OrderedDict[tuple[str, str, str], tuple[float, safety.SafetyCheckResult]] = OrderedDict()
    providers = OfflineProviders().queue("safety", {"text": "NO"})
    with patch.object(safety, "_SAFETY_CACHE", warm_cache), offline_transport(providers):
        first = safety.check_llm_result(FIXTURE["accepted_tweet"])
        assert first.execution_status == "completed" and not first.cache_hit
        assert len(warm_cache) == 1 and len(providers.physical) == 1
        test_durable_intent_and_wire_record_exist_before_each_physical_send(journey_env, tmp_path)
        assert safety._SAFETY_CACHE is warm_cache and len(warm_cache) == 1
        reused = safety.check_llm_result(FIXTURE["accepted_tweet"])
        assert reused.execution_status == "completed" and reused.cache_hit
        assert len(providers.physical) == 1  # The caller's valid cached verdict remains reusable.
