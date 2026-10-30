"""W05: national-service observed temperature through the real runner, admission, pipeline and review.

Every packet, station id and value is invented; no AEMET/IMD/SAWS bytes were
fetched. Registered places come from the checked-in place registry. Model stages
are offline fakes through the real provider boundary; the deterministic claim floor
inside the real pipeline still runs.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json

import pytest

from src.data import places, regional_observations as ro
from src.data.temperature_evidence import temperature_claim_failures
from src.editorial import revisions
from src.orchestrator.sources import regional_observed as runner
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from tests.live_content_harness import trap_network
from tests.nhc_advisory_pipeline_helpers import stage_fakes

RETRIEVED = "2026-10-29T08:00:00Z"
DAY = "2026-10-28"
VALUE_COPY = ("A station at Madrid logged 47.3°C for its 28 October reporting day, AEMET data show, "
              "above the 42°C absolute band for its latitude.")
RECORD_COPY = "Madrid set a new record: 47.3°C, the hottest day ever measured there, AEMET data show."


def _packet(adapter: str, payload: str, stations: list[dict], *, access=True, contract=None, requested=None) -> dict:
    packet = {
        "schema": ro.PACKET_SCHEMA, "adapter": adapter, "retrieved_at": RETRIEVED,
        "access": {"arrangement": "invented_owner_key", "terms_reference": "invented terms note"} if access else None,
        "requested": {"date": DAY, "stations": requested or [s["station_id"] for s in stations]},
        "stations": stations, "payload": payload, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }
    if contract is not None:
        packet["schema_contract"] = contract
    return packet


def aemet_packet(**kw) -> dict:
    rows = [
        {"fecha": DAY, "indicativo": "9X01", "nombre": "MADRID", "provincia": "MADRID", "altitud": "667",
         "tmax": "47,3", "horatmax": "15:40", "tmin": "30,1", "horatmin": "06:10"},
        {"fecha": DAY, "indicativo": "9X02", "nombre": "MADRID", "provincia": "MADRID", "altitud": "690",
         "tmax": "46,0", "horatmax": "16:00", "tmin": "", "horatmin": ""},
        {"fecha": DAY, "indicativo": "9X03", "nombre": "MADRID", "provincia": "MADRID", "altitud": "650",
         "tmax": "", "horatmax": "", "tmin": "", "horatmin": ""},
    ]
    stations = [
        {"station_id": "9X01", "name": "Madrid", "country": "Spain", "lat": 40.42, "lon": -3.7, "elevation_m": 667},
        {"station_id": "9X02", "name": "Madrid", "country": "Spain", "lat": 40.45, "lon": -3.69, "elevation_m": 690},
        {"station_id": "9X03", "name": "Madrid", "country": "Spain", "lat": 40.41, "lon": -3.72, "elevation_m": 650},
    ]
    return _packet("aemet", json.dumps(rows), stations, **kw)


IMD_CONTRACT = {"version": "invented-imd-contract-1", "unit": "C",
                "field_map": {"station_id": "stn", "date": "obs_date", "tmax_c": "max_c", "qc_flag": "qc"}}


def imd_packet(**kw) -> dict:
    payload = "stn,obs_date,max_c,qc\nIN-F1,2026-10-28,51.2,\nIN-F2,2026-10-28,52.4,S\n"
    stations = [{"station_id": "IN-F1", "name": "Navapur Ficticio", "country": "India", "lat": 21.1, "lon": 73.8},
                {"station_id": "IN-F2", "name": "Kalpi Ficticio", "country": "India", "lat": 21.3, "lon": 74.1}]
    return _packet("imd", payload, stations, **kw)


def saws_packet(**kw) -> dict:
    payload = "id,date,tx\nZA-F1,2026-10-28,44.0\n"
    stations = [{"station_id": "ZA-F1", "name": "Vlakte Ficticio", "country": "South Africa", "lat": -28.1, "lon": 21.2}]
    return _packet("saws", payload, stations, **kw)


@pytest.fixture
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    for name, value in (("ANTHROPIC_API_KEY", "invented-no-provider-access"),
                        ("GEMINI_API_KEY", "invented-no-provider-access"), ("THEHEAT_WRITER_SAMPLES", "1"),
                        ("THEHEAT_CRITIC_REVISE_ENABLED", "0"), ("THEHEAT_CRITIC_ENABLED", "1"),
                        ("THEHEAT_TRIAGE_ENABLED", "0")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
    monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    return monkeypatch


def _produce(patch, packets, *, copy=VALUE_COPY, state=None):
    sent: list[str] = []
    writer, safety, fact, critic = stage_fakes(sent, copy=copy)
    patch.setattr(pipeline.writer, "write_tweet", writer)
    patch.setattr(pipeline, "run_safety_pipeline", safety)
    patch.setattr(pipeline.fact_check, "fact_check", fact)
    patch.setattr(pipeline.critic, "critic_review", critic)
    state = deepcopy(DEFAULT_STATE) if state is None else state
    run: dict = {"id": "invented-run-w05", "started_at": RETRIEVED, "sources": []}
    with redirect_stdout(io.StringIO()):
        runner.run_regional_observed(state, run, packets)
        _drain_and_write_triage_queue(state, run)
    details = next(row["details"] for row in run["sources"] if row["source"] == "regional_observed")
    return state, run, details, sent


# --- 05.1 adapters and named holds -------------------------------------------------
def test_each_adapter_yields_typed_evidence_or_its_own_named_hold():
    parsed = ro.parse_packet(aemet_packet())
    assert parsed["denominators"] == {"requested_stations": 3, "returned_stations": 3, "qualified_station_days": 2}
    evidence = parsed["observations"][0]["evidence"]
    assert evidence["evidence_type"] == "observed" and evidence["source_product"] == "aemet-opendata-climatological-daily-v1"
    assert evidence["variables"]["TMAX"]["value_c"] == 47.3 and evidence["baseline"] is None
    assert {row["reason"] for row in parsed["exclusions"]} == {"missing_value"}
    with pytest.raises(ro.RegionalHold) as hold:
        ro.parse_packet(saws_packet(access=False))
    assert (hold.value.adapter, hold.value.code) == ("saws", "access_unavailable") and "SAWS" in hold.value.text
    with pytest.raises(ro.RegionalHold) as hold:
        ro.parse_packet(imd_packet())  # no owner schema contract
    assert (hold.value.adapter, hold.value.code) == ("imd", "schema_contract_unverified")
    imd = ro.parse_packet(imd_packet(contract=IMD_CONTRACT))
    assert imd["denominators"]["qualified_station_days"] == 1
    assert imd["exclusions"] == [{"station_id": "IN-F2", "valid_date": DAY, "variable": "TMAX", "reason": "qc_flagged"}]
    tampered = aemet_packet()
    tampered["payload"] = tampered["payload"].replace("47,3", "49,9")
    with pytest.raises(ro.RegionalHold) as hold:
        ro.parse_packet(tampered)
    assert hold.value.code == "payload_digest_mismatch"


# --- 05.2 station admission ---------------------------------------------------------
def test_station_joins_registered_point_but_never_falls_back_to_a_nearby_city(monkeypatch):
    exact = ro.admit_station([{"station_id": "9X01", "name": "Madrid", "country": "Spain", "lat": 40.42, "lon": -3.7}], DAY)
    assert exact["join"] == "registered_sampling_point" and exact["place"]["place_id"] == "pl0322"
    near = ro.admit_station([{"station_id": "9X02", "name": "Madrid", "country": "Spain", "lat": 40.45, "lon": -3.69}], DAY)
    assert near["join"] == "station_point_distinct_from_named_place" and near["place"]["place_id"].startswith("ux")
    moved = [{"station_id": "9X01", "name": "Madrid", "country": "Spain", "lat": 40.42, "lon": -3.7,
              "effective_to": "2026-01-01"},
             {"station_id": "9X01", "name": "Madrid", "country": "Spain", "lat": 40.43, "lon": -3.7,
              "effective_from": "2026-06-01"}]
    with pytest.raises(ValueError, match="station_relocation_period_unresolved"):
        ro.admit_station(moved, "2026-03-01")
    assert ro.admit_station(moved, DAY)["station_lat"] == 40.43
    twin = [{"place_id": f"plfict{i}", "city": "Villa Ficticia", "country": "Spain", "country_code": "ES",
             "lat": 39.0 + i, "lon": -2.0, "aliases": []} for i in (0, 1)]
    monkeypatch.setattr(places, "registry", lambda: tuple(twin))
    places.resolve_place.cache_clear()
    try:
        with pytest.raises(ValueError, match="ambiguous_station_place"):
            ro.admit_station([{"station_id": "V1", "name": "Villa Ficticia", "country": "Spain", "lat": 39.5,
                               "lon": -2.0}], DAY)
    finally:
        places.resolve_place.cache_clear()


# --- 05.3 time semantics ------------------------------------------------------------
def test_source_day_is_not_a_utc_day_and_currentness_follows_support():
    support = ro.time_support(DAY, RETRIEVED, max_lag_days=4)
    assert support["valid_start"] is None and support["valid_end"] is None and support["timezone"] is None
    assert support["currentness"] == "current" and support["reporting_interval_known"] is False
    assert ro.time_support("2026-10-20", RETRIEVED, max_lag_days=4)["currentness"] == "stale"
    assert ro.time_support("2026-10-30", RETRIEVED, max_lag_days=4)["currentness"] == "invalid_future_day"
    stale = ro.parse_packet(aemet_packet())["observations"][0]
    stale["evidence"] = {**stale["evidence"], "time_support": ro.time_support("2026-10-20", RETRIEVED, max_lag_days=4)}
    assert ro.build_candidate(stale) == (None, "time_support_stale")


# --- 05.4 comparator warrant --------------------------------------------------------
def test_record_wording_needs_the_scoped_warrant_otherwise_value_only():
    observation = ro.parse_packet(aemet_packet())["observations"][0]
    warrant = ro.qualify_comparison(observation["evidence"], {"reconciled": True, "source_product": "ghcn"})
    assert warrant["claim_scope"] == "value_or_absolute_band_only"
    assert warrant["reasons"] == ["comparator_warrant_not_scoped_to_this_product"]
    bundle, reason = ro.build_candidate(observation)
    assert reason is None and bundle is not None
    assert temperature_claim_failures(RECORD_COPY, bundle)
    assert temperature_claim_failures(VALUE_COPY, bundle) == []
    facts = {row["label"]: row["value"] for row in bundle.current_facts}
    assert "no record" in facts["claim_limit"] and facts["source_station"] == "Madrid (9X01)"


# --- 05.5 multi-region production through admission ---------------------------------
def test_one_region_hold_does_not_stop_others_and_denominators_are_explicit(offline):
    state, run, details, _sent = _produce(offline, [aemet_packet(), imd_packet(), saws_packet(access=False)])
    regions = details["regional_observed"]["regions"]
    assert regions["aemet"]["status"] == "processed" and regions["aemet"]["candidates_admitted"] == 2
    assert (regions["aemet"]["requested_stations"], regions["aemet"]["returned_stations"],
            regions["aemet"]["qualified_station_days"]) == (3, 3, 2)
    assert regions["imd"]["hold"] == "schema_contract_unverified"
    assert regions["saws"]["hold"] == "access_unavailable" and regions["saws"]["owner_action"]
    entry = next(row for row in run["sources"] if row["source"] == "regional_observed")
    assert entry["status"] == "degraded" and entry["promoted"] == 2
    assert details["regional_observed"]["discovery_cap"] is None
    assert "not national" in details["regional_observed"]["scope"]


def test_flag_off_runner_does_nothing(offline):
    offline.delenv(runner.FLAG, raising=False)
    state = deepcopy(DEFAULT_STATE)
    run: dict = {"sources": []}
    runner.run_regional_observed(state, run)
    assert run["sources"] == []
    offline.setenv(runner.FLAG, "true")
    runner.run_regional_observed(state, run)
    assert run["sources"] == []


# --- 05.6 editorial consumption ------------------------------------------------------
def test_value_copy_reaches_a_reviewable_draft_and_source_change_invalidates_review(offline):
    state, _run, _details, sent = _produce(offline, [aemet_packet()])
    drafts = [d for d in state["drafts"] if (d.get("review_context") or {}).get("source_key") == "regional_observed"]
    assert drafts, state.get("suppressions")
    draft = drafts[0]
    facts = {row["label"]: row["value"] for row in draft["review_context"]["facts"]}
    assert facts["Claim scope"] == "value_or_absolute_band_only" and facts["Source reporting day"] == DAY
    bundle = draft["review_context"]["two_bot"]["bundle"]
    assert bundle["raw_signal_dump"]["evidence"]["comparison_warrant"]["claim_scope"] == "value_or_absolute_band_only"
    assert "writer" in sent
    # Saved claim reference: the operator links the quoted value to the retained station fact.
    from src.editorial import operator_claim_references as refs
    pointer = next(f"/current_facts/{i}" for i, row in enumerate(bundle["current_facts"])
                   if row["label"] == "source_station")
    quote = "47.3°C"
    start = draft["text"].index(quote)
    saved = refs.build_operator_claim_references(draft["text"], bundle, [
        {"claim": {"start": start, "end": start + len(quote), "text": quote}, "sources": [{"pointer": pointer}]}])
    draft["review_context"]["operator_claim_references"] = saved
    view = refs.project_operator_claim_references(draft)
    assert view["status"] == "saved" and view["source_label"].startswith("AEMET observed station")
    assert view["items"][0]["sources"][0]["fact"]["value"] == "Madrid (9X01)"
    # The native GHCN temperature graphic does not apply: no archive comparison, so it refuses.
    from src.media.temperature_graphic_adapter import temperature_graphic_spec
    candidate, _ = ro.build_candidate(ro.parse_packet(aemet_packet())["observations"][0])
    with pytest.raises(ValueError):
        temperature_graphic_spec("temperature_comparator", [candidate], expected_bundle_sha256=["0" * 64],
                                 synthetic=True)
    revisions.initialize_revision(draft)
    revisions.record_human_review(draft)
    assert revisions.review_is_current(draft)
    # A replaced/revised source packet is new evidence: the review binding no longer matches.
    replaced = deepcopy(draft)
    replaced["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["source_payload_sha256"] = "0" * 64
    assert not revisions.review_is_current(replaced)


def test_record_copy_is_refused_at_the_real_local_check(offline):
    state, _run, _details, sent = _produce(offline, [aemet_packet()], copy=RECORD_COPY)
    assert not [d for d in state["drafts"] if (d.get("review_context") or {}).get("source_key") == "regional_observed"]
    # Both candidates reached the writer; the real local floor stopped each before safety/fact/critic.
    assert sent == ["writer", "writer"]
    bundle, _reason = ro.build_candidate(ro.parse_packet(aemet_packet())["observations"][0])
    rejected = pipeline.fact_check.local_rejection(RECORD_COPY, [], bundle, state)
    assert rejected is not None and "national-service observed value" in json.dumps(rejected.failures)
