"""Offline purchase-boundary tests; invented data/SDKs never certify weather."""
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from src.two_bot import trial_budget as limits

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fresh_sample_trial", ROOT / "scripts/fresh_sample_trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def request(stage):
    if stage == "writer":
        return {"model": limits.MODELS[stage][1], "messages": [{"role": "user", "content": "Invented offline content"}]}
    return {"model": limits.MODELS[stage][1], "contents": "Invented offline content"}


def budget(tmp_path):
    rows = []
    value = limits.TrialBudget(rows.append, tmp_path / "STOP")
    return value, rows


def test_all_eight_requests_and_outputs_are_bounded_without_mutating_inputs(tmp_path):
    value, rows = budget(tmp_path)
    send = MagicMock(return_value=SimpleNamespace(text="offline"))
    with limits.trial_scope(value):
        for candidate in ("invented-a", "invented-b"):
            value.begin_candidate(candidate)
            for stage in limits.MODELS:
                original = request(stage)
                before = deepcopy(original)
                limits.provider_call(stage, limits.MODELS[stage][0], original, send)
                assert original == before
                kwargs = send.call_args.kwargs
                assert (kwargs["max_tokens"] if stage == "writer"
                        else kwargs["config"]["max_output_tokens"]) == limits.OUTPUT_LIMITS[stage]
        with pytest.raises(limits.TrialStopped, match="candidate_limit"):
            value.begin_candidate("invented-c")
    assert send.call_count == 8 and len(value.calls) == 8
    assert len(rows) == 16 and all(r["actual_cost_known"] is False for r in rows)
    assert value.estimated_reserved > 0


def test_retry_reservation_cannot_buy_a_second_call(tmp_path):
    value, rows = budget(tmp_path)
    value.begin_candidate("invented")
    send = MagicMock(return_value="offline")
    with limits.trial_scope(value):
        limits.provider_call("critic", "google", request("critic"), send)
        reserve = value.estimated_reserved
        with pytest.raises(limits.TrialStopped, match="retry_or_call_limit"):
            limits.provider_call("critic", "google", request("critic"), send)
    assert send.call_count == 1 and value.estimated_reserved == reserve


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionError(), KeyboardInterrupt()])
def test_uncertain_failure_stops_all_future_calls_without_refund(tmp_path, failure):
    value, rows = budget(tmp_path)
    value.begin_candidate("invented")
    send = MagicMock(side_effect=failure)
    with limits.trial_scope(value):
        with pytest.raises(type(failure)):
            limits.provider_call("writer", "anthropic", request("writer"), send)
        assert value.calls and value.estimated_reserved > 0
        assert rows[0]["outcome"] == "reserved_before_dispatch"
        with pytest.raises(limits.TrialStopped, match="outcome_unknown"):
            limits.provider_call("safety", "google", request("safety"), send)
    send.assert_called_once()


@pytest.mark.parametrize("case", ["no_candidate", "unknown_model", "oversize", "tools", "stop", "money", "count"])
def test_refusal_never_touches_provider(tmp_path, case):
    value, _ = budget(tmp_path)
    if case != "no_candidate":
        value.begin_candidate("invented")
    payload = request("critic")
    if case == "unknown_model":
        payload["model"] = "gemini-flash-latest"
    if case == "oversize":
        payload["contents"] = "x" * limits.MAX_REQUEST_BYTES
    if case == "tools":
        payload["config"] = {"tools": [{"google_search": {}}]}
    if case == "stop":
        (tmp_path / "STOP").touch()
    if case == "money":
        value.estimated_reserved = Decimal("2")
    if case == "count":
        value.calls = [{"candidate": "different", "stage": "writer"}] * 8
    send = MagicMock()
    with limits.trial_scope(value), pytest.raises(limits.TrialStopped):
        limits.provider_call("critic", "google", payload, send)
    send.assert_not_called()


def test_failed_journal_prevents_dispatch(tmp_path):
    value = limits.TrialBudget(MagicMock(side_effect=OSError("offline journal failure")), tmp_path / "STOP")
    value.begin_candidate("invented")
    send = MagicMock()
    with limits.trial_scope(value), pytest.raises(OSError):
        limits.provider_call("writer", "anthropic", request("writer"), send)
    assert value.stopped == "trial_journal_failed"
    send.assert_not_called()


def test_journal_failure_after_response_holds_charge_and_stops_next_candidate(tmp_path):
    journal = MagicMock(side_effect=[None, OSError("offline disk failure")])
    value = limits.TrialBudget(journal, tmp_path / "STOP")
    value.begin_candidate("invented")
    send = MagicMock(return_value="returned")
    with limits.trial_scope(value), pytest.raises(OSError):
        limits.provider_call("writer", "anthropic", request("writer"), send)
    assert value.estimated_reserved > 0 and len(value.calls) == 1
    assert value.stopped == "trial_journal_failed_after_dispatch"
    with pytest.raises(limits.TrialStopped):
        value.begin_candidate("next")
    send.assert_called_once()


