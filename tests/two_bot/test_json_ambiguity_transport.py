"""Terminal ambiguity at actual SDK/caller/cache boundaries; invented offline replies."""

from copy import deepcopy
from dataclasses import asdict
import json

import anthropic
from google import genai
import httpx
import pytest

from src.editorial.policy import current_editorial_policy
from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
from src.two_bot import check_requests, critic, fact_check, usage_ledger, writer
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.provider_http import anthropic_httpx
from src.two_bot.rejected_candidate import capture_critic_rejection
from src.two_bot.types import WriterResult
from src.voice import safety
from tests.test_negative_cache_boundaries import bundle, run_direct
from tests.test_negative_cache import _score
from tests.two_bot.conftest import _bundle, _memory, _state_with_memory
from tests.two_bot.test_candidate_derivation import packet


TEXT = "A satellite measured 361 MW near Mali."
VIABLE = dict(tweet=TEXT, kill_reason=None, angle_chosen="plain_number",
              era_anchor_used=None, peer_comparison_used=None, reasoning="Invented fixture.")
KILL = dict(VIABLE, tweet=None, kill_reason="Invented missing comparative evidence.",
            kill_scope="evidence", kill_code="insufficient_evidence")
FACT_PASS = dict(passed=True, failures=[], extracted_claims=[
    dict(text="361 MW", kind="number"), dict(text="Mali", kind="named_entity")])
FACT_FAIL = dict(FACT_PASS, passed=False, failures=["Invented unsupported comparison."])
CRITIC_PASS = dict(verdict="PASS", kill_reason=None, selected_index=None)
CRITIC_KILL = dict(verdict="KILL", kill_reason="Invented repeated opener.", selected_index=None)


def ambiguous(first, second):
    return json.dumps(first) + "\n" + json.dumps(second)


def envelope(raw):
    return dict(candidates=[dict(index=0, finishReason="STOP",
        content=dict(role="model", parts=[dict(text=raw)]))],
        usageMetadata=dict(promptTokenCount=19, candidatesTokenCount=7, totalTokenCount=26))


