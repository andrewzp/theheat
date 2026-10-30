"""Actual collector -> audit -> queue -> legacy/triage/refill drain -> health.

Invented RSS bodies only. The existing streaming RSS reader serves a mocked
response; generation entry is intercepted with a non-successful stop, so no
writer, checker, provider, save or paid call can occur.
"""
from copy import deepcopy
from itertools import permutations
import random
import socket
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest
import requests
import responses

from src import state as state_module
from src.data import gdacs
from src.orchestrator import common
from src.orchestrator.sources.gdacs import INTAKE_COUNTS, run_gdacs
from src.orchestrator.triage_queue import _drain_and_write_triage_queue, _enqueue_story_candidate
from src.state import DEFAULT_STATE
from tests.test_gdacs_intake_contract import items
from tests.test_gdacs_publication_freshness import NOW, feed

MODES = {"legacy": {}, "triage": {"THEHEAT_TRIAGE_ENABLED": "1"},
         "refill": {"THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_REFILL_ENABLED": "1"}}
SIX = ["intake-control", "intake-current-old", "intake-duplicate", "intake-shared-1", "intake-shared-2",
       "intake-unknown-country"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: NOW)
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("No network in invented intake")))
    for key in ("THEHEAT_TRIAGE_ENABLED", "THEHEAT_REFILL_ENABLED", "THEHEAT_FUNNEL_TELEMETRY"):
        monkeypatch.delenv(key, raising=False)


def journey(monkeypatch, bodies, mode, *, state=None, drain=True, witness=None):
    for key, value in MODES[mode].items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness or Mock(side_effect=AssertionError("No witness")))
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("No process I/O")))
    state = state if state is not None else deepcopy(DEFAULT_STATE)
    run = {"sources": []}
    entries = []

    def generation_entry(bundle, bot_state, score, **kwargs):
        entries.append(bundle.raw_signal_dump["source_event_id"])
        return None  # Non-successful stop; nothing downstream of entry runs.

    monkeypatch.setattr(common, "_try_two_bot_draft", generation_entry)
    calls = []
    for body in bodies:
        with responses.RequestsMock() as mock:
            if isinstance(body, int):
                mock.add(responses.GET, gdacs.GDACS_GEORSS_URL, status=body)
            else:
                mock.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=body)
            run_gdacs(state, run)
            calls += [call.request.url for call in mock.calls]
    queued = [row.bundle.raw_signal_dump.get("source_event_id") or row.event_id for row in state.get("_triage_queue", [])]
    result = _drain_and_write_triage_queue(state, run) if drain else None
    return dict(state=state, run=run, queue=queued, entries=entries, calls=calls, result=result)


def assert_no_spend_or_saved_effect(outcome):
    state = outcome["state"]
    assert outcome["result"] in (0, None) and state["drafts"] == []
    assert not state.get("writer_negative_cache")
    assert not any(row["stage"] not in {"duplicate_draft", "triage_cap"} for row in state.get("suppressions", []))


