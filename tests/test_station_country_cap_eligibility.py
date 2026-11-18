"""Live station-cap boundaries over invented archives and the real source pipeline."""
from copy import deepcopy
from datetime import date, timedelta

from freezegun import freeze_time
import pytest

from src.data import ghcn
from src.data.ghcn_db import open_db, upsert_thresholds
from src.data.ghcn_format import DailyObs, compute_thresholds
from src.orchestrator import caps
from src.orchestrator.sources import open_meteo as source
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_awc_observed_automatic import world as world
from tests.test_ghcn_time_integrity import dly

DAY = date(2026, 11, 16)
NOW = "2026-11-17T10:00:00Z"
FIELDS = ("all_time_high", "all_time_low", "monthly_high", "monthly_low",
          "absolute_extreme", "anomaly_hot", "anomaly_cold", "calendar_date_high", "calendar_date_low")


@pytest.fixture
def supply_inputs(tmp_path, request):
    # Entirely invented station identifiers and complete engineered archives.
    # No named historical point values or source packets are reused here.
    start = date(1990, 1, 1)
    history = [(day, "TMAX", 319 if day == date(2000, 1, 1) else 280, "", "T")
               for offset in range((DAY-start).days) if (day := start+timedelta(days=offset))]
    stations, observations, payloads = [], {}, {}
    path = tmp_path / "invented-stations.sqlite"
    options = getattr(request, "param", {})
    countries = options if isinstance(options, list) else options.get("countries", ["US"]*9)
    days = options.get("days", [DAY]*9) if isinstance(options, dict) else [DAY]*9
    values = options.get("values", [39.9]*9) if isinstance(options, dict) else [39.9]*9
    sparse = options.get("sparse", True) if isinstance(options, dict) else True
    if sparse:
        # Explicit source missing cells, not omitted days. Accepted samples cover
        # January 1 and November across 37 years. This narrower retained archive
        # fits the existing writer capture bound; it certifies no complete history.
        history = [(day, element, value if day.month == 11 or day.month == day.day == 1 else -9999, qflag, sflag)
                   for day, element, value, qflag, sflag in history]
    with open_db(path) as conn:
        for index in range(9):
            country = countries[index]
            sid = f"{country}W{90000000+index:08d}"
            stations.append(dict(station_id=sid, name=f"INVENTED STATION {index}",
                country_code=country, country_name="United States" if country == "US" else "Canada",
                state="UT" if country == "US" else "",
                lat=(40 if country == "US" else 50)+index*0.05, lon=-111.0))
            threshold = compute_thresholds([DailyObs(sid, date(2000, 1, 1), "TMAX", 31.9)])
            assert threshold is not None
            upsert_thresholds(conn, threshold)
            valid = days[index]
            observations[(sid, valid)] = [DailyObs(sid, valid, "TMAX", float("nan") if index == 8 else values[index])]
            rows = history if index != 7 else [history[0], history[-1]]
            rows = [row for row in rows if row[0] != valid]
            payloads[sid] = dly(rows+[(valid, "TMAX", round(values[index]*10), "S" if index == 6 else "", "T")], sid)
    return dict(stations=stations, db_path=path, _fetch_obs_fn=lambda _: observations,
                _fetch_archive_fn=payloads.__getitem__, _now_fn=lambda: NOW)


def run_source(monkeypatch, supply_inputs, state, *, transform=None):
    qualify = ghcn.check_extreme_signals_for_stations
    calls = []

    def station_source(**kwargs):
        calls.append("source")
        bundles, countries = qualify(**supply_inputs, bot_state=kwargs["bot_state"], metrics_out=kwargs["metrics_out"])
        if transform:
            transform(bundles)
        return bundles, countries

    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", station_source)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    # Discovery-cache receipt for the engineered SQLite fixture only; claim
    # qualification still uses the real parser and complete retained archives.
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "0")
    run = dict(id="invented-station-cap-run", mode="alerts", sources=[])
    with freeze_time(NOW):
        source.run_extreme_signals(state, run, [], {}, {})
    assert calls == ["source"]
    return run


def consume_events(state, bundles, *, count, fields=FIELDS):
    for bundle in bundles[:count]:
        for field in fields:
            event = getattr(bundle, field)
            if event is not None:
                state["posted_events"].append(event.event_id)


def individual_queue(state):
    return [row for row in state.get("_triage_queue", []) if row.legacy_type == "all_time_high"]


