"""An explicit unsupported consequence survives unrelated malformed soft details.

All content/verdicts are invented. SDK-shaped fixtures exercise the existing
critic transport/parser without calling a model or any external service.
"""
from __future__ import annotations

import json

import pytest

from src.two_bot import critic
from src.two_bot.types import StoryBundle
from tests import live_content_harness as h


UNSUPPORTED = {
    "focus": "single", "repetition": "none", "jargon": "plain",
    "length": "ok", "consequence": "unsupported",
}
MALFORMED_UNSUPPORTED = [
    pytest.param({**UNSUPPORTED, "length": "short"}, id="unknown-soft-value"),
    pytest.param({key: value for key, value in UNSUPPORTED.items() if key != "focus"}, id="missing-soft-key"),
    pytest.param({**UNSUPPORTED, "extra": "invented"}, id="extra-soft-key"),
]


def _body(legacy: bool, quality) -> dict:
    envelope = {"passed": True} if legacy else {"verdict": "PASS", "selected_index": None}
    return {**envelope, "kill_reason": None, "quality": quality, "quality_note": None}


def _assert_unsupported(result, raw: str) -> None:
    assert result.passed is False and result.verdict == "KILL"
    assert result.kill_reason.startswith("unsupported_claim:")
    assert result.raw_response == raw


@pytest.mark.parametrize("legacy", [False, True], ids=["verdict", "legacy-passed"])
@pytest.mark.parametrize("quality", MALFORMED_UNSUPPORTED)
def test_raw_unsupported_survives_malformed_unrelated_soft_details(legacy, quality):
    raw = json.dumps(_body(legacy, quality))
    result = critic._parse_critic_result(raw)
    _assert_unsupported(result, raw)
    assert result.quality is None  # Malformed optional display details still drop.


@pytest.mark.parametrize("quality", [UNSUPPORTED, {"consequence": "unsupported"}])
def test_legacy_pass_cannot_bypass_an_explicit_unsupported_consequence(quality):
    raw = json.dumps(_body(True, quality))
    _assert_unsupported(critic._parse_critic_result(raw), raw)
    passed, reason = critic._parse_critic_json(raw)
    assert passed is False and reason is not None and reason.startswith("unsupported_claim:")


@pytest.mark.parametrize("legacy", [False, True], ids=["verdict", "legacy-passed"])
@pytest.mark.parametrize("quality", [
    {**UNSUPPORTED, "length": "short", "consequence": "none"},
    {"focus": "single"},
    "unsupported",
])
def test_harmless_malformed_optional_details_do_not_change_a_pass(legacy, quality):
    raw = json.dumps(_body(legacy, quality))
    result = critic._parse_critic_result(raw)
    assert result.passed is True and result.verdict == "PASS" and result.kill_reason is None
    assert result.raw_response == raw and result.quality is None


@pytest.mark.parametrize("envelope", [{"passed": True}, {"verdict": "PASS"}])
def test_existing_no_detail_pass_serialization_is_unchanged(envelope):
    raw = json.dumps({**envelope, "kill_reason": None})
    assert critic._parse_critic_result(raw).to_dict() == {
        "passed": True, "kill_reason": None, "raw_response": raw,
        "verdict": "PASS", "revise_instruction": None,
    }


@pytest.mark.parametrize("legacy", [False, True], ids=["verdict", "legacy-passed"])
def test_unsupported_detail_never_replaces_or_upgrades_an_existing_kill(legacy):
    body = _body(legacy, {**UNSUPPORTED, "length": "short"})
    body.update({"passed": False} if legacy else {"verdict": "KILL"})
    body["kill_reason"] = "missing_qualifier: invented existing refusal"
    result = critic._parse_critic_result(json.dumps(body))
    assert result.passed is False and result.verdict == "KILL"
    assert result.kill_reason == body["kill_reason"]


@pytest.mark.parametrize("body,reason", [
    ({"passed": "yes", "quality": UNSUPPORTED}, "boolean passed"),
    ({"verdict": "PASS", "selected_index": "0", "quality": UNSUPPORTED}, "selected_index"),
    ({"verdict": "KILL", "quality": UNSUPPORTED}, "must include kill_reason"),
])
def test_unsupported_detail_does_not_bypass_verdict_schema(body, reason):
    with pytest.raises(ValueError, match=reason):
        critic._parse_critic_result(json.dumps(body))


def _bundle() -> StoryBundle:
    return StoryBundle(
        signal_kind="anomaly_hot", where="Port Example", when="2026-10-30",
        event_id="invented-critic-raw-consequence",
        headline_metric={"label": "forecast_high_c", "value": 47, "unit": "C"},
        current_facts=[], historical_context={}, raw_signal_dump={},
    )


@pytest.mark.parametrize("legacy", [False, True], ids=["verdict", "legacy-passed"])
@pytest.mark.parametrize("quality", MALFORMED_UNSUPPORTED)
def test_sdk_shaped_review_refuses_on_the_first_existing_critic_call(monkeypatch, legacy, quality):
    body = _body(legacy, quality)
    script = h.ModelScript(critic=body)
    script.install(monkeypatch.setattr)
    monkeypatch.setenv("GEMINI_API_KEY", h.INVENTED_TOKEN)
    result = critic.critic_review(
        "Port Example's forecast high is 47°C.", _bundle(),
        {"drafts": [], "memory": {"shipped_tweets": []}}, shipped_recent=[],
    )
    _assert_unsupported(result, json.dumps(body))
    assert script.stages() == ["critic"]  # No parse retry, rewrite or additional model stage.


def test_sdk_shaped_slate_pass_with_bad_soft_length_is_not_selected(monkeypatch):
    body = _body(False, {**UNSUPPORTED, "length": "short"})
    body["selected_index"] = 0
    script = h.ModelScript(critic=body)
    script.install(monkeypatch.setattr)
    monkeypatch.setenv("GEMINI_API_KEY", h.INVENTED_TOKEN)
    result = critic.critic_select_slate(
        ["Port Example's forecast high is 47°C."], _bundle(),
        {"drafts": [], "memory": {"shipped_tweets": []}}, shipped_recent=[],
    )
    _assert_unsupported(result, json.dumps(body))
    assert result.selected_index is None and script.stages() == ["critic"]
