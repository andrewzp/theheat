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


def _agg(calls=1, in_=100, cached=0, cw=0, out=10, usd=0.001):
    return {"calls": calls, "in": in_, "cached_in": cached,
            "cache_write": cw, "out": out, "usd": usd}


def test_merge_enforces_retention_so_pruned_days_stay_pruned():
    """codex r1 P1: a plain overlay merge resurrected drain-pruned days on
    every write (45 → 46). The dedicated merge strategy caps at retention."""
    from src.state import _merge_llm_usage

    base = {f"2026-01-{d:02d}": {"writer|m": _agg()} for d in range(1, 32)}
    base.update({f"2026-02-{d:02d}": {"writer|m": _agg()} for d in range(1, 21)})
    assert len(base) == 51
    # Incoming snapshot pruned to newest 45 (as drain produces).
    incoming = {day: base[day] for day in sorted(base)[-45:]}

    merged = _merge_llm_usage(base, incoming)

    assert len(merged) == usage_ledger.LLM_USAGE_RETENTION_DAYS
    assert "2026-01-01" not in merged, "the oldest day stays pruned after merge"
    assert "2026-02-20" in merged


def test_merge_stale_overlay_cannot_roll_a_day_backwards():
    """codex r1 P1: reject-all-drafts (own concurrency group) can write from
    a stale read. Element-wise max keeps the larger, newer counters."""
    from src.state import _merge_llm_usage

    newer = {"2026-07-14": {"writer|claude-sonnet-4-6": _agg(calls=15, in_=1500, usd=0.09)}}
    stale = {"2026-07-14": {"writer|claude-sonnet-4-6": _agg(calls=10, in_=1000, usd=0.06)}}

    merged = _merge_llm_usage(newer, stale)
    agg = merged["2026-07-14"]["writer|claude-sonnet-4-6"]
    assert agg["calls"] == 15
    assert agg["in"] == 1500
    assert agg["usd"] == 0.09

    # Disjoint stage-model keys union across sides.
    other = {"2026-07-14": {"critic|gemini-2.5-pro": _agg(calls=3)}}
    merged = _merge_llm_usage(newer, other)
    assert set(merged["2026-07-14"]) == {"writer|claude-sonnet-4-6", "critic|gemini-2.5-pro"}


def test_merge_tolerates_corrupt_shapes():
    from src.state import _merge_llm_usage

    merged = _merge_llm_usage(None, {"2026-07-14": {"writer|m": _agg()}})
    assert merged["2026-07-14"]["writer|m"]["calls"] == 1
    merged = _merge_llm_usage({"2026-07-14": "junk"}, {"2026-07-14": {"writer|m": _agg()}})
    assert merged["2026-07-14"]["writer|m"]["calls"] == 1
    merged = _merge_llm_usage({"2026-07-14": {"writer|m": "junk"}}, {})
    assert merged["2026-07-14"]["writer|m"]["calls"] == 0


def test_drain_resets_corrupted_llm_usage_instead_of_losing_rows():
    """codex r1 P1: a corrupted gist value (None / list / str) must neither
    crash the drain nor swallow the buffered rows nor poison write_state."""
    for corrupt in (None, ["junk"], "junk", 7):
        usage_ledger._BUFFER.clear()
        usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=100)
        state: dict = {"llm_usage": corrupt}
        drained = usage_ledger.drain_into_state(state)
        assert drained == 1, f"rows lost for corrupt value {corrupt!r}"
        assert isinstance(state["llm_usage"], dict)
        day = next(iter(state["llm_usage"]))
        assert state["llm_usage"][day]["writer|claude-sonnet-4-6"]["calls"] == 1

    # Corrupted inner day bucket repairs too.
    usage_ledger._BUFFER.clear()
    usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=100)
    import datetime as _dt

    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    state = {"llm_usage": {today: "notadict"}}
    assert usage_ledger.drain_into_state(state) == 1
    assert state["llm_usage"][today]["writer|claude-sonnet-4-6"]["calls"] == 1


def test_drain_rebuffers_rows_on_fold_failure():
    """codex r1 P1: the buffer is the only copy — an unexpected fold failure
    must put the rows back for a later drain, not destroy them."""
    usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=100)
    # None has no __setitem__: the defensive reset raises, hitting the
    # re-buffer path.
    assert usage_ledger.drain_into_state(None) == 0
    assert len(usage_ledger._BUFFER) == 1, "rows must be re-buffered"

    state: dict = {}
    assert usage_ledger.drain_into_state(state) == 1, "later drain persists them"


def test_price_prefix_is_boundary_aware():
    """codex r1 P2: claude-sonnet-4-60 is NOT Sonnet 4.6."""
    assert usage_ledger.estimate_usd("claude-sonnet-4-60", input_tokens=1_000_000) == 0.0
    assert usage_ledger.estimate_usd(
        "claude-sonnet-4-6-20250929", input_tokens=1_000_000
    ) == pytest.approx(3.00)
    assert usage_ledger.estimate_usd(
        "claude-sonnet-4-6", input_tokens=1_000_000
    ) == pytest.approx(3.00)


def test_negative_and_absurd_tokens_are_clamped():
    """codex r1 P2: negative → 0; huge → finite (Infinity is not strict JSON)."""
    assert usage_ledger.estimate_usd("claude-sonnet-4-6", input_tokens=-500) == 0.0
    huge = usage_ledger.estimate_usd("claude-sonnet-4-6", input_tokens=10**30)
    import math

    assert math.isfinite(huge)

    usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=-500)
    state: dict = {}
    usage_ledger.drain_into_state(state)
    day = next(iter(state["llm_usage"]))
    agg = state["llm_usage"][day]["writer|claude-sonnet-4-6"]
    assert agg["in"] == 0
    assert agg["usd"] == 0.0


def test_raising_usage_property_never_breaks_the_call(monkeypatch):
    """codex r1 P2: usage extraction sits inside the fail-open boundary."""
    import anthropic
    from anthropic.types import TextBlock

    class _Resp:
        content = [TextBlock(type="text", text='{"tweet": null}')]

        @property
        def usage(self):
            raise RuntimeError("usage property exploded")

    class _FakeMessages:
        def create(self, **kwargs):
            return _Resp()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    from src.two_bot.writer import _call_anthropic

    raw = _call_anthropic("user prompt")
    assert "tweet" in raw, "the paid call's result must survive accounting failure"


def test_write_state_drains_structurally(monkeypatch):
    """codex r1 P1: the drain is owned by write_state, so every state-writing
    process persists its spend without a call-site dependency."""
    import src.state as state_mod

    usage_ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=100)
    # Force the sqlite backend with no DB_PATH: write_state returns False
    # early, but the drain must already have folded into the passed dict.
    monkeypatch.setattr(state_mod, "_configured_backend", lambda: "sqlite")
    monkeypatch.setattr(state_mod, "DB_PATH", "")

    from copy import deepcopy

    bot_state = deepcopy(state_mod.DEFAULT_STATE)
    assert state_mod.write_state(bot_state) is False
    assert len(usage_ledger._BUFFER) == 0, "buffer drained by write_state"
    day = next(iter(bot_state["llm_usage"]))
    assert bot_state["llm_usage"][day]["writer|claude-sonnet-4-6"]["calls"] == 1


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
