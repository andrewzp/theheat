"""Real staged airport slates cannot spend their one writer slot on old evidence.

HTTP bytes and SDK replies are invented. Source parsing, threaded staging,
selection, budget, all required checks and pending admission are unmodified.
No sender or platform call runs; this is not live-model or source-truth evidence.
"""
from datetime import timedelta
import gzip
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.orchestrator import funnel
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.scheduler import SourceRunner, run_stage1_sources
from src.orchestrator.sources.awc_observed import run_awc_observed
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.two_bot.types import StoryBundle
from tests import live_content_harness as h
from tests.test_awc_observed import NOW, TARGET, csv_bytes, history_xml
from tests.test_awc_observed_automatic import Transport
from tests.test_observed_airport_body_budget import SHORT, clock, ordinary


class DatedTransport(h.Transport):
    """Serve the current invented capture at its own historical-query date."""

    def __init__(self, initial: Transport):
        super().__init__()
        self.stations = initial.stations
        self.rows = initial.rows
        self.awc_calls: list[tuple[str, dict]] = []

    def send(self, _adapter, request, **_options):
        parts = urlsplit(request.url)
        url = f"{parts.scheme}://{parts.netloc}{parts.path}"
        if url not in (source.METARS_URL, source.STATIONS_URL, source.HISTORY_URL):
            return super().send(_adapter, request, **_options)
        assert request.method == "GET" and _options["stream"] is True
        query = {key: value[0] for key, value in parse_qs(parts.query).items()}
        if url == source.HISTORY_URL:
            assert query == {"ids": "TAAA,TBBB", "format": "xml", "taf": "false",
                             "hours": "2", "date": self.rows[0][2]}
            body = history_xml(self.rows)
        else:
            assert query == {}
            raw = csv_bytes(self.rows) if url == source.METARS_URL else json.dumps(self.stations).encode()
            body = gzip.compress(raw, mtime=0)
        self.awc_calls.append((url, query))
        return h._reply(request, 200, body)


def stage(state, run):
    run_stage1_sources(state, run, serial_runners=[],
        concurrent_runners=[SourceRunner("awc_observed", run_awc_observed)], max_workers=1)
    row = run["sources"][-1]
    assert row["source"] == "awc_observed" and row["status"] == "success", row
    assert row["promoted"] == 1


