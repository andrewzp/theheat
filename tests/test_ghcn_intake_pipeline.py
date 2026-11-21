"""Real source runner, engine and durable metrics, with invented HTTP only."""
from copy import deepcopy

import pytest

from dashboard.tests.fixtures.ghcn_intake_producer import produce
from src.storage.scientific_supply import _outcome


@pytest.mark.parametrize("provider", ["ghcn", "both_global"])
@pytest.mark.parametrize("case,groups", [("mixed", 1), ("empty", 0)])
def test_real_source_engine_forwards_complete_intake_without_eliding_zeros(provider, case, groups):
    state = produce(case, provider)
    [row] = state["run_history"][0]["sources"]
    assert row["source"] == "open_meteo_extreme_signals"
    details = row["details"]
    metrics = details["pipeline_metrics" if provider == "ghcn" else "ghcn_pipeline_metrics"]
    assert metrics["diff_intake"]["counts"]["final_station_days"] == groups
    assert metrics["station_obs_pairs"] == groups
    assert metrics["diff_intake"]["counts"]["future_rows"] == 1
    assert metrics["diff_intake"]["counts"]["inactive_station_rows"] == 1
    assert metrics["threshold_verification"] == "success"
    assert metrics["archive_verification_attempted"] == metrics["archive_verification_verified"] == 1
    original = deepcopy(metrics)
    original.pop("diff_intake")
    assert _outcome(metrics) == _outcome(original), "Diagnostics cannot change the retained scientific outcome contract"
    assert len(state["source_health"][row["source"]]["runs"]) == 1
    assert state["drafts"] == []
