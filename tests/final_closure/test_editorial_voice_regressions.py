"""Final closure B3: offline voice/factual regressions through the real SDK parsers.

The model boundary is the SDKs' own response types (tests/live_content_harness.py):
the real writer request/parser and the real safety, fact-check and critic
interpreters run unchanged, but every verdict is scripted to *approve*. A known
factual defect must still be rejected by the free local gates before any paid
check; that is the P07a rule "a known factual defect overrides all prose grades".

Texts are the repository's synthetic probe variants or newly invented copy; no
historical exact text, held draft or private corpus is read. A scripted approval
is never a quality or truth claim, and a control reaching the paid checks is
verification-required, not publishable gold.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.evaluation import historical as evaluation
from src.orchestrator.suppression import _record_downstream_suppression
from src.two_bot import pipeline
from tests import live_content_harness as h
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.two_bot.conftest import _bundle, _state_with_memory, configured_pipeline_providers  # noqa: F401

LABELS, SPECS = evaluation.load_catalog()
TARGETED = [(spec, v) for spec in SPECS.values() for v in spec["variants"] if v["expected_outcome"] == "targeted_rejection"]
CONTROLS = [(spec, v) for spec in SPECS.values() for v in spec["variants"] if v["expected_outcome"] == "verification_required"
            and not v.get("required_capability")]
REQUIRED_FINDINGS = {
    "alert_threshold_is_not_a_rain_record", "forecast_is_not_an_observed_record",
    "forecast_landfall_is_not_completed_landfall", "thermal_detection_is_not_verified_wildfire",
    "record_progression_and_later_quality_revision",
}


@pytest.fixture
def approving_models(monkeypatch):
    """Every model verdict approves; local gates alone must reject known defects."""
    from collections import OrderedDict
    from src.voice import safety
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    # A fresh exact safety cache per test, so every stage the pipeline buys is visible.
    monkeypatch.setattr(safety, "_SAFETY_CACHE", OrderedDict())
    h.trap_network(monkeypatch.setattr)
    script = h.ModelScript(fact_passed=True, safety="NO")
    script.install(monkeypatch.setattr)
    return script


def _codes(outcome):
    import re
    return set(evaluation.failure_codes(re.split(r"; (?=[a-z_]+:|temperature evidence:)", outcome.get("kill_reason", ""))))


def test_required_historical_findings_keep_their_evidence_limits():
    labels = {row["case_id"]: row for row in LABELS}
    assert REQUIRED_FINDINGS <= set(labels)
    for case_id in REQUIRED_FINDINGS:
        row = labels[case_id]
        assert row["evidence_limit"] and row["expected_rejection"] and row["permitted_claim"]
    # Limits that must survive (EVIDENCE.md): not proofs of original values or causes.
    assert "not recovered" in labels["forecast_is_not_an_observed_record"]["evidence_limit"]
    assert "not proven" in labels["thermal_detection_is_not_verified_wildfire"]["evidence_limit"].lower() \
        or "no independent classification" in labels["thermal_detection_is_not_verified_wildfire"]["evidence_limit"].lower()
    assert "does not establish when S was added" in labels["record_progression_and_later_quality_revision"]["evidence_limit"]


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("spec,variant", TARGETED, ids=lambda row: row.get("probe_id", row.get("case_id")))
def test_known_defect_overrides_approving_models_through_real_parsers(spec, variant, approving_models):
    approving_models.copy = variant["tweet"]
    outcome = {}
    bundle = evaluation.structural_bundle(spec)
    assert pipeline.generate_draft(bundle, {}, result_out=outcome) is None
    assert approving_models.stages() == ["writer"]  # Real SDK writer parse; no paid check bought.
    assert outcome["kill_stage"] == "fact_check"
    assert set(variant["expected_codes"]) <= _codes(outcome)
    rejected = outcome["rejected_candidate"]
    assert rejected["verdict"]["check_path"] == "local_precheck" and rejected["text"] == variant["tweet"]

    # Downstream consumer: the ordinary suppression ledger retains stage and the
    # fixed code; the private candidate stays in state, never in stdout.
    state = {"suppressions": []}
    _record_downstream_suppression(bot_state=state, source="synthetic_probe", run_id=None, event_id=bundle.event_id,
                                   score=None, kill_stage=outcome["kill_stage"], kill_reason=outcome["kill_reason"],
                                   summary=None, rejected_candidate=outcome["rejected_candidate"])
    row = state["suppressions"][-1]
    assert row["stage"] == "fact_check" and row["reasons"] == [outcome["kill_reason"]]
    assert set(variant["expected_codes"]) <= _codes({"kill_reason": row["reasons"][0]})
    assert row["rejected_candidate"]["text"] == variant["tweet"]


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("spec,variant", CONTROLS, ids=lambda row: row.get("probe_id", row.get("case_id")))
def test_controls_are_not_rejected_locally_and_still_buy_every_required_check(spec, variant, approving_models):
    approving_models.copy = variant["tweet"]
    draft = pipeline.generate_draft(evaluation.structural_bundle(spec), {}, result_out={})
    # The scripted approvals produce a draft only to prove the order of required
    # checks; this says nothing about the control's truth or quality.
    assert draft is not None and draft["text"] == variant["tweet"]
    assert approving_models.stages() == ["writer", "safety", "fact_check", "critic"]


def test_intervening_record_history_needs_named_archive_scope_and_cutoff():
    """The shared deterministic rule (generation precheck and retained checks).

    Invented GHCN progression from the real archive helpers; the full comparator is
    too large for a generation capture, so the shared local rule is called directly.
    """
    from src.two_bot import fact_check
    bundle = graphic_bundles(direction="high", tier="all_time")[-1]
    old_mark = "Sample Station broke its all-time heat record at 42.2°C, beating its 2020 mark."
    rejected = fact_check.local_rejection(old_mark, [], bundle, {})
    assert rejected is not None and not rejected.passed
    assert "temperature_scope_unqualified" in set(evaluation.failure_codes(rejected.failures))


@pytest.mark.usefixtures("configured_pipeline_providers")
@pytest.mark.parametrize("tweet,code", [
    ("A satellite detection model shows Mali thermal power at 361 MW.", "source_led_opener"),
    ("Mali thermal power is 361 MW, highlighting a hot dry season.", "generic_explanatory_ending"),
    ("Mali thermal power is 361 MW. The pixel is near Bamako. Detection was at noon.", "too_many_sentences"),
])
def test_voice_defect_is_rejected_free_through_the_real_sdk_writer(tweet, code, approving_models):
    approving_models.copy = tweet
    outcome = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=outcome) is None
    assert approving_models.stages() == ["writer"]
    assert outcome["kill_stage"] == "copy_gate" and outcome["kill_reason"].startswith(code)


@pytest.mark.usefixtures("configured_pipeline_providers")
def test_cutting_an_unsupported_ending_is_what_lets_an_evidence_equivalent_rewrite_proceed(approving_models):
    """P07a rewrite comparison, offline: same facts, ending removed. Not a model preference."""
    padded = "Mali thermal power is 361 MW, a stark reminder of a warming world."
    cut = "Mali thermal power is 361 MW."
    approving_models.copy = padded
    first = {}
    assert pipeline.generate_draft(_bundle(), _state_with_memory(), result_out=first) is None
    assert first["kill_stage"] == "copy_gate"
    approving_models.requests.clear()
    approving_models.copy = cut
    draft = pipeline.generate_draft(_bundle(), _state_with_memory(), result_out={})
    assert draft is not None and draft["text"] == cut
    assert approving_models.stages() == ["writer", "safety", "fact_check", "critic"]


def test_unenforced_capabilities_stay_named_holds_not_passes():
    pending = {v["probe_id"]: v["required_capability"] for spec in SPECS.values() for v in spec["variants"]
               if v.get("required_capability")}
    assert pending == {"unreconciled_rain": "product_disagreement_quarantine_not_yet_enforced",
                       "country_mismatch": "versioned_country_boundary_check_not_yet_enforced"}
    assert deepcopy(pending) == pending