def test_already_posted_stations_do_not_consume_the_live_country_cap(monkeypatch, supply_inputs):
    qualify = ghcn.check_extreme_signals_for_stations
    bundles, _ = qualify(**supply_inputs)
    assert len(bundles) == 6
    state: dict = deepcopy(dict(DEFAULT_STATE))
    consume_events(state, bundles, count=2)

    # Prove that the third real-parser result reaches the existing factual audit.
    # It is still invented source data, not a provider truth or live freshness claim.
    selected = source._select_individual_signal(state, bundles[2], set(), {}, observed_labels=True)
    assert selected.signal is not None and selected.legacy_type == "all_time_high"
    prepared = source._two_bot_bundle_for_extreme_signal(
        selected.legacy_type, selected.signal, source="ghcn",
    )
    assert prepared is not None
    audit = audit_story_bundle(prepared)
    assert audit.prompt_ready, audit

    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == 2
    assert {row.event_id for row in queued}.isdisjoint(state["posted_events"])
    assert all(audit_story_bundle(row.bundle).prompt_ready for row in queued)
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert metrics["scientific_signal_bundles"] == 6
    assert metrics["individual_station_preflight_holds"] == {"no_live_signal": 2}
    assert metrics["individual_station_cap_excluded"] == 2


@pytest.mark.parametrize("cap", [0, 1, 2, 6])
@pytest.mark.parametrize("consumed", [0, 2, 6])
def test_full_supply_survives_live_cap_and_only_viable_rows_take_it(monkeypatch, supply_inputs, cap, consumed):
    bundles, _ = ghcn.check_extreme_signals_for_stations(**supply_inputs)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    consume_events(state, bundles, count=consumed)
    monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", cap)
    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == min(cap, 6-consumed)
    assert {row.event_id for row in queued}.isdisjoint(state["posted_events"])
    assert state["drafts"] == [] and state.get("publish_ledger", {}) == DEFAULT_STATE.get("publish_ledger", {})
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert metrics["scientific_signal_bundles"] == 6
    assert metrics["individual_station_cap_excluded"] == max(0, 6-consumed-cap)
    assert metrics["individual_station_preflight_holds"] == ({"no_live_signal": consumed} if consumed else {})
    if not consumed:
        expected = caps.select_individual_station_bundles(bundles, max_per_country=cap)
        assert all(b.all_time_high is not None for b in expected)
        assert [row.event_id for row in queued] == [b.all_time_high.event_id for b in expected if b.all_time_high]


@pytest.mark.parametrize("supply_inputs", [["US"]*3+["CA"]*6], indirect=True)
def test_viable_country_quota_is_independent_and_full_supply_is_retained(monkeypatch, supply_inputs):
    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == 4
    assert sum(row.bundle.raw_signal_dump["country"] == "United States" for row in queued) == 2
    assert sum(row.bundle.raw_signal_dump["country"] == "Canada" for row in queued) == 2
    assert run["sources"][0]["details"]["pipeline_metrics"]["scientific_signal_bundles"] == 6


@pytest.mark.parametrize("intent", ["manual", "schedule", "explicit"])
def test_current_manual_fallback_is_kept_only_for_its_existing_intent(monkeypatch, supply_inputs, intent):
    bundles, _ = ghcn.check_extreme_signals_for_stations(**supply_inputs)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    # The real cascade chooses the remaining +11.9 C monthly anomaly first.
    consume_events(state, bundles, count=2, fields=("all_time_high", "monthly_high"))
    for key, value in {"GITHUB_EVENT_NAME": "schedule" if intent == "schedule" else "workflow_dispatch",
                       "GITHUB_REF": "refs/heads/main", "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1",
                       "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-release-20261117",
                       "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
                       "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1" if intent == "explicit" else "0"}.items():
        monkeypatch.setenv(key, value)
    run = run_source(monkeypatch, supply_inputs, state)
    queue = state.get("_triage_queue", [])
    assert len(queue) == 2
    if intent == "manual":
        assert [row.legacy_type for row in queue] == ["anomaly_hot", "anomaly_hot"]
    else:
        assert [row.legacy_type for row in queue] == ["all_time_high", "all_time_high"]
        assert run["sources"][0]["details"]["pipeline_metrics"]["individual_station_preflight_holds"] == {"automatic_policy": 2}


@pytest.mark.parametrize("corruption", ["source_product", "new_temp_c"])
def test_unqualified_front_rows_do_not_take_a_valid_rows_country_slot(monkeypatch, supply_inputs, corruption):
    def tamper(bundles):
        for bundle in bundles[:2]:
            if corruption == "source_product":
                for field in FIELDS:
                    event = getattr(bundle, field)
                    if event is not None:
                        event.evidence["source_product"] = "invented-wrong-product"
            else:
                bundle.all_time_high.new_temp_c += 1

    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state, transform=tamper)
    queue = individual_queue(state)
    assert len(queue) == 2
    rejected = {row["station_id"] for row in supply_inputs["stations"][:2]}
    assert all(row.bundle.raw_signal_dump["evidence"]["station_id"] not in rejected for row in queue)
    assert all(audit_story_bundle(row.bundle).prompt_ready for row in queue)
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert sum(metrics["individual_station_preflight_holds"].values()) == 2


