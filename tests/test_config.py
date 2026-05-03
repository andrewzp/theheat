"""Tests for src/config.py — central model defaults and env-var overrides."""

from __future__ import annotations

import importlib

import src.config as config_module


def _reload_config():
    """Reload the config module so re-reads pick up the current env."""
    return importlib.reload(config_module)


def test_cheap_model_default(monkeypatch):
    monkeypatch.delenv("THEHEAT_CHEAP_MODEL", raising=False)
    cfg = _reload_config()
    assert cfg.CHEAP_MODEL == "gemini-2.5-flash"


def test_cheap_model_env_override(monkeypatch):
    monkeypatch.setenv("THEHEAT_CHEAP_MODEL", "gemini-2.5-flash-lite")
    cfg = _reload_config()
    assert cfg.CHEAP_MODEL == "gemini-2.5-flash-lite"


def test_writer_model_default(monkeypatch):
    monkeypatch.delenv("THEHEAT_WRITER_MODEL", raising=False)
    cfg = _reload_config()
    assert cfg.WRITER_MODEL == "claude-sonnet-4-6"


def test_writer_model_env_override(monkeypatch):
    monkeypatch.setenv("THEHEAT_WRITER_MODEL", "claude-opus-4-1")
    cfg = _reload_config()
    assert cfg.WRITER_MODEL == "claude-opus-4-1"


def test_voice_generator_uses_cheap_model_default(monkeypatch):
    """Voice generator must default to the central CHEAP_MODEL,
    not the prior 'gemini-flash-latest' alias that caused the
    2026-05-02 timeout incident."""
    monkeypatch.delenv("THEHEAT_CHEAP_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    _reload_config()
    import src.voice.generator as gen
    importlib.reload(gen)
    assert gen.GEMINI_MODEL == "gemini-2.5-flash"
    # Retry budget tightened to 1 in the same incident response.
    assert gen.MAX_RETRIES == 1


def test_two_bot_callers_use_central_defaults(monkeypatch):
    """fact_check, claim_extractor, and writer should all read
    defaults from src/config.py — historically each hardcoded its
    own and the inconsistency hid the bug for weeks."""
    monkeypatch.delenv("THEHEAT_CHEAP_MODEL", raising=False)
    monkeypatch.delenv("THEHEAT_WRITER_MODEL", raising=False)
    monkeypatch.delenv("THEHEAT_FACT_CHECK_MODEL", raising=False)
    monkeypatch.delenv("THEHEAT_CLAIM_EXTRACT_MODEL", raising=False)
    _reload_config()
    import src.two_bot.fact_check as fc
    import src.two_bot.claim_extractor as ce
    import src.two_bot.writer as wr
    importlib.reload(fc)
    importlib.reload(ce)
    importlib.reload(wr)
    assert fc.FACT_CHECKER_MODEL == "gemini-2.5-flash"
    assert ce.CLAIM_EXTRACT_MODEL == "gemini-2.5-flash"
    assert wr.WRITER_MODEL == "claude-sonnet-4-6"
