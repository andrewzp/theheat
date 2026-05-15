"""Tests for Copernicus EMS Rapid Mapping flood activations."""

from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock

import pytest
import responses

from src import main
from src.data.copernicus_ems import (
    DETAIL_URL,
    SUMMARY_URL,
    CopernicusFloodActivation,
    detect_flood_events,
    fetch_active_flood_activations,
)
from src.data.source_status import SourceFetchError
from src.editorial.approval import recommend_approval_policy
from src.editorial.scoring import score_global_flood
from src.state import DEFAULT_STATE


def _activation(
    *,
    activation_id: str = "EMSR999",
    severity: str = "Major",
    population: int = 120_000,
    area_km2: float = 215.4,
) -> CopernicusFloodActivation:
    return CopernicusFloodActivation(
        activation_id=activation_id,
        country="Colombia",
        event_type="Riverine flood",
        severity=severity,
        populations_affected=population,
        affected_area_km2=area_km2,
        lat=8.8,
        lon=-75.9,
        activation_date="2026-05-14T12:00:00",
        copernicus_url=f"https://mapping.emergency.copernicus.eu/activations/{activation_id}/",
        event_id=f"copernicus_flood_{activation_id}_{severity.lower()}",
        name="Flood in Cordoba, Colombia",
    )


def _summary_payload(*, results: list[dict] | None = None) -> dict:
    return {
        "count": len(results or []),
        "next": None,
        "previous": None,
        "results": results or [],
    }


def _summary_row(code: str = "EMSR999") -> dict:
    today = date.today().isoformat()
    return {
        "code": code,
        "countries": ["Colombia"],
        "eventTime": f"{today}T06:00:00",
        "name": "Flood in Cordoba, Colombia",
        "centroid": "POINT (-75.91788189882986 8.806678771226656)",
        "activationTime": f"{today}T12:00:00",
        "category": "Flood",
        "lastUpdate": f"{today}T13:00:00",
        "closed": False,
        "gdacsId": None,
        "n_aois": 1,
        "n_products": 1,
    }


def _detail_payload(code: str = "EMSR999") -> dict:
    today = date.today().isoformat()
    return {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "code": code,
                "name": "Flood in Cordoba, Colombia",
                "category": "Flood",
                "subCategory": "Riverine flood",
                "activationTime": f"{today}T12:00:00",
                "closed": False,
                "countries": [{"name": "Colombia"}],
                "centroid": "POINT (-75.91788189882986 8.806678771226656)",
                "stats": {
                    "Population [No.]": 125000,
                    "max_extent": 21540.0,
                },
            }
        ],
    }


@responses.activate
def test_fetch_active_flood_activations_parses_current_schema():
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload(results=[_summary_row()]))
    responses.add(responses.GET, DETAIL_URL, json=_detail_payload())

    events = fetch_active_flood_activations(strict=True)

    assert len(events) == 1
    event = events[0]
    assert event.activation_id == "EMSR999"
    assert event.country == "Colombia"
    assert event.event_type == "Riverine flood"
    assert event.severity == "Major"
    assert event.populations_affected == 125000
    assert event.affected_area_km2 == 215.4
    assert event.lat == pytest.approx(8.806678771226656)
    assert event.lon == pytest.approx(-75.91788189882986)
    assert event.event_id == "copernicus_flood_EMSR999_major"


@responses.activate
def test_fetch_include_closed_parses_high_extent_archive_fixture():
    row = _summary_row("EMSR998")
    row["closed"] = True
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload(results=[row]))
    detail = _detail_payload("EMSR998")
    detail["results"][0]["closed"] = True
    detail["results"][0]["stats"] = {
        "Population [No.]": 1200,
        "max_extent": 60000.0,
    }
    responses.add(responses.GET, DETAIL_URL, json=detail)

    events = fetch_active_flood_activations(strict=True, include_closed=True)

    assert events[0].severity == "Extreme"
    assert events[0].affected_area_km2 == 600.0


@responses.activate
def test_detail_failure_non_strict_keeps_summary_activation():
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload(results=[_summary_row()]))
    responses.add(responses.GET, DETAIL_URL, status=500)

    events = fetch_active_flood_activations()

    assert len(events) == 1
    assert events[0].severity == "Major"
    assert events[0].populations_affected == 0


