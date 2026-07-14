"""Economics P1.1 — monthly budget watch over the usage ledger."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.orchestrator import budget

NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


def _state(mtd_usd_per_day: float, days: int = 7) -> dict:
    return {
        "llm_usage": {
            f"2026-07-{d:02d}": {
                "writer|claude-sonnet-4-6": {
                    "calls": 10, "in": 1000, "cached_in": 0,
                    "cache_write": 0, "out": 100, "usd": mtd_usd_per_day,
                },
            }
            for d in range(1, days + 1)
        },
    }


def test_month_to_date_sums_only_current_month():
    state = _state(1.0, days=7)
    state["llm_usage"]["2026-06-30"] = {
        "writer|claude-sonnet-4-6": {"calls": 1, "in": 1, "cached_in": 0,
                                     "cache_write": 0, "out": 1, "usd": 99.0},
    }
    assert budget.month_to_date_usd(state, now=NOW) == pytest.approx(7.0)


def test_month_to_date_tolerates_corruption():
    assert budget.month_to_date_usd({}, now=NOW) == 0.0
    assert budget.month_to_date_usd({"llm_usage": None}, now=NOW) == 0.0
    assert budget.month_to_date_usd({"llm_usage": {"2026-07-01": "junk"}}, now=NOW) == 0.0
    assert budget.month_to_date_usd(
        {"llm_usage": {"2026-07-01": {"writer|m": {"usd": "junk"}}}}, now=NOW
    ) == 0.0


def test_budget_default_and_override(monkeypatch):
    monkeypatch.delenv("THEHEAT_MONTHLY_BUDGET_USD", raising=False)
    assert budget.monthly_budget_usd() == 14.0
    monkeypatch.setenv("THEHEAT_MONTHLY_BUDGET_USD", "20")
    assert budget.monthly_budget_usd() == 20.0
    monkeypatch.setenv("THEHEAT_MONTHLY_BUDGET_USD", "-5")
    assert budget.monthly_budget_usd() == 14.0
    monkeypatch.setenv("THEHEAT_MONTHLY_BUDGET_USD", "junk")
    assert budget.monthly_budget_usd() == 14.0


def test_levels_at_exact_70_and_90_boundaries(monkeypatch):
    """codex P2: pin the EXACT >= boundaries — a >=→> regression must fail.
    $14 budget: 70% = $9.80, 90% = $12.60."""
    monkeypatch.delenv("THEHEAT_MONTHLY_BUDGET_USD", raising=False)
    assert budget.budget_status(_state(1.0, days=7), now=NOW)["level"] == "ok"
    just_under_70 = _state(9.79 / 7, days=7)
    assert budget.budget_status(just_under_70, now=NOW)["level"] == "ok"
    exactly_70 = _state(9.80 / 7, days=7)
    assert budget.budget_status(exactly_70, now=NOW)["level"] == "warn_70"
    just_under_90 = _state(12.59 / 7, days=7)
    assert budget.budget_status(just_under_90, now=NOW)["level"] == "warn_70"
    exactly_90 = _state(12.60 / 7, days=7)
    assert budget.budget_status(exactly_90, now=NOW)["level"] == "alarm_90"


def test_month_sum_rejects_junk_day_keys_and_overflow():
    """codex P1+P2: shape-junk keys and absurd usd values must neither
    pollute the sum nor raise."""
    state = _state(1.0, days=7)
    state["llm_usage"]["2026-07-zz"] = {"writer|m": {"usd": 99.0}}
    state["llm_usage"]["9999-99-00"] = {"writer|m": {"usd": 99.0}}
    state["llm_usage"]["2026-07-08"] = {"writer|m": {"usd": 10**400}}  # float() overflows
    assert budget.month_to_date_usd(state, now=NOW) == pytest.approx(7.0)


def test_record_budget_health_survives_status_explosion(monkeypatch):
    """codex P1: the status computation itself is fail-open — a raising
    state object must not abort the CLI before write_state."""
    class _Bomb:
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    status = budget.record_budget_health(_Bomb(), now=NOW)
    assert status["level"] == "ok"
    assert status["mtd_usd"] == 0.0


def test_projection_is_straight_line():
    # $7 by day 14 of a 31-day month → ~$15.50 projected.
    status = budget.budget_status(_state(1.0, days=7), now=NOW)
    assert status["projected_usd"] == pytest.approx(7.0 / 14 * 31, abs=0.01)


def test_record_budget_health_maps_levels_to_source_health(monkeypatch):
    monkeypatch.delenv("THEHEAT_MONTHLY_BUDGET_USD", raising=False)
    calls: list = []

    def fake_record(state, source, status, error=None, **kwargs):
        calls.append((source, status, error))

    monkeypatch.setattr("src.state.record_source_health", fake_record)

    budget.record_budget_health(_state(1.0, days=7), now=NOW)
    budget.record_budget_health(_state(1.5, days=7), now=NOW)
    budget.record_budget_health(_state(2.0, days=7), now=NOW)

    assert [c[1] for c in calls] == ["success", "degraded", "failed"]
    assert all(c[0] == "budget" for c in calls)
    assert calls[1][2] is not None and "MTD" in calls[1][2]
    assert calls[2][2] is not None and "projected" in calls[2][2]


def test_record_budget_health_never_raises(monkeypatch):
    def exploding_record(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.state.record_source_health", exploding_record)
    status = budget.record_budget_health(_state(1.0), now=NOW)
    assert status["level"] == "ok", "the status still returns despite the sink failing"