@pytest.fixture
def sdk_wires(monkeypatch):
    """Real pinned SDKs, with every physical HTTP send intercepted offline."""
    real_anthropic, real_google = anthropic.Anthropic, genai.Client
    family = anthropic_httpx()
    clients, anthropic_sends, google_sends = [], [], []
    replies = {"anthropic": "", "google": ""}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-no-provider-access")
    monkeypatch.setattr(writer, "WRITER_PROVIDER", "anthropic")
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    safety._SAFETY_CACHE.clear()
    usage_ledger._BUFFER.clear()

    def anthropic_handler(request):
        anthropic_sends.append(json.loads(request.content))
        return family.Response(200, json=dict(id="msg_offline_fixture", type="message",
            role="assistant", model=writer.WRITER_MODEL, stop_reason="end_turn", stop_sequence=None,
            content=[dict(type="text", text=replies["anthropic"])],
            usage=dict(input_tokens=19, output_tokens=7)))

    def anthropic_factory(**kwargs):
        client = real_anthropic(**kwargs,
            http_client=family.Client(transport=family.MockTransport(anthropic_handler)))
        clients.append(client)
        return client

    def google_handler(request):
        google_sends.append(json.loads(request.content))
        response = replies["google"](request) if callable(replies["google"]) else replies["google"]
        return httpx.Response(200, json=envelope(response))

    def google_factory(**kwargs):
        kwargs["http_options"].client_args = {"transport": httpx.MockTransport(google_handler)}
        client = real_google(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(anthropic, "Anthropic", anthropic_factory)
    monkeypatch.setattr(genai, "Client", google_factory)
    yield replies, anthropic_sends, google_sends
    for client in clients:
        client.close()
    safety._SAFETY_CACHE.clear()
    usage_ledger._BUFFER.clear()


@pytest.mark.parametrize("raw", [ambiguous(KILL, VIABLE), ambiguous(VIABLE, KILL),
    ambiguous(KILL, KILL), ambiguous([], VIABLE)],
    ids=["kill-first", "viable-first", "identical-kill", "wrong-selector"])
def test_ambiguous_writer_never_repairs_saves_or_qualifies_negative_cache(sdk_wires, raw):
    replies, sends, google_sends = sdk_wires
    replies["anthropic"] = raw
    state, source = _state_with_memory(), bundle()
    original_source = deepcopy(source.to_dict())
    original_drafts, original_memory = deepcopy(state["drafts"]), deepcopy(state["memory"])
    original_ledger = deepcopy(state.get("publish_ledger"))
    for attempt in range(3):
        outcome = {}
        assert not run_direct(state, source, outcome)
        assert outcome["kill_stage"] == "writer" and not outcome.get("cacheable")
        assert outcome["model_diagnostics"][0]["raw_response"] == raw
        assert outcome["model_diagnostics"][0]["truncated"] is False
        assert len(sends) == attempt + 1  # Exactly one physical send per explicit invocation.
        assert not state.get("writer_negative_cache")
    assert not google_sends
    assert state["drafts"] == original_drafts and state["memory"] == original_memory
    assert state.get("publish_ledger") == original_ledger and source.to_dict() == original_source
    assert all("JSON-output retry" not in json.dumps(request) for request in sends)


@pytest.mark.parametrize("raw", [ambiguous(FACT_PASS, FACT_FAIL), ambiguous(FACT_FAIL, FACT_PASS),
    ambiguous(FACT_PASS, FACT_PASS), ambiguous([], FACT_PASS),
    json.dumps(FACT_PASS) + "\nSee https://example.invalid/source for context; revised result: " + json.dumps(FACT_FAIL)],
    ids=["pass-first", "fail-first", "identical-pass", "wrong-selector", "url-hidden-second"])
def test_fact_checker_ambiguity_fails_once_and_keeps_exact_raw_and_inputs(sdk_wires, raw):
    replies, anthropic_sends, sends = sdk_wires
    replies["google"] = raw
    source, state = _bundle(), _state_with_memory()
    original_source, original_state = deepcopy(source.to_dict()), deepcopy(state)
    assert fact_check.local_rejection(TEXT, [], source, state) is None
    result = fact_check.fact_check(TEXT, [], source, state)
    assert not result.passed and result.failures and result.raw_response == raw
    assert result.extracted_claims == [] and len(sends) == 1 and not anthropic_sends
    assert source.to_dict() == original_source and state == original_state
    assert "JSON-output retry" not in json.dumps(sends[0])


def test_writer_url_preamble_remains_one_request_without_repair(sdk_wires):
    replies, sends, google_sends = sdk_wires
    replies["anthropic"] = "For https://example.invalid/source the result is " + json.dumps(VIABLE)
    result = writer.write_tweet(_bundle(), _memory())
    assert result.tweet == TEXT and result.kill_reason is None
    assert len(sends) == 1 and not google_sends


def test_critic_url_hidden_verdict_is_terminal_unavailable_without_repair(sdk_wires):
    replies, anthropic_sends, sends = sdk_wires
    replies["google"] = json.dumps(CRITIC_PASS) + (
        "\nSee https://example.invalid/source for context; revised result: "
    ) + json.dumps(CRITIC_KILL)
    source = _bundle()
    result = critic.critic_review(TEXT, source, _state_with_memory())
    assert not result.passed and result.raw_response == "(json-parse retry exhausted)"
    assert len(sends) == 1 and not anthropic_sends
    captured = capture_critic_rejection(TEXT, source, capture_bundle(source), result, attempt=1)
    assert captured["status"] == "unavailable" and captured["reason"] == "critic_check_unavailable"


@pytest.mark.parametrize("slate", [False, True])
@pytest.mark.parametrize("first,second", [(CRITIC_PASS, CRITIC_KILL), (CRITIC_KILL, CRITIC_PASS),
    (CRITIC_PASS, CRITIC_PASS),
    (dict(verdict="REVISE", kill_reason=None, revise_instruction="Invented revision."), CRITIC_PASS)],
    ids=["pass-first", "kill-first", "identical-pass", "revise-first"])
def test_critic_ambiguity_is_unavailable_without_selection_revision_or_repair(
    sdk_wires, slate, first, second,
):
    replies, anthropic_sends, sends = sdk_wires
    if slate:
        first, second = dict(first, selected_index=0), dict(second, selected_index=0)
    replies["google"] = ambiguous(first, second)
    source, state = _bundle(), _state_with_memory()
    original_source, original_state = deepcopy(source.to_dict()), deepcopy(state)
    result = (critic.critic_select_slate([TEXT], source, state) if slate else
              critic.critic_review(TEXT, source, state, allow_revise=True))
    assert not result.passed and result.verdict == "KILL" and result.selected_index is None
    assert result.revise_instruction is None and len(sends) == 1 and not anthropic_sends
    assert result.raw_response == "(json-parse retry exhausted)"
    captured = capture_critic_rejection(TEXT, source, capture_bundle(source), result, attempt=1)
    assert captured["status"] == "unavailable" and captured["reason"] == "critic_check_unavailable"
    assert "text" not in captured and "bundle" not in captured and "verdict" not in captured
    assert source.to_dict() == original_source and state == original_state
    assert "JSON-output retry" not in json.dumps(sends[0])


def test_safety_ambiguity_is_not_a_completed_verdict_or_cache_entry(sdk_wires):
    replies, anthropic_sends, sends = sdk_wires
    replies["google"] = ambiguous(dict(allowed=True), dict(allowed=False))
    result = safety.check_llm_result(TEXT)
    assert not result.allowed and result.execution_status == "failed" and result.verdict is None
    assert len(sends) == 1 and not anthropic_sends and not safety._SAFETY_CACHE


@pytest.mark.parametrize("stage,send_count", [("safety", 1), ("fact_check", 2), ("critic", 3)])
def test_actual_dispatch_stops_at_ambiguous_required_check_without_saving(
    sdk_wires, monkeypatch, stage, send_count,
):
    replies, writer_sends, check_sends = sdk_wires
    replies["anthropic"] = json.dumps(VIABLE)
    raw = {"safety": ambiguous(dict(allowed=True), dict(allowed=False)),
           "fact_check": ambiguous(FACT_PASS, FACT_FAIL),
           "critic": ambiguous(CRITIC_PASS, CRITIC_KILL)}[stage]

    def response(request):
        if safety.GEMINI_SAFETY_MODEL in request.url.path:
            return raw if stage == "safety" else "NO"
        if fact_check.FACT_CHECKER_MODEL in request.url.path:
            return raw if stage == "fact_check" else json.dumps(FACT_PASS)
        assert critic.CRITIC_MODEL in request.url.path
        return raw

    replies["google"] = response
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    source, state, outcome = _bundle(), _state_with_memory(), {}
    original_source, original_state = deepcopy(source.to_dict()), deepcopy(state)
    assert not _try_two_bot_draft(source, state, _score(category="fire"), legacy_type="fire",
                                 event_id=source.event_id, review_context={}, result_out=outcome)
    assert outcome["kill_stage"] == stage and not outcome.get("cacheable")
    assert len(writer_sends) == 1 and len(check_sends) == send_count
    assert state["drafts"] == original_state["drafts"] and state["memory"] == original_state["memory"]
    assert state.get("publish_ledger") == original_state.get("publish_ledger")
    assert not state.get("writer_negative_cache") and source.to_dict() == original_source
    assert all("JSON-output retry" not in json.dumps(request) for request in check_sends)
    if stage == "fact_check":
        assert outcome["model_diagnostics"][0]["raw_response"] == raw
        assert outcome["rejected_candidate"]["verdict"]["failures"][0].startswith(
            "Fact-check output contract rejected:")
    else:
        assert outcome["rejected_candidate"]["status"] == "unavailable"


@pytest.mark.parametrize("stage,raw", [
    ("safety", ambiguous(dict(allowed=True), dict(allowed=False))),
    ("fact_check", ambiguous(FACT_PASS, FACT_FAIL)),
    ("critic", ambiguous(CRITIC_PASS, CRITIC_KILL)),
])
def test_retained_required_check_parsers_do_not_invent_completed_verdicts(stage, raw):
    saved = packet(dict(candidate=asdict(WriterResult(**VIABLE)), candidate_id="e" * 64,
                        bundle=_bundle().to_dict(), policy=current_editorial_policy()))
    original = deepcopy(saved)
    wire = json.dumps(envelope(raw)).encode("utf-8")
    original_wire = bytes(wire)
    result = check_requests.interpret_observation(saved, stage,
        dict(complete=True, http_status=200), wire)
    assert result["execution_status"] == "error" and result["verdict"] is None
    assert result["result"] == dict(reason="invalid_check_response")
    assert result["usage"] == envelope(raw)["usageMetadata"]
    assert saved == original and wire == original_wire
