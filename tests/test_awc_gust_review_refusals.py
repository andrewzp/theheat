"""Permanent invented counterexamples from the gust boundary review."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from freezegun import freeze_time
import pytest

from src.data import awc_gust as gust, awc_observed as awc
from src.orchestrator import posting, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from src.two_bot.types import StoryBundle
from tests import test_awc_gust as t
from tests.test_awc_gust import world as world
from tests.live_content_harness import GIST_ID
from tests.test_scheduled_automatic_preflight import (
    world as _budget_world, manual_slate, enqueue_automatic, run,
)


budget_world = _budget_world


@pytest.mark.parametrize("field,value", [
    ("wind_gust_kt", "64.999999999999999"), ("wind_gust_kt", "100.0000000000000001"),
    ("wind_speed_kt", "39.999999999999999"),
])
def test_exact_decoded_decimal_is_checked_before_binary_rounding(field, value):
    rows = t.rows()
    if value.startswith("100"):
        rows[0][0] = rows[0][0].replace("G65KT", "G100KT")
    rows[0][t.GUST_HEADER.index(field)] = value
    assert gust.parse_metars(t.csv_bytes(rows, header=t.GUST_HEADER), t.metadata(), now=t.NOW) == {}


@pytest.mark.parametrize("earlier_first", [False, True])
def test_calm_off_target_report_without_a_gust_does_not_hide_exact_target(world, monkeypatch, earlier_first):
    reply = ET.fromstring(t.xml(t.rows()))
    data = reply.find("data")
    calm = deepcopy(data[0])
    calm.find("raw_text").text = "TAAA 151100Z AUTO 27020KT CAVOK M20/M25 Q1010"
    calm.find("observation_time").text = "2026-11-15T11:00:00Z"
    calm.find("wind_speed_kt").text = "20"
    calm.remove(calm.find("wind_gust_kt"))
    data.insert(0 if earlier_first else 1, calm)
    data.set("num_results", "2")
    monkeypatch.setattr(t, "xml", lambda rows: ET.tostring(reply))
    bundle = gust.build_bundle(t.evidence(), now=t.NOW)
    assert awc.current_bundle_hold(bundle, live=True, now=t.NOW) is None


@pytest.mark.parametrize("case", ["before-due", "autoship-withdrawn", "normal-due"])
def test_final_transport_respects_due_clock_and_current_autoship(world, monkeypatch, case):
    t.generate(world)
    transport, state, _, called, _ = world
    draft = state["drafts"][0]
    assert called == ["writer", "safety", "fact_check", "critic"]
    if case == "before-due":
        from src.posting import twitter
        transport.gist = {"state.json": json.dumps(state)}
        monkeypatch.setattr("src.state.GIST_ID", GIST_ID)
        monkeypatch.setattr("src.state.GITHUB_TOKEN", "invented-no-access")
        for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
            monkeypatch.setattr(twitter, key, "invented-no-access")
        with freeze_time(t.NOW + timedelta(seconds=20), tick=True):
            assert posting.post_approved(draft, state) == "failed"
        assert not state["publish_ledger"]  # Not even an early durable intent.
    else:
        before = len(transport.awc_calls)
        if case == "autoship-withdrawn":
            def withdraw():
                if len(transport.awc_calls) == before + 4:
                    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
            transport.before_reply = withdraw
        t.sender(monkeypatch, world)
    assert len(transport.x_posts) == (1 if case == "normal-due" else 0)


@pytest.mark.parametrize("when", ["before-selection", "before-send"])
@pytest.mark.parametrize("conflicts", [[{"phase": "unknown"}], [None], "malformed"])
def test_nested_or_malformed_previous_attempt_remains_held(world, monkeypatch, when, conflicts):
    transport, state, _, called, _ = world
    event = "metar_gust_TAAA_2026-11-10"
    row = {"phase": "not_sent", "at": "2026-11-10T12:00:00Z", "attempt_conflicts": conflicts}
    if when == "before-selection":
        state["publish_ledger"][event] = deepcopy(row)
    t.generate(world)
    if when == "before-selection":
        assert called == []
    else:
        state["publish_ledger"][event] = deepcopy(row)
        t.sender(monkeypatch, world)
    assert transport.x_posts == [] and state["publish_ledger"][event] == row


def test_outer_gust_type_cannot_wrap_a_foreign_source(world):
    candidate = SimpleNamespace(legacy_type=gust.KIND, event_id="test_non_airport", tweet_date="2026-11-15",
        bundle=StoryBundle("monthly_high", "Test", "2026-11-15", "test_non_airport",
                           {"label": "high", "value": 40, "unit": "C"}, []))
    with freeze_time(t.NOW):
        assert triage_queue._automatic_source_hold(candidate) == "awc_source_identity_changed"


def test_mixed_foreign_candidate_is_refused_before_the_only_paid_slot(budget_world, monkeypatch):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv(gust.ENABLE_FLAG, "1")
    state, _ = manual_slate()
    enqueue_automatic(state, budget_world, monkeypatch)
    foreign = state["_triage_queue"][-1]
    state["_triage_queue"] = [replace(foreign, legacy_type=gust.KIND)]
    triage_queue._drain_and_write_triage_queue(state, run(), candidate_budget=CandidateBudget("invented", 1))
    assert budget_world.writer_events() == []


@pytest.mark.parametrize("conflicts", [None, "", {}, [{"phase": "unknown"}]])
def test_old_station_draft_cannot_hide_malformed_or_uncertain_conflicts(conflicts):
    old = deepcopy(t.evidence())
    old["points"][0]["valid_time"] = (t.NOW - timedelta(hours=25)).isoformat()
    state = {"drafts": [{"type": gust.KIND, "event_id": "metar_gust_TAAA_previous", "attempt_conflicts": conflicts,
             "review_context": {"two_bot": {"bundle": {"raw_signal_dump": {"evidence": old}}}}}], "publish_ledger": {}}
    assert gust.retained_station_hold(state, t.evidence(), now=t.NOW) == "awc_gust_uncertain_previous_attempt"


@pytest.mark.parametrize("fields", [
    {"requested": "2026-11-15T12:08:00Z", "due": "2026-11-15T12:09:00Z"},
    {"requested": "2026-11-15T12:10:00Z", "due": "2026-11-15T12:10:10Z"},
])
def test_mutable_schedule_fields_cannot_shorten_the_bound_approval_window(world, monkeypatch, fields):
    t.generate(world)
    draft = world[1]["drafts"][0]
    draft["auto_approve_requested_at"] = fields["requested"]
    draft["auto_approve_at"] = fields["due"]
    t.sender(monkeypatch, world, t.NOW + timedelta(seconds=20))
    assert world[0].x_posts == [] and not world[1]["publish_ledger"]


def test_old_unresolved_attempt_timestamp_blocks_the_actual_writer(world):
    transport, state, _, called, _ = world
    previous = deepcopy(t.evidence())
    previous["points"][0]["valid_time"] = "2026-11-13T12:00:00Z"
    state["drafts"].append({"type": gust.KIND, "id": "invented-old-draft", "event_id": "metar_gust_TAAA_2026-11-13",
        "status": "pending", "last_publish_attempt_at": "2026-11-13T12:10:00Z",
        "review_context": {"two_bot": {"bundle": {"raw_signal_dump": {"evidence": previous}}}}})
    before = deepcopy(state["drafts"])
    t.generate(world)
    assert called == [] and transport.x_posts == [] and state["drafts"] == before