def slate(monkeypatch, state, *, triage, fresh):
    initial, models, _run, _budget = ordinary(monkeypatch, state, triage=triage)
    transport = DatedTransport(initial)
    transport.install(monkeypatch.setattr)
    old_target = (NOW - timedelta(days=1, minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in transport.rows:
        row[0] = row[0].replace("151200Z", "141200Z")
        row[2] = old_target
    with freeze_time(NOW - timedelta(days=1), tick=True):
        stage(state, {"id": "invented-previous-source", "mode": "alerts", "sources": []})
    [old] = state["_triage_queue"]
    assert old.event_id == "metar_pair_TAAA_TBBB_2026-11-14"
    assert models.stages() == []
    if fresh:
        for row in transport.rows:
            row[0] = row[0].replace("141200Z", "151200Z")
            row[2] = TARGET
        with freeze_time(NOW, tick=True):
            stage(state, {"id": "invented-current-source", "mode": "alerts", "sources": []})
        assert len(state["_triage_queue"]) == 2
        current = state["_triage_queue"][1]
        assert current.event_id == "metar_pair_TAAA_TBBB_2026-11-15"
        assert old.score.total >= current.score.total
    return transport, models, old


@pytest.mark.parametrize("triage", ["0", "1"], ids=["legacy", "production-triage"])
@pytest.mark.parametrize("reverse", [False, True], ids=["old-first", "fresh-first"])
def test_staged_old_pair_cannot_take_the_fresh_pairs_only_sdk_attempt(
        monkeypatch, fresh_state, triage, reverse):
    transport, models, old = slate(monkeypatch, fresh_state, triage=triage, fresh=True)
    if reverse:
        fresh_state["_triage_queue"].reverse()
    run: dict = {"id": "invented-mixed-drain", "mode": "alerts", "sources": []}
    sink = funnel.new_funnel()
    # Use the actual configured operation budget: legacy intentionally has no
    # ranking cap, while the route and automatic policy still permit one story.
    budget = CandidateBudget.for_operation("alerts")
    # The drain follows the captures, rather than rewinding the ticking clock
    # to before their retrieved_at timestamps on each new freeze context.
    with freeze_time(NOW + timedelta(minutes=1), tick=True), _suppression_context(
            fresh_state, source="alerts", run_id=run["id"]):
        count = _drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget, funnel_sink=sink)
        assert count == 1, [(row["event_id"], row["stage"], row.get("reasons"))
                            for row in fresh_state.get("suppressions", [])]
        [saved] = fresh_state["drafts"]
        raw = json.loads(json.dumps(saved["review_context"]["two_bot"]["bundle"], allow_nan=False))
        assert source.validate_bundle(StoryBundle(**raw), now=clock)["points"][0]["valid_time"] == TARGET
        assert source.claim_failures(saved["text"], raw, now=clock) == []
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert budget.attempts == 1 and not budget.seen("event:" + old.event_id)
    assert saved["event_id"] == "metar_pair_TAAA_TBBB_2026-11-15"
    assert saved["text"] == SHORT + "\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert len(saved["text"]) <= 200 and saved["approval_binding"]["mode"] == "auto"
    assert saved["status"] == "pending" and "tweet_id" not in saved
    assert sink["_slate_terminal"][old.event_id] == "awc_source"
    report = next(row for row in run["sources"] if row["source"] == "automatic_selection")
    assert report["details"]["source_ready_count"] == 1
    assert report["details"]["held_source_candidates"] == 1
    assert [query["date"] for url, query in transport.awc_calls if url == source.HISTORY_URL] == [TARGET, TARGET]
    assert transport.x_posts == [] and transport.gist_patches == 0
    assert fresh_state.get("publish_ledger", {}) == {}


@pytest.mark.parametrize("triage", ["0", "1"], ids=["legacy", "production-triage"])
def test_staged_all_old_pairs_make_no_sdk_request_or_budget_reservation(monkeypatch, fresh_state, triage):
    transport, models, old = slate(monkeypatch, fresh_state, triage=triage, fresh=False)
    run: dict = {"id": "invented-held-drain", "mode": "alerts", "sources": []}
    budget = CandidateBudget.for_operation("alerts")
    before_http = list(transport.awc_calls)
    with freeze_time(NOW + timedelta(minutes=1), tick=True), _suppression_context(
            fresh_state, source="alerts", run_id=run["id"]):
        assert _drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget) == 0
    assert models.stages() == [] and budget.attempts == 0
    assert not budget.seen("event:" + old.event_id) and fresh_state["drafts"] == []
    assert transport.awc_calls == before_http  # Classification makes no source refresh.
    assert transport.x_posts == [] and transport.gist_patches == 0
    report = next(row for row in run["sources"] if row["source"] == "automatic_selection")
    assert report["details"]["source_ready_count"] == 0
    assert report["details"]["held_source_candidates"] == 1


@pytest.mark.parametrize("seconds_before_delay_boundary,expected", [(10, 1), (-10, 0)],
                         ids=["send-delay-fits", "send-delay-would-expire"])
def test_real_source_window_preflight_reserves_time_for_the_minimum_send_delay(
        monkeypatch, fresh_state, seconds_before_delay_boundary, expected):
    transport, models, _old = slate(monkeypatch, fresh_state, triage="1", fresh=True)
    run: dict = {"id": "invented-window-drain", "mode": "alerts", "sources": []}
    budget = CandidateBudget.for_operation("alerts")
    boundary = NOW.replace(hour=12, minute=0) + source.MAX_AGE - timedelta(minutes=source.AUTO_DELAY_MINUTES)
    at = boundary - timedelta(seconds=seconds_before_delay_boundary)
    before_http = list(transport.awc_calls)
    with freeze_time(at, tick=True), _suppression_context(fresh_state, source="alerts", run_id=run["id"]):
        assert _drain_and_write_triage_queue(fresh_state, run, candidate_budget=budget) == expected
    assert budget.attempts == expected and len(fresh_state["drafts"]) == expected
    assert models.stages() == (["writer", "safety", "fact_check", "critic"] if expected else [])
    if not expected:
        assert transport.awc_calls == before_http
        report = next(row for row in run["sources"] if row["source"] == "automatic_selection")
        assert report["details"]["source_holds"] == {
            "awc_observation_expired": 1, "awc_source_insufficient_window": 1}
    assert transport.x_posts == [] and transport.gist_patches == 0