@responses.activate
def test_detail_failure_raises_in_strict_mode():
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload(results=[_summary_row()]))
    responses.add(responses.GET, DETAIL_URL, status=500)

    with pytest.raises(SourceFetchError):
        fetch_active_flood_activations(strict=True)


@responses.activate
def test_non_flood_summary_is_ignored():
    row = _summary_row("EMSR997")
    row["category"] = "Wildfire"
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload(results=[row]))

    assert fetch_active_flood_activations() == []


@responses.activate
def test_empty_open_flood_feed_is_success():
    responses.add(responses.GET, SUMMARY_URL, json=_summary_payload())

    assert fetch_active_flood_activations(strict=True) == []


@responses.activate
def test_schema_drift_raises_in_strict_mode():
    responses.add(responses.GET, SUMMARY_URL, json={"count": 1})

    with pytest.raises(SourceFetchError):
        fetch_active_flood_activations(strict=True)


def test_detector_fires_new_major_activation():
    event = _activation()

    assert detect_flood_events([event], {}) == [event]


def test_detector_suppresses_same_tier_already_fired():
    event = _activation()

    assert detect_flood_events([event], {"EMSR999": "Major"}) == []


def test_detector_fires_escalation_to_higher_tier():
    event = _activation(severity="Extreme", population=300_000)

    assert detect_flood_events([event], {"EMSR999": "Major"}) == [event]


def test_detector_allows_population_threshold_even_if_tier_is_lower():
    event = _activation(severity="Moderate", population=100_000)

    assert detect_flood_events([event], {}) == [event]


def test_detector_suppresses_minor_low_impact_activation():
    event = _activation(severity="Minor", population=5000, area_km2=2.0)

    assert detect_flood_events([event], {}) == []


def test_detector_preserves_event_order_for_multiple_new_activations():
    first = _activation(activation_id="EMSR001")
    second = _activation(activation_id="EMSR002", severity="Extreme", population=300_000)

    assert detect_flood_events([first, second], {}) == [first, second]


def test_detector_ignores_unknown_severity_without_population_threshold():
    event = _activation(severity="Unknown", population=99_999, area_km2=200.0)

    assert detect_flood_events([event], {}) == []


def test_score_global_flood_passes_major_population_threshold():
    score = score_global_flood("Major", 100_000, 20.0, "Colombia")

    assert score.category == "global_flood"
    assert score.passes
    assert score.threshold == 72


def test_score_global_flood_suppresses_minor_low_impact():
    score = score_global_flood("Minor", 3000, 1.0, "Italy")

    assert not score.passes


def test_score_global_flood_extreme_scores_above_major():
    major = score_global_flood("Major", 100_000, 20.0, "Colombia")
    extreme = score_global_flood("Extreme", 300_000, 600.0, "Colombia")

    assert extreme.total > major.total
    assert extreme.passes


def test_global_flood_approval_is_manual_only():
    policy = recommend_approval_policy("global_flood", signal_total=80)

    assert policy.mode == "manual_only"
    assert not policy.can_auto_approve