def test_normal_transport_preserves_exact_request_and_default_retry_options():
    original = {"model": "other-production-model", "config": object(), "contents": "unchanged"}
    send = MagicMock(return_value="returned")
    assert limits.provider_call("unknown", "google", original, send) == "returned"
    assert send.call_args.kwargs == original
    assert send.call_args.kwargs["config"] is original["config"]
    assert limits.google_trial_options() == {}


def test_real_sdk_boundaries_all_use_one_attempt_and_existing_requests(monkeypatch, tmp_path):
    import anthropic
    from anthropic.types import TextBlock
    from google import genai
    from src.two_bot import writer, fact_check, critic
    from src.voice import safety
    from tests.two_bot.conftest import _bundle
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-only")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-only")
    for module, attr, stage in [(writer, "WRITER_MODEL", "writer"), (fact_check, "FACT_CHECKER_MODEL", "fact_check"),
                                (critic, "CRITIC_MODEL", "critic"), (safety, "GEMINI_SAFETY_MODEL", "safety")]:
        monkeypatch.setattr(module, attr, limits.MODELS[stage][1])
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-only")
    monkeypatch.setattr(safety, "_SAFETY_CACHE", OrderedDict())
    anthropic_client = MagicMock()
    anthropic_client.messages.create.return_value = SimpleNamespace(
        content=[TextBlock(type="text", text="offline writer JSON")], stop_reason="end_turn", usage=None)
    af = MagicMock(return_value=anthropic_client)
    monkeypatch.setattr(anthropic, "Anthropic", af)
    google_client = MagicMock()
    google_client.models.generate_content.return_value = SimpleNamespace(text="NO", usage_metadata=None)
    gf = MagicMock(return_value=google_client)
    monkeypatch.setattr(genai, "Client", gf)
    value, _ = budget(tmp_path)
    value.begin_candidate("invented")
    with limits.trial_scope(value):
        assert writer._call_anthropic("invented user") == "offline writer JSON"
        assert safety.check_llm_result("Invented offshore warning.").allowed
        assert fact_check._call_gemini("Invented offshore warning.", _bundle()) == "NO"
        assert critic._call_gemini("Invented offshore warning.", _bundle(), [], []) == "NO"
    assert len(value.calls) == 4
    af.assert_called_once_with(api_key="offline-only", timeout=180.0, max_retries=0)
    assert gf.call_count == 3
    assert all(c.kwargs["http_options"].retry_options.attempts == 1 for c in gf.call_args_list)
    assert [c.kwargs["config"]["max_output_tokens"] for c in google_client.models.generate_content.call_args_list] == [2048,8192,8192]


def test_threaded_writer_slate_refused_inside_trial(tmp_path):
    from src.two_bot.pipeline import _writer_sample_slate
    value, _ = budget(tmp_path)
    with limits.trial_scope(value), pytest.raises(limits.TrialStopped, match="one_writer_sample"):
        _writer_sample_slate(None, None, 3)


