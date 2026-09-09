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
    assert budget.month_to_date_usd({}, now=NOW) is None
    assert budget.month_to_date_usd({"llm_usage": None}, now=NOW) is None
    assert budget.month_to_date_usd({"llm_usage": {"2026-07-01": "junk"}}, now=NOW) is None
    assert budget.month_to_date_usd(
        {"llm_usage": {"2026-07-01": {"writer|m": {"usd": "junk"}}}}, now=NOW
    ) is None


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
    """codex P2 (r2): pin the EXACT >= boundaries with float-identical
    ratios — a >=→> regression must fail. Budget $16 (a power of two) makes
    16*0.7/16 recover the literal 0.7 double exactly, so pct == WARN_PCT
    precisely at the boundary (with $14, 9.80/14 lands a ULP above 0.70 and
    a > regression would sneak through)."""
    monkeypatch.setenv("THEHEAT_MONTHLY_BUDGET_USD", "16")
    assert (16 * 0.7) / 16 == 0.7 and (16 * 0.9) / 16 == 0.9  # test precondition
    assert budget.budget_status(_state(11.2, days=1), now=NOW)["level"] == "warn_70"
    assert budget.budget_status(_state(14.4, days=1), now=NOW)["level"] == "alarm_90"
    # A hair under each boundary stays at the lower level.
    assert budget.budget_status(_state(11.19, days=1), now=NOW)["level"] == "coverage_incomplete"
    assert budget.budget_status(_state(14.39, days=1), now=NOW)["level"] == "warn_70"


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
    assert status["level"] == "coverage_incomplete"
    assert status["mtd_usd"] is None


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

    assert [c[1] for c in calls] == ["skipped", "degraded", "failed"]
    assert all(c[0] == "budget" for c in calls)
    assert calls[1][2] is not None and "MTD" in calls[1][2]
    assert calls[2][2] is not None and "projected" in calls[2][2]


def test_record_budget_health_never_raises(monkeypatch):
    def exploding_record(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.state.record_source_health", exploding_record)
    status = budget.record_budget_health(_state(1.0), now=NOW)
    assert status["level"] == "coverage_incomplete", "the status still returns despite the sink failing"


def test_expected_partial_accounting_does_not_reopen_prior_alarm_incident():
    from datetime import timedelta
    from src import state as state_module
    from scripts.source_health_sentinel import classify_source, plan_issue_actions, run_sentinel
    from tests.test_usage_coverage import node

    current = datetime.now(timezone.utc)
    snapshot = {}
    state_module.record_source_health(snapshot, "budget", "failed", "Previous real threshold alarm",
                                      timestamp=current-timedelta(hours=6))
    alarm = snapshot["source_health"]["budget"]["runs"][0].copy()
    for _ in range(5):
        result = budget.record_budget_health(snapshot, now=current)
        health = snapshot["source_health"]["budget"]
        assert result["level"] == "coverage_incomplete" and result["mtd_usd"] is None
        assert classify_source("budget", health, now=current)["category"] == "idle"
    report = run_sentinel(snapshot["source_health"], now=current)
    unknown = {v["source"] for v in report["healthy"] if v.get("issue_resolution_unknown")}
    assert unknown == {"budget"}
    assert plan_issue_actions({}, {"budget": 123}, resolution_unknown=unknown) == []
    assert plan_issue_actions({}, {}, resolution_unknown=unknown) == []
    assert health["runs"][0] == alarm and health["failed"] == 1
    assert all(row["status"] == "skipped" and row["error_class"] == "accounting_coverage" for row in health["runs"][1:])
    dashboard = node('''
      import {readFileSync} from "node:fs";
      import {buildSourceHealthPayload} from "./dashboard/lib/source-health.js";
      console.log(JSON.stringify(buildSourceHealthPayload(JSON.parse(readFileSync(0,"utf8"))).sources));
    ''', snapshot)
    assert dashboard[0]["health"] == "idle"
    assert "accounting unavailable" in dashboard[0]["accounting_note"]
    # A NEW actual threshold alarm still uses the existing incident path.
    snapshot["llm_usage"] = {current.date().isoformat(): {"writer|old": {"calls": 1, "usd": 20}}}
    assert budget.record_budget_health(snapshot, now=current)["level"] == "alarm_90"
    assert classify_source("budget", snapshot["source_health"]["budget"], now=current)["category"] == "failing"
