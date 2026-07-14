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

def test_two_bot_callers_use_central_defaults(monkeypatch):
    """fact_check and writer should both read defaults from src/config.py —
    historically each hardcoded its own and the inconsistency hid the bug for
    weeks."""
    monkeypatch.delenv("THEHEAT_CHEAP_MODEL", raising=False)
    monkeypatch.delenv("THEHEAT_WRITER_MODEL", raising=False)
    monkeypatch.delenv("THEHEAT_FACT_CHECK_MODEL", raising=False)
    _reload_config()
    import src.two_bot.fact_check as fc
    import src.two_bot.writer as wr
    importlib.reload(fc)
    importlib.reload(wr)
    assert fc.FACT_CHECKER_MODEL == "gemini-2.5-flash"
    assert wr.WRITER_MODEL == "claude-sonnet-4-6"
