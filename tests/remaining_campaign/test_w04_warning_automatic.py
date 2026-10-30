"""W04: default-off typed official-warning automatic text, in process.

The actual NHC runner -> queue -> pipeline -> admission (stage fakes go through the
real provider boundary), then the actual ``process_due_drafts`` sender with the
real X adapter behind invented SDK factories. NHC HTTP is an invented transport
serving an imaginary storm over imaginary places. No network, model, Gist or X.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import io
import json

from freezegun import freeze_time
import pytest

from src.data import nhc_advisory as source
from src.editorial import approval, revisions, warning_automatic as wa
from src.editorial.nhc_advisory import validate_capture
from src.editorial.nhc_advisory_runtime import AdvisoryOwner, advisory_owner_scope
from src.orchestrator.sources.nhc_advisory import run_nhc_advisory
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle
from tests import nhc_advisory_helpers as h
from tests.gist_media_helpers import install_fake_x
from tests.nhc_advisory_pipeline_helpers import COPY, Transport, configure, stage_fakes

EPOCH = "invented-warning-epoch-0001"
FLAGS = ("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "THEHEAT_OFFICIAL_WARNING_AUTO_TEXT", "THEHEAT_NWS_WARNING_AUTO_TEXT")
DUE = h.NOW + timedelta(minutes=35)
CORRECTED = h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4")))


@pytest.fixture
def world(monkeypatch):
    for name in FLAGS + ("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "THEHEAT_PRODUCTION_PAUSED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", EPOCH)
    return monkeypatch


def produce(patch, transport, *, state=None, copy=COPY, nomination=None):
    """The real runner then the real drain/admission at the invented capture time."""
    configure(patch, transport, nomination=nomination or h.nominated(freshness_minutes=60))
    sent: list[str] = []
    writer, safety, fact, critic = stage_fakes(sent, copy=copy)
    patch.setattr(pipeline.writer, "write_tweet", writer)
    patch.setattr(pipeline, "run_safety_pipeline", safety)
    patch.setattr(pipeline.fact_check, "fact_check", fact)
    patch.setattr(pipeline.critic, "critic_review", critic)
    state = deepcopy(DEFAULT_STATE) if state is None else state
    run: dict = {"sources": []}
    with freeze_time(h.NOW, tick=True), advisory_owner_scope(AdvisoryOwner()), redirect_stdout(io.StringIO()):
        result = run_nhc_advisory(state, run)
        _drain_and_write_triage_queue(state, run)
    return state, {"result": result, "sent": sent, "run": run}


def send_due(patch, state, transport, *, at=DUE):
    fake = install_fake_x(patch)
    patch.setattr(fake.posting, "_hot10_media_for_draft", lambda _draft: (None, None))
    patch.setattr(source, "_http_get", transport)
    with freeze_time(at, tick=True), advisory_owner_scope(AdvisoryOwner()), redirect_stdout(io.StringIO()):
        fake.posting.process_due_drafts(state)
    return fake


def armed(patch, transport=None):
    patch.setenv("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "1")
    state, seen = produce(patch, transport or Transport())
    draft = state["drafts"][0]
    assert draft["approval_policy"]["key"] == "nhc_advisory_auto_text" and draft["approval_mode"] == "policy_auto"
    return state, draft


# ------------------------------------------------------------------ 04.2 flags/policies/projections

@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "1 "])
def test_flags_are_exact_one_and_default_off(world, value):
    for kind, family in wa.FAMILIES.items():
        if value is None:
            world.delenv(family["flag"], raising=False)
        else:
            world.setenv(family["flag"], value)
        policy = approval.recommend_approval_policy(kind, signal_total=99, candidate_score={"total": 99})
        assert policy.mode == "manual_only" and policy.can_auto_approve is False
    assert set(wa.inventory_flags().values()) == {False}
    assert all(row["enabled"] is False and row["manual_review"] == "always_available"
               for row in wa.runtime_projection().values())


def test_each_family_flag_is_independent(world):
    world.setenv("THEHEAT_NWS_WARNING_AUTO_TEXT", "1")
    keys = {kind: approval.recommend_approval_policy(kind, signal_total=0).key for kind in wa.FAMILIES}
    assert keys == {"nhc_advisory": "nhc_advisory_manual", "official_warning": "official_warning_manual",
                    "severe_weather": "nws_warning_auto_text"}
    assert wa.inventory_flags() == {"nhc_advisory_auto_text_enabled": False,
                                    "official_warning_auto_text_enabled": False,
                                    "nws_warning_auto_text_enabled": True}
    from src.runtime_inventory import collect_runtime_inventory
    assert collect_runtime_inventory("alerts")["flags"]["nws_warning_auto_text_enabled"] is True


# ------------------------------------------------------------------ 04.1/04.6 actual runner -> admission -> due send

def test_flag_off_keeps_the_ordinary_manual_draft(world):
    state, seen = produce(world, Transport())
    draft = state["drafts"][0]
    assert seen["result"]["status"] == "queued" and draft["approval_policy"]["mode"] == "manual_only"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft
    assert draft["review_context"]["warning_consequence_brief"]["assertion"] == \
        "attributed_forecast_threat_not_observed_harm"
    fake = send_due(world, state, Transport())
    assert fake.calls == [] and draft["status"] == "pending"


def test_opt_in_arms_after_admission_then_posts_once_after_a_fresh_source_check(world):
    transport = Transport()
    world.setenv("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "1")
    state, seen = produce(world, transport)
    draft = state["drafts"][0]
    assert draft["approval_mode"] == "policy_auto" and seen["sent"] == ["writer", "safety", "fact_check", "critic"] and len(draft["text"]) <= 200
    fake = send_due(world, state, transport)
    assert fake.calls == [("create", COPY, {})] and fake.safety.call_count == 1
    assert draft["status"] == "posted" and state["publish_ledger"][draft["event_id"]]["tweet_id"]
    assert transport.calls.count(source.INDEX_URL) >= 2  # due entry and after the durable intent
    again = send_due(world, state, Transport(), at=DUE + timedelta(minutes=30))
    assert again.calls == []


@pytest.mark.parametrize("change,reason", [
    (lambda mp, t: t.responses.__setitem__(h.URL, (200, {}, CORRECTED)), "nhc_advisory_current_source_changed"),
    (lambda mp, t: t.responses.__setitem__(h.URL, ConnectionError("invented outage")),
     "nhc_advisory_current_source_unavailable"),
    (lambda mp, t: mp.setenv("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "0"), "warning_auto_text_disabled"),
    (lambda mp, t: mp.setenv("THEHEAT_PRODUCTION_PAUSED", "1"), "warning_auto_production_paused"),
], ids=["changed-source", "unavailable-check", "flag-off", "paused"])
def test_due_holds_stop_before_safety_and_x(world, change, reason):
    transport = Transport()
    state, draft = armed(world, transport)
    change(world, transport)
    fake = send_due(world, state, transport)
    assert fake.calls == [] and fake.safety.call_count == 0
    assert draft["approval_mode"] == "manual" and reason in draft["post_error"] and "auto_approve_at" not in draft


def test_paused_policy_retired_epoch_and_attachment_never_send(world):
    state, draft = armed(world)
    world.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    assert send_due(world, state, Transport()).calls == [] and draft["status"] == "pending"
    world.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    world.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "invented-warning-epoch-0002")
    assert send_due(world, state, Transport()).calls == [] and draft["approval_mode"] == "manual"
    image = deepcopy(armed(world)[1])
    assert wa.auto_text_hold({**image, "media_attachment": {"kind": "invented"}}) == "warning_auto_text_only"


def test_held_draft_stays_inspectable_and_manually_reviewable_without_stale_passes(world):
    transport = Transport()
    state, draft = armed(world, transport)
    world.setenv("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "0")
    send_due(world, state, transport)
    assert "approval_binding" not in draft and "auto_approve_at" not in draft
    view = wa.operator_view(draft)
    assert view["manual_review"] == "available" and view["brief"]["places"][0]["name"] == "Example Province"
    # A later due run never revives the old automatic pass.
    assert send_due(world, state, transport, at=DUE + timedelta(minutes=5)).calls == []
    # The ordinary manual path: explicit invented human review + approval, then the manual sender.
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-warning-intent")
    draft.update(status="approved", publish_intent_id="invented-warning-intent")
    fake = install_fake_x(world)
    world.setattr(fake.posting, "_hot10_media_for_draft", lambda _d: (None, None))
    world.setattr(source, "_http_get", transport)
    from src import state as real_state
    fake.storage.record_event.side_effect = real_state.record_event
    for name, value in (("DRAFT_ID", draft["id"]), ("TWEET_TEXT", draft["text"]),
                        ("PUBLISH_INTENT_ID", "invented-warning-intent")):
        world.setenv(name, value)
    with freeze_time(DUE + timedelta(minutes=6), tick=True), advisory_owner_scope(AdvisoryOwner()), \
            redirect_stdout(io.StringIO()):
        fake.posting.run_manual_tweet(state)
    assert fake.calls == [("create", COPY, {})]


# ------------------------------------------------------------------ 04.4 qualified consequence copy

def _bundle(**page_changes):
    advisory = page_changes.get("advisory", "34")
    evidence = validate_capture(h.capture(page_bytes=h.page(h.bulletin(**page_changes)) if page_changes else None,
                                          index_bytes=h.index(advisory=advisory)),
                                h.selected(advisory=advisory, freshness_minutes=60), now=h.NOW)
    return capture_bundle(build_nhc_advisory_bundle(evidence)).payload()


def test_brief_is_attributed_timed_placed_and_separates_motion_from_intensity():
    brief = wa.consequence_brief("nhc_advisory", _bundle(context="The depression is moving toward the northwest "
                                                                   "near 8 mph."))
    assert brief["attribution_names"][0] == "NHC" and brief["statements"][0]["class"] == "forecast_threat"
    assert brief["timing"]["upstream_expiry"] is None and brief["places"] == [
        {"name": "Example Province", "country": "ZZ"}]
    speeds = {(row["value"], row["unit"]): row["class"] for row in brief["speeds"]}
    assert speeds[(30.0, "mph")] == "wind_intensity" and speeds[(8.0, "mph")] == "storm_motion"


@pytest.mark.parametrize("copy,reason", [
    (COPY, None),
    ("Example Province flooded as rain fell, NHC says.", "warning_auto_observed_harm_claim"),
    ("Life-threatening flash flooding could hit Example Province tonight, NHC forecasts.",
     "warning_auto_unsupported_consequence"),
    ("A Category 3 storm could bring flash flooding to Example Province, NHC forecasts.",
     "warning_auto_unsupported_consequence"),
    ("Winds of 8 mph could bring flash flooding to Example Province tonight, NHC forecasts.",
     "warning_auto_motion_intensity_conflated"),
    ("The storm moving at 30 mph could flood Example Province roads tonight, NHC forecasts.",
     "warning_auto_motion_intensity_conflated"),
    ("Winds of 55 mph could hit Example Province tonight, NHC forecasts.", "warning_auto_unsupported_speed"),
    ("Up to 3 inches of rain will fall on Example Province tonight.", "warning_auto_qualifier_missing"),
])
def test_copy_rules_never_manufacture_impact(copy, reason):
    brief = wa.consequence_brief("nhc_advisory", _bundle(context="The depression is moving toward the northwest "
                                                                   "near 8 mph."))
    assert wa.copy_hold(copy, brief) == reason


# ------------------------------------------------------------------ 04.3/04.5 episodes, updates, supersession

def _draft(bundle, *, status="pending", draft_id="d"):
    return {"id": draft_id, "type": "nhc_advisory", "event_id": bundle["event_id"], "status": status, "text": COPY,
            "review_context": {"two_bot": {"bundle": bundle}}}


def test_episode_rules_first_material_update_repeat_unknown_and_supersession(world):
    world.setenv("THEHEAT_NHC_ADVISORY_AUTO_TEXT", "1")
    first = _bundle()
    same_text = _bundle(advisory="35", title=f"Tropical Storm {h.NAME} Advisory Number  35")
    changed = _bundle(advisory="35", hazard=h.HAZARD.replace("1 to 3", "2 to 4"))
    posted = _draft(first, status="posted", draft_id="old")
    state = {"drafts": [posted], "posted_events": [first["event_id"]],
             "publish_ledger": {first["event_id"]: {"tweet_id": "invented-1"}}}
    assert wa.episode_hold(_draft(first, draft_id="repeat"), state) == "warning_episode_already_published"
    assert wa.episode_hold(_draft(same_text, draft_id="tier"), state) == "warning_update_not_material"
    assert wa.episode_hold(_draft(changed, draft_id="material"), state) is None
    unknown = {"drafts": [_draft(first, status="approved", draft_id="old")],
               "publish_ledger": {first["event_id"]: {"phase": "submitted"}}}
    assert wa.episode_hold(_draft(changed, draft_id="new"), unknown) == "warning_prior_delivery_unknown"
    newer_pending = {"drafts": [_draft(changed, draft_id="newer")]}
    assert wa.episode_hold(_draft(first, draft_id="older"), newer_pending) == "warning_superseded_by_newer_update"
    # Another storm (different issuer-side identity) with the same place never merges.
    other = _bundle(advisory="35", hazard=h.HAZARD.replace("1 to 3", "2 to 4"))
    other["raw_signal_dump"]["nhc_advisory"]["nomination"]["storm_id"] = "EP502026"
    assert wa.episode_hold(_draft(other, draft_id="other"), state) is None


def test_runner_buys_no_writer_for_an_unchanged_published_statement(world):
    state, _ = produce(world, Transport())
    draft = state["drafts"][0]
    draft["status"] = "posted"
    state["posted_events"].append(draft["event_id"])
    state["publish_ledger"][draft["event_id"]] = {"tweet_id": "invented-1"}
    tier_only = h.page(h.bulletin(advisory="35", title=f"Tropical Storm {h.NAME} Advisory Number  35"))
    later = Transport({source.INDEX_URL: (200, {}, h.index(advisory="35")), h.URL: (200, {}, tier_only)})
    state, seen = produce(world, later, state=state, nomination=h.nominated(advisory="35", freshness_minutes=60))
    assert seen["result"] == {"status": "held", "reason": "warning_update_not_material", "promoted": 0}
    assert seen["sent"] == [] and len(state["drafts"]) == 1


def test_official_and_nws_families_build_typed_briefs_with_their_own_issuers():
    official = {"event_id": "official_warning:x", "raw_signal_dump": {
        "source_name": "Invented Met Service", "official_warning": {
            "source_utf8": "Gale warning for Example Bay: gusts to 50 km/h expected.",
            "metadata_utf8": json.dumps({"issuer_id": "zz-invented-met", "report_id": "R1", "issued_at": "2026-10-29T20:00:00Z",
                                         "valid_until": "2026-10-30T06:00:00Z",
                                         "warning": {"text": "Gale warning for Example Bay: gusts to 50 km/h expected."},
                                         "place": {"name": "Example Bay", "country": "ZZ"}})}}}
    nws = {"event_id": "nws_x", "raw_signal_dump": {"source_evidence": {"feature": {"properties": {
        "event": "Hurricane Warning", "areaDesc": "Example Bay", "sent": "2026-10-29T20:00:00-05:00",
        "headline": "Hurricane Warning issued", "description": "Hurricane conditions are expected.",
        "senderName": "NWS Invented Office"}}}}}
    first = wa.consequence_brief("official_warning", official)
    second = wa.consequence_brief("severe_weather", nws)
    assert first["episode"]["key"][0] == "zz-invented-met" and second["episode"]["key"][0] == "nws"
    assert first["episode"]["key"][2] == second["episode"]["key"][2] == "example bay"  # same name, separate issuers
    assert wa.copy_hold("Invented Met Service warns gusts to 50 km/h are expected in Example Bay.", first) is None
    assert wa.copy_hold("Gusts reached 50 km/h and damaged Example Bay, Invented Met Service says.", first) == \
        "warning_auto_observed_harm_claim"
    assert wa.copy_hold("NWS warns hurricane conditions are expected in Example Bay.", second) is None


# ------------------------------------------------------------------ official_warning: supplied owner, same rules

def test_supplied_official_warning_arms_posts_once_and_holds_without_its_owner(world):
    from src.editorial.scoring import EditorialScore
    from src.editorial.warning_runtime import WarningSource, warning_source_scope
    from src.orchestrator.sources.official_warning import run_official_warning
    from tests import warning_helpers as wh
    from tests.warning_journey_helpers import COPY as WARNING_COPY, source

    world.setenv("THEHEAT_OFFICIAL_WARNING_AUTO_TEXT", "1")
    configure(world, Transport())  # Offline provider profile; the NHC opt-in is irrelevant here.
    world.setenv("THEHEAT_NHC_ADVISORY_ACQUISITION", "0")
    sent_stages: list[str] = []
    writer, safety, fact, critic = stage_fakes(sent_stages, copy=WARNING_COPY)
    for owner, name, fake_stage in ((pipeline.writer, "write_tweet", writer), (pipeline, "run_safety_pipeline", safety),
                                    (pipeline.fact_check, "fact_check", fact), (pipeline.critic, "critic_review", critic)):
        world.setattr(owner, name, fake_stage)
    score = EditorialScore("official_warning", 80, 80, 80, 80, 80, 0, 80, 60, ["Explicit invented nomination."])
    state = deepcopy(DEFAULT_STATE)
    selected = source()  # The supplied owner's own clock dates the packet.
    with redirect_stdout(io.StringIO()):
        assert run_official_warning(state, None, source=selected, score=score)["promoted"] == 1
        with warning_source_scope(selected):
            _drain_and_write_triage_queue(state, None)
    draft = state["drafts"][0]
    assert draft["approval_policy"]["key"] == "official_warning_auto_text" and draft["approval_mode"] == "policy_auto"
    assert draft["review_context"]["warning_consequence_brief"]["places"][0]["name"] == "Example Island"
    held_state = deepcopy(state)

    def due(target, scope):
        fake = install_fake_x(world)
        world.setattr(fake.posting, "_hot10_media_for_draft", lambda _d: (None, None))
        later = datetime.now(UTC) + timedelta(minutes=35)  # A plain module clock; freezegun would replace
        world.setattr(fake.posting, "_utc_now", lambda: later)  # the datetime type the packet validator pins.
        with scope, redirect_stdout(io.StringIO()):
            fake.posting.process_due_drafts(target)
        return fake

    sent = due(state, warning_source_scope(source()))
    assert sent.calls == [("create", WARNING_COPY, {})] and draft["status"] == "posted"
    absent = due(held_state, warning_source_scope(WarningSource(lambda: None, clock=lambda: wh.NOW)))
    assert absent.calls == [] and "warning_current_source_unavailable" in held_state["drafts"][0]["post_error"]
