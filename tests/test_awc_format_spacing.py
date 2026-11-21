"""Invented publication receipts and offline source bytes; no paid/live calls."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.editorial.revisions import draft_identity
from src.editorial.format_spacing import awc_format_hold, candidate_format_hold
from src.orchestrator.draft_save import can_draft_candidate
from tests.test_awc_observed import NOW, install


def prior_publication(state, *, at=None):
    at = at or NOW - timedelta(hours=18)
    event = "metar_pair_TAAA_TCCC_2026-11-14"
    draft = {"id": "invented-prior", "event_id": event, "type": source.KIND,
             "status": "posted", "publish_outcome": "confirmed", "tweet_id": "123456789",
             "text": "Invented earlier airport comparison, not actual weather.",
             "content_revision": 1, "tweet_date": at.isoformat(),
             "posted_at": at.isoformat(), "review_context": {"two_bot": {"bundle": {
                 "signal_kind": source.KIND, "event_id": event}}}}
    state.setdefault("drafts", []).append(draft)
    receipt = {**draft_identity(draft), "phase": "confirmed", "tweet_id": draft["tweet_id"],
               "at": at.isoformat(), "confirmed_at": at.isoformat()}
    state.setdefault("publish_ledger", {})[event] = receipt
    return draft, receipt


def candidate(monkeypatch):
    install(monkeypatch)
    bundle = source.build_bundle(source.nominate(now=NOW), now=NOW)
    return SimpleNamespace(bundle=bundle, legacy_type=source.KIND, event_id=bundle.event_id,
                           city="", tweet_date=bundle.when, score=SimpleNamespace(total=80),
                           cooldown_exempt=False)


def test_actual_pre_writer_gate_defers_changed_pair_and_date_after_confirmed_post(monkeypatch, fresh_state):
    prior_publication(fresh_state)
    item = candidate(monkeypatch)
    before = deepcopy(fresh_state)
    with freeze_time(NOW):
        assert can_draft_candidate(fresh_state, item) == (False, "awc_format_spacing")
    assert fresh_state == before


@pytest.mark.parametrize("age,expected", [
    (timedelta(hours=24, microseconds=-1), "awc_format_spacing"),
    (timedelta(hours=24), None), (timedelta(hours=25), None),
])
def test_exact_confirmation_time_boundary(fresh_state, age, expected):
    prior_publication(fresh_state, at=NOW - age)
    assert awc_format_hold(fresh_state, now=NOW) == expected


@pytest.mark.parametrize("change", ["missing_ledger", "legacy_receipt", "submitted", "unknown", "not_sent",
    "conflicting_attempt", "invalid_conflicts", "wrong_id", "bad_id", "zero_id", "leading_zero_id",
    "changed_text", "changed_type", "changed_evidence", "changed_revision", "future", "naive", "invalid_time",
    "reversed_time", "not_posted", "conflicting_outcome", "control_time", "offset_time", "overprecise_time"])
def test_uncertain_or_changed_publication_is_never_a_confirmed_spacing_basis(fresh_state, change):
    draft, receipt = prior_publication(fresh_state)
    if change == "missing_ledger":
        fresh_state["publish_ledger"] = {}
    elif change == "legacy_receipt":
        receipt.pop("evidence_sha256")
    elif change in {"submitted", "unknown", "not_sent"}:
        receipt["phase"] = change
    elif change == "conflicting_attempt":
        receipt["attempt_conflicts"] = [{"phase": "unknown"}]
    elif change == "invalid_conflicts":
        receipt["attempt_conflicts"] = None
    elif change == "wrong_id":
        receipt["tweet_id"] = "987654321"
    elif change in {"bad_id", "zero_id", "leading_zero_id"}:
        receipt["tweet_id"] = draft["tweet_id"] = {"bad_id": "invented-not-an-x-id", "zero_id": "0", "leading_zero_id": "0123"}[change]
    elif change == "changed_text":
        draft["text"] += " edited"
    elif change == "changed_type":
        draft["type"] = "other"
    elif change == "changed_evidence":
        draft["review_context"]["two_bot"]["bundle"]["signal_kind"] = "other"
    elif change == "changed_revision":
        draft["content_revision"] += 1
    elif change == "future":
        receipt["confirmed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "naive":
        receipt["confirmed_at"] = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    elif change == "invalid_time":
        receipt["confirmed_at"] = "invented-bad-time"
    elif change == "control_time":
        receipt["confirmed_at"] = receipt["confirmed_at"].replace("T", "\n")
    elif change == "offset_time":
        receipt["confirmed_at"] = (NOW - timedelta(hours=17)).isoformat().replace("+00:00", "+01:00")
    elif change == "overprecise_time":
        receipt["confirmed_at"] = receipt["confirmed_at"].replace("+00:00", ".0000001Z")
    elif change == "reversed_time":
        receipt["at"] = NOW.isoformat()
    elif change == "not_posted":
        draft["status"] = "pending"
    else:
        draft["publish_outcome"] = "unknown"
    before = deepcopy(fresh_state)
    assert awc_format_hold(fresh_state, now=NOW) is None
    assert fresh_state == before


def test_current_policy_is_not_replayed_for_historical_publication(monkeypatch, fresh_state):
    prior_publication(fresh_state)
    def forbidden(*args, **kwargs):
        pytest.fail("No re-review, source or policy lookup of a historical send")
    monkeypatch.setattr("src.editorial.policy.current_editorial_policy", forbidden)
    monkeypatch.setattr("src.editorial.revisions.review_is_current", forbidden)
    assert awc_format_hold(fresh_state, now=NOW) == "awc_format_spacing"


def test_other_formats_and_mutable_display_timestamps_do_not_change_spacing(monkeypatch, fresh_state):
    draft, _receipt = prior_publication(fresh_state)
    item = candidate(monkeypatch)
    item.legacy_type = "other_observed_kind"
    assert candidate_format_hold(fresh_state, item, now=NOW) is None
    draft.update(posted_at="invented-invalid", updated_at=NOW.isoformat(), created_at=NOW.isoformat())
    assert awc_format_hold(fresh_state, now=NOW) == "awc_format_spacing"


@pytest.mark.parametrize("field,value", [("drafts", None), ("publish_ledger", [])])
def test_malformed_history_is_explicitly_unavailable(fresh_state, field, value):
    fresh_state[field] = value
    assert awc_format_hold(fresh_state, now=NOW) == "awc_format_spacing_unavailable"


@pytest.mark.parametrize("triage", ["0", "1"])
def test_actual_source_still_observes_but_does_not_enqueue_a_recent_format(monkeypatch, fresh_state, triage):
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from tests.test_observed_airport_body_budget import ordinary
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage=triage)
    prior_publication(fresh_state)
    with freeze_time(NOW, tick=True):
        run_awc_observed(fresh_state, run)
    assert fresh_state.get("_triage_queue", []) == []
    row = run["sources"][-1]
    assert row["status"] == "success" and row["observed"] == 1 and row["promoted"] == 0
    assert row["details"] == {"editorial_hold": "awc_format_spacing"}
    assert models.stages() == [] and budget.attempts == 0
    assert len(transport.awc_calls) == 2 and transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_prequeued_candidate_cannot_spend_after_a_known_publication(monkeypatch, fresh_state, mode):
    from src.orchestrator import funnel, triage_queue
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from tests.test_observed_airport_body_budget import ordinary
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage="0" if mode == "legacy" else "1")
    with freeze_time(NOW, tick=True):
        run_awc_observed(fresh_state, run)
        assert len(fresh_state["_triage_queue"]) == 1
        event = fresh_state["_triage_queue"][0].event_id
        prior_publication(fresh_state)
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
        sink = funnel.new_funnel()
        before_http = list(transport.awc_calls)
        assert triage_queue._drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget, funnel_sink=sink) == 0
    assert models.stages() == [] and budget.attempts == 0 and not budget.seen("event:" + event)
    assert transport.awc_calls == before_http and transport.x_posts == [] and transport.gist_patches == 0
    assert sink["_slate_terminal"][event] == "editorial_spacing"
    report = next(row for row in run["sources"] if row["source"] == "automatic_selection")
    assert report["details"]["editorial_holds"] == {"awc_format_spacing": 1}
    assert "source_holds" not in report["details"]


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_recheck_before_writer_sees_a_publication_after_preflight(monkeypatch, fresh_state, mode):
    from src.editorial import format_spacing
    from src.orchestrator import triage_queue
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from tests.test_observed_airport_body_budget import ordinary
    _transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage="0" if mode == "legacy" else "1")
    with freeze_time(NOW, tick=True):
        run_awc_observed(fresh_state, run)
        original = format_spacing.candidate_format_hold
        calls = []
        def publish_between_checks(state, item, *, now):
            result = original(state, item, now=now)
            calls.append(result)
            if len(calls) == 1:
                prior_publication(state)
            return result
        monkeypatch.setattr(format_spacing, "candidate_format_hold", publish_between_checks)
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
        assert triage_queue._drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget) == 0
    assert calls == [None, "awc_format_spacing"]
    assert models.stages() == [] and budget.attempts == 0


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_lower_ranked_other_format_keeps_the_one_writer_slot(monkeypatch, mode):
    from dataclasses import replace
    from src.orchestrator import funnel, triage_queue
    from src.orchestrator.candidate_budget import CandidateBudget
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from tests import test_scheduled_automatic_preflight as scheduled
    with freeze_time(NOW, tick=True):
        spy = scheduled.world.__wrapped__(monkeypatch)
        state, _manual = scheduled.manual_slate()
        state["_triage_queue"].clear()
        install(monkeypatch)
        monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
        monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
        record = scheduled.run()
        run_awc_observed(state, record)
        [airport] = state["_triage_queue"]
        state["_triage_queue"][0] = replace(airport, score=replace(airport.score, total=99))
        eligible = scheduled.enqueue_automatic(state, spy, monkeypatch)
        prior_publication(state)
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0" if mode == "legacy" else "1")
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
        budget, sink = CandidateBudget("invented", 1), funnel.new_funnel()
        assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget, funnel_sink=sink) == 1
    assert spy.writer_events() == [eligible]
    assert [stage for stage, _ in spy.calls] == ["writer", "safety", "fact_check", "critic"]
    assert budget.attempts == 1 and not budget.seen("event:" + airport.event_id)
    assert sink["_slate_terminal"][airport.event_id] == "editorial_spacing"


def test_actual_fixture_publisher_receipt_survives_normal_json_storage(monkeypatch, fresh_state):
    import json
    from tests import live_content_harness as h
    from tests import test_awc_observed_automatic as actual
    world = actual.world.__wrapped__(monkeypatch, fresh_state)
    transport, state, _run, _called, _stages = world
    original = transport.send
    def numeric_fixture_response(adapter, request, **options):
        response = original(adapter, request, **options)
        if request.url == h.X_CREATE and response.status_code == 201:
            body = response.json()
            body["data"]["id"] = "1234567890123456789"
            return h._reply(request, 201, json.dumps(body).encode())
        return response
    transport.send = numeric_fixture_response
    actual.generate(world)
    actual.sender(monkeypatch, world)
    [draft] = state["drafts"]
    assert draft["status"] == "posted" and draft["tweet_id"] == "1234567890123456789"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    from src import state as storage
    # process_due_drafts returns the confirmed state to its caller; the ordinary
    # workflow persists that result after the pre-send submitted checkpoint.
    storage.write_state(state)
    # The actual fake-Gist write uses the normal state codec. No hosted/database
    # restore case or real-platform operation is run by this fixture.
    stored = json.loads(transport.gist["state.json"])
    assert stored["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    def forbidden(*args, **kwargs):
        pytest.fail("Old publication evidence must not be refreshed")
    monkeypatch.setattr(source, "_read", forbidden)
    assert awc_format_hold(stored, now=NOW + timedelta(hours=18)) == "awc_format_spacing"
    assert len(transport.x_posts) == 1


@pytest.mark.parametrize("text", ["A different actually transported body.", None, 7])
def test_present_contradictory_receipt_text_is_not_a_matching_publication(fresh_state, text):
    _draft, receipt = prior_publication(fresh_state)
    receipt["text"] = text
    assert awc_format_hold(fresh_state, now=NOW) is None


def test_matching_or_absent_optional_receipt_text_keeps_hash_bound_history(fresh_state):
    draft, receipt = prior_publication(fresh_state)
    assert "text" not in receipt
    assert awc_format_hold(fresh_state, now=NOW) == "awc_format_spacing"
    receipt["text"] = draft["text"]
    assert awc_format_hold(fresh_state, now=NOW) == "awc_format_spacing"


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_receipt_appearing_after_selection_or_last_cache_check_never_reserves_writer(monkeypatch, fresh_state, mode):
    from src.orchestrator import funnel, triage_queue, triage
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from src.two_bot import negative_cache
    from tests.test_observed_airport_body_budget import ordinary
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage="0" if mode == "legacy" else "1")
    with freeze_time(NOW, tick=True):
        run_awc_observed(fresh_state, run)
        [queued] = fresh_state["_triage_queue"]
        inserted = []
        if mode == "triage":
            original = triage.select_survivors
            def publish_after_selection(state, pool, **kwargs):
                result = original(state, pool, **kwargs)
                prior_publication(state)
                inserted.append(True)
                return result
            monkeypatch.setattr(triage, "select_survivors", publish_after_selection)
        else:
            original = negative_cache.should_skip
            def publish_after_cache(state, *args, **kwargs):
                result = original(state, *args, **kwargs)
                if not inserted:
                    prior_publication(state)
                    inserted.append(True)
                return result
            monkeypatch.setattr(negative_cache, "should_skip", publish_after_cache)
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
        sink = funnel.new_funnel()
        assert triage_queue._drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget, funnel_sink=sink) == 0
    assert inserted == [True]
    assert models.stages() == [] and budget.attempts == 0 and not budget.seen("event:" + queued.event_id)
    assert sink["_slate_terminal"][queued.event_id] == "editorial_spacing"
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_editorial_hold_does_not_reduce_source_ready_denominator(monkeypatch, fresh_state):
    from dataclasses import replace
    from src.orchestrator import triage_queue
    from src.orchestrator.sources.awc_observed import run_awc_observed
    from tests.test_observed_airport_body_budget import ordinary
    _transport, models, run, budget = ordinary(monkeypatch, fresh_state)
    with freeze_time(NOW, tick=True):
        run_awc_observed(fresh_state, run)
        [valid] = fresh_state["_triage_queue"]
        fresh_state["_triage_queue"].append(replace(valid, event_id=valid.event_id + "_different"))
        prior_publication(fresh_state)
        assert triage_queue._drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget) == 0
    details = next(row for row in run["sources"] if row["source"] == "automatic_selection")["details"]
    assert details["potential_type_count"] == 2
    assert details["held_source_candidates"] == 1 and details["held_editorial_candidates"] == 1
    assert details["source_ready_count"] == 1
    assert models.stages() == [] and budget.attempts == 0