@pytest.mark.parametrize("filename", ["writer-dryrun.yml", "news-enrich-dryrun.yml", "reganom-dryrun.yml"])
def test_all_manual_paid_jobs_obey_exact_pause_and_opt_in_predicate(filename):
    wf = yaml.load((ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)
    assert list(wf["on"]) == ["workflow_dispatch"]
    assert wf["jobs"]["dryrun"]["if"] == (
        "vars.THEHEAT_PRODUCTION_PAUSED != '1' && vars.THEHEAT_PAID_EVALUATION_ENABLED == '1'")
    assert wf["jobs"]["dryrun"]["steps"][0] == {"uses": "actions/checkout@v6"}


def packet(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(trial, "binding", lambda: {"offline_binding": True})
    monkeypatch.setattr(trial, "eligible", lambda bundle, now: True)
    state_raw, bundle_raw = b'{"drafts":[]}', trial.encoded([{"event_id": "invented"}])
    plan = {"prepared_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
            "packet_path": str(tmp_path.resolve()), "binding": trial.binding(),
            "state_sha256": trial.digest(state_raw), "bundles_sha256": trial.digest(bundle_raw),
            "candidate_event_ids": ["invented"]}
    for name, raw in [("state.json",state_raw),("bundles.json",bundle_raw),("plan.json",trial.encoded(plan))]:
        trial.save(tmp_path / name, raw)
    return now, trial.digest(trial.encoded(plan))


@pytest.mark.parametrize("case", ["wrong_approval", "expired", "state_changed", "bundle_changed", "binding_changed", "relocated"])
def test_packet_expiry_and_tamper_rejected_before_execution(tmp_path, monkeypatch, case):
    now, sha = packet(tmp_path, monkeypatch)
    if case == "wrong_approval":
        sha = "0" * 64
    if case == "expired":
        now += timedelta(hours=2)
    if case == "state_changed":
        (tmp_path / "state.json").write_text("{}")
    if case == "bundle_changed":
        (tmp_path / "bundles.json").write_text("[]")
    if case == "binding_changed":
        monkeypatch.setattr(trial, "binding", lambda: {"changed": True})
    if case == "relocated":
        data = json.loads((tmp_path / "plan.json").read_bytes())
        data["packet_path"] = "/different"
        (tmp_path / "plan.json").write_bytes(trial.encoded(data))
        sha = trial.digest(trial.encoded(data))
    with pytest.raises(ValueError):
        trial.validate_packet(tmp_path, sha, now)
    assert not (tmp_path / "execution-started.json").exists()


def test_exclusive_claim_survives_interruption_and_blocks_other_packet_copy(tmp_path, monkeypatch):
    common = tmp_path / "repo/.git"
    common.mkdir(parents=True)
    monkeypatch.setattr(trial.subprocess, "check_output", lambda *a, **k: str(common))
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    now = datetime.now(timezone.utc)
    trial.claim_execution(first, "a" * 64, now)
    with pytest.raises(FileExistsError):
        trial.claim_execution(first, "a" * 64, now)
    with pytest.raises(FileExistsError):
        trial.claim_execution(second, "a" * 64, now)
    assert not (second / "execution-started.json").exists()


def alert(now, event="Blizzard Warning", identity="invented-1"):
    from src.commands.schema import utc_text
    from src.data.nws_alerts import SevereWeatherAlert
    from src.media.published_radar import source_envelope
    times = {"sent": (now - timedelta(minutes=20)).isoformat(),
             "effective": (now - timedelta(minutes=20)).isoformat(),
             "onset": (now - timedelta(minutes=10)).isoformat(),
             "expires": (now + timedelta(hours=2)).isoformat(), "ends": None}
    feature = {"type": "Feature", "geometry": None,
               "properties": {**times, "id": identity, "event": event}}
    return SevereWeatherAlert(event, "Invented test area", "Extreme", "Invented warning", "nws_" + identity,
                              source_evidence=source_envelope(feature, utc_text(now)))


def test_actual_source_builder_and_freshness_filter_reject_stale_expired_and_tampered():
    from src.two_bot.intern import build_severe_weather_bundle
    now = datetime.now(timezone.utc)
    bundle = build_severe_weather_bundle(alert(now)).to_dict()
    assert trial.eligible(bundle, now)
    assert not trial.eligible(bundle, now + timedelta(hours=3))
    assert not trial.eligible(bundle, now - timedelta(hours=1))
    changed = deepcopy(bundle)
    changed["raw_signal_dump"]["source_evidence"]["feature"]["properties"]["event"] = "changed"
    assert not trial.eligible(changed, now)


def test_prepare_selects_two_kinds_once_no_purchases_and_no_state_mutation(tmp_path, monkeypatch):
    from src.data import nws_alerts
    now = datetime.now(timezone.utc)
    fetch = MagicMock(return_value=[alert(now), alert(now, identity="same-kind"),
                                  alert(now, "Hurricane Warning", "invented-2"),
                                  alert(now, "Storm Surge Warning", "invented-3")])
    monkeypatch.setattr(nws_alerts, "fetch_alerts", fetch)
    monkeypatch.setattr(trial, "binding", lambda: {"offline_binding": True})
    state = tmp_path / "input-state.json"
    original = b'{"drafts": [], "posted_events": []}'
    state.write_bytes(original)
    output = tmp_path / "packet"
    result = trial.prepare(state, output, now)
    assert result["paid_calls"] == 0 and result["candidate_count"] == 2
    assert state.read_bytes() == original
    fetch.assert_called_once_with(strict=True)
    assert len(json.loads((output / "bundles.json").read_bytes())) == 2
    assert not (output / "execution-started.json").exists()


def test_execute_loop_persists_before_call_and_stops_after_uncertain_first_attempt(tmp_path, monkeypatch):
    from src.two_bot import pipeline, provider_preflight
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(trial, "validate_packet", lambda *a: ({"drafts": []}, [
        {"signal_kind": "severe_weather", "where": "Invented", "when": now.isoformat(),
         "event_id": event, "headline_metric": {}, "current_facts": []} for event in ("a", "b")]))
    monkeypatch.setattr(trial, "eligible", lambda *a: True)
    monkeypatch.setattr(trial, "claim_execution", lambda output, sha, at: trial.save(output / "execution-started.json", b'{}'))
    monkeypatch.setattr(provider_preflight, "current_provider_preflight", lambda **k: {"status": "configured_unverified"})
    send = MagicMock(side_effect=TimeoutError())

    def offline_pipeline(bundle, state, result_out):
        assert (tmp_path / "execution-started.json").exists()
        try:
            limits.provider_call("writer", "anthropic", request("writer"), send)
        except TimeoutError:
            result_out["kill_stage"] = "pipeline_error"
        return None

    generate = MagicMock(side_effect=offline_pipeline)
    monkeypatch.setattr(pipeline, "generate_draft", generate)
    result = trial.execute(tmp_path, "a" * 64, now)
    assert result["attempted_candidates"] == 1 and result["drafts_returned"] == 0
    assert result["stop_reason"] == "trial_provider_outcome_unknown"
    assert result["paid_dispatch_reservations"] == 1 and result["actual_cost_known"] is False
    assert json.loads((tmp_path / "purchases.jsonl").read_text())["outcome"] == "reserved_before_dispatch"
    assert result["production_state_writes"] == result["posts"] == 0
    assert generate.call_count == send.call_count == 1


def load_script(name):
    value = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(value)
    value.loader.exec_module(module)
    return module


@pytest.mark.parametrize("case", ["first", "rerun", "duplicate", "unobserved", "history_limit", "invalid_id"])
def test_github_claim_is_first_id_only_and_fail_closed(case):
    module = load_script("claim_sample_trial")
    identity = "a" * 32
    env = {"TRIAL_ID": identity, "GITHUB_REPOSITORY": "fixture/repo", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_RUN_ID": "10"}
    data = {"total_count": 1, "workflow_runs": [{"id": 10, "display_title": "Fresh sample " + identity}]}
    if case == "rerun":
        env["GITHUB_RUN_ATTEMPT"] = "2"
    if case == "duplicate":
        data["workflow_runs"].append({"id": 9, "display_title": "Fresh sample " + identity})
    if case == "unobserved":
        data["workflow_runs"] = []
    if case == "history_limit":
        data["total_count"] = 101
    if case == "invalid_id":
        env["TRIAL_ID"] = "unsafe input"
    if case == "first":
        module.claim(env, lambda path: data)
    else:
        with pytest.raises(ValueError):
            module.claim(env, lambda path: data)


def test_one_shot_workflow_never_uploads_plaintext_or_enables_recurring_bot():
    wf = yaml.load((ROOT / ".github/workflows/fresh-sample-trial.yml").read_text(), Loader=yaml.BaseLoader)
    assert list(wf["on"]) == ["workflow_dispatch"]
    assert wf["permissions"] == {"contents": "read", "actions": "read"}
    job = wf["jobs"]["trial"]
    condition = " ".join(job["if"].split())
    assert "github.run_attempt == 1" in condition
    assert "vars.THEHEAT_PRODUCTION_PAUSED == '1'" in condition
    assert "inputs.approval == 'APPROVE-2-USD-SAMPLE-TRIAL'" in condition
    steps = job["steps"]
    claim_index = next(i for i,s in enumerate(steps) if "claim_sample_trial.py" in s.get("run", ""))
    paid_index = next(i for i,s in enumerate(steps) if "ANTHROPIC_API_KEY" in s.get("env", {}))
    assert claim_index < paid_index
    assert steps[-1]["with"]["path"] == "${{ runner.temp }}/sample-trial.cms"
    assert steps[-2]["run"] == "python scripts/package_sample_trial.py"
    assert "RECIPIENT_CERTIFICATE" in steps[-2]["env"]
    assert "secrets." not in str(steps[-2]["env"])
    assert not any("bot.yml" in s.get("run", "") or "gh variable set" in s.get("run", "") for s in steps)


def test_encrypted_artifact_round_trip_and_malformed_recipient_refusal(tmp_path):
    module = load_script("package_sample_trial")
    key, cert = tmp_path / "private.pem", tmp_path / "public.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=InventedTrial", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True, timeout=15)
    content = tmp_path / "sample-trial"
    content.mkdir()
    (content / "candidate-1.json").write_text('{"text":"Invented private draft"}')
    module.package(tmp_path, cert.read_text())
    encrypted = (tmp_path / "sample-trial.cms").read_bytes()
    assert b"Invented private draft" not in encrypted
    decoded = subprocess.check_output(["openssl", "cms", "-decrypt", "-binary", "-inform", "DER",
                  "-in", str(tmp_path / "sample-trial.cms"), "-recip", str(cert), "-inkey", str(key)], timeout=15)
    assert decoded == (tmp_path / "sample-trial.tar.gz").read_bytes()
    # A malformed certificate cannot produce an uploadable plaintext substitute.
    (tmp_path / "sample-trial.cms").unlink()
    with pytest.raises(subprocess.CalledProcessError):
        module.package(tmp_path, "invalid public certificate")
