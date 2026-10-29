"""Invented offline G10-A reader failures through lineage, diagnosis and fresh CLI."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.evaluation import archive_usage, operator_diagnosis as diagnosis
from src.two_bot import request_archive_replay as replay
from tests.test_archive_identity_followup import MALFORMED, _diagnose, _malformed, batch_family
from tests.test_diagnosis_identity_journey import diagnose_cli
from tests.test_operator_diagnosis import explicit_node_fixture
from tests.test_request_archive_review_closure import keyed
from tests.test_request_archive_sdk import private_root
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contracts

__all__ = ["batch_family", "explicit_node_fixture", "keyed"]
inputs = contracts.inputs
store = workers.store
KINDS = MALFORMED + ["type_dict", "type_null", "result_null", "result_string", "message_list", "message_null"]
HOSTILE = 'x` ![remote](https://example.invalid/pixel) `y'
PAYLOADS = [HOSTILE, '``` `` ` [link](https://example.invalid/x) ![image](//example.invalid/x)',
            '<img src="https://example.invalid/pixel"> & | [x] "quote" 雨', 'a\nb\rc\td',
            '   ', '\\`![x](https://example.invalid/x)']


def malformed(valid, kind):
    row = deepcopy(valid)
    if kind in MALFORMED:
        return _malformed(valid, kind)
    if kind.startswith("type_"):
        row["result"]["type"] = {} if kind == "type_dict" else None
    elif kind.startswith("result_"):
        row["result"] = None if kind == "result_null" else "invented result"
    else:
        row["result"]["message"] = [] if kind == "message_list" else None
    return row


@pytest.mark.parametrize("kind", KINDS)
def test_malformed_result_actual_lineage_diagnosis_and_fresh_cli(batch_family, tmp_path, kind):
    _, valid, unrelated, make = batch_family
    bad = make("bad", malformed(valid, kind))
    good, control = make("good", valid), make("control", unrelated)
    assert bad.status == "complete" and bad.problems == ()
    lineage = replay.route_lineage(bad)
    result, = [r["results"] for r in lineage["routes"] if r["family"] == "batch_results"]
    assert result["observed_custom_ids"] == [valid["custom_id"]]
    assert result["status"] == "invalid" and result["invalid_lines"] == 1
    for label, archives in (("lone", [bad]), ("conflict", [good, bad, control]),
                            ("reversed", [control, bad, good])):
        report = _diagnose(archives)
        code, _, fresh = diagnose_cli(private_root(tmp_path, label), [a.directory for a in archives])
        assert code == 0 and fresh["routes"] == report["routes"]
        routes = report["routes"]
        assert routes["route_totals_status"] == "incomplete"
        assert report["overview"]["spend"]["status"] == "absent"  # no supplied billing, never a zero cost
        usage = archive_usage.archive_usage(archives)
        assert all(row["billing"] == "unknown" for row in usage["route_result_lines"])
        assert usage["route_token_totals"] == (archive_usage.archive_usage([control])["route_token_totals"]
                                                if label != "lone" else [])
        conflicts = routes["result_conflicts"]
        if label == "lone":
            assert conflicts == []
        else:
            conflict, = conflicts
            assert conflict["custom_id"] == valid["custom_id"] and len(conflict["sources"]) == 2
        for ext, renderer in (("json", diagnosis.report_json), ("md", diagnosis.render_markdown),
                              ("html", diagnosis.render_html)):
            rendered = renderer(fresh)
            expected = rendered if isinstance(rendered, bytes) else rendered.encode()
            assert (tmp_path / label / f"diagnosis.{ext}").read_bytes() == expected


def hostile_report(payload=HOSTILE):
    """Every interpolated slot, including hand-built supported view fixtures."""
    report = _diagnose([])
    report["routes"] = {"route_totals_status": payload, "route_totals_unknown_reasons": [payload], "scopes": [],
                        "result_conflicts": [{"custom_id": payload, "provider_batch_id": payload,
                                              "sources": [{"scope_id": payload, "route": 1, "line": 1}]}]}
    report["components"] = [{"component": payload, "status": payload}]
    report["candidates"] = [{"anchor": payload, "scope_id": payload, "attempt": payload,
                             "candidate_text_sha256": payload, "event_id": payload, "decision": payload,
                             "dispositions": [payload], "publication": {"status": "joined", "other": payload}}]
    report["generations"] = [{"scope_id": payload, "event_id": payload, "terminal": payload,
                              "candidate_count": 1, "dispositions": [payload]}]
    report["unjoined_posts"] = [{key: payload for key in ("tweet_id", "revision_status", "publication_context", "join")}]
    report["next_actions"] = [{"code": payload, "action": payload}]
    report["limits"] = [payload]
    return report


@pytest.mark.parametrize("payload", PAYLOADS)
def test_all_markdown_slots_use_context_safe_serialization(payload):
    report = hostile_report(payload)
    before = diagnosis.report_json(report)
    rendered = diagnosis.render_markdown(report)
    assert diagnosis._md(payload) in rendered
    assert diagnosis.report_json(report) == before  # exact JSON identities never rewritten
    assert '\n' not in diagnosis._md(payload) and '\r' not in diagnosis._md(payload)
    assert '|' not in diagnosis._md(payload) and '<' not in diagnosis._md(payload)


def test_old_renderer_verified_hashes_stay_truthfully_unverifiable(tmp_path, monkeypatch):
    old = private_root(tmp_path, "old")
    with monkeypatch.context() as patch:
        patch.setattr(diagnosis, "VIEW_RENDERER", "theheat.private-diagnosis-views/v3")
        report = _diagnose([])
        diagnosis.write_report(old, report)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    assert diagnosis.verify_output(old) == {"status": "unverifiable_views", "reason": "view_renderer_version_differs"}
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    marker = json.loads((old / diagnosis.MARKER).read_bytes())
    (old / "diagnosis.md").write_bytes(b"invented tamper")
    assert marker["report_sha256"] == report["report_sha256"]
    assert diagnosis.verify_output(old)["reason"] == "component_hash_mismatch"


@pytest.mark.parametrize("payload", PAYLOADS)
def test_hostile_custom_ids_survive_actual_conflicts_and_fresh_cli(batch_family, tmp_path, payload):
    _, valid, _, make = batch_family
    valid["custom_id"] = payload
    other = deepcopy(valid)
    other["result"]["message"]["usage"]["input_tokens"] += 1
    one, two = make("one", valid), make("two", other)
    code, _, report = diagnose_cli(private_root(tmp_path, "hostile"), [one.directory, two.directory])
    assert code == 0
    conflict, = report["routes"]["result_conflicts"]
    assert conflict["custom_id"] == payload and len(conflict["sources"]) == 2
    assert diagnosis._md(payload) in (tmp_path / "hostile/diagnosis.md").read_text()