def intake_counts(row):
    counts = row["details"]["intake"]
    assert row["observed"] == sum(counts[key] for key in INTAKE_COUNTS)  # Exactly one disposition each.
    assert row["promoted"] == counts["queue_new"]
    return counts


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("same_event", [False, True])
@pytest.mark.parametrize("level", ["Green", "Red"])
@pytest.mark.parametrize("field", ["severity", "alert_score", "population"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_malformed_numeric_peer_never_discards_or_poison_valid_control(
        monkeypatch, mode, same_event, level, field, value):
    control = items("intake-control")[0]
    bad = deepcopy(control)
    ns = "{http://www.gdacs.org}"
    if not same_event:
        bad.find(ns + "eventid").text = "intake-malformed-number"
    bad.find(ns + "episodeid").text = "malformed-peer-episode"
    bad.find(ns + "alertlevel").text = level
    bad.find(ns + "episodealertlevel").text = level
    tag = {"severity": "severity", "alert_score": "alertscore", "population": "population"}[field]
    node = bad.find(ns + tag)
    if node is None:
        node = ET.SubElement(bad, ns + tag)
    if field == "alert_score":
        node.text = value
    else:
        node.set("value", value)
    outcome = journey(monkeypatch, [feed(bad, control)], mode)
    assert outcome["calls"] == [gdacs.GDACS_GEORSS_URL]
    assert outcome["queue"] == outcome["entries"] == ["intake-control"]
    row = outcome["run"]["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == 1
    diagnostics = row["details"]["feed_diagnostics"]
    assert diagnostics["feed_items_total"] == 2 and diagnostics["feed_items_validated"] == 1
    assert diagnostics["quarantined_items"] == 1 and diagnostics["status"] == "partial_feed"
    assert diagnostics["rejected_by_field"]["numeric_" + field] == 1
    assert diagnostics["rejected_selected_alerts"] == int(level == "Red")
    assert diagnostics["current_selection"]["ambiguous_groups"] == 0
    assert intake_counts(row)["queue_new"] == 1
    assert_no_spend_or_saved_effect(outcome)


@pytest.mark.parametrize("mode", MODES)
def test_held_groups_never_reach_generation_in_any_mode_or_xml_permutation(monkeypatch, mode):
    rows = items("intake-redred", "intake-redgreen", "intake-control")
    assert len(rows) == 5
    for ordering in permutations(rows):
        outcome = journey(monkeypatch, [feed(*deepcopy(list(ordering)))], mode)
        assert outcome["calls"] == [gdacs.GDACS_GEORSS_URL]
        assert outcome["queue"] == ["intake-control"] and outcome["entries"] == ["intake-control"]
        row = outcome["run"]["sources"][0]
        assert row["status"] == "degraded" and row["observed"] == row["promoted"] == 1
        assert "withheld_ambiguous_alerts:3 ambiguous_groups:2" in row["note"]
        assert row["details"]["feed_diagnostics"]["status"] == "ambiguous_current_selection"
        assert intake_counts(row)["queue_new"] == 1
        assert_no_spend_or_saved_effect(outcome)


@pytest.mark.parametrize("mode", MODES)
def test_mixed_capture_journey_is_xml_order_independent_with_exact_health(monkeypatch, mode):
    expected = None
    for seed in range(8):
        rows = items()
        random.Random(seed).shuffle(rows)
        outcome = journey(monkeypatch, [feed(*rows)], mode)
        assert outcome["queue"] == SIX  # Canonical exact source-key staging order.
        row = outcome["run"]["sources"][0]
        assert row["observed"] == row["promoted"] == 6 and outcome["calls"] == [gdacs.GDACS_GEORSS_URL]
        for token in ("quarantined_items:1", "withheld_selected_alerts:2", "withheld_current_alerts:4",
                      "withheld_ambiguous_alerts:5", "ambiguous_groups:3", "exact_duplicate_items:1"):
            assert token in row["note"]
        selection = row["details"]["feed_diagnostics"]["current_selection"]
        assert selection["selected_groups"] == 6 and selection["ambiguous_groups"] == 3
        assert intake_counts(row) == {"witness_skipped": 0, "history_duplicates": 0, "score_withheld": 0,
                                      "queue_new": 6, "queue_reused": 0, "queue_refused": 0, "pending_disagreements": 0}
        assert set(outcome["entries"]) <= set(SIX) and len(outcome["entries"]) == len(set(outcome["entries"]))
        assert_no_spend_or_saved_effect(outcome)
        observed = (outcome["queue"], outcome["entries"], row["note"])
        if expected is not None:
            assert observed == expected
        expected = observed
    assert expected is not None
    if mode == "legacy":
        assert expected[1] == SIX  # Every distinct staged candidate, in staged order.
    elif mode == "refill":
        # Contract change (live operating guards, O2): refill's own ceiling (2 x target 3 = 6)
        # used to attempt all six; with triage enabled it may no longer exceed the
        # operation's THEHEAT_MAX_DRAFTS_PER_CYCLE budget (default 3). Nothing succeeded.
        assert len(expected[1]) == 3 and set(expected[1]) <= set(SIX)
    else:
        assert len(expected[1]) == 2  # Existing per-category triage cap.


@pytest.mark.parametrize("mode", MODES)
def test_repeated_identical_collector_calls_admit_one_capture_once(monkeypatch, mode):
    body = feed(*items("intake-control", "intake-shared-1"))
    outcome = journey(monkeypatch, [body, body], mode)
    assert outcome["calls"] == [gdacs.GDACS_GEORSS_URL] * 2 and outcome["queue"] == ["intake-control", "intake-shared-1"]
    first, second = outcome["run"]["sources"]
    assert (first["observed"], first["promoted"], second["observed"], second["promoted"]) == (2, 2, 2, 0)
    assert intake_counts(second)["queue_reused"] == 2 and "queue_reused:2" in second["note"]
    assert sorted(outcome["entries"]) == ["intake-control", "intake-shared-1"]
    assert sum(row.get("triaged_in", 0) for row in outcome["run"]["sources"]) == 2
    assert not any(row["stage"] == "duplicate_draft" for row in outcome["state"].get("suppressions", []))
    assert len(outcome["state"]["candidates_log"]) == 2
    assert_no_spend_or_saved_effect(outcome)


def test_changed_later_capture_keeps_existing_event_rules_and_exposes_disagreement(monkeypatch):
    first = feed(*items("intake-control"))
    later_rows = items("intake-control")
    later_rows[0].find("description").text = "Invented later wording."
    outcome = journey(monkeypatch, [first, feed(*later_rows)], "legacy")
    second = outcome["run"]["sources"][1]
    assert outcome["queue"] == ["intake-control", "intake-control"]
    assert second["promoted"] == 1 and intake_counts(second)["pending_disagreements"] == 1
    assert "pending_disagreements:1" in second["note"]
    # The existing one-entry-per-event drain rule chooses; nothing is merged here.
    assert outcome["entries"] == ["intake-control"]
    assert [row["stage"] for row in outcome["state"]["suppressions"]] == ["duplicate_draft"]


def test_existing_history_and_non_gdacs_queue_behavior_are_unchanged(monkeypatch):
    from tests.two_bot.conftest import _bundle
    state = deepcopy(DEFAULT_STATE)
    fire = _bundle()
    for _ in range(2):  # A non-GDACS caller still appends each submission.
        assert _enqueue_story_candidate(state, bundle=fire, score=Mock(total=80), source="firms",
                                        legacy_type="fire", event_id=fire.event_id, review_context={})
    events_before = [row for row in state["_triage_queue"]]
    rows = items("intake-control", "intake-shared-1")
    posted = journey(monkeypatch, [feed(*rows)], "legacy", state=state, drain=False)
    assert posted["state"]["_triage_queue"][:2] == events_before  # Unrelated rows keep order and identity.
    assert posted["queue"] == [fire.event_id, fire.event_id, "intake-control", "intake-shared-1"]
    history = deepcopy(DEFAULT_STATE)
    control_id = posted["state"]["_triage_queue"][2].event_id
    history["posted_events"] = [control_id]
    outcome = journey(monkeypatch, [feed(*rows)], "legacy", state=history)
    row = outcome["run"]["sources"][0]
    assert intake_counts(row)["history_duplicates"] == 1 and outcome["entries"] == ["intake-shared-1"]


@responses.activate
@pytest.mark.parametrize("cohort", [("intake-redred",), ("intake-redred", "intake-control")])
def test_withheld_capture_health_persists_as_degraded_with_explicit_withholding(monkeypatch, cohort):
    from tests.test_gdacs_witness_provenance import persist_and_project
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", Mock(side_effect=AssertionError("No witness")))
    monkeypatch.setattr(common, "_try_two_bot_draft", Mock(side_effect=AssertionError("Collector only")))
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=feed(*items(*cohort)))
    bot_state = deepcopy(state_module.DEFAULT_STATE)
    run = state_module.init_run("alerts")
    run_gdacs(bot_state, run)
    row = run["sources"][0]
    expected = 1 if "intake-control" in cohort else 0
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == expected
    assert "withheld_ambiguous_alerts:2 ambiguous_groups:1" in row["note"]
    # Real Gist serialization (mocked HTTP) and the existing Node health projection.
    restored, projections = persist_and_project(monkeypatch, bot_state, run)
    assert restored["run_history"][0]["sources"][0]["details"]["intake"]["queue_new"] == expected
    health = restored["source_health"]["gdacs"]
    assert health["degraded"] == 1 and health["success"] == 0 and health["last_error"] == row["note"]
    for payload in projections:
        source = payload["sources"][0]
        assert source["health"] == source["last_run_status"] == "degraded"
        assert "withheld_ambiguous_alerts:2" in source["last_error"]
        assert payload["stats"]["healthy_count"] == 0


@pytest.mark.parametrize("case", ["empty", "outage", "access", "stale_clock", "malformed"])
def test_source_failure_and_empty_dispositions_stay_distinct_and_spend_nothing(monkeypatch, case):
    witness = Mock(return_value=gdacs.DisasterBatch([], source_diagnostics={
        "source_leg": gdacs.GDACS_SUBTYPE_LEG, "configured_product": "gdacs-subtype-witnesses",
        "primary_product": "gdacs-georss", "primary_status": "unavailable", "scope": ["Earthquake", "Tropical Cyclone"],
        "status": "witnesses_completed", "legs": {}, "selected_alerts": 0}))
    green = items("intake-control")
    green[0].find("{http://www.gdacs.org}alertlevel").text = "Green"
    green[0].find("{http://www.gdacs.org}episodealertlevel").text = "Green"
    body = {"empty": feed(*green), "outage": 503, "access": 401,
            "stale_clock": feed(*items("intake-control"), published="2026-09-01T00:00:00Z"),
            "malformed": "<rss><channel>"}[case]
    outcome = journey(monkeypatch, [body], "refill", witness=witness)
    row = outcome["run"]["sources"][0]
    assert outcome["queue"] == outcome["entries"] == [] and outcome["state"]["drafts"] == []
    assert len(outcome["calls"]) == (3 if case == "outage" else 1)  # Existing strict retry cap only.
    # Settled P09-C5 eligibility: transport outage and stale publication may use
    # the subtype witness; access, schema and an empty valid selection never do.
    assert witness.call_count == int(case in {"outage", "stale_clock"})
    if case == "empty":
        assert row["status"] == "degraded" and row["details"]["feed_diagnostics"]["status"] == "valid_no_qualifying_alerts"
        assert row["details"]["intake"]["queue_new"] == 0
    elif case in {"outage", "stale_clock"}:
        assert row["status"] == "degraded" and "served via subtype_witnesses" in row["note"]
    else:
        assert row["status"] == "failed" and row["promoted"] == 0


def test_strict_transport_exception_does_not_purchase_requests_beyond_retry_cap(monkeypatch):
    witness = Mock(side_effect=requests.ConnectionError("invented witness outage"))
    outcome = journey(monkeypatch, [503], "legacy", witness=witness)
    assert len(outcome["calls"]) == 3 and witness.call_count == 1
    assert outcome["run"]["sources"][0]["status"] == "failed" and outcome["entries"] == []
