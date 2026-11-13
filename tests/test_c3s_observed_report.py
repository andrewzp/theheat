"""Invented publisher pages through the real parser/bundle/current-source path."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.data import c3s_monthly as source
from src.editorial import observed_scope

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


def page(*, recent="0.8", pre="1.6", extra="", marker="globally ,"):
    return (f'<main id="maincontent"><article><h2>Global temperature</h2><li>October 2026 was the warmest October {marker} '
        f"with an average surface air temperature of 15.2°C, {recent}°C above the 1991-2020 average for the month.</li>"
        f"<li>October 2026 was {pre}°C above the estimated 1850-1900 pre-industrial average for the month.</li>"
        f"{extra}</article></main>").encode()


def report():
    return source.parse_report(page(), "2026-10", now=NOW)


def test_only_completed_month_findings_enter_the_bundle():
    raw = page(extra="<p>2026 is predicted to finish 1.9°C above its baseline, with a 99% probability.</p>")
    r = source.parse_report(raw, "2026-10", now=NOW)
    assert r["anomaly_1991_2020_c"] == .8 and r["anomaly_1850_1900_c"] == 1.6
    bundle = source.build_bundle(r)
    assert source.validate_bundle(bundle, now=NOW) == r
    assert observed_scope.story_hold(bundle, observed_only=True) is None
    assert "1.9" not in str(bundle.to_dict()) and "99%" not in str(bundle.to_dict())
    assert bundle.when == "2026-10-31" and bundle.event_id == "c3s_monthly_2026-10"


@pytest.mark.parametrize("month", ["2026-11", "2026-12", "2026-09", "../../private", "2026-13", "2026-1"])
def test_future_old_or_arbitrary_source_nomination_is_refused(month):
    with pytest.raises(source.ReportHeld):
        source.report_period(month, NOW)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"x" * (source.MAX_BODY+1),
    b"October 2026 is forecast to be the warmest October globally.",
    page().replace(b"was the warmest", b"might become the warmest"),
    page().replace(b"1991-2020", b"1981-2010"),
    page().replace(b"1850-1900", b"1901-2000"),
    page(extra=page(pre="1.8").decode()),
    b"<script>" + page() + b"</script>"],
    ids=["empty", "encoding", "oversize", "outlook", "future-tense", "recent-baseline", "old-baseline", "conflict", "script-only"])
def test_missing_conflicting_hidden_or_outlook_only_findings_never_become_data(raw):
    with pytest.raises(source.ReportHeld):
        source.parse_report(raw, "2026-10", now=NOW)


def test_markup_spacing_changes_do_not_change_selected_finding():
    a = source.parse_report(page(marker="globally,"), "2026-10", now=NOW)
    b = source.parse_report(page().replace(b"1.6", b"<strong>1.6</strong>"), "2026-10", now=NOW)
    assert a["finding_sha256"] == b["finding_sha256"] and a["response_sha256"] != b["response_sha256"]


def test_navigation_quotations_and_corrections_cannot_supply_a_current_finding():
    for raw in (b"<nav>" + page() + b"</nav><article>No finding</article>",
                b"<article><blockquote>" + page() + b"</blockquote></article>",
                page(extra="<p>Correction: the original monthly finding has been withdrawn.</p>")):
        if raw.startswith(b"<nav>"):
            # A navigation fragment is not an article. Supply its sentence outside
            # article markup rather than an invented nested main article.
            raw = raw.replace(b"<article>", b"<div>", 1).replace(b"</article>", b"</div>", 1)
        with pytest.raises(source.ReportHeld):
            source.parse_report(raw, "2026-10", now=NOW)


@pytest.mark.parametrize("field,value", [("source_url", "https://example.test/wrong"),
    ("source_product", "fake"), ("rank", "warmest ever"), ("anomaly_1850_1900_c", True),
    ("finding_sha256", "0"*64), ("retrieved_at", "2026-11-09T00:00:00Z")])
def test_retained_field_changes_cannot_reuse_a_finding(field, value):
    r = report()
    r[field] = value
    with pytest.raises(source.ReportHeld):
        source.validate_bundle(source.build_bundle(r), now=NOW)


def test_changed_derived_facts_or_kind_cannot_reuse_source(monkeypatch):
    monkeypatch.setenv(observed_scope.FLAG, "1")
    b = source.build_bundle(report()).to_dict()
    b["headline_metric"]["value"] = 99
    assert source.current_bundle_hold(b, live=False, now=NOW) == "c3s_current_source_unavailable"
    d = {"type": "monthly_high", "review_context": {"two_bot": {"bundle": source.build_bundle(report()).to_dict()}}}
    assert source.current_draft_hold(d, live=False, now=NOW) == "c3s_kind_changed"


def test_live_recheck_compares_finding_not_site_chrome(monkeypatch):
    monkeypatch.setenv(observed_scope.FLAG, "1")
    r = report()
    b = source.build_bundle(r).to_dict()
    captured = deepcopy(b)
    same = {**r, "response_sha256": "e"*64}
    calls = []
    def fetch(month, **_):
        calls.append(month)
        return same
    monkeypatch.setattr(source, "fetch_report", fetch)
    assert source.current_bundle_hold(b, live=False, now=NOW) is None and calls == []
    assert source.current_bundle_hold(b, live=True, now=NOW) is None and calls == ["2026-10"]
    same["finding_sha256"] = "f"*64
    assert source.current_bundle_hold(b, live=True, now=NOW) == "c3s_monthly_finding_changed"
    assert b == captured


def test_source_unavailable_never_uses_saved_label_as_live_confirmation(monkeypatch):
    monkeypatch.setenv(observed_scope.FLAG, "1")
    def unavailable(*_a, **_kw): raise source.ReportHeld("c3s_source_unavailable")
    monkeypatch.setattr(source, "fetch_report", unavailable)
    d = {"type": source.KIND, "review_context": {"two_bot": {"bundle": source.build_bundle(report()).to_dict()}}}
    assert source.current_draft_hold(d, live=True, now=NOW) == "c3s_current_source_unavailable"


def test_nomination_requires_observed_mode_and_real_critic_before_acquisition(monkeypatch):
    from src.orchestrator.observed_report import run_observed_report
    def forbidden(*_a, **_kw): raise AssertionError("no acquisition or model call")
    monkeypatch.setattr(source, "fetch_report", forbidden)
    monkeypatch.delenv(observed_scope.FLAG, raising=False)
    state, run = {"drafts": []}, {"sources": []}
    assert run_observed_report(state, run) is state and state["drafts"] == []
    assert run["sources"][0]["error"] == "c3s_observed_mode_and_critic_required"


@pytest.mark.parametrize("cap", ["0", "-1", "bad"])
def test_invalid_existing_candidate_limit_never_becomes_a_one_candidate_fallback(monkeypatch, cap):
    from src.orchestrator.observed_report import run_observed_report
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", cap)
    monkeypatch.setenv(observed_scope.FLAG, "1")
    def forbidden(*_a, **_kw): raise AssertionError("no acquisition or model call")
    monkeypatch.setattr(source, "fetch_report", forbidden)
    state, run = {"drafts": []}, {"sources": []}
    run_observed_report(state, run)
    assert state["drafts"] == [] and run["sources"][0]["status"] == "failed"


def test_real_observed_report_path_runs_every_stage_and_arms_only_that_exact_draft(monkeypatch):
    from freezegun import freeze_time
    from src.orchestrator.observed_report import run_observed_report
    from src.state import DEFAULT_STATE
    from src.two_bot import pipeline
    from tests.nhc_advisory_pipeline_helpers import stage_fakes
    monkeypatch.setenv(observed_scope.FLAG, "1")
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access", "GEMINI_API_KEY": "invented-no-access",
        "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_TRIAGE_ENABLED": "0",
        "THEHEAT_REFILL_ENABLED": "0", "THEHEAT_OBSERVED_REPORT_MONTH": "2026-10",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-observed-epoch",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-access")
    monkeypatch.setattr(source, "fetch_report", lambda *_a, **_kw: report())
    sent = []
    stages = stage_fakes(sent, copy="October was the warmest October in Copernicus’s record—1.6°C above the pre-industrial October average.")
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    from src.voice import safety
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-observed-run", "mode": "observed_report", "sources": []}
    with freeze_time(NOW, tick=True):
        run_observed_report(state, run)
    assert sent == ["writer", "safety", "fact_check", "critic"], str([(x.get("stage"), x.get("reasons")) for x in state.get("suppressions", [])])
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert draft["type"] == source.KIND and draft["review_binding"]["kind"] == "model"
    assert draft["approval_binding"]["mode"] == "auto" and draft["auto_approve_at"]
    assert draft["review_binding"]["editorial_policy"]["flags"]["observed_weather_only"] is True
    assert draft["review_context"]["two_bot"]["fact_check"]["passed"]
    assert report()["source_url"] in draft["text"]
    with freeze_time(NOW, tick=True):
        run_observed_report(state, {"id": "invented-repeat", "mode": "observed_report", "sources": []})
    assert sent == ["writer", "safety", "fact_check", "critic"]  # Same event never buys a second write.
    assert len(state["drafts"]) == 1
    # Continue through the real due sender, real write-first Gist boundary and
    # real X adapter against the invented HTTP transport. October31 remains the
    # data period: it must not be mistaken for an old queued breaking-news draft.
    import json
    from datetime import timedelta
    from src.orchestrator import posting
    from src.posting import twitter
    from tests import live_content_harness as h
    transport = h.Transport(gist={"state.json": json.dumps(state)}, now=lambda: NOW + timedelta(minutes=2))
    transport.install(monkeypatch.setattr)
    monkeypatch.setattr("src.state.GIST_ID", h.GIST_ID)
    monkeypatch.setattr("src.state.GITHUB_TOKEN", "invented-no-access")
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(twitter, key, "invented-no-access")
    monkeypatch.setattr(posting, "run_safety_pipeline", safety.run_safety_pipeline)
    with freeze_time(NOW + timedelta(minutes=2), tick=True):
        assert posting._autoship_freshness_anchor(draft) == NOW
        posting.process_due_drafts(state, {"sources": []})
    assert transport.x_posts == [draft["text"]]
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert draft["review_context"]["two_bot"]["bundle"]["when"] == "2026-10-31"
    with freeze_time(NOW + timedelta(minutes=4), tick=True):
        posting.process_due_drafts(state, {"sources": []})
    assert len(transport.x_posts) == 1


@pytest.mark.parametrize("created", [None, "invalid", "2099-01-01T00:00:00Z"])
def test_retrospective_freshness_invalid_queue_time_fails_closed(monkeypatch, created):
    from datetime import datetime, UTC
    from src.orchestrator import posting
    monkeypatch.setattr(posting, "_utc_now", lambda: NOW)
    value = report()
    draft = {"type": source.KIND, "created_at": created,
             "review_context": {"two_bot": {"bundle": source.build_bundle(value).to_dict()}}}
    assert posting._autoship_freshness_anchor(draft) == datetime.min.replace(tzinfo=UTC)