def test_final_real_admission_rechecks_the_prepared_packet_and_counts_no_promotion(monkeypatch, supply_inputs):
    admit = source._enqueue_story_candidate
    attempted = []

    def drift(state, **kwargs):
        packet = kwargs["bundle"]
        if kwargs["legacy_type"] == "all_time_high":
            assert audit_story_bundle(packet).prompt_ready
            packet.raw_signal_dump["new_temp_c"] += 1
            attempted.append(kwargs["event_id"])
        return admit(state, **kwargs)

    monkeypatch.setattr(source, "_enqueue_story_candidate", drift)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state)
    assert len(attempted) == 2 and individual_queue(state) == []
    assert run["sources"][0]["promoted"] == 0
    assert state["drafts"] == []


@pytest.mark.parametrize("supply_inputs", [{"days": [DAY-timedelta(days=3)]*2+[DAY]*7}], indirect=True)
def test_source_stale_stations_leave_the_live_automatic_cap_for_fresh_stations(monkeypatch, supply_inputs):
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "1")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == 2
    assert all(row.tweet_date == DAY.isoformat() for row in queued)
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert metrics["scientific_signal_bundles"] == 6
    assert metrics["individual_station_preflight_holds"] == {"automatic_source": 2}
    assert metrics["individual_station_cap_excluded"] == 2


@pytest.mark.parametrize("supply_inputs", [{"values": [36.1]*2+[39.9]*7}], indirect=True)
def test_existing_score_floor_holds_weak_remaining_signals_before_country_cap(monkeypatch, supply_inputs):
    bundles, _ = ghcn.check_extreme_signals_for_stations(**supply_inputs)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    # First two stations have only an unconsumed +8.1 C anomaly. Their qualified
    # stronger records were previously consumed; no scoring function is patched.
    consume_events(state, bundles, count=2, fields=tuple(f for f in FIELDS if f != "anomaly_hot"))
    assert all(bundle.anomaly_hot is not None for bundle in bundles[:2])
    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == 2
    assert {row.event_id for row in queued}.isdisjoint(state["posted_events"])
    assert all(row.bundle.raw_signal_dump["evidence"]["station_id"] not in
               {b.station_id for b in bundles[:2]} for row in queued)
    assert run["sources"][0]["details"]["pipeline_metrics"]["individual_station_preflight_holds"] == {"no_live_signal": 2}


@pytest.mark.parametrize("supply_inputs", [{"sparse": False}], indirect=True)
def test_complete_dense_station_warrant_reaches_cap_losslessly(monkeypatch, supply_inputs):
    from src.two_bot.bundle_capture import BundleCaptureError, capture_bundle
    from src.two_bot.ghcn_readable_warrant import decode_wire
    from src.media.temperature_graphic_adapter import story_bundle_snapshot
    bundles, _ = ghcn.check_extreme_signals_for_stations(**supply_inputs)
    story = source._two_bot_bundle_for_extreme_signal("all_time_high", bundles[0].all_time_high, source="ghcn")
    assert audit_story_bundle(story).prompt_ready
    with pytest.raises(BundleCaptureError, match="bundle_capture_too_large"):
        capture_bundle(story)
    monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", 2)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state)
    queued = individual_queue(state)
    assert len(queued) == 2 and state["drafts"] == []
    for candidate in queued:
        original = next(bundle for bundle in bundles if bundle.all_time_high.event_id == candidate.event_id)
        expected = source._two_bot_bundle_for_extreme_signal("all_time_high", original.all_time_high, source="ghcn")
        captured = capture_bundle(candidate.bundle)
        assert len(captured.serialized.encode()) <= 32768
        assert decode_wire(captured.payload()) == story_bundle_snapshot(expected)
        assert audit_story_bundle(candidate.bundle).prompt_ready
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert metrics["scientific_signal_bundles"] == 6
    assert metrics["individual_station_preflight_holds"] == {}
    assert metrics["individual_station_cap_excluded"] == 4
    assert run["sources"][0]["promoted"] == 2


