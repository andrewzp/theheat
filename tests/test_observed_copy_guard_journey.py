"""Observed weather copy through the real source, writer, required checks and pending save.

Model replies are explicit offline fakes at the SDK client factories only
(``tests.live_content_harness.ModelScript``): the real writer request/parser, the deterministic
guards, the safety regex and interpreter, and the fact-check and critic interpreters all run.
Source bytes are invented and read by the real parsers. Nothing here posts, dispatches a
sender, calls X or writes a Gist; a saved pending draft is not a publication.

Contracts and their actual consumers:

* Positive complete path: the airport observed-temperature contrast (AWC METAR), with an
  ASCII-signed value, the appended public source citation and the real automatic arming.
* All six GHCN record comparators (high/low x archive/month/calendar date): their copy, with the
  available-archive scope and the literal verified cutoff, passes the real deterministic floor and
  the real safety pipeline; missing scope/cutoff and national/full-history claims refuse there.
  The dense full GHCN record bundle (> 32 KB) is refused by the pipeline's bundle capture before
  any model call. That refusal is retained as a limit (root's compact-claim work), not a success.
* Observed-only scope holds a real forecast bulletin before the writer.
* A failed or unavailable required check saves nothing; the writer runs once; no revise/refill.
* Automatic length counts the appended citation; an edit after checks invalidates the review.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import tempfile

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.data.temperature_evidence import temperature_claim_failures
from src.editorial import revisions
from src.editorial.automatic_text import AUTOMATIC_TEXT_MAX_SCALARS, automatic_text_hold
from src.orchestrator.metar_report import run_metar_report
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.voice import safety
from tests import live_content_harness as h
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_awc_observed import NOW, TARGET
from tests.test_awc_observed_automatic import Transport

# One clear observed story: two airports at the same UTC moment, a signed value typed with an
# ASCII hyphen, no forecast, and the reason it matters (the size of the simultaneous contrast).
COPY = "At 12:00 UTC Nov 15, North Test airport, Norway, recorded -20°C; South Test airport, Chile, 45°C—a 65°C gap."
CITATION = source.citation(["TAAA", "TBBB"], TARGET)
ENV = {
    "THEHEAT_OBSERVED_WEATHER_ONLY": "1", "THEHEAT_AWC_OBSERVED_CONTRAST": "1",
    "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0", "THEHEAT_WRITER_SAMPLES": "1",
    "THEHEAT_TRIAGE_ENABLED": "0", "THEHEAT_REFILL_ENABLED": "0", "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1",
    "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1", "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1",
    "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-observed-copy-epoch",
    "THEHEAT_PRODUCTION_PAUSED": "0", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
}
REQUIRED = ["writer", "safety", "fact_check", "critic"]


def _models(monkeypatch, **script):
    for key, value in {**h.MODEL_ENV, **ENV}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", h.INVENTED_TOKEN)
    monkeypatch.setattr(safety, "_SAFETY_CACHE", type(safety._SAFETY_CACHE)())
    models = h.ModelScript(**script)
    models.install(monkeypatch.setattr)
    return models


@pytest.fixture
def airport(monkeypatch, fresh_state):
    transport = Transport()
    transport.install(monkeypatch.setattr)
    run = {"id": "invented-observed-copy-run", "mode": "metar_report", "sources": []}
    return transport, fresh_state, run


def _generate(state, run):
    with freeze_time(NOW, tick=True):
        run_metar_report(state, run)


def _stage_kills(state):
    return [(row.get("stage"), row.get("reason")) for row in state.get("suppressions", [])]


# --- positive complete path -------------------------------------------------------------------

def test_observed_contrast_reaches_a_pending_draft_through_every_real_check(monkeypatch, airport):
    transport, state, run = airport
    models = _models(monkeypatch, copy=COPY)
    _generate(state, run)
    assert models.stages() == REQUIRED, _stage_kills(state)  # one writer, each required check once
    [draft] = state["drafts"]
    # The exact writer bytes plus the cited source, appended before the checks; no rewrite after them.
    assert draft["text"] == COPY + "\n" + CITATION
    checked = [request for stage, request in models.requests if stage == "safety"]
    assert len(checked) == 1 and draft["text"] in str(checked[0]["contents"])
    # Automatic length counts the citation, not just the writer's body.
    assert len(COPY) < AUTOMATIC_TEXT_MAX_SCALARS and len(draft["text"]) <= AUTOMATIC_TEXT_MAX_SCALARS
    assert automatic_text_hold(draft["text"]) is None
    # Saved and armed is not published: no sender ran, no X request, no ledger receipt.
    assert draft["status"] == "pending" and "tweet_id" not in draft and "posted_at" not in draft
    assert transport.x_posts == [] and draft["event_id"] not in state.get("publish_ledger", {})


@pytest.mark.parametrize("minus", ["-", "−"], ids=["ascii", "unicode"])
def test_signed_value_survives_unchanged_in_both_spellings(monkeypatch, airport, minus):
    _transport, state, run = airport
    copy = COPY.replace("-20°C", f"{minus}20°C")
    models = _models(monkeypatch, copy=copy)
    _generate(state, run)
    assert models.stages() == REQUIRED, _stage_kills(state)
    assert state["drafts"][0]["text"] == copy + "\n" + CITATION


def test_edit_after_checks_invalidates_the_model_review_through_the_real_revision_path(monkeypatch, airport):
    _transport, state, run = airport
    _models(monkeypatch, copy=COPY)
    _generate(state, run)
    [draft] = state["drafts"]
    assert draft["review_binding"]["kind"] == "model"
    assert revisions.review_is_current(draft)
    edited = deepcopy(draft)
    revisions.invalidate_text(edited, draft["text"].replace("65°C gap", "65°C difference"))
    assert edited["text"] != draft["text"] and not revisions.review_is_current(edited)
    assert edited.get("approval_binding") is None or edited["approval_binding"] != draft["approval_binding"]


# --- refusals at their actual consumers ---------------------------------------------------------

@pytest.mark.parametrize("script,stages,stage", [
    ({"fact_passed": False}, ["writer", "safety", "fact_check"], "fact_check"),
    ({"safety": "YES"}, ["writer", "safety"], "safety"),
    ({"safety": "MAYBE"}, ["writer", "safety"], "safety"),  # unparseable verdict = unavailable, held
    ({"writer_kill": "invented decline"}, ["writer"], None),
])
def test_a_failed_or_unavailable_required_check_saves_nothing(monkeypatch, airport, script, stages, stage):
    transport, state, run = airport
    models = _models(monkeypatch, copy=COPY, **script)
    _generate(state, run)
    assert models.stages() == stages
    assert state["drafts"] == [] and transport.x_posts == []
    if stage:
        assert any(kill == stage for kill, _reason in _stage_kills(state)), _stage_kills(state)


def test_missing_safety_credential_holds_before_any_safety_request(monkeypatch, airport):
    transport, state, run = airport
    models = _models(monkeypatch, copy=COPY)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    _generate(state, run)
    assert "safety" not in models.stages() and "fact_check" not in models.stages()
    assert state["drafts"] == [] and transport.x_posts == []


def test_citation_that_would_pass_the_automatic_cap_saves_nothing(monkeypatch, airport):
    # Existing contract: the body alone fits 200, the body plus its citation does not, and an
    # uncited body is never offered instead. The writer still ran once; nothing was saved.
    body = ("At 12:00 UTC Nov 15, Norway's North Test airport recorded -20°C, while Chile's South Test airport "
            "reported 45°C, a 65°C difference between these two airport observations made at the same UTC moment.")
    assert len(body) <= AUTOMATIC_TEXT_MAX_SCALARS < len(body) + 1 + len(CITATION)
    transport, state, run = airport
    models = _models(monkeypatch, copy=body)
    _generate(state, run)
    assert models.stages().count("writer") == 1 and state["drafts"] == [] and transport.x_posts == []


# --- the six GHCN record comparators ---------------------------------------------------------------

VARIANTS = [(direction, tier) for direction in ("high", "low") for tier in ("all_time", "monthly", "calendar")]
CUTOFF = "2026-09-02"  # The fixture's verified source cutoff; the reading is from 3 September.
SCOPE = f"in the available GHCN archive through {CUTOFF}"


def _record_copy(direction, tier):
    reading = "reached 40.2°C" if direction == "high" else "fell to -20.2°C"
    claim = {"all_time": f"its archive {direction}", "monthly": "a September record",
             "calendar": "a record for 3 September"}[tier]
    return f"Graphic Fixture {reading} on 3 September, {claim} {SCOPE}."


@pytest.mark.parametrize("direction,tier", VARIANTS)
def test_record_copy_keeps_scope_and_cutoff_through_the_real_deterministic_and_safety_checks(
        monkeypatch, direction, tier):
    bundle = graphic_bundles(direction=direction, tier=tier)[0]
    copy = _record_copy(direction, tier)
    models = _models(monkeypatch, copy=copy)
    assert temperature_claim_failures(copy, bundle) == []
    assert pipeline.fact_check.local_rejection(copy, [], bundle, deepcopy(DEFAULT_STATE)) is None
    assert safety.check_regex(copy) == (True, None)  # was "Banned pattern: '-09'" before S1
    assert safety.run_safety_pipeline(copy) == (True, None)
    assert models.stages() == ["safety"] and copy in str(models.requests[0][1]["contents"])


@pytest.mark.parametrize("direction,tier", VARIANTS)
@pytest.mark.parametrize("mutation,expected", [
    (lambda c: c.replace(f" through {CUTOFF}", ""), "verified cutoff"),
    (lambda c: c.replace(CUTOFF, "2026-09-01"), "verified cutoff"),
    (lambda c: c.replace("available ", ""), "verified cutoff"),
    (lambda c: c.replace(SCOPE, f"and a national record {SCOPE}"), "national records"),
    (lambda c: c.replace(SCOPE, f"in its complete observation history {SCOPE}"), "national records"),
], ids=["no-cutoff", "wrong-cutoff", "no-scope", "national", "full-history"])
def test_record_copy_without_scope_or_with_overclaim_is_refused_at_the_deterministic_floor(
        direction, tier, mutation, expected):
    bundle = graphic_bundles(direction=direction, tier=tier)[0]
    copy = mutation(_record_copy(direction, tier))
    rejected = pipeline.fact_check.local_rejection(copy, [], bundle, deepcopy(DEFAULT_STATE))
    assert rejected is not None and not rejected.passed and expected in " ".join(rejected.failures)


@pytest.mark.parametrize("direction,tier", VARIANTS)
def test_dense_full_record_bundle_is_held_at_capture_before_any_model_call(monkeypatch, direction, tier):
    # Retained limit, not a success: the full 26-year source calendar exceeds the 32 KB capture
    # bound. Root owns the production compact claim; this proves no paid call precedes the hold.
    bundle = graphic_bundles(direction=direction, tier=tier)[0]
    models = _models(monkeypatch, copy=_record_copy(direction, tier))
    outcome: dict = {}
    assert pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE), result_out=outcome) is None
    assert models.requests == []
    assert (outcome["kill_stage"], outcome["kill_reason"], outcome["writer_started"]) == (
        "bundle_retention", "bundle_capture_too_large", False)


@pytest.mark.parametrize("copy", [
    "Graphic Fixture reached 41.8°C on 3 September, its archive high in the available GHCN archive through 2026-09-02.",
    "Graphic Fixture reached 40.2°C on 7 September, its archive high in the available GHCN archive through 2026-09-02.",
    "Graphic Fixture is forecast to reach 40.2°C on 3 September, its archive high in the available GHCN archive through 2026-09-02.",
], ids=["wrong-value", "wrong-date", "forecast-phrasing"])
def test_value_date_and_forecast_phrasing_are_left_to_the_model_fact_check(copy):
    # Finding F-S2-1 (reported, not changed here): the deterministic floor passes these;
    # only the paid fact-check model can refuse them. None is not a factual pass.
    bundle = graphic_bundles(direction="high", tier="all_time")[0]
    assert pipeline.fact_check.local_rejection(copy, [], bundle, deepcopy(DEFAULT_STATE)) is None


# --- observed-only scope ------------------------------------------------------------------------------

def test_observed_only_scope_holds_a_real_forecast_bulletin_before_the_writer(monkeypatch):
    from src.editorial import hot10_contract
    from src.two_bot.intern import build_hot10_bundle
    from tests.gist_hazard_helpers import HOT10_CAPTURE

    with tempfile.TemporaryDirectory() as directory:
        _catalogue, normals, temps = h.qualified_inputs(Path(directory), HOT10_CAPTURE)
    result = hot10_contract.qualify(temps, normals, sampled=len(h.CITIES), now=HOT10_CAPTURE)
    bundle = build_hot10_bundle(result["rows"], changes=[], event_id="hot10_invented", universe=result["universe"])
    models = _models(monkeypatch, copy="An invented forecast leaderboard sentence.")
    outcome: dict = {}
    with freeze_time(datetime(2026, 10, 29, 23, 0, tzinfo=UTC)):
        assert pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE), result_out=outcome) is None
    assert models.requests == []
    assert outcome["kill_stage"] == "editorial_scope" and outcome["kill_reason"].startswith("editorial_forecast_excluded")
