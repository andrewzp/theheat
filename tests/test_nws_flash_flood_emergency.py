"""Invented emergency products through the actual collector and publication guards."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest
import responses

from src.data.nws_alerts import fetch_alerts
from src.orchestrator import nws_publication as nws
from tests import test_nws_publication as publication
from tests.remaining_campaign import test_w04_nws_cli_journey as journey
from tests.test_nws_alerts import _typhoon_feature


def emergency(identity="invented-flood", message_type="Alert", refs=None):
    item = _typhoon_feature(identity, message_type, refs)
    props = item["properties"]
    props.update(event="Flash Flood Warning", severity="Severe", areaDesc="Invented valley",
                 headline="Flash Flood Warning issued by NWS Invented Office",
                 description="Life-threatening flash flooding is expected in the invented valley.",
                 parameters={"flashFloodDamageThreat": ["CATASTROPHIC"],
                             "NWSheadline": ["FLASH FLOOD EMERGENCY FOR INVENTED VALLEY"]})
    return item


def collect(features):
    with responses.RequestsMock() as http:
        http.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": features})
        return fetch_alerts(strict=True)


@pytest.mark.parametrize("kind", ["Alert", "Update"])
def test_emergency_product_and_complete_source_survive(kind):
    source = emergency(message_type=kind, refs=[{"identifier": "invented-old"}] if kind == "Update" else [])
    original = deepcopy(source)
    selected = collect([source])
    assert len(selected) == 1
    assert selected[0].event_type == "Flash Flood Warning"  # Keep the official product name.
    assert selected[0].event_id == "nws_invented-flood"
    assert selected[0].source_evidence["feature"] == original


@pytest.mark.parametrize("field,value", [
    ("event", "Flood Warning"), ("status", "Test"), ("category", "Safety"),
    ("messageType", "Cancel"), ("id", ""), ("areaDesc", ""),
    ("parameters", {}), ("parameters", None),
    ("parameters", {"flashFloodDamageThreat": ["CONSIDERABLE"], "NWSheadline": ["FLASH FLOOD EMERGENCY"]}),
    ("parameters", {"flashFloodDamageThreat": "CATASTROPHIC", "NWSheadline": ["FLASH FLOOD EMERGENCY"]}),
    ("parameters", {"flashFloodDamageThreat": ["CATASTROPHIC", "CONSIDERABLE"], "NWSheadline": ["FLASH FLOOD EMERGENCY"]}),
    ("parameters", {"flashFloodDamageThreat": ["CATASTROPHIC"]}),
    ("parameters", {"flashFloodDamageThreat": ["CATASTROPHIC"], "NWSheadline": ["Ordinary flood warning"]}),
])
def test_routine_or_incomplete_designations_are_not_promoted(field, value):
    source = emergency()
    source["properties"][field] = value
    assert collect([source]) == []


@pytest.mark.parametrize("refs", [None, [], {}, [{}], [{"identifier": ""}], [{"identifier": "invented-flood"}]])
def test_updates_require_usable_nonself_cap_references(refs):
    source = emergency(message_type="Update")
    source["properties"]["references"] = refs
    assert collect([source]) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_update_supersedes_predecessor_in_both_orders(reverse):
    old = emergency("invented-old")
    current = emergency("invented-new", "Update", [{"identifier": "invented-old"}])
    rows = [old, current]
    selected = collect(rows[::-1] if reverse else rows)
    assert [a.event_id for a in selected] == ["nws_invented-new"]


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_update_never_resurrects_predecessor(reverse):
    old = emergency("invented-old")
    current = emergency("invented-new", "Update", [{"identifier": "invented-old"}])
    conflict = deepcopy(current)
    conflict["properties"]["description"] = "A conflicting invented forecast."
    rows = [old, current, conflict]
    assert collect(rows[::-1] if reverse else rows) == []


def test_unlinked_products_are_held_and_identical_copies_collapse():
    one = emergency()
    assert len(collect([one, deepcopy(one)])) == 1
    assert collect([one, emergency("invented-other")]) == []


def test_other_warning_family_same_area_does_not_hide_either():
    flood = emergency()
    typhoon = _typhoon_feature("invented-typhoon")
    typhoon["properties"]["areaDesc"] = flood["properties"]["areaDesc"]
    assert {a.event_id for a in collect([flood, typhoon])} == {"nws_invented-flood", "nws_invented-typhoon"}


@pytest.mark.parametrize("kind", ["Alert", "Update"])
def test_current_source_guard_accepts_only_exact_live_emergency(monkeypatch, kind):
    source = emergency(message_type=kind, refs=[{"identifier": "invented-old"}] if kind == "Update" else [])
    # Use the existing invented publication clock and retain all source dates.
    for field in ("sent", "effective", "onset", "expires", "ends"):
        source["properties"][field] = publication.feature()["properties"][field]
    value = publication.draft(source)
    monkeypatch.setattr(nws, "_clock", lambda: publication.NOW)
    monkeypatch.setattr(nws, "_active_feed", lambda: {"features": [source]})
    assert nws.current_nws_source(value, live=True) is None
    changed = deepcopy(source)
    changed["properties"]["parameters"]["flashFloodDamageThreat"] = ["CONSIDERABLE"]
    monkeypatch.setattr(nws, "_active_feed", lambda: {"features": [changed]})
    assert nws.current_nws_source(value, live=True) == "nws_source_changed_or_missing"
    monkeypatch.setattr(nws, "_clock", lambda: publication.NOW + timedelta(hours=3))
    assert nws.current_nws_source(value, live=False) == "nws_source_expired_or_future"


@pytest.fixture
def cli(tmp_path):
    return journey.cli.__wrapped__(tmp_path)


@pytest.mark.parametrize("change_source", [False, True])
def test_real_scheduled_cli_checks_arms_and_sends_once(cli, change_source):
    data = json.loads(journey.feed())
    props = data["features"][0]["properties"]
    props.update(event="Flash Flood Warning", severity="Severe", messageType="Update",
                 references=[{"identifier": "invented-old-flood"}],
                 description="Life-threatening flash flooding is expected along the Ficta Coast.",
                 parameters={"flashFloodDamageThreat": ["CATASTROPHIC"],
                             "NWSheadline": ["FLASH FLOOD EMERGENCY FOR FICTA COAST"]})
    (cli["dir"] / "nws/feed.json").write_text(json.dumps(data))
    copy = "Life-threatening flash flooding threatens the Ficta Coast, where a flash flood emergency is in effect, the NWS warns."
    env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
           "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1"}
    produced = journey.run_cli(cli, ["alerts"], 0, env=env, copy=copy)
    (saved,) = journey.drafts(cli)
    assert produced["x"] == [] and saved["text"] == copy
    assert saved["approval_mode"] == "policy_auto" and saved["auto_approve_at"]
    assert produced["models"] == ["writer", "safety", "fact_check", "critic"]
    if change_source:
        props["description"] = "The current warning has changed since admission."
        (cli["dir"] / "nws/feed.json").write_text(json.dumps(data))
        held = journey.run_cli(cli, ["auto_publish_due"], 35, env=env, copy=copy)
        assert held["x"] == [] and journey.drafts(cli)[0]["approval_mode"] == "manual"
        return
    sent = journey.run_cli(cli, ["auto_publish_due"], 35, env=env, copy=copy)
    assert sent["x"] == [copy] and journey.drafts(cli)[0]["status"] == "posted"
    assert journey.run_cli(cli, ["auto_publish_due"], 70, env=env, copy=copy)["x"] == []


@pytest.mark.parametrize("reverse", [False, True])
def test_downgraded_update_does_not_resurrect_catastrophic_predecessor(reverse):
    old = emergency("invented-old")
    current = emergency("invented-new", "Update", [{"identifier": "invented-old"}])
    current["properties"]["parameters"]["flashFloodDamageThreat"] = ["CONSIDERABLE"]
    rows = [old, current]
    assert collect(rows[::-1] if reverse else rows) == []


def retained_source():
    source = emergency()
    for field in ("sent", "effective", "onset", "expires", "ends"):
        source["properties"][field] = publication.feature()["properties"][field]
    return source


def test_new_unlinked_same_area_product_blocks_existing_send(monkeypatch):
    source = retained_source()
    value = publication.draft(source)
    other = deepcopy(source)
    other["properties"]["id"] = "invented-unlinked"
    monkeypatch.setattr(nws, "_clock", lambda: publication.NOW)
    monkeypatch.setattr(nws, "_active_feed", lambda: {"features": [source, other]})
    assert nws.current_nws_source(value, live=True) == "nws_source_area_conflict"


@pytest.mark.parametrize("tamper", [None, "hash", "event", "source"])
def test_warning_prose_is_bound_to_original_current_event(tamper):
    from src.commands.schema import utc_text
    from src.data.nws_alerts import SevereWeatherAlert
    from src.media.published_radar import source_envelope
    from src.two_bot.copy_gates import copy_rejection
    from src.two_bot.intern import build_severe_weather_bundle

    source = retained_source()
    props = source["properties"]
    envelope = source_envelope(source, utc_text(publication.NOW))
    event_id = "nws_" + props["id"]
    if tamper == "hash":
        envelope["feature_sha256"] = "0" * 64
    elif tamper == "event":
        event_id = "nws_invented-other"
    elif tamper == "source":
        envelope["source_url"] = "https://example.test/unqualified"
    alert = SevereWeatherAlert(props["event"], props["areaDesc"], props["severity"], props["headline"],
                               event_id, description=props["description"], source_evidence=envelope)
    bundle = build_severe_weather_bundle(alert)
    warnings = [f for f in bundle.current_facts if f["label"] == "warning_text"]
    text = "Life-threatening flash flooding threatens the invented valley, the NWS warns."
    if tamper is None:
        assert len(warnings) == 1 and warnings[0]["event_id"] == event_id
        assert props["description"] in warnings[0]["value"]
        assert copy_rejection(text, bundle) is None
    else:
        assert warnings == []
        assert "invented_danger" in copy_rejection(text, bundle)
