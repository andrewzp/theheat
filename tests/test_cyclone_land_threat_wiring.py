"""Orchestrator wiring tests for the cyclone land-threat signal (#375)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from src.data import jtwc
from src.data.cyclones import CycloneAdvisory, ForecastPoint
from src.orchestrator.cyclones import _process_cyclone_source
from src.state import DEFAULT_STATE

_TAIPEI = [{"city": "Taipei", "country": "Taiwan", "lat": "25.03", "lon": "121.57", "elevation_m": "9"}]


def _bavi_advisory() -> CycloneAdvisory:
    now = datetime.now(UTC)
    return CycloneAdvisory(
        source="jtwc", storm_id="05W", storm_name="Bavi", basin="WP",
        advisory_number="024", issued_at=now.isoformat(), wind_kt=135,
        lat=21.8, lon=126.9,
        forecast_points=(
            ForecastPoint(valid_at="081200Z", lat=25.4, lon=121.6,
                          max_wind_kt=95, tau_h=48),
        ),
    )


def _fresh_state() -> dict:
    s = deepcopy(DEFAULT_STATE)
    # Pre-record the storm's current tier so detect_tier_crossings stays
    # quiet and the ONLY candidate is the land threat.
    s["cyclone_tiers"] = {"jtwc:05w": 4}
    return s


def _run(monkeypatch, bot_state, enqueue_returns=True):
    captured: list[dict] = []

    def _fake_enqueue(bs, **kwargs):
        captured.append(kwargs)
        if enqueue_returns and kwargs.get("on_draft_success"):
            kwargs["on_draft_success"]()
        return enqueue_returns

    monkeypatch.setattr(
        "src.orchestrator.common._enqueue_story_candidate", _fake_enqueue
    )
    monkeypatch.setattr(
        "src.orchestrator.cyclones.load_cities", lambda *a, **k: _TAIPEI
    )
    _process_cyclone_source(
        bot_state,
        {"sources": []},
        source_key="jtwc",
        source_label="JTWC",
        fetch_fn=lambda: [_bavi_advisory()],
        detect_module=jtwc,
    )
    return captured


def test_land_threat_enqueues_exactly_one_candidate(monkeypatch):
    bot_state = _fresh_state()
    captured = _run(monkeypatch, bot_state, enqueue_returns=True)

    lt = [c for c in captured if c.get("legacy_type") == "cyclone_land_threat"]
    assert len(lt) == 1
    kwargs = lt[0]
    # Attribution: the SAME source_key this pass uses for RI/tier/landfall.
    assert kwargs["source"] == "jtwc"
    assert kwargs["review_context"]["source_key"] == "jtwc"
    assert kwargs["bundle"].signal_kind == "cyclone_land_threat"
    # Success path recorded the pair.
    assert bot_state["cyclone_land_threat_pairs"]["jtwc:05w"] == ["taiwan"]


def test_land_threat_pair_not_recorded_without_success(monkeypatch):
    bot_state = _fresh_state()
    captured = _run(monkeypatch, bot_state, enqueue_returns=False)

    assert any(c.get("legacy_type") == "cyclone_land_threat" for c in captured)
    assert bot_state.get("cyclone_land_threat_pairs", {}) == {}


def test_land_threat_respects_recorded_pair(monkeypatch):
    bot_state = _fresh_state()
    bot_state["cyclone_land_threat_pairs"] = {"jtwc:05w": ["taiwan"]}
    captured = _run(monkeypatch, bot_state, enqueue_returns=True)

    assert not any(c.get("legacy_type") == "cyclone_land_threat" for c in captured)
