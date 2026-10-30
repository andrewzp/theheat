"""W07.1/07.4/07.5 on the ordinary source runners: stable hazard episode keys and repeat polls.

Invented captures only. GDACS goes through the real runner and the real evidence
audit/queue; Copernicus, NWS and FIRMS go through their real runners with the queue
recorded. ``THEHEAT_HAZARD_EPISODES`` is default off: off, the candidates and their
review context are exactly today's.
"""
from __future__ import annotations

from copy import deepcopy
import dataclasses
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from src.data import copernicus_ems, gdacs
from src.data.copernicus_ems import CopernicusFloodActivation
from src.data.nws_alerts import SevereWeatherAlert
from src.editorial import hazard_episodes as he
from src.orchestrator.sources import copernicus_ems as copernicus_runner, firms as firms_runner
from src.orchestrator.sources import gdacs as gdacs_runner, nws_alerts as nws_runner
from src.state import DEFAULT_STATE
from tests.live_content_harness import trap_network
from tests.test_gdacs_intake_contract import capture, items
from tests.test_gdacs_publication_freshness import NS


@pytest.fixture
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.delenv(he.FLAG, raising=False)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    return monkeypatch


def _gdacs_event(*, day: str, country: str | None = None, event_id: str = "intake-control", level: str | None = None):
    rows = items(event_id)
    if country is not None:
        rows[0].find(NS + "country").text = country
    if level is not None:
        rows[0].find(NS + "episodealertlevel").text = level
    events, _, _ = capture(rows, min_level=0)
    assert len(events) == 1, [ET.tostring(r) for r in rows]
    event = events[0]
    # Non-cyclone GDACS IDs are one per calendar day: emulate the next day's poll of the same event.
    return dataclasses.replace(event, event_id=event.event_id.rsplit("_", 1)[0] + f"_{day}")


def _run_gdacs(patch, state, *events):
    patch.setattr(gdacs, "fetch_disasters", lambda **_: list(events))
    run = {"id": "invented-run-w07", "sources": []}
    gdacs_runner.run_gdacs(state, run)
    return run["sources"][-1]


def _queue(state):
    return state.get("_triage_queue", [])


def _draft_from_queue(state, status="pending", **extra):
    row = _queue(state).pop(0)
    state.setdefault("drafts", []).append({"id": f"draft-{row.event_id}", "event_id": row.event_id,
                                           "status": status, "review_context": deepcopy(row.review_context), **extra})


def test_flag_off_keeps_todays_daily_gdacs_writer_opportunities_and_review_context(offline):
    state = deepcopy(DEFAULT_STATE)
    first = _gdacs_event(day="2026-10-28")
    second = _gdacs_event(day="2026-10-29")
    row = _run_gdacs(offline, state, first, second)
    assert row["promoted"] == 2 and len(_queue(state)) == 2  # today: each calendar-day ID is a new opportunity
    assert all("physical_episode" not in c.review_context and "physical_episode_hold" not in c.review_context
               for c in _queue(state))
    assert not any(s.get("stage") == "episode_repeat" for s in state.get("suppressions", []))


