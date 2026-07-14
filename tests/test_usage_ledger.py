"""Economics P0.6 — per-call LLM usage ledger MVP."""

from __future__ import annotations

import threading

import pytest

from src.two_bot import usage_ledger


@pytest.fixture(autouse=True)
def _clean_buffer():
    usage_ledger._BUFFER.clear()
    yield
    usage_ledger._BUFFER.clear()


def test_record_and_drain_aggregates_per_day_stage_model():
    usage_ledger.record_usage(
        "writer", "claude-sonnet-4-6",
        input_tokens=1000, output_tokens=200,
        cache_write_tokens=15000, cache_read_tokens=0,
    )
    usage_ledger.record_usage(
        "writer", "claude-sonnet-4-6",
        input_tokens=1000, output_tokens=300,
        cache_write_tokens=0, cache_read_tokens=15000,
    )
    state: dict = {}
    drained = usage_ledger.drain_into_state(state)

    assert drained == 2
    days = list(state["llm_usage"].keys())
    assert len(days) == 1
    agg = state["llm_usage"][days[0]]["writer|claude-sonnet-4-6"]
    assert agg["calls"] == 2
    assert agg["in"] == 2000
    assert agg["cache_write"] == 15000
    assert agg["cached_in"] == 15000
    assert agg["out"] == 500
    assert agg["usd"] > 0


def test_sonnet_pricing_math_exact():
    # 1M input @ $3 + 1M output @ $15 + 1M cache-write @ $3.75 + 1M read @ $0.30
    usd = usage_ledger.estimate_usd(
        "claude-sonnet-4-6",
        input_tokens=1_000_000, output_tokens=1_000_000,
        cache_write_tokens=1_000_000, cache_read_tokens=1_000_000,
    )
    assert usd == pytest.approx(3.00 + 15.00 + 3.75 + 0.30)


def test_unknown_model_records_tokens_with_zero_usd():
    usage_ledger.record_usage("writer", "some-future-model", input_tokens=500)
    state: dict = {}
    usage_ledger.drain_into_state(state)
    day = next(iter(state["llm_usage"]))
    agg = state["llm_usage"][day]["writer|some-future-model"]
    assert agg["in"] == 500
    assert agg["usd"] == 0.0


def test_drain_prunes_to_retention_window():
    state: dict = {"llm_usage": {
        f"2026-01-{day:02d}": {"writer|m": {"calls": 1, "in": 1, "cached_in": 0,
                                            "cache_write": 0, "out": 1, "usd": 0.0}}
        for day in range(1, 32)
    }}
    # Add 20 more synthetic days so total (51) exceeds the 45-day window.
    for day in range(1, 21):
        state["llm_usage"][f"2026-02-{day:02d}"] = {
            "writer|m": {"calls": 1, "in": 1, "cached_in": 0,
                         "cache_write": 0, "out": 1, "usd": 0.0},
        }
    usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=1)
    usage_ledger.drain_into_state(state)

    assert len(state["llm_usage"]) == usage_ledger.LLM_USAGE_RETENTION_DAYS
    # Oldest days pruned first; today's row survives.
    assert "2026-01-01" not in state["llm_usage"]
    assert any("claude-sonnet-4-6" in k for day in state["llm_usage"].values() for k in day)


def test_empty_drain_returns_zero_and_touches_nothing():
    state: dict = {}
    assert usage_ledger.drain_into_state(state) == 0
    assert "llm_usage" not in state


def test_buffer_cap_bounds_undrained_paths():
    for i in range(usage_ledger._BUFFER_CAP + 50):
        usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=i)
    assert len(usage_ledger._BUFFER) == usage_ledger._BUFFER_CAP


def test_record_is_thread_safe():
    def hammer():
        for _ in range(25):
            usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=1)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    state: dict = {}
    assert usage_ledger.drain_into_state(state) == 200
    day = next(iter(state["llm_usage"]))
    assert state["llm_usage"][day]["writer|claude-sonnet-4-6"]["calls"] == 200


def test_writer_anthropic_call_records_usage(monkeypatch):
    """_call_anthropic feeds the ledger from response.usage."""
    import anthropic
    from anthropic.types import TextBlock

    class _Usage:
        input_tokens = 111
        output_tokens = 22
        cache_creation_input_tokens = 15000
        cache_read_input_tokens = 0

    class _FakeMessages:
        def create(self, **kwargs):
            class _Resp:
                content = [TextBlock(type="text", text='{"tweet": null}')]
                usage = _Usage()

            return _Resp()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    from src.two_bot.writer import _call_anthropic

    _call_anthropic("user prompt")

    state: dict = {}
    assert usage_ledger.drain_into_state(state) == 1
    day = next(iter(state["llm_usage"]))
    agg = next(iter(state["llm_usage"][day].values()))
    assert agg["in"] == 111
    assert agg["cache_write"] == 15000
