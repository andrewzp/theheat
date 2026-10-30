"""Milestone F2: one combined native manual journey, for root's Linux CI.

The same source-produced PM2.5 copy (the real air-quality source runner, drain,
SDK-shaped offline checks and admission) gets the native Pillow chart, the trusted
delegated joint review, ordinary manual approval and the real manual sender to the
fake X SDK factories, with unrelated drafts and ledger rows preserved. It renders
with the pinned native toolchain, so it runs only on Linux, where root's CI pins
Pillow/FreeType; it is skipped elsewhere and never forced on locally. The route-level
attach/review of PM2.5 graphics stays in the existing actual-handler journeys.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
import sys

from freezegun import freeze_time
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="native rendering journey: root runs it on Linux CI")


def test_source_produced_pm25_copy_reaches_x_with_its_native_chart_once(tmp_path, monkeypatch):
    from src.data import places
    from src.editorial import delegated_media_review as seam, revisions
    from src.media import gist_hazard_media as hazard
    from src.orchestrator.candidate_budget import CandidateBudget
    from src.orchestrator.sources.air_quality import run_air_quality
    from src.orchestrator.suppression import _activate_suppression_ctx
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue
    from src.state import DEFAULT_STATE
    from tests import live_content_harness as h
    from tests.gist_media_helpers import install_fake_x, run_manual

    copy = "Lahore's PM2.5 is forecast to average 250 µg/m³ today, about 17 times the WHO 24-hour guideline, per CAMS model data."
    lahore = {**(row := h.catalogue_rows(["Lahore"])[0]), **places.place_for_row(row)}
    transport = h.Transport(air_quality={h.coordinate_key(lahore["lat"], lahore["lon"]): {"pm25": 250.0, "dust": 100.0}})
    transport.install(monkeypatch.setattr)
    h.ModelScript(copies={"air_quality_hazard": copy}).install(monkeypatch.setattr)
    for name, value in {**h.MODEL_ENV, "THEHEAT_AQ_DUST_ENABLED": "0"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", h.INVENTED_TOKEN)
    monkeypatch.setattr("src.data.air_quality._pacing_sleep", lambda _s: None)
    state = deepcopy(DEFAULT_STATE)
    unrelated = {"id": "unrelated", "event_id": "unrelated-event", "type": "co2_milestone", "text": "Unrelated.", "status": "pending"}
    state["drafts"] = [deepcopy(unrelated)]
    state["publish_ledger"] = {"other-event": {"tweet_id": "invented-other", "phase": "confirmed"}}
    with freeze_time("2026-10-29T13:00:00Z", tick=True):
        _activate_suppression_ctx(state, source="air_quality", run_id="run-f2")
        run = {"id": "run-f2", "sources": []}
        run_air_quality(state, run, [lahore])
        _drain_and_write_triage_queue(state, run, candidate_budget=CandidateBudget.for_operation("alerts"))
        draft = next(d for d in state["drafts"] if d["type"] == "air_quality_hazard")
        prepared = hazard.prepare_media(draft["review_context"]["two_bot"]["bundle"])
        revisions.invalidate_media_attachment(draft, prepared["descriptor"], at="2026-10-29T13:05:00Z")
        authorization = tmp_path / "authorization.json"
        authorization.write_text(json.dumps({"schema": seam.AUTHORIZATION_SCHEMA, "scope": "one_manual_post",
                                             "draft_id": draft["id"], "granted_by": "andrew", "reviewer": "codex"}))
        receipt = tmp_path / "receipt.json"
        receipt.write_text(json.dumps(seam.expected_receipt(draft, authorization_sha256=sha256(authorization.read_bytes()).hexdigest())))
        seam.record_verified(draft, authorization_path=authorization, receipt_path=receipt)
        revisions.authorize_draft(draft, "manual", "invented-native-intent")
        draft.update(status="approved", approval_mode="manual", publish_intent_id="invented-native-intent")
        fake = install_fake_x(monkeypatch)
        run_manual(monkeypatch, fake, state, draft)
    assert draft["text"] == copy and draft["review_binding"]["kind"] == "delegated_media"
    assert fake.calls == [("upload", prepared["png"], "hot10.png"), ("alt", "98765", prepared["delivery_text"]),
                          ("create", copy, {"media_ids": ["98765"]})]
    assert sha256(prepared["png"]).hexdigest() == draft["media_attachment"]["image"]["png_sha256"]
    assert next(d for d in state["drafts"] if d["id"] == "unrelated") == unrelated
    assert state["publish_ledger"]["other-event"] == {"tweet_id": "invented-other", "phase": "confirmed"}
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