def test_gdacs_repeat_polls_update_status_without_new_writer_opportunities(offline):
    offline.setenv(he.FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    day1 = _gdacs_event(day="2026-10-28")
    assert _run_gdacs(offline, state, day1)["promoted"] == 1
    binding = _queue(state)[0].review_context["physical_episode"]
    assert binding["episode_id"] == f"ep1:{he.GDACS_HAZARDS[day1.source_provenance['eventtype']]}:gdacs:" \
        f"{day1.source_provenance['eventtype']}-{day1.source_event_id}"
    # Candidate ID, source revision, physical episode and publication identity stay distinct.
    lineage = binding["lineage"]
    assert lineage["candidate_id"] == day1.event_id and lineage["publication_id"] is None
    assert len({lineage["candidate_id"], binding["source_revision"], binding["episode_id"]}) == 3
    assert binding["eligibility"] == ["new_episode"] and binding["update_of"] is None
    _draft_from_queue(state)

    # Next day: same event and facts; only GDACS's episode ID and update time moved -> a new source
    # revision is recorded as a status row, with no writer opportunity.
    later = _gdacs_event(day="2026-10-29")
    day2 = dataclasses.replace(later, source_provenance={**later.source_provenance, "episode_id": "invented-ep-2",
                                                         "source_updated_at": "2026-10-29T06:00:00Z"})
    row = _run_gdacs(offline, state, day2)
    assert row["promoted"] == 0 and _queue(state) == []
    repeat = [s for s in state["suppressions"] if s["stage"] == "episode_repeat"]
    assert len(repeat) == 1 and repeat[0]["event_id"] == day2.event_id
    assert "no_new_material_facts" in repeat[0]["reasons"][0] and "retrieved_at" in repeat[0]["reasons"][0]
    assert binding["episode_id"] in repeat[0]["reasons"][0]

    # A genuinely new place is material: one separately reviewed update, bound to the prior revision.
    day3 = _gdacs_event(day="2026-10-30", country="Fictonia, Exemplaria")
    assert _run_gdacs(offline, state, day3)["promoted"] == 1
    update = _queue(state)[0].review_context["physical_episode"]
    assert update["episode_id"] == binding["episode_id"] and update["update_of"] == binding["source_revision"]
    assert update["eligibility"] == ["new_place"] and update["source_revision"] != binding["source_revision"]
    # The delivered draft's binding is untouched (old source revision retained, not erased).
    assert state["drafts"][0]["review_context"]["physical_episode"] == binding


def test_same_name_event_in_another_country_or_id_never_collides(offline):
    offline.setenv(he.FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    here = _gdacs_event(day="2026-10-28")
    elsewhere = dataclasses.replace(here, source_event_id=here.source_event_id + "9",
                                    event_id=here.event_id.replace("intake-control", "intake-control9"),
                                    country="Exemplaria")
    assert here.name == elsewhere.name
    assert _run_gdacs(offline, state, here, elsewhere)["promoted"] == 2
    keys = [c.review_context["physical_episode"]["episode_id"] for c in _queue(state)]
    assert len(set(keys)) == 2
    anon = {"hazard": "fire", "issuer": "firms", "place_id": "cell", "start_date": "2026-10-28"}
    assert he.episode_key({**anon, "country_code": "AU"}) != he.episode_key({**anon, "country_code": "BR"})
    assert he.episode_key({**anon, "country_code": "AU"}) != he.episode_key(
        {**anon, "country_code": "AU", "start_date": "2026-10-29"})


def test_unknown_delivery_fences_the_episode_and_unidentified_events_stay_visible(offline):
    offline.setenv(he.FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    _run_gdacs(offline, state, _gdacs_event(day="2026-10-28"))
    _draft_from_queue(state, status="approved", publish_outcome="unknown")
    changed = _gdacs_event(day="2026-10-29", country="Fictonia, Exemplaria")  # material, but delivery unknown
    assert _run_gdacs(offline, state, changed)["promoted"] == 0
    assert "unknown_delivery_fence" in state["suppressions"][-1]["reasons"][0]
    # A hand-made legacy event with no provider ID cannot be keyed: today's path, gap visible.
    legacy = dataclasses.replace(_gdacs_event(day="2026-10-29", event_id="intake-shared-1"), source_event_id="",
                                 source_provenance={})
    assert _run_gdacs(offline, state, legacy)["promoted"] == 1
    assert _queue(state)[-1].review_context["physical_episode_hold"] == "episode_identity_unsupported"


def _record_queue(patch, runner):
    def enqueue(bot_state, **kwargs):
        bot_state.setdefault("_triage_queue", []).append(SimpleNamespace(**kwargs))
        return True
    patch.setattr(runner, "_enqueue_story_candidate", enqueue)


def _activation(severity, area):
    return CopernicusFloodActivation(
        activation_id="EMSR9901", country="Fictonia", event_type="Flood", severity=severity,
        populations_affected=1200, affected_area_km2=area, lat=1.0, lon=2.0, activation_date="2026-10-27T00:00:00Z",
        copernicus_url="https://invented.example/EMSR9901", event_id=f"copernicus_flood_EMSR9901_{severity.lower()}",
        name="Ficta River flood", last_update="2026-10-28T00:00:00Z")


def test_copernicus_tier_crossing_alone_is_not_material_but_area_growth_is(offline):
    offline.setenv(he.FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    _record_queue(offline, copernicus_runner)
    offline.setattr(copernicus_runner, "_should_draft", lambda *a, **k: True)
    offline.setattr(copernicus_ems, "detect_flood_events", lambda activations, _tiers: activations)
    # Today each tier crossing is a new event ID; only mapped-area growth > 5% is a new fact.
    polls = [[_activation("Orange", 100.0)], [_activation("Red", 102.0)], [_activation("Red", 150.0)]]
    offline.setattr(copernicus_ems, "fetch_active_flood_activations", lambda **_: polls.pop(0))
    for _ in range(3):
        copernicus_runner.run_copernicus_ems(state, {"sources": []})
    queued = [c.review_context["physical_episode"] for c in _queue(state)]
    assert [b["eligibility"] for b in queued] == [["new_episode"], ["value_changed"]]
    assert queued[1]["update_of"] == queued[0]["source_revision"]
    repeat = [s for s in state["suppressions"] if s["stage"] == "episode_repeat"]
    assert len(repeat) == 1 and repeat[0]["event_id"] == "copernicus_flood_EMSR9901_red"
    assert "no_new_material_facts" in repeat[0]["reasons"][0] and "tier" in repeat[0]["reasons"][0]


def test_nws_and_firms_bind_their_own_source_identity(offline):
    from tests.fire_source_fixtures import fire_event

    offline.setenv(he.FLAG, "1")
    state = deepcopy(DEFAULT_STATE)
    alert = SevereWeatherAlert(event_type="Tornado Warning", area="Ficta County", severity="Extreme",
                               headline="Invented", event_id="nws_urn:oid:invented.1",
                               source_evidence={"source_alert_id": "urn:oid:invented.1",
                                                "captured_at": "2026-10-28T00:00:00Z"})
    _record_queue(offline, nws_runner)
    offline.setattr(nws_runner, "_fetch_strict", lambda *a, **k: [alert])
    offline.setattr(nws_runner, "_should_draft", lambda *a, **k: True)
    nws_runner.run_nws_alerts(state, {"sources": []})
    nws_runner.run_nws_alerts(state, {"sources": []})  # identical repeat poll in the same queue
    assert [c.review_context["physical_episode"]["episode_id"] for c in _queue(state)] == [
        "ep1:severe_weather:nws:urn:oid:invented.1"]
    assert state["suppressions"][-1]["reasons"][0].endswith("same_source_revision")

    fire = fire_event()
    _record_queue(offline, firms_runner)
    offline.setattr(firms_runner, "_fetch_firms_with_attempts", lambda attempts: [fire])
    offline.setattr(firms_runner.state, "is_duplicate", lambda *a: False)
    offline.setattr(firms_runner, "_should_draft", lambda *a, **k: True)
    firms_runner.run_firms(state, None)
    binding = _queue(state)[-1].review_context["physical_episode"]
    assert binding["episode_id"] == f"ep1:fire:firms:{fire.event_id}" and binding["evidence_type"] == "thermal_detection"


def test_flag_off_runners_leave_review_context_byte_identical(offline):
    from tests.fire_source_fixtures import fire_event

    state = deepcopy(DEFAULT_STATE)
    _record_queue(offline, firms_runner)
    offline.setattr(firms_runner, "_fetch_firms_with_attempts", lambda attempts: [fire_event()])
    offline.setattr(firms_runner.state, "is_duplicate", lambda *a: False)
    offline.setattr(firms_runner, "_should_draft", lambda *a, **k: True)
    firms_runner.run_firms(state, None)
    firms_runner.run_firms(state, None)
    assert len(_queue(state)) == 2  # no episode fence while off
    assert all(not {"physical_episode", "physical_episode_hold"} & set(c.review_context) for c in _queue(state))
    assert not state.get("suppressions")
