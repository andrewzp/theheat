"""Milestone B: PM2.5/dust forecasts as opt-in, guarded automatic TEXT supply.

B1 the forecast window contract (exact day, zone, grid, 24 samples, units); B2 one
bounded current re-read of the same city/window at paid generation, admission and
the pre-safety automatic send; B3 separate default-off flags (exact "1"), text only,
forecast-qualified copy, global epoch/pause; B4 episode identities (first post or a
rise; an unknown delivery blocks), and a dust peak never compared with a 24-hour
mean or WHO period.

Invented values only, on registered catalogue cities. Named fake boundaries in
tests/live_content_harness.py; no network, model, Gist or X.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.data import air_quality as source
from src.data import air_quality_contract as contract
from src.data import air_quality_current as current
from src.data import places
from src.data.source_status import SourceFetchError
from src.state import DEFAULT_STATE
from tests import live_content_harness as h

DAY = "2026-10-29"
T0 = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
EPOCH = "invented-aq-epoch-0001"
PM25_COPY = "Lahore's PM2.5 is forecast to average 250 µg/m³ today, about 17 times the WHO 24-hour guideline, per CAMS model data."
DUST_COPY = "Dust is forecast to peak near 2,000 µg/m³ over Lahore today, per CAMS model data."


def city(name: str) -> dict:
    row = h.catalogue_rows([name])[0]
    return {**row, **places.place_for_row(row)}


LAHORE, DELHI = city("Lahore"), city("Delhi")
LAHORE_KEY = h.coordinate_key(LAHORE["lat"], LAHORE["lon"])
HAZARD: dict[str, Any] = {"pm25": 250.0, "dust": 2000.0, "pm10": 90.0}  # Tier 2 PM2.5 and tier 2 dust.


def observation(**values):
    payload = h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **{**HAZARD, **values})
    return source._parse_single_location(payload, "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], DAY,
                                         requested_at=f"{DAY}T12:00:00Z", retrieved_at=f"{DAY}T12:00:01Z")


def pm25_bundle(**values):
    from src.two_bot.intern.air_quality import build_pm25_hazard_bundle

    event = source.detect_pm25_hazard(observation(**values))
    assert event is not None
    return build_pm25_hazard_bundle(event)


def dust_bundle(**values):
    from src.two_bot.intern.air_quality import build_dust_event_bundle

    event = source.detect_dust_event(observation(**values))
    assert event is not None
    return build_dust_event_bundle(event)


# ---------------------------------------------------------------- B1: the forecast contract


def test_complete_window_keeps_day_zone_grid_units_and_24_samples():
    obs = observation()
    packet = obs.forecast_window
    assert packet["date"] == DAY and packet["timezone"] == "GMT" and packet["utc_offset_seconds"] == 0
    assert packet["requested_location"] == {"city": "Lahore", "country": "Pakistan", "lat": 31.55, "lon": 74.35}
    assert packet["grid_location"] == [31.55, 74.35] and len(packet["hours"]) == 24
    assert packet["series"]["pm2_5"]["unit"] == "μg/m³" and obs.pm25_24h_mean == 250.0 and obs.dust_daily_max == 2000.0


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(latitude=p["latitude"] + 1.0),  # A grid cell far from the requested point.
    lambda p: p["hourly"]["time"].__setitem__(5, p["hourly"]["time"][4]),  # A duplicated hour.
    lambda p: p["hourly"]["time"].pop(),  # A missing hour.
    lambda p: p.update(utc_offset_seconds=3600),  # An offset inconsistent with the zone.
    lambda p: p["hourly"]["time"].__setitem__(0, "2026-10-28T23:00"),  # A wrong-day sample.
], ids=["far-grid", "duplicate-hour", "missing-hour", "inconsistent-offset", "wrong-day"])
def test_inconsistent_location_or_time_is_withheld(mutate):
    payload = h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD)
    mutate(payload)
    assert source._parse_single_location(payload, "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], DAY,
                                         requested_at=f"{DAY}T12:00:00Z", retrieved_at=f"{DAY}T12:00:01Z") is None


@pytest.mark.parametrize(("variable", "bad"), [("pm2_5", float("nan")), ("pm2_5", None), ("pm2_5", -1.0)],
                         ids=["nan", "missing-sample", "negative"])
def test_incomplete_or_invalid_series_never_becomes_a_value(variable, bad):
    payload = h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD)
    payload["hourly"][variable][7] = bad
    obs = source._parse_single_location(payload, "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], DAY,
                                        requested_at=f"{DAY}T12:00:00Z", retrieved_at=f"{DAY}T12:00:01Z")
    assert obs is not None and obs.pm25_24h_mean is None and source.detect_pm25_hazard(obs) is None


def test_wrong_units_and_dst_days_are_not_qualified():
    payload = h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD)
    payload["hourly_units"]["pm2_5"] = "mg/m³"
    assert observation().pm25_24h_mean == 250.0
    obs = source._parse_single_location(payload, "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], DAY,
                                        requested_at=f"{DAY}T12:00:00Z", retrieved_at=f"{DAY}T12:00:01Z")
    assert obs is not None and obs.pm25_24h_mean is None
    dst = h.aq_payload(LAHORE["lat"], LAHORE["lon"], "2026-10-25", zone="Europe/London", offset=3600, **HAZARD)
    assert source._parse_single_location(dst, "Lahore", "Pakistan", LAHORE["lat"], LAHORE["lon"], "2026-10-25",
                                         requested_at="2026-10-25T12:00:00Z", retrieved_at="2026-10-25T12:00:01Z") is None


def test_current_series_must_match_the_retained_day_zone_and_grid():
    packet = observation().forecast_window
    same = h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **HAZARD)
    assert contract.current_series(same, packet)["pm2_5"] == packet["series"]["pm2_5"]
    for change in ({"timezone": "Asia/Karachi", "utc_offset_seconds": 18000}, {"latitude": 31.6}):
        with pytest.raises(SourceFetchError):
            contract.current_series({**same, **change}, packet)
    with pytest.raises(SourceFetchError):
        contract.current_series(h.aq_payload(LAHORE["lat"], LAHORE["lon"], "2026-10-30", **HAZARD), packet)


# ---------------------------------------------------------------- B2: one bounded current re-read


class Recorder:
    def __init__(self, body: bytes = b"", error: Exception | None = None):
        self.calls: list[dict] = []
        self.body, self.error = body, error

    def __call__(self, url, **options):
        self.calls.append({"url": url, **options})
        if self.error is not None:
            raise self.error
        body = self.body
        return SimpleNamespace(iter_content=lambda chunk_size: [body[i:i + chunk_size] for i in range(0, len(body), chunk_size)],
                               close=lambda: None)


def reread(**values) -> Recorder:
    return Recorder(json.dumps(h.aq_payload(LAHORE["lat"], LAHORE["lon"], DAY, **{**HAZARD, **values})).encode())


def test_disabled_kinds_never_fetch(monkeypatch):
    monkeypatch.delenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", raising=False)
    recorder = reread()
    assert current.generation_hold(pm25_bundle(), T0, transport=recorder) is None
    for value in ("true", "yes", " 1", "1 ", "on"):
        monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", value)
        assert current.generation_hold(pm25_bundle(), T0, transport=recorder) is None
    assert recorder.calls == []


def test_one_bounded_request_for_exactly_the_retained_city_and_day(monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    recorder = reread()
    assert current.generation_hold(pm25_bundle(), T0, transport=recorder) is None
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == contract.SOURCE_URL and call["timeout"] == 10.0 and call["attempts"] == 1
    assert call["stream"] is True
    assert call["params"] == {"latitude": "31.55", "longitude": "74.35", "hourly": "pm2_5,pm10,dust,aerosol_optical_depth,us_aqi",
                              "timezone": "auto", "domains": "auto", "start_date": DAY, "end_date": DAY}


@pytest.mark.parametrize(("recorder", "code"), [
    (lambda: reread(pm25=251.0), "air_quality_source_changed"),
    (lambda: reread(pm25=None), "air_quality_source_changed"),
    (lambda: Recorder(error=TimeoutError("invented")), "air_quality_source_unavailable"),
    (lambda: Recorder(b"{" + b" " * current.MAX_BODY_BYTES + b"}"), "air_quality_source_oversize"),
    (lambda: Recorder(json.dumps(h.aq_payload(31.55, 74.35, DAY, zone="Asia/Karachi", offset=18000, **HAZARD)).encode()),
     "air_quality_source_shape"),
    (lambda: Recorder(b"not json"), "air_quality_source_shape"),
], ids=["changed", "now-missing", "unavailable", "oversize", "zone-changed", "malformed"])
def test_any_current_difference_or_failure_holds_after_exactly_one_request(monkeypatch, recorder, code):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    transport = recorder()
    assert current.generation_hold(pm25_bundle(), T0, transport=transport) == code
    assert len(transport.calls) == 1  # Never a retry, another city or another day.


def test_dust_compares_its_pm10_anchor_only_when_supplied(monkeypatch):
    monkeypatch.setenv("THEHEAT_DUST_FORECAST_AUTO_TEXT", "1")
    assert current.generation_hold(dust_bundle(), T0, transport=reread(pm10=91.0)) == "air_quality_source_changed"
    assert current.generation_hold(dust_bundle(pm10=None), T0, transport=reread(pm10=91.0)) is None


def test_ended_window_and_stale_retained_source_hold_without_any_request(monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    recorder = reread()
    assert current.generation_hold(pm25_bundle(), datetime(2026, 10, 30, 0, 0, tzinfo=UTC), transport=recorder) == \
        "air_quality_window_ended"
    assert current.generation_hold(pm25_bundle(), datetime(2026, 10, 29, 18, 1, tzinfo=UTC), transport=recorder) == \
        "air_quality_source_stale"
    assert current.generation_hold(pm25_bundle(), datetime(2026, 10, 29, 11, 0, tzinfo=UTC), transport=recorder) == \
        "air_quality_source_future"
    assert recorder.calls == []
    assert current.static_hold(pm25_bundle(), datetime(2026, 10, 29, 23, 0, tzinfo=UTC), automatic=False) is None


# ---------------------------------------------------------------- B2/B3: the real path, in process


@pytest.fixture
def aq(tmp_path, monkeypatch):
    from freezegun import freeze_time

    transport = h.Transport(air_quality={LAHORE_KEY: dict(HAZARD)}, gist={"state.json": json.dumps(deepcopy(DEFAULT_STATE))},
                            now=lambda: datetime.now(UTC))
    transport.install(monkeypatch.setattr)
    script = h.ModelScript(copy=PM25_COPY, copies={"air_quality_hazard": PM25_COPY, "dust_event": DUST_COPY})
    script.install(monkeypatch.setattr)
    for name, value in h.MODEL_ENV.items():
        monkeypatch.setenv(name, value)
    from src.voice import safety
    monkeypatch.setattr(safety, "GEMINI_API_KEY", h.INVENTED_TOKEN)
    monkeypatch.setattr(safety, "_SAFETY_CACHE", type(safety._SAFETY_CACHE)())
    monkeypatch.setattr("src.data.air_quality._pacing_sleep", lambda _s: None)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", EPOCH)
    monkeypatch.setenv("THEHEAT_AQ_DUST_ENABLED", "0")
    for name in ("THEHEAT_PM25_FORECAST_AUTO_TEXT", "THEHEAT_DUST_FORECAST_AUTO_TEXT", "OPENAQ_API_KEY",
                 "THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "THEHEAT_TRIAGE_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    from src.orchestrator import candidate_budget
    settled: list = []
    real_settle = candidate_budget.CandidateBudget.settle

    def settle(self, key, *, writer_started):
        settled.append((key, writer_started))
        return real_settle(self, key, writer_started=writer_started)
    monkeypatch.setattr(candidate_budget.CandidateBudget, "settle", settle)
    with freeze_time(T0, tick=True):
        yield SimpleNamespace(transport=transport, script=script, settled=settled)


def alerts(world, state=None) -> Any:
    """The real air-quality source runner, then the ordinary drain (one operation)."""
    from src.orchestrator.candidate_budget import CandidateBudget
    from src.orchestrator.sources.air_quality import run_air_quality
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue

    from src.orchestrator.suppression import _activate_suppression_ctx

    state = state if state is not None else deepcopy(DEFAULT_STATE)
    run: dict = {"id": "run-aq-b", "sources": []}
    world.script.requests.clear()
    _activate_suppression_ctx(state, source="air_quality", run_id=run["id"])  # As run_alerts does.
    run_air_quality(state, run, [LAHORE, DELHI])
    _drain_and_write_triage_queue(state, run, candidate_budget=CandidateBudget.for_operation("alerts"))
    return state


def test_flags_default_off_keep_air_quality_manual_with_no_extra_fetch(aq):
    state = alerts(aq)
    draft = state["drafts"][0]
    assert draft["type"] == "air_quality_hazard" and draft["approval_policy"]["mode"] == "manual_only"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft
    assert "automatic_source_hold" not in draft and len(aq.transport.aq_calls) == 1  # The sweep only.


def test_pm25_flag_arms_policy_auto_only_for_pm25_after_three_bounded_reads(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    monkeypatch.setenv("THEHEAT_AQ_DUST_ENABLED", "1")
    state = alerts(aq)
    by_type = {d["type"]: d for d in state["drafts"]}
    pm25, dust = by_type["air_quality_hazard"], by_type["dust_event"]
    assert pm25["approval_policy"]["key"] == "pm25_forecast_auto_text" and pm25["approval_mode"] == "policy_auto"
    assert pm25["auto_approve_at"] and "automatic_source_hold" not in pm25
    assert dust["approval_policy"]["mode"] == "manual_only" and dust["approval_mode"] == "manual"  # Separate flag.
    # Sweep, then the PM2.5 candidate's generation and admission re-reads; the dust one never re-reads.
    assert [c["points"] for c in aq.transport.aq_calls] == [2, 1, 1]


def test_source_change_before_the_writer_holds_and_keeps_the_slot(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    original = aq.transport.send

    def changed_after_sweep(adapter, request, **options):
        if len(aq.transport.aq_calls) == 1:
            aq.transport.air_quality[LAHORE_KEY] = {**HAZARD, "pm25": 260.0}
        return original(adapter, request, **options)
    aq.transport.send = changed_after_sweep
    state = alerts(aq)
    assert state["drafts"] == [] and aq.script.stages() == []
    kill = next(row for row in state["suppressions"] if row.get("stage") == "air_quality_source")
    assert kill["reasons"][0] == "air_quality_source_changed"
    assert aq.settled[-1][1] is True  # The slot is kept: a hold cannot buy another city.


def test_source_change_after_the_writer_is_never_saved_with_old_evidence(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    original = aq.transport.send

    def changed_after_generation(adapter, request, **options):
        if len(aq.transport.aq_calls) == 2:
            aq.transport.air_quality[LAHORE_KEY] = {**HAZARD, "pm25": 240.0}
        return original(adapter, request, **options)
    aq.transport.send = changed_after_generation
    state = alerts(aq)
    assert state["drafts"] == [] and aq.script.stages() == ["writer", "safety", "fact_check", "critic"]
    assert len(aq.transport.aq_calls) == 3


def test_unavailable_reread_at_admission_keeps_a_manual_draft(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    original = aq.transport.send

    def outage_at_admission(adapter, request, **options):
        if len(aq.transport.aq_calls) == 2:
            aq.transport.aq_failure = "unavailable"
        return original(adapter, request, **options)
    aq.transport.send = outage_at_admission
    draft = alerts(aq)["drafts"][0]
    assert draft["automatic_source_hold"] == "air_quality_source_unavailable"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft


def test_copy_without_a_forecast_qualifier_stays_manual(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    aq.script.copies["air_quality_hazard"] = "Lahore's PM2.5 averages 250 µg/m³ today, about 17 times the WHO 24-hour guideline, per CAMS."
    draft = alerts(aq)["drafts"][0]  # The invented checks pass it; automatic eligibility does not.
    assert draft["automatic_source_hold"] == "air_quality_auto_missing_forecast_qualifier"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft


def send_due(aq, monkeypatch, state, at: datetime):
    from freezegun import freeze_time
    from tests.gist_media_helpers import install_fake_x

    fake = install_fake_x(monkeypatch)
    monkeypatch.setattr(fake.posting, "_hot10_media_for_draft", lambda _draft: (None, None))  # Text only.
    aq.transport.aq_calls.clear()
    with freeze_time(at, tick=True):
        fake.posting.process_due_drafts(state)
    return fake


def armed(aq, monkeypatch) -> Any:
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    state = alerts(aq)
    assert state["drafts"][0]["approval_mode"] == "policy_auto"
    return state


def test_due_text_rereads_once_before_safety_then_posts(aq, monkeypatch):
    state = armed(aq, monkeypatch)
    fake = send_due(aq, monkeypatch, state, T0 + timedelta(minutes=40))
    assert fake.calls == [("create", PM25_COPY, {})] and fake.safety.call_count == 1
    assert [c["points"] for c in aq.transport.aq_calls] == [1]  # Not again after the durable intent.
    assert state["drafts"][0]["status"] == "posted"


@pytest.mark.parametrize(("change", "reason"), [
    (lambda aq, mp: aq.transport.air_quality.__setitem__(LAHORE_KEY, {**HAZARD, "pm25": 230.0}), "air_quality_source_changed"),
    (lambda aq, mp: mp.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "0"), "air_quality_auto_text_disabled"),
    (lambda aq, mp: setattr(aq.transport, "aq_failure", "unavailable"), "air_quality_source_unavailable"),
], ids=["source-changed", "flag-off", "source-unavailable"])
def test_send_time_holds_never_reach_safety_or_x(aq, monkeypatch, change, reason):
    state = armed(aq, monkeypatch)
    change(aq, monkeypatch)
    fake = send_due(aq, monkeypatch, state, T0 + timedelta(minutes=40))
    draft = state["drafts"][0]
    assert fake.calls == [] and fake.safety.call_count == 0
    assert draft["approval_mode"] == "manual" and reason in draft["post_error"]


def test_ended_window_and_retired_epoch_hold(aq, monkeypatch):
    state = armed(aq, monkeypatch)
    late = deepcopy(state)
    fake = send_due(aq, monkeypatch, late, datetime(2026, 10, 30, 0, 5, tzinfo=UTC))
    assert fake.calls == [] and "air_quality_window_ended" in (late["drafts"][0].get("post_error") or "")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "invented-aq-epoch-0002")
    fake = send_due(aq, monkeypatch, state, T0 + timedelta(minutes=40))
    assert fake.calls == [] and state["drafts"][0]["approval_mode"] == "manual"


def test_an_attachment_never_gains_automatic_authority(aq, monkeypatch):
    state = armed(aq, monkeypatch)
    draft = state["drafts"][0]
    assert current.auto_text_hold({**draft, "media_attachment": {"kind": "invented"}}, state, T0, live=False) == \
        "air_quality_auto_text_only"


def test_dashboard_never_schedules_an_air_quality_forecast():
    route = (h.ROOT / "dashboard/app/api/drafts/route.js").read_text()
    assert '["air_quality_hazard", "dust_event"].includes(draft.type)' in route and '"air_quality_auto_owner"' in route


# ---------------------------------------------------------------- B4: episode anti-spam


def _ledger(event_id: str, *, tweet_id: str | None, phase: str) -> dict:
    return {event_id: {"tweet_id": tweet_id, "phase": phase, "text": "invented earlier post", "at": "2026-10-29T08:00:00Z"}}


def pm25_event_id(tier: int, day: str = DAY) -> str:
    return f"pm25_{places.event_location_key('Lahore', 'Pakistan', 31.55, 74.35)}_{day}_tier{tier}"


def test_unchanged_repeat_poll_and_fall_create_no_new_candidate(aq):
    first = alerts(aq)
    assert len(first["drafts"]) == 1 and first["air_quality_pm25_tiers"]
    repeat = alerts(aq, first)  # Same tier and day; only the retrieval timestamp differs.
    assert len(repeat["drafts"]) == 1 and aq.script.stages() == []
    aq.transport.air_quality[LAHORE_KEY] = {**HAZARD, "pm25": 160.0}  # Fall to tier 1.
    fell = alerts(aq, repeat)
    assert len(fell["drafts"]) == 1 and aq.script.stages() == []


def test_rise_after_a_published_tier_is_a_meaningful_update(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    state = deepcopy(DEFAULT_STATE)
    state["publish_ledger"] = _ledger(pm25_event_id(1), tweet_id="invented-x-earlier", phase="confirmed")
    state["posted_events"] = [pm25_event_id(1)]
    state["air_quality_pm25_tiers"] = {places.event_location_key("Lahore", "Pakistan", 31.55, 74.35): {"tier": 1, "date": DAY}}
    draft = alerts(aq, state)["drafts"][0]
    assert draft["event_id"] == pm25_event_id(2) and draft["approval_mode"] == "policy_auto"


def test_previous_unknown_delivery_blocks_a_new_candidate_and_automatic_send(aq, monkeypatch):
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    state = deepcopy(DEFAULT_STATE)
    state["publish_ledger"] = _ledger(pm25_event_id(1), tweet_id=None, phase="unknown")
    after = alerts(aq, state)
    assert after["drafts"] == [] and aq.script.stages() == []
    assert current.episode_hold({"event_id": pm25_event_id(2)}, state) == "air_quality_prior_delivery_unknown"


def test_same_or_lower_tier_after_publication_is_not_automatic(aq):
    state = deepcopy(DEFAULT_STATE)
    state["publish_ledger"] = _ledger(pm25_event_id(3), tweet_id="invented-x-earlier", phase="confirmed")
    assert current.episode_hold({"event_id": pm25_event_id(2)}, state) == "air_quality_episode_already_published"
    assert current.episode_hold({"event_id": pm25_event_id(3, "2026-10-30")}, state) is None  # Next day.


def test_next_qualified_day_is_a_new_first_publication(aq):
    state = deepcopy(DEFAULT_STATE)
    state["air_quality_pm25_tiers"] = {places.event_location_key("Lahore", "Pakistan", 31.55, 74.35): {"tier": 3, "date": "2026-10-28"}}
    assert alerts(aq, state)["drafts"][0]["event_id"] == pm25_event_id(2)


@pytest.mark.parametrize(("copy", "rejected"), [
    ("Dust is forecast to peak near 2,000 µg/m³ over Lahore today, 44 times the WHO guideline.", True),
    ("Dust over Lahore is forecast to reach a 24-hour average of 2,000 µg/m³.", True),
    ("Lahore's dust is forecast to peak near 2,000 µg/m³ today (a peak, not a daily mean).", False),
    ("Dust is forecast to peak near 2,000 µg/m³ over Lahore today; PM10 is forecast to average 90 µg/m³, "
     "twice the WHO 24-hour guideline.", False),
], ids=["who-multiple", "24h-average", "negated-mean", "pm10-anchor-clause"])
def test_a_dust_peak_is_never_a_24_hour_or_who_comparison(copy, rejected):
    from src.two_bot.fact_check import local_rejection

    result = local_rejection(copy, [], dust_bundle(), deepcopy(DEFAULT_STATE))
    failures = result.failures if result is not None else []
    assert any(f.startswith("dust_peak_comparison") for f in failures) is rejected
