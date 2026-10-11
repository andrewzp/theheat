"""Shared save planning is detached, deterministic and clock/policy explicit."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.editorial.draft_admission import plan_draft_admission, resolve_admission_place_facts
from src.editorial.policy import current_editorial_policy
from src.orchestrator import draft_save

AT = datetime(2026, 10, 11, 12, tzinfo=UTC)


def plan(state, **changes):
    args = dict(text="Synthetic City recorded 40°C.", tweet_type="absolute_extreme", event_id="synthetic-new",
        draft_id="synthetic-new-draft", at=AT, editorial_policy=current_editorial_policy(),
        city="Synthetic City", tweet_date="2026-10-11", score={"total": 80})
    args.update(changes)
    return plan_draft_admission(state, **args, place_facts=resolve_admission_place_facts(state, args["event_id"]))


def old_rows():
    return [dict(id="weaker", event_id="synthetic-old", text="Synthetic weaker signal.", status="pending", city="Synthetic City", tweet_date="2026-10-11", score={"total": 70}),
        dict(id="posted", event_id="synthetic-posted", text="Synthetic earlier signal.", status="posted", city="Synthetic City", tweet_date="2026-10-10", posted_at="2026-10-10T12:00:00Z")]


def test_later_cooldown_refusal_cannot_remove_weaker_pending_draft():
    state = {"drafts": old_rows(), "publish_ledger": {"retained": {"phase": "unknown"}}}
    before = deepcopy(state)
    result = plan(state)
    assert result.reason == "city_cooldown" and result.draft is None
    assert result.state == before == state
    assert not any(s["kill_stage"] == "same_day_superseded" for s in result.suppressions)


def test_wrapper_preserves_weaker_draft_after_cooldown_refusal(monkeypatch):
    state = {"drafts": old_rows()}
    before = deepcopy(state)
    class Score:
        total = 80
        def as_dict(self):
            return {"total": self.total}
    monkeypatch.setattr(draft_save, "_utc_now", lambda: AT)
    assert not draft_save.save_draft("Synthetic strong signal.", state, "absolute_extreme", "synthetic-new", score=Score(), city="Synthetic City", tweet_date="2026-10-11")
    assert state == before


def test_same_inputs_repeat_without_ambient_clock_or_policy(monkeypatch):
    from src.editorial import revisions, policy
    from src.orchestrator import dedup
    captured = current_editorial_policy()
    def forbidden(*args, **kwargs):
        raise AssertionError("Planner read ambient time/policy")
    monkeypatch.setattr(revisions, "_now", forbidden)
    monkeypatch.setattr(dedup, "_utc_now", forbidden)
    monkeypatch.setattr(policy, "current_editorial_policy", forbidden)
    state = {"drafts": old_rows()[:1]}
    args = dict(text="Synthetic new signal.", tweet_type="absolute_extreme", event_id="synthetic-new", draft_id="new",
        at=AT, editorial_policy=captured, city="Synthetic City", tweet_date="2026-10-11", score={"total": 80})
    args["place_facts"] = resolve_admission_place_facts(state, args["event_id"])
    one, two = plan_draft_admission(state, **args), plan_draft_admission(state, **args)
    assert one == two and one.draft["created_at"] == one.draft["updated_at"] == "2026-10-11T12:00:00Z"
    assert one.changed_ids == ("weaker", "new") and state == {"drafts": old_rows()[:1]}


@pytest.mark.parametrize("score,exempt,accepted", [({"total": 99}, False, True), (None, True, True), (None, False, False)])
def test_copy_exception_and_explicit_exemption_preserved(score, exempt, accepted):
    result = plan({"drafts": old_rows()}, candidate_score=score, cooldown_exempt=exempt)
    assert (result.draft is not None) is accepted


@pytest.mark.parametrize("key", ["id", "text", "status", "review_binding", "approval_binding", "publish_intent_id"])
def test_evaluator_metadata_cannot_overlay_authority_fields(key):
    with pytest.raises(ValueError, match="unsupported_evaluator_metadata"):
        plan({"drafts": []}, evaluator_metadata={key: "malicious"})


def test_durable_posted_events_repeat_preflight():
    result = plan({"drafts": [], "posted_events": ["synthetic-new"]})
    assert result.reason == "duplicate_posted" and result.draft is None


def test_hot10_metadata_retains_only_the_allowed_detached_rows():
    rows = [dict(rank=1, city="Synthetic City", country="XX", anomaly_c=7.0, temp_high_c=38.0)]
    result = plan({"drafts": []}, tweet_type="hot10", city="", tweet_date="", evaluator_metadata={"hot10_rows": rows})
    assert result.draft["hot10_rows"] == rows and result.draft["hot10_rows"] is not rows


def test_retained_admission_score_requires_the_existing_typed_contract():
    from src.commands import postgres_candidate_admission as admission
    from src.commands.schema import CommandError
    from src.editorial.scoring import EditorialScore
    score = EditorialScore(category="fire", severity=90, novelty=80, timeliness=70, confidence=90,
        shareability=80, sensitivity=0, total=83, threshold=65, reasons=["Invented fixture score"]).as_dict()
    bundle = {"signal_kind": "fire", "event_id": "invented-fire"}
    save = dict(legacy_type="fire", event_id="invented-fire", score=score, city="", tweet_date="", cooldown_exempt=False,
        review_context=None, evaluator_metadata=None)
    admission._save(save, bundle)
    for broken in ({"total": 83}, {**score, "passes": False}, {**score, "severity": True}, {**score, "total": 101}, {**score, "extra": 1}):
        with pytest.raises(CommandError) as exc:
            admission._save({**save, "score": broken}, bundle)
        assert exc.value.code == "invalid_admission_score"


def test_resolved_place_facts_bind_exact_event_and_every_detached_state_field():
    state = {"drafts": old_rows()[:1], "publish_ledger": {}, "unknown_durable": {"number": 1, "source_day": AT.date()}}
    facts = resolve_admission_place_facts(state, "synthetic-new")
    args = dict(text="Invented new observation.", tweet_type="fire", event_id="synthetic-new", draft_id="new",
        at=AT, editorial_policy=current_editorial_policy(), place_facts=facts)
    planned = plan_draft_admission(deepcopy(state), **args)
    assert planned.draft is not None and planned.state["unknown_durable"] == state["unknown_durable"]
    assert type(planned.state["unknown_durable"]["source_day"]) is type(AT.date())
    for replacement in (AT.date().isoformat(), {"date": AT.date().isoformat()}, ["date", AT.date().isoformat()], AT.replace(hour=0)):
        lookalike = deepcopy(state)
        lookalike["unknown_durable"]["source_day"] = replacement
        with pytest.raises(ValueError, match="stale_admission_place_facts"):
            plan_draft_admission(lookalike, **args)
    changed_day = deepcopy(state)
    changed_day["unknown_durable"]["source_day"] = AT.date().isoformat()
    changed = deepcopy(state)
    changed["unknown_durable"]["number"] = 1.0  # Exact serialized state, not numeric normalization.
    for current, values in ((changed, args), (changed_day, args), (state, {**args, "event_id": "other-event"}),
                            ({**state, "publish_ledger": {"old": {"phase": "unknown"}}}, args)):
        with pytest.raises(ValueError, match="stale_admission_place_facts"):
            plan_draft_admission(current, **values)


def test_wrapper_preserves_exact_transient_and_unrelated_durable_references(monkeypatch):
    class LiveCycleObject:
        def __deepcopy__(self, memo):
            raise AssertionError("Transient cycle object must not enter planning")
    transients = {key: LiveCycleObject() for key in ("_triage_queue", "_funnel_sink", "_reganom_live_cache")}
    durable = {"empty": [], "number": 1.0}
    state = {"drafts": [], "unknown_durable": durable, **transients}
    monkeypatch.setattr(draft_save, "_utc_now", lambda: AT)
    assert draft_save.save_draft("Invented isolated observation.", state, "fire", "synthetic-event")
    assert state["unknown_durable"] is durable
    assert all(state[key] is value for key, value in transients.items())


def test_planner_in_fresh_process_never_reads_cold_place_registry():
    from dataclasses import asdict
    import json
    from pathlib import Path
    import subprocess
    import sys
    from src.data import places
    event = "alltime_high_" + places.event_location_key("Barcelona", "Spain") + "_2026-10-11"
    point = places.resolve_place("Barcelona", "Spain")
    legacy = dict(id="legacy", event_id="alltime_high_Barcelona_2026-10-11", text="Invented legacy observation.",
        city="Barcelona", tweet_date="2026-10-11", status="pending", score={"total": 70},
        review_context={"two_bot": {"bundle": {"raw_signal_dump": {k: point[k] for k in ("city", "country", "lat", "lon")}}}})
    states = [{"drafts": []}, {"drafts": [legacy]}, {"drafts": [{**legacy, "status": "posted"}]},
              {"drafts": [], "posted_events": ["country_high_Thailand_2026-10-11"]}]
    events = [event, event, event, "country_high_TH_2026-10-11"]
    payload = []
    for state, identity in zip(states, events):
        args = dict(text="Invented new observation.", tweet_type="all_time_high", event_id=identity,
            draft_id="new", editorial_policy=current_editorial_policy(), city="Barcelona", tweet_date="2026-10-11", score={"total": 80})
        facts = resolve_admission_place_facts(state, identity)
        expected = plan_draft_admission(state, at=AT, place_facts=facts, **args)
        payload.append(dict(state=state, args=args, facts=asdict(facts), expected=expected.reason, saved=expected.draft is not None))
    # This is a fresh interpreter, not an lru_cache-warmed in-process assertion.
    code = r'''
import json,sys
from datetime import UTC,datetime
from src.data import places
from src.editorial.draft_admission import AdmissionPlaceFacts,plan_draft_admission
rows=json.loads(sys.stdin.read())
places.registry.cache_clear();places.country_codes.cache_clear();places.resolve_place.cache_clear()
assert places.registry.cache_info().currsize==places.country_codes.cache_info().currsize==0
def no_io(event,args):
    if event in {"open","socket.connect","os.listdir","os.scandir"}:
        raise AssertionError("Planner performed I/O: "+event)
sys.addaudithook(no_io)
for row in rows:
    facts=row["facts"];facts["draft_place_ids"]=tuple(facts["draft_place_ids"])
    result=plan_draft_admission(row["state"],at=datetime(2026,10,11,12,tzinfo=UTC),place_facts=AdmissionPlaceFacts(**facts),**row["args"])
    assert result.reason==row["expected"] and (result.draft is not None)==row["saved"]
assert places.registry.cache_info().currsize==places.country_codes.cache_info().currsize==0
print("4 cold-registry planning cases passed without file or network I/O")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        input=json.dumps(payload), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout+result.stderr
    assert "4 cold-registry planning cases passed" in result.stdout
