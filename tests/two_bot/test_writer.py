import importlib

import pytest

from src.two_bot.writer import write_fire_tweet

from tests.two_bot.conftest import (
    _bundle,
    _fake_writer_response,
    _fake_writer_response_raw,
    _memory,
)


def test_write_fire_tweet_returns_tweet(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "Mali fire test",
            "kill_reason": None,
            "angle_chosen": "rarity",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "test",
        }
    )

    result = write_fire_tweet(_bundle(), _memory())

    assert result.tweet == "Mali fire test"
    assert result.kill_reason is None
    assert mock_anthropic.called


def test_write_fire_tweet_returns_kill(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": None,
            "kill_reason": "no historical_context available",
            "angle_chosen": "",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "test",
        }
    )

    result = write_fire_tweet(_bundle(), _memory())

    assert result.tweet is None
    assert result.kill_reason


def test_write_fire_tweet_raises_on_both_tweet_and_kill_set(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response(
        {
            "tweet": "x",
            "kill_reason": "y",
            "angle_chosen": "x",
            "era_anchor_used": None,
            "peer_comparison_used": None,
            "reasoning": "x",
        }
    )

    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())


def test_write_fire_tweet_raises_on_invalid_json(mock_anthropic):
    mock_anthropic.return_value = _fake_writer_response_raw("not json")

    with pytest.raises(ValueError):
        write_fire_tweet(_bundle(), _memory())


def test_write_fire_tweet_raises_on_missing_api_key(monkeypatch):
    from src.two_bot import writer

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(writer, "_call_anthropic", writer._call_anthropic)

    with pytest.raises(RuntimeError):
        write_fire_tweet(_bundle(), _memory())


def test_writer_provider_resolved_at_import(monkeypatch):
    import src.two_bot.writer as writer_module

    monkeypatch.setenv("THEHEAT_WRITER_MODEL", "totally-fake-model")
    with pytest.raises(RuntimeError):
        importlib.reload(writer_module)

    monkeypatch.delenv("THEHEAT_WRITER_MODEL", raising=False)
    importlib.reload(writer_module)

