from itertools import product

import pytest

from src.two_bot.provider_preflight import provider_preflight, current_provider_preflight
from src.two_bot import pipeline
from tests.two_bot.conftest import _bundle


@pytest.mark.parametrize("anthropic,google,safety,critic", list(product((False, True), repeat=4)))
@pytest.mark.parametrize("provider", ["anthropic", "google", "unsupported_openai"])
def test_preflight_routes_and_mandatory_checks(anthropic, google, safety, critic, provider):
    result = provider_preflight(
        writer_provider=provider,
        anthropic_configured=anthropic,
        google_configured=google,
        loaded_safety_configured=safety,
        critic_enabled=critic,
    )
    ready = (
        provider in {"anthropic", "google"}
        and google
        and safety
        and (anthropic or provider == "google")
    )
    assert (result["status"] == "configured_unverified") is ready
    stages = {row["stage"] for row in result["blocked_stages"]}
    assert ("critic" in stages) is (critic and not google)
    assert result["funding_verified"] is result["provider_access_verified"] is False


@pytest.mark.parametrize("value", [1, 0, None, "true", [], {}])
def test_preflight_does_not_coerce_availability(value):
    with pytest.raises(ValueError):
        provider_preflight(
            writer_provider="anthropic",
            anthropic_configured=value,
            google_configured=True,
            loaded_safety_configured=True,
            critic_enabled=True,
        )


@pytest.mark.parametrize("missing", ["writer", "google", "loaded_safety", "unsupported"])
def test_pipeline_blocks_before_any_writer_memory_or_checker_work(
    monkeypatch, missing
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-configured")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-configured")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "offline-configured")
    monkeypatch.setattr(pipeline.writer, "WRITER_PROVIDER", "anthropic")
    if missing == "writer":
        monkeypatch.delenv("ANTHROPIC_API_KEY")
    elif missing == "google":
        monkeypatch.delenv("GEMINI_API_KEY")
    elif missing == "loaded_safety":
        monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "")
    else:
        monkeypatch.setattr(pipeline.writer, "WRITER_PROVIDER", "unsupported_openai")

    def forbidden(*args, **kwargs):
        pytest.fail("Known-blocked pipeline reached paid or preparatory work")

    monkeypatch.setattr(pipeline.writer, "write_tweet", forbidden)
    monkeypatch.setattr(pipeline.memory, "build_memory_slice", forbidden)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", forbidden)
    monkeypatch.setattr(pipeline.critic, "critic_review", forbidden)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", forbidden)
    telemetry = {"stage_outcomes": {"writer": "pass"}, "cacheable": True, "kill_scope": "evidence"}
    assert pipeline.generate_draft(_bundle(), {}, result_out=telemetry) is None
    assert telemetry["kill_stage"] == "provider_preflight"
    assert telemetry["stage_outcomes"] == {"provider_preflight": "kill"}
    assert "cacheable" not in telemetry and "kill_scope" not in telemetry
    assert "offline-configured" not in str(telemetry)


def test_environment_presence_does_not_replace_missing_loaded_safety_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured")
    monkeypatch.setenv("GEMINI_API_KEY", "configured")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "")
    assert {
        r["stage"] for r in current_provider_preflight(critic_enabled=True)["blocked_stages"]
    } == {"safety"}