@pytest.mark.parametrize("supply_inputs", [{"sparse": False}], indirect=True)
def test_oversized_complete_readable_warrant_still_holds_before_cap(monkeypatch, supply_inputs):
    build = source._two_bot_bundle_for_extreme_signal

    def enlarged(*args, **kwargs):
        packet = build(*args, **kwargs)
        if packet is not None:
            packet.raw_signal_dump["retained_operator_note"] = "x" * 6000
        return packet

    monkeypatch.setattr(source, "_two_bot_bundle_for_extreme_signal", enlarged)
    state: dict = deepcopy(dict(DEFAULT_STATE))
    run = run_source(monkeypatch, supply_inputs, state)
    assert not state.get("_triage_queue") and state["drafts"] == []
    metrics = run["sources"][0]["details"]["pipeline_metrics"]
    assert metrics["scientific_signal_bundles"] == 6
    assert metrics["individual_station_preflight_holds"] == {"bundle_retention": 6}
    assert metrics["individual_station_cap_excluded"] == 0 and run["sources"][0]["promoted"] == 0


@pytest.fixture(scope="module")
def point_stories():
    # Existing entirely engineered source bytes, real archive verification and
    # six comparators. This older fixture proves retained binding, not freshness.
    return {(direction, tier): graphic_bundles(direction=direction, tier=tier)[0]
            for direction in ("high", "low") for tier in ("all_time", "monthly", "calendar")}


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("tier", ["all_time", "monthly", "calendar"])
def test_shared_admission_accepts_all_six_real_source_record_comparators(point_stories, direction, tier):
    story = point_stories[direction, tier]
    assert audit_story_bundle(story).prompt_ready
    from src.two_bot.types import StoryBundle
    from src.two_bot.json_utils import json_default
    import json
    # Persisted JSON strings and in-memory date objects have the same proof.
    restored = StoryBundle(**json.loads(json.dumps(story.to_dict(), default=json_default)))
    # Construction projects retained evidence again; use the actual saved view
    # rather than treating duplicate projection as a valid serialization roundtrip.
    restored.current_facts = deepcopy(story.current_facts)
    assert audit_story_bundle(restored).prompt_ready
    from tests.ghcn_claim_contract_helpers import reference
    from src.two_bot.ghcn_claim_contract import project
    field = f"calendar_date_{direction}" if tier == "calendar" else f"{tier}_{direction}"
    ref = reference(story, field)
    compact = project(story, ref, ref["selection"])
    assert audit_story_bundle(compact).prompt_ready
    compact.raw_signal_dump["ghcn_claim_view"]["observation_revision"] = "0"*64
    assert not audit_story_bundle(compact).prompt_ready


@pytest.mark.parametrize("direction", ["high", "low"])
@pytest.mark.parametrize("change", ["product", "value", "quality", "comparator", "cutoff", "station",
                                  "headline", "history", "country", "where", "fact", "date"])
def test_shared_admission_refuses_changed_point_or_projection_even_after_rehash(point_stories, direction, change):
    from src.data.temperature_evidence import fingerprint
    story = deepcopy(point_stories[direction, "all_time"])
    raw = story.raw_signal_dump
    evidence, baseline = raw["evidence"], raw["evidence"]["baseline"]
    element = "TMAX" if direction == "high" else "TMIN"
    variable = "temperature_2m_max" if direction == "high" else "temperature_2m_min"
    if change == "product":
        evidence["source_product"] = "invented-wrong-product"
    elif change == "value":
        raw["new_temp_c"] += 1
    elif change == "quality":
        evidence["variables"][element]["qflag"] = "S"
    elif change == "comparator":
        baseline["variables"][variable]["record_values_c"]["all_time"] += 1
    elif change == "cutoff":
        baseline["variables"][variable]["verified_source_cutoff"] = story.when
    elif change == "station":
        evidence["station_id"] = "USC99000002"
    elif change == "headline":
        story.headline_metric["value"] += 1
    elif change == "history":
        story.historical_context["prior_record_year"] -= 1
    elif change == "country":
        raw["country"] = "Invented other country"
    elif change == "where":
        story.where = "Invented other place"
    elif change == "fact":
        next(f for f in story.current_facts if f["label"] == "today_temp_c")["value"] += 1
    else:
        raw["signal_date"] = DAY
    # A self-consistent new capture hash cannot make conflicting fields agree.
    evidence["revision_id"] = fingerprint({k: v for k, v in evidence.items() if k not in {"revision_id", "retrieved_at"}})
    audit = audit_story_bundle(story)
    assert not audit.prompt_ready
    assert "ghcn_record_point_unqualified" in {issue.code for issue in audit.issues}


