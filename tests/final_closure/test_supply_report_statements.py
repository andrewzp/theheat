"""A6: report statements keep quote, attribution, date, language/translation and source revision into the editor.

The real supplied-packet producer (``report_supply._packet_items``) builds the
statements; the strict evidence contract checks them; the shared fixture is the
exact draft shape the dashboard editor reads (dashboard/tests/
final-closure-supply-report-statements.test.js). Invented report only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from src.editorial import report_supply as rs
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import StoryBundle
from tests.remaining_campaign.test_w08_report_portfolio import RETAINED

FIXTURE = Path(__file__).parent / "fixtures" / "supply_report_statements.json"
TEXT = RETAINED + " Las carreteras siguen cerradas."


def _produce():
    report = {"schema": rs.REPORT_SCHEMA, "retrieval_status": "full_text_retained", "retained_text": TEXT,
              "retained_text_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
              "source_name": "Ficta Daily (invented)", "url": "https://example.invalid/ficta/flood",
              "source_date": "2026-10-28", "report_sha256": "c" * 64, "claims": [
                  {"claim_id": "c1", "quote": "120 households were evacuated", "attribution": "Ficta Civil Protection",
                   "original_language": "en", "translation": {"status": "not_needed"}},
                  {"claim_id": "c2", "quote": "Las carreteras siguen cerradas", "attribution": "Ficta municipality",
                   "original_language": "es", "translation": {"status": "human_reviewed", "text": "Roads remain closed",
                                                              "decision_ref": "editor-note-invented-7"}}]}
    bundle = StoryBundle(signal_kind="global_flood", where="Ficta", when="2026-10-28", event_id="report_invented_ficta",
                         headline_metric={"label": "households_evacuated", "value": 120},
                         current_facts=[{"label": "source_name", "value": "Ficta Daily (invented)"}],
                         raw_signal_dump={"source": "Ficta Daily (invented)"})
    digest = hashlib.sha256(capture_bundle(bundle).serialized.encode()).hexdigest()
    packet = {"target_event_id": bundle.event_id, "bundle_sha256": digest, "report": report,
              "selected_claim_ids": ["c1", "c2"]}
    items = rs._packet_items(packet, SimpleNamespace(bundle=bundle, review_context={}))
    bundle.human_impact = items
    return bundle, items


def test_producer_statements_pass_the_checks_and_match_the_editor_fixture():
    bundle, items = _produce()
    assert not [issue for issue in audit_story_bundle(bundle).issues if issue.code.startswith("impact")]
    reviewed = next(item for item in items if item["claim_id"] == "c2")
    assert reviewed["value"] == "Las carreteras siguen cerradas" and reviewed["claim"] == "Roads remain closed"
    assert reviewed["translation"]["independent_confirmation"] is False
    assert all(item["retained_text_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest() for item in items)
    draft = json.loads(FIXTURE.read_text())["draft"]
    # The editor fixture is exactly what the producer emits into the retained bundle and the saved copy.
    assert draft["review_context"]["two_bot"]["bundle"]["human_impact"] == items
    assert draft["review_context"]["two_bot"]["human_impact"] == items
