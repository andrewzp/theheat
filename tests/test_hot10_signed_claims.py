"""Invented cold forecasts through real source qualification and the copy floor.

SDK responses in the pipeline cases are explicit offline fixtures, not evidence
of model quality or permission to publish. No live provider or platform is used.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.data import open_meteo, places
from src.data.temperature_evidence import forecast_day
from src.editorial import hot10_contract as contract
from src.two_bot.hot10_claims import claim_failures
from src.two_bot.intern import build_hot10_bundle
from tests import live_content_harness as h

NOW = datetime(2032, 3, 1, 0, 15, tzinfo=UTC)
COLD_NORMAL = -28.2
CITIES = (("Verkhoyansk", "Asia/Vladivostok", 15.8), *h.CITIES[:9])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    h.trap_network(monkeypatch.setattr)


def bulletin(tmp_path, *, normal=COLD_NORMAL, cities=CITIES):
    table = h.forecast_table(cities, normal_c=normal)
    temps = []
    for row in h.catalogue_rows([name for name, _zone, _kind in cities]):
        place = places.place_for_row(row)
        spec = table[h.coordinate_key(place["lat"], place["lon"])]
        payload = h.forecast_payload(place["lat"], place["lon"], zone=spec["zone"],
                                     max_c=spec["max_c"], now=NOW)
        result = forecast_day(payload, retrieved_at=NOW.isoformat())
        temps.append(open_meteo.CityTemp(row["city"], row["country"], place["lat"], place["lon"], result["max_c"],
                                        signal_date=date.fromisoformat(result["valid_date"]),
                                        evidence=result["evidence"]))
    path = tmp_path / "invented-cold-normals.csv"
    h.write_normals(path, h.normal_rows(2, cities, normal_c=normal) + h.normal_rows(3, cities, normal_c=normal))
    qualified = contract.qualify(temps, open_meteo.load_normals(str(path)), sampled=len(cities), now=NOW)
    assert qualified["complete"], qualified["universe"]
    bundle = build_hot10_bundle(qualified["rows"], changes=[], event_id="invented-cold-ranking",
                                universe=qualified["universe"])
    assert contract.validate_bundle(bundle) == []
    assert contract.current_hold(bundle, NOW) is None
    return bundle


def copy_with(values, *, city="Verkhoyansk", weekday="Monday"):
    return f"{city}'s forecast {weekday}: {values}, among 10 sampled cities."


@pytest.mark.parametrize("values", [
    "-12.4°C, 15.8°C above its -28.2°C normal",
    "−12.4°C, +15.8°C above its −28.2°C normal",
    "− 12.4°C, + 15.8°C above its - 28.2°C normal",
    "9.7°F, +28.4°F above its -18.8°F normal",
    "-12°C, 16°C above its -28°C normal",
])
def test_supplied_signed_celsius_and_fahrenheit_survive_the_real_source_path(tmp_path, values):
    assert claim_failures(copy_with(values), bulletin(tmp_path)) == []


@pytest.mark.parametrize("value", ["12.4°C", "+12.4°C", "-15.8°C", "− 15.8°C", "-13.4°C", "-12.40°C", "-12.4°F",
                                   "--13.4°C", "+−13.4°C", "- − 12.4°C", "++15.8°C"])
def test_unsupported_sign_magnitude_precision_or_unit_is_held(tmp_path, value):
    assert any("temperature value" in error for error in claim_failures(copy_with(value), bulletin(tmp_path)))


@pytest.mark.parametrize("value", ["-4.5°C", "−4.5°C", "4.5°C below normal", "-8.1°F", "8.1°F below normal"])
def test_supplied_negative_departure_keeps_its_sign_and_below_magnitude(tmp_path, value):
    cities = tuple((name, zone, -4.5) for name, zone, _kind in CITIES)
    bundle = bulletin(tmp_path, normal=20.0, cities=cities)
    assert claim_failures(copy_with(value, weekday="Monday"), bundle) == []


@pytest.mark.parametrize("value", ["0°C", "-0.0°C", "−0°C", "+0.0°C"])
def test_exact_zero_departure_has_no_material_sign(tmp_path, value):
    cities = tuple((name, zone, 0.0) for name, zone, _kind in CITIES)
    assert claim_failures(copy_with(value), bulletin(tmp_path, normal=-20.0, cities=cities)) == []


def test_lead_weekday_is_explicit_source_local_context(tmp_path):
    bundle = bulletin(tmp_path)
    facts = {row["label"]: row["value"] for row in bundle.current_facts}
    assert facts["leader_local_weekday"] == "Monday"
    assert bundle.raw_signal_dump["universe"]["local_days"] == ["2032-02-29", "2032-03-01"]
    assert contract.local_weekday("2032-02-29") == "Sunday"
    assert contract.local_weekday("2032-03-01") == "Monday"


@pytest.mark.parametrize("weekday", ["Sunday", "sUnDaY", "Tuesday", "Monday and Sunday"])
def test_single_named_city_cannot_borrow_another_rows_weekday(tmp_path, weekday):
    bundle = bulletin(tmp_path)
    assert any("weekday" in error for error in claim_failures(copy_with("-12.4°C", weekday=weekday), bundle))


def test_nonleader_uses_its_own_local_day_and_multi_city_copy_still_needs_models(tmp_path):
    bundle = bulletin(tmp_path)
    assert claim_failures(copy_with("5.5°C above normal", city="Phoenix", weekday="Sunday"), bundle) == []
    assert any("weekday" in error for error in claim_failures(
        copy_with("5.5°C above normal", city="Phoenix", weekday="Monday"), bundle))
    # The lexical floor deliberately does not adjudicate multiple city/day clauses.
    assert claim_failures("Verkhoyansk's forecast is for Monday; Phoenix's for Sunday, among 10 sampled cities.",
                          bundle) == []


def test_malformed_source_is_held_before_interpreting_copy(tmp_path):
    bundle = bulletin(tmp_path)
    bundle.raw_signal_dump["cities"][0]["valid_date"] = "2032-02-30"
    assert any("source contract" in error for error in claim_failures(copy_with("-12.4°C"), bundle))


@pytest.mark.parametrize("outcome", ["pass", "fact_failure", "safety_failure", "critic_failure", "missing_fact"])
def test_cold_pipeline_invokes_required_checks_and_never_promotes_a_failure(tmp_path, monkeypatch, outcome):
    from copy import deepcopy
    from freezegun import freeze_time
    from src.orchestrator import hot10
    from src.state import DEFAULT_STATE

    text = ("Riyadh's forecast Thursday: -19.0°C, 9.2°C above its -28.2°C normal, "
            "among 14 sampled cities.")
    world = h.install_hot10_world(tmp_path, monkeypatch, copy=text)
    h.write_normals(world.normals_csv, h.normal_rows(10, normal_c=COLD_NORMAL))
    world.transport.forecasts = h.forecast_table(normal_c=COLD_NORMAL)
    if outcome == "fact_failure":
        world.script.fact_passed = False
    elif outcome == "safety_failure":
        world.script.safety = "YES"
    elif outcome == "critic_failure":
        world.script.critic = {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                               "selected_index": None}
    elif outcome == "missing_fact":
        original = world.script.google_text

        def missing(request):
            stage, response = original(request)
            if stage == "fact_check":
                raise RuntimeError("invented: missing required response")
            return stage, response

        monkeypatch.setattr(world.script, "google_text", missing)
    state = deepcopy(DEFAULT_STATE)
    with freeze_time(datetime(2026, 10, 29, 9, tzinfo=UTC), tick=True):
        hot10.run_leaderboard(state, {"id": "invented-signed-hot10", "sources": []})
    if outcome == "pass":
        assert world.script.stages() == ["writer", "safety", "fact_check", "critic"]
        assert len(state["drafts"]) == 1 and state["drafts"][0]["status"] == "pending"
        request = world.script.requests[0][1]["messages"][0]["content"]
        assert '"leader_local_weekday"' in request and '"Thursday"' in request
    else:
        assert state["drafts"] == []
    assert world.script.stages().count("writer") == 1
    assert len(world.settled) == 1 and world.settled[0][2] is True
    assert world.transport.x_posts == []