@pytest.mark.parametrize("retained_hint", ["history", "fact", "event", "compact-reference"])
def test_relabelled_raw_packet_cannot_hide_its_retained_ghcn_family(point_stories, retained_hint):
    story = deepcopy(point_stories["high", "all_time"])
    raw = story.raw_signal_dump
    story.headline_metric["label"] = "high_c"
    for evidence in (raw["evidence"], raw["evidence"]["baseline"]):
        evidence.pop("station_id", None)
        evidence["source_product"] = "invented-other-product"
    if retained_hint != "history":
        story.historical_context["baseline"].pop("station_id", None)
        story.historical_context["baseline"]["source_product"] = "invented-other-product"
    if retained_hint != "fact":
        for fact in story.current_facts:
            if fact["label"] == "source_product":
                fact["value"] = "invented-other-product"
    if retained_hint != "event":
        story.event_id = raw["event_id"] = "invented-generic-point"
    if retained_hint == "compact-reference":
        # A marker is a family hint, never a bypass or a resolved source proof.
        raw["ghcn_claim_view"] = {"kind": "ghcn_claim_view_v1"}
    audit = audit_story_bundle(story)
    assert not audit.prompt_ready
    assert "ghcn_record_point_unqualified" in {issue.code for issue in audit.issues}


@pytest.mark.parametrize("removed", [(), ("new_temp_c",), ("old_record_c",),
                                    ("new_temp_c", "old_record_c"),
                                    ("new_temp_c", "old_record_c", "old_record_year", "years_of_data", "kind", "signal_date")])
def test_changed_kind_cannot_hide_an_inconsistent_retained_ghcn_record(point_stories, removed):
    story = deepcopy(point_stories["high", "all_time"])
    story.signal_kind = "invented_unchecked_record"
    story.raw_signal_dump["new_temp_c"] += 1
    for key in removed:
        story.raw_signal_dump.pop(key)
    audit = audit_story_bundle(story)
    assert not audit.prompt_ready
    assert "ghcn_record_point_unqualified" in {issue.code for issue in audit.issues}


@pytest.mark.parametrize("scheduled", [False, True], ids=["manual-unapproved", "ordinary-auto-delay"])
def test_real_station_pipeline_spends_one_offline_writer_opportunity_and_saves_pending(monkeypatch, supply_inputs, world, scheduled):
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue
    from src.two_bot import pipeline
    from src.orchestrator.candidate_budget import CandidateBudget
    from src.voice import safety
    from tests.nhc_advisory_pipeline_helpers import stage_fakes

    transport, state, _, calls, _ = world
    # Scheduled intent is inferred by its existing policy; explicit1 is valid
    # only on the separately bounded workflow_dispatch entry point.
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1" if scheduled else "0")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1" if scheduled else "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule" if scheduled else "workflow_dispatch")
    # A value-only fixture, not a certified/full-history record claim. The
    # independent copy floor still owns record-scope/cutoff language.
    text = "Invented Station 0 in Utah reached 39.9°C on November 16."
    stages = stage_fakes(calls, copy=text)
    generate, outcomes = pipeline.generate_draft, []

    def observed_generate(*args, **kwargs):
        result = generate(*args, **kwargs)
        outcomes.append({key: kwargs.get("result_out", {}).get(key) for key in
                         ("kill_stage", "kill_reason", "stage_outcomes", "writer_started")})
        return result

    monkeypatch.setattr(pipeline, "generate_draft", observed_generate)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    run = run_source(monkeypatch, supply_inputs, state)
    assert len(individual_queue(state)) == 2
    proof = individual_queue(state)[0].bundle.raw_signal_dump["evidence"]["baseline"]["variables"]["temperature_2m_max"]
    assert proof["source_coverage_complete"] and not proof["complete"]
    assert proof["source_missing_count"] > 0 and proof["years_with_samples"] >= ghcn.MIN_ARCHIVE_YEARS
    budget = CandidateBudget("invented-station-consumer", 1)
    with freeze_time(NOW, tick=True):
        written = _drain_and_write_triage_queue(state, run, candidate_budget=budget)
        assert written == 1, outcomes
    assert budget.attempts == 1
    assert calls == ["writer", "safety", "fact_check", "critic"]
    draft, = state["drafts"]
    assert draft["status"] == "pending" and draft["text"] == text
    assert draft["review_binding"]["kind"] == "model"
    if scheduled:
        assert draft["approval_mode"] == "auto" and draft["approval_binding"] and draft["auto_approve_at"]
    else:
        assert draft["approval_mode"] == "manual"
        assert not draft.get("approval_binding") and not draft.get("auto_approve_at")
    assert transport.x_posts == []