def _patch_other_alert_sources(monkeypatch):
    monkeypatch.setattr(main.open_meteo, "load_cities", lambda *a, **k: [])
    monkeypatch.setattr(
        main.open_meteo,
        "check_extreme_signals_for_cities",
        lambda *a, **k: ([], []),
    )
    monkeypatch.setattr(main.firms, "fetch_fires", lambda *a, **k: [])
    monkeypatch.setattr(main.fire_footprint, "fetch_active_fire_perimeters", lambda *a, **k: [])
    monkeypatch.setattr(main.fire_footprint, "detect_tier_crossings", lambda *a, **k: [])
    monkeypatch.setattr(main.co2, "fetch_co2_data", lambda *a, **k: [])
    monkeypatch.setattr(main.co2, "detect_milestone", lambda *a, **k: None)
    monkeypatch.setattr(main.methane, "fetch_ch4_milestones", lambda *a, **k: [])
    monkeypatch.setattr(main.methane, "detect_milestone", lambda *a, **k: None)
    monkeypatch.setattr(main.coral_dhw, "fetch_coral_dhw", lambda *a, **k: [])
    monkeypatch.setattr(main.coral_dhw, "detect_dhw_thresholds", lambda *a, **k: [])
    monkeypatch.setattr(main.nws_alerts, "fetch_alerts", lambda *a, **k: [])
    monkeypatch.setattr(main.gdacs, "fetch_disasters", lambda *a, **k: [])
    monkeypatch.setattr(main.nhc, "fetch_active_cyclones", lambda *a, **k: [])
    monkeypatch.setattr(main.nhc, "detect_rapid_intensification", lambda *a, **k: [])
    monkeypatch.setattr(main.nhc, "detect_tier_crossings", lambda *a, **k: [])
    monkeypatch.setattr(main.nhc, "detect_landfalls", lambda *a, **k: [])
    monkeypatch.setattr(main.jtwc, "fetch_active_cyclones", lambda *a, **k: [])
    monkeypatch.setattr(main.jtwc, "detect_rapid_intensification", lambda *a, **k: [])
    monkeypatch.setattr(main.jtwc, "detect_tier_crossings", lambda *a, **k: [])
    monkeypatch.setattr(main.jtwc, "detect_landfalls", lambda *a, **k: [])
    monkeypatch.setattr(main.sea_ice, "fetch_sea_ice", lambda *a, **k: [])
    monkeypatch.setattr(main.sea_ice, "detect_record_low", lambda *a, **k: None)
    monkeypatch.setattr(main.drought, "fetch_drought_data", lambda *a, **k: [])
    monkeypatch.setattr(main.enso, "fetch_enso_data", lambda *a, **k: [])
    monkeypatch.setattr(main.enso, "detect_transition", lambda *a, **k: None)
    monkeypatch.setattr(main.ocean, "fetch_ocean_conditions", lambda *a, **k: [])
    monkeypatch.setattr(main.ocean, "detect_extreme_waves", lambda *a, **k: [])
    monkeypatch.setattr(main.ocean_sst, "fetch_global_sst", lambda *a, **k: None)
    monkeypatch.setattr(main.ocean_sst, "detect_streak_milestone", lambda *a, **k: (None, None))
    monkeypatch.setattr(main.water_levels, "fetch_water_levels", lambda *a, **k: [])
    monkeypatch.setattr(main.water_levels, "detect_storm_surge", lambda *a, **k: [])
    monkeypatch.setattr(main.river_gauges, "fetch_river_levels", lambda *a, **k: [])
    monkeypatch.setattr(main.river_gauges, "detect_floods", lambda *a, **k: [])
    monkeypatch.setattr(main.ice_mass, "fetch_grace_mass", lambda *a, **k: [])
    monkeypatch.setattr(main.ice_mass, "detect_monthly_record", lambda *a, **k: None)
    monkeypatch.setattr(main.ice_mass, "detect_cumulative_milestone", lambda *a, **k: None)
    monkeypatch.setattr(main.synthesis, "detect_fire_drought_heat", lambda *a, **k: [])
    monkeypatch.setattr(main.ghcn, "check_extreme_signals_for_stations", lambda *a, **k: ([], []))


def test_run_alerts_wires_copernicus_flood_bundle(monkeypatch):
    _patch_other_alert_sources(monkeypatch)
    event = _activation()
    monkeypatch.setattr(
        main.copernicus_ems,
        "fetch_active_flood_activations",
        MagicMock(return_value=[event]),
    )

    captured = {}

    def fake_try_two_bot(bundle, bot_state, score, *, legacy_type, event_id, review_context, **kwargs):
        captured["bundle"] = bundle
        captured["legacy_type"] = legacy_type
        captured["review_context"] = review_context
        return main.save_draft(
            "Copernicus mapped a major flood in Colombia.",
            bot_state,
            legacy_type,
            event_id,
            score=score,
            review_context=review_context,
        )

    monkeypatch.setattr(main, "_try_two_bot_draft", fake_try_two_bot)
    bot_state = deepcopy(DEFAULT_STATE)
    current_run = {"id": "run_1", "sources": []}

    main.run_alerts(bot_state, current_run=current_run)

    assert bot_state["drafts"][0]["type"] == "global_flood"
    assert bot_state["flood_activation_tiers"]["EMSR999"] == "Major"
    assert bot_state["flood_annual_count"][str(date.today().year)] == 1
    assert captured["legacy_type"] == "global_flood"
    assert captured["bundle"].signal_kind == "global_flood"
    assert captured["review_context"]["source_key"] == "copernicus_ems"
    source = next(item for item in current_run["sources"] if item["source"] == "copernicus_ems")
    assert source["observed"] == 1
    assert source["promoted"] == 1
    assert source["drafted"] == 1
