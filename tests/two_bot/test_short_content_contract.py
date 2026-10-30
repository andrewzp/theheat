"""Milestone C: a short complete writer target, soft critic quality details, the hard
automatic TEXT cap (200 Unicode scalars, Python/JS parity) and recheck invalidation.

Every copy, score and verdict here is invented. Model answers are explicit offline
SDK-shaped responses (tests/live_content_harness.py); they are not Andrew's rating
or measured copy quality. No network, model, Gist or X access.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest

from src.editorial.automatic_text import (
    AUTOMATIC_TEXT_MAX_SCALARS, HOLD_MESSAGES, MALFORMED, OVER_CAP, automatic_text_hold, scalar_count,
)
from src.state import DEFAULT_STATE
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
EPOCH = "invented-short-copy-epoch-01"
BASE = "Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure among 14 sampled cities"
CONCISE = BASE + "."  # 116 scalars.
AT_CAP = BASE + ", ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own monthly normals today."
OVER = BASE + ", ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own monthly normals, today."
LONG_TRUE = BASE + ", ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own normals in this forecast comparison."


def test_invented_copy_lengths_are_exact():
    assert [scalar_count(text) for text in (CONCISE, AT_CAP, OVER, LONG_TRUE)] == [116, 200, 201, 214]


# ---------------------------------------------------------------- C1: the writer target


def _system() -> str:
    from src.two_bot import writer

    request = writer.anthropic_writer_request("invented user prompt")
    assert request["max_tokens"] == 1024 and request["messages"] == [{"role": "user", "content": "invented user prompt"}]
    return request["system"][0]["text"]


def test_writer_request_carries_the_precise_short_target():
    system = _system()
    assert ("Usually 90-170 characters (Unicode scalars), no minimum or padding; over 200 cannot post automatically."
            in system)
    assert "One primary hook" in system and "No hype, invented stakes or second hook." in system
    assert ("Keep required forecast/model, sampled-universe, window and source qualifiers even when they cost "
            "characters; else narrow the angle or decline.") in system
    assert "No minimum character count; stay within 280 characters." not in system


def _examples(system: str) -> list[str]:
    line = next(row for row in system.splitlines() if row.startswith("Invented shapes, never evidence:"))
    return re.findall(r'"([^"]+)"', line)


def test_invented_examples_cover_each_family_and_stay_short_and_qualified():
    examples = _examples(_system())
    assert len(examples) == 4
    assert [("sampled cities" in e, "PM2.5" in e, "dust" in e, "not station-measured" in e) for e in examples] == [
        (True, False, False, False), (False, True, False, False), (False, False, True, False), (False, False, False, True)]
    for example in examples:
        assert 80 <= scalar_count(example) <= 170 and "forecast" in example
        assert "Port Example" in example or "Sample City" in example  # Fictional places, never evidence.


def _forecast_bundle():
    from src.two_bot.types import StoryBundle

    return StoryBundle(signal_kind="anomaly_hot", where="Port Example", when="2026-10-29", event_id="invented_c1_case",
                       headline_metric={"label": "forecast_high_c", "value": 47, "unit": "C"},
                       current_facts=[{"label": "source_product", "value": "openmeteo-best-match-forecast-daily-v1"}],
                       raw_signal_dump={"evidence": {"evidence_type": "forecast", "domain": "temperature_example"}})


def test_negated_disclaimer_example_passes_the_actual_observation_scan():
    from src.two_bot.scientific_claims import scientific_claim_failures

    weather = _examples(_system())[3]
    bundle = _forecast_bundle()
    assert scientific_claim_failures(weather, bundle) == []
    affirmative = weather.replace("not station-measured", "station-measured")
    assert any(f.startswith("forecast_as_observation") for f in scientific_claim_failures(affirmative, bundle))


def test_short_complete_copy_is_never_rejected_for_length():
    from src.two_bot import writer

    short = "Port Example is forecast to reach 47°C on Thursday."
    payload = {"tweet": short, "kill_reason": None, "angle_chosen": "forecast_value", "era_anchor_used": None,
               "peer_comparison_used": None, "reasoning": "Invented short response.", "cited_impact": None,
               "kill_scope": None, "kill_code": None}
    assert writer._parse_writer_json(json.dumps(payload)).tweet == short and scalar_count(short) < 90


# ---------------------------------------------------------------- C2: soft critic quality details

QUALITY = {"focus": "single", "repetition": "none", "jargon": "plain", "length": "ok", "consequence": "none"}


def _critic_bundle():
    return _forecast_bundle()


def test_critic_request_carries_the_exact_quality_instructions():
    from src.two_bot import critic

    contents = critic.prepare_request(CONCISE, _critic_bundle(), [], [])["contents"]
    assert ("quality: focus single|diffuse, repetition none|repetitive, jargon plain|jargon, length ok|long "
            "(over about 170 characters), consequence supported|none|unsupported.") in contents
    assert 'A missing consequence ("none") is fine, never a reason to demand one' in contents
    assert "an unsupported one means KILL unsupported_claim. Brevity is not a factual pass." in contents
    assert '"quality_note": null}' in contents


def _review(monkeypatch, body: dict):
    from src.two_bot import critic

    script = h.ModelScript(critic=body)
    script.install(monkeypatch.setattr)
    monkeypatch.setenv("GEMINI_API_KEY", h.INVENTED_TOKEN)
    result = critic.critic_review(CONCISE, _critic_bundle(), deepcopy(DEFAULT_STATE), shipped_recent=[])
    return result, script.stages()


def test_quality_details_parse_and_are_retained_with_the_verdict(monkeypatch):
    note = "Name the sampled-city universe earlier."
    result, stages = _review(monkeypatch, {"verdict": "PASS", "kill_reason": None, "revise_instruction": None,
                                           "selected_index": None, "quality": QUALITY, "quality_note": note})
    assert stages == ["critic"] and result.passed and result.verdict == "PASS"
    assert result.to_dict()["quality"] == QUALITY and result.to_dict()["quality_note"] == note


def test_unsupported_consequence_detail_fails_closed_without_another_call(monkeypatch):
    result, stages = _review(monkeypatch, {"verdict": "PASS", "kill_reason": None, "revise_instruction": None,
                                           "selected_index": None, "quality": {**QUALITY, "consequence": "unsupported"},
                                           "quality_note": None})
    assert stages == ["critic"]  # No parse retry or extra model call.
    assert not result.passed and result.verdict == "KILL" and result.kill_reason.startswith("unsupported_claim")


@pytest.mark.parametrize("quality", [{"focus": "single"}, {**QUALITY, "length": "short"}, "ok", {**QUALITY, "x": "y"}])
def test_malformed_quality_is_dropped_and_never_changes_a_verdict(monkeypatch, quality):
    result, _stages = _review(monkeypatch, {"verdict": "PASS", "kill_reason": None, "revise_instruction": None,
                                            "selected_index": None, "quality": quality, "quality_note": 7})
    assert result.passed and "quality" not in result.to_dict() and "quality_note" not in result.to_dict()


def test_good_quality_never_upgrades_a_kill_and_legacy_records_are_unchanged(monkeypatch):
    killed, _ = _review(monkeypatch, {"verdict": "KILL", "kill_reason": "missing_qualifier", "revise_instruction": None,
                                      "selected_index": None, "quality": QUALITY, "quality_note": None})
    assert not killed.passed and killed.kill_reason == "missing_qualifier"
    legacy, _ = _review(monkeypatch, {"verdict": "PASS", "kill_reason": None, "revise_instruction": None,
                                      "selected_index": None})
    assert set(legacy.to_dict()) == {"passed", "kill_reason", "raw_response", "verdict", "revise_instruction"}


# ---------------------------------------------------------------- C3: the hard automatic TEXT cap

VECTORS = [
    ("ascii-200", "a" * 200), ("ascii-201", "a" * 201), ("emoji-200", "🔥" * 200), ("emoji-201", "🔥" * 201),
    ("combining", "é" * 150 + "é" * 25), ("zwj", "👩‍👩‍👧" * 40), ("cjk", "熱" * 201),
    ("mixed", CONCISE), ("at-cap", AT_CAP), ("over", OVER),
]


@pytest.mark.parametrize(("name", "text"), VECTORS, ids=[name for name, _text in VECTORS])
def test_python_counts_unicode_scalars(name, text):
    assert scalar_count(text) == len(text)
    assert automatic_text_hold(text) == (OVER_CAP if len(text) > AUTOMATIC_TEXT_MAX_SCALARS else None)


def test_lone_surrogates_are_malformed():
    for text in ("\ud800", "a\udfff", "🔥\ud83d"):
        with pytest.raises(ValueError):
            scalar_count(text)
        assert automatic_text_hold(text) == MALFORMED
    assert automatic_text_hold(None) == MALFORMED


def test_python_and_javascript_hold_identically(tmp_path):
    node = os.environ.get("THEHEAT_TEST_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node is required for the JavaScript parity check")
    texts = [text for _name, text in VECTORS] + ["\ud800", "a\udfff", "🔥\ud83d"]
    vectors = tmp_path / "vectors.json"
    vectors.write_text(json.dumps(texts))  # ASCII escapes keep lone surrogates intact for both parsers.
    script = ("import fs from 'node:fs'; import { automaticTextHold, scalarCount } from './lib/automatic-text.js';"
              "const texts = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));"
              "console.log(JSON.stringify(texts.map(t => [automaticTextHold(t), t.isWellFormed() ? scalarCount(t) : null])))")
    run = subprocess.run([node, "--input-type=module", "-e", script, str(vectors)], cwd=ROOT / "dashboard",
                         env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    expected = []
    for text in json.loads(vectors.read_text()):
        hold = automatic_text_hold(text)
        expected.append([hold, None if hold == MALFORMED else scalar_count(text)])
    assert json.loads(run.stdout) == expected


@pytest.fixture
def world(tmp_path, monkeypatch):
    from freezegun import freeze_time

    world = h.install_hot10_world(tmp_path, monkeypatch, copy=CONCISE)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", EPOCH)
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    with freeze_time(T0, tick=True):
        yield world


def leaderboard(world, copy: str) -> Any:
    from src.orchestrator import hot10

    world.script.copy = copy
    world.script.requests.clear()
    state = deepcopy(DEFAULT_STATE)
    hot10.run_leaderboard(state, {"id": "run-short-c", "sources": []})
    return state


def test_allowlist_autoship_arming_is_capped_and_never_truncates(world):
    from src.editorial.revisions import approval_is_current, review_is_current

    armed = leaderboard(world, AT_CAP)["drafts"][0]
    assert armed["text"] == AT_CAP and armed.get("auto_approve_at") and "automatic_text_hold" not in armed
    assert armed["approval_mode"] == "auto" and approval_is_current(armed, "auto")
    for text in (OVER, LONG_TRUE):
        held = leaderboard(world, text)["drafts"][0]
        assert held["text"] == text and held["status"] == "pending"  # The complete draft, never shortened.
        assert held["automatic_text_hold"] == OVER_CAP and held["approval_mode"] == "manual"
        assert "auto_approve_at" not in held and "approval_binding" not in held
        assert review_is_current(held)  # Its current model review stays available for manual approval.
        assert world.script.stages() == ["writer", "safety", "fact_check", "critic"]  # Same checks, no extra stage.


def test_policy_auto_arming_is_capped_too(world, monkeypatch):
    """The armed_auto policy path (autoship flag off) at the real save boundary, with the
    review context the real checks produced for that exact text."""
    from src.editorial.scoring import score_hot10
    from src.orchestrator import draft_save

    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    for text, armed in ((AT_CAP, True), (OVER, False)):
        produced = leaderboard(world, text)["drafts"][0]
        state = deepcopy(DEFAULT_STATE)
        assert draft_save.save_draft(text, state, "hot10", produced["event_id"], score=score_hot10(9.2, 10, 10),
                                     candidate_score={"total": 90}, review_context=deepcopy(produced["review_context"]),
                                     evaluator_metadata={"hot10_rows": produced["hot10_rows"]})
        draft = state["drafts"][0]
        assert draft["approval_policy"]["mode"] == "armed_auto" and draft["text"] == text
        assert draft["approval_mode"] == ("policy_auto" if armed else "manual")
        assert bool(draft.get("auto_approve_at")) is armed and ("automatic_text_hold" in draft) is not armed


def _armed_before_cap(text: str) -> tuple[dict, Any]:
    """A draft armed for automatic send before this cap existed, through the real review/authorization
    functions (the legacy situation the send-time cap protects against). Not a claim about the save path."""
    from src.editorial import revisions
    from src.editorial.policy import current_editorial_policy

    bundle = {"event_id": "invented_capped_event", "signal_kind": "co2_milestone"}
    policy = current_editorial_policy()
    draft: dict[str, Any] = {"id": "draft_pre_cap", "event_id": "invented_capped_event", "type": "co2_milestone", "text": text,
             "status": "pending", "created_at": "2026-10-29T08:00:00Z",
             "approval_policy": {"mode": "armed_auto", "can_auto_approve": True, "recommended_delay_minutes": 20},
             "review_context": {"two_bot": {"bundle": bundle, "fact_check": {"passed": True},
                                            "critic": {"passed": True, "verdict": "PASS"},
                                            "reviewed_text_sha256": revisions.text_hash(text),
                                            "reviewed_bundle_sha256": revisions.fingerprint(bundle),
                                            "reviewed_policy_sha256": revisions.fingerprint(policy)}}}
    revisions.initialize_revision(draft)
    revisions.authorize_draft(draft, "auto", publication_epoch=EPOCH)
    draft.update(approval_mode="policy_auto", auto_approve_at="2026-10-29T08:30:00Z")
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    return draft, state


def test_send_time_cap_holds_an_over_cap_draft_armed_before_the_cap(world, monkeypatch):
    from src.orchestrator import posting
    from tests.gist_media_helpers import install_fake_x

    fake = install_fake_x(monkeypatch)
    draft, state = _armed_before_cap(OVER)
    fake.posting.process_due_drafts(state)
    assert fake.calls == [] and fake.safety.call_count == 0
    assert draft["approval_mode"] == "manual" and draft["post_error"] == HOLD_MESSAGES[OVER_CAP]
    assert "auto_approve_at" not in draft and draft["text"] == OVER
    direct, direct_state = _armed_before_cap(OVER)
    assert posting.post_approved(direct, direct_state) == "failed"
    assert direct["post_error"] == HOLD_MESSAGES[OVER_CAP] and direct_state["publish_ledger"] == {}


def test_long_true_draft_stays_manually_publishable(world, monkeypatch):
    from src.editorial import revisions
    from tests.gist_media_helpers import install_fake_x

    draft = leaderboard(world, LONG_TRUE)["drafts"][0]
    fake = install_fake_x(monkeypatch)
    # The Hot10 card flag is off by default, so the ordinary sender posts text only.
    monkeypatch.setattr(fake.posting, "_hot10_media_for_draft", lambda _draft: (None, None))
    revisions.record_human_review(draft)
    revisions.authorize_draft(draft, "manual", "invented-manual-intent")
    draft.update(status="approved", approval_mode="manual", publish_intent_id="invented-manual-intent")
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    assert fake.posting.post_approved(draft, state) == "posted"
    assert fake.calls == [("create", LONG_TRUE, {})]  # The exact complete text; the cap is automatic-only.


# ---------------------------------------------------------------- C4: edits, select, source change, recheck


def _fresh_checks(draft: dict, text: str, bundle: dict | None = None) -> None:
    """What the pipeline binds after required checks pass for this exact text and source."""
    from src.editorial import revisions
    from src.editorial.policy import current_editorial_policy

    two_bot = draft["review_context"]["two_bot"]
    bundle = bundle if bundle is not None else two_bot["bundle"]
    two_bot.update(fact_check={"passed": True, "failures": [], "raw_response": "invented recheck"},
                   critic={"passed": True, "kill_reason": None, "raw_response": "invented recheck", "verdict": "PASS",
                           "revise_instruction": None},
                   reviewed_text_sha256=revisions.text_hash(text), reviewed_bundle_sha256=revisions.fingerprint(bundle),
                   reviewed_policy_sha256=revisions.fingerprint(current_editorial_policy()))


def test_edit_select_source_change_and_restored_text_invalidate_old_passes(world):
    from src.editorial import revisions

    draft = leaderboard(world, CONCISE)["drafts"][0]
    assert revisions.approval_is_current(draft, "auto")
    original_bundle = deepcopy(draft["review_context"]["two_bot"]["bundle"])
    revisions.invalidate_text(draft, CONCISE.replace("largest", "biggest"))  # An ordinary edit.
    assert not revisions.review_is_current(draft) and "auto_approve_at" not in draft
    assert set(draft["review_context"]["two_bot"]) <= {"bundle", "signal_kind"}  # Old verdicts are not carried.
    revisions.invalidate_text(draft, CONCISE)  # Restoring the reviewed text does not restore its passes.
    revisions.record_model_review(draft)
    assert not revisions.review_is_current(draft) and draft["content_revision"] == 3
    with pytest.raises(ValueError):
        revisions.authorize_draft(draft, "auto", publication_epoch=EPOCH)
    # A candidate selection is the same text transition (dashboard select_candidate → invalidateText).
    revisions.invalidate_text(draft, AT_CAP)
    assert not revisions.review_is_current(draft)
    # A source change keeps the text but changes the evidence identity.
    _fresh_checks(draft, AT_CAP)
    revisions.record_model_review(draft)
    assert revisions.review_is_current(draft)
    draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["cities"][0]["temp_high_c"] = 45.0
    assert not revisions.review_is_current(draft)
    draft["review_context"]["two_bot"]["bundle"] = original_bundle
    assert revisions.review_is_current(draft)  # The exact reviewed source again, nothing else.


def test_fresh_recheck_restores_eligibility_only_for_current_copy_and_source(world):
    from src.editorial import revisions

    draft = leaderboard(world, CONCISE)["drafts"][0]
    revisions.invalidate_text(draft, CONCISE.replace("largest", "biggest"))
    _fresh_checks(draft, CONCISE)  # Checks of other text cannot bind.
    revisions.record_model_review(draft)
    assert not revisions.review_is_current(draft)
    changed = deepcopy(draft["review_context"]["two_bot"]["bundle"])
    changed["raw_signal_dump"]["universe"]["sampled_cities"] = 99
    _fresh_checks(draft, draft["text"], changed)  # Checks of another source cannot bind.
    revisions.record_model_review(draft)
    assert not revisions.review_is_current(draft)
    _fresh_checks(draft, draft["text"])
    revisions.record_model_review(draft)
    assert revisions.review_is_current(draft)
    revisions.authorize_draft(draft, "auto", publication_epoch=EPOCH)
    assert revisions.approval_is_current(draft, "auto")


REAL_CONSUMER_CASES = [
    ("short false copy", "Riyadh hit 39.2°C among 14 sampled cities.", "killed"),
    ("long true copy", LONG_TRUE, "manual_only"),
    ("missing forecast qualifier", "Riyadh's high of 39.2°C runs 9.2°C above its October normal among 14 sampled cities.",
     "killed"),
    ("observation substitution", "Riyadh recorded 39.2°C, 9.2°C above its October normal among 14 sampled cities.",
     "killed"),
    ("record substitution", "Riyadh is forecast to set a record 39.2°C, 9.2°C above normal among 14 sampled cities.",
     "killed"),
    ("unsupported impact", "Riyadh's forecast 9.2°C departure among 14 sampled cities could fill hospitals.", "killed"),
    ("valid concise result", CONCISE, "armed"),
]


@pytest.mark.parametrize(("label", "copy", "outcome"), REAL_CONSUMER_CASES, ids=[case[0] for case in REAL_CONSUMER_CASES])
def test_real_consumers_decide_each_invented_copy(world, label, copy, outcome):
    state = leaderboard(world, copy)
    stages = world.script.stages()
    assert world.settled[-1][2] is True  # One started writer per operation in every case.
    if outcome == "killed":
        assert state["drafts"] == [] and stages == ["writer"], label
        return
    draft = state["drafts"][0]
    assert draft["text"] == copy and stages == ["writer", "safety", "fact_check", "critic"]
    assert bool(draft.get("auto_approve_at")) is (outcome == "armed")
    assert ("automatic_text_hold" in draft) is (outcome == "manual_only")


def test_send_boundary_recomputes_the_cap_from_current_text(world):
    from src.orchestrator import posting

    draft = leaderboard(world, CONCISE)["drafts"][0]
    assert automatic_text_hold(draft["text"]) is None and posting.automatic_text_hold is automatic_text_hold
    assert (datetime.fromisoformat(draft["auto_approve_at"].replace("Z", "+00:00")) - T0) <= timedelta(minutes=31)
