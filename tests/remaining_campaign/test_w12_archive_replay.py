"""W12.1 / W12.2 — explicit archive coverage and deterministic retained re-parse.

Archives come from the actual pipeline with invented offline providers
(tests.test_request_archive_sdk). Nothing sends, generates or reads live state.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.two_bot import call_inventory as inv
from src.two_bot import request_archive
from src.two_bot import request_archive_replay as replay
from src.two_bot.archive_reparse import reparse_archive
from tests.test_request_archive_replay import cli
from tests.test_request_archive_sdk import FIXTURE, accepted_script, fact_json, journey_env, private_root, run_journey

__all__ = ["journey_env"]


@pytest.fixture
def archives(journey_env, tmp_path):
    accepted = run_journey(accepted_script(), root=private_root(tmp_path, "accepted"))
    factual = accepted_script()
    factual["fact_check"] = [{"text": fact_json(False, failures=[FIXTURE["factual_failure"]])}]
    del factual["critic"]
    rejected = run_journey(factual, root=private_root(tmp_path, "rejected"))
    return accepted.archive, rejected.archive


def _by_stage(report):
    return {row["stage"]: row for row in report["calls"]}


def test_retained_responses_reparse_through_the_real_parsers(archives):
    accepted, rejected = (replay.load_archive(path) for path in archives)
    report = reparse_archive(accepted)
    rows = _by_stage(report)
    assert report["provider_io"] == "forbidden" and report["new_model_verdicts"] == 0
    assert rows["writer"]["replay_state"] == "reparsed" and rows["writer"]["result"]["tweet_present"] is True
    assert rows["safety"]["result"] == {"decision": "allow"}
    assert rows["critic"]["result"]["verdict"] == "PASS"
    assert rows["fact_check"]["result"]["parser_passed"] is True
    # Admission needs inputs the archive does not retain: precise unsupported state, never a guess.
    assert rows["fact_check"]["admission"] == {"replay_state": "unsupported", "reason": "admission_inputs_not_archived",
                                              "missing": ["tweet_text", "story_bundle", "checker_state"]}
    for row in report["calls"]:
        assert row["new_model_verdict"] is False and row["publication_eligible"] is False
        assert row["parser"]["parser_changed"] is False and len(row["raw_response_sha256"]) == 64
    assert _by_stage(reparse_archive(rejected))["fact_check"]["result"]["parser_passed"] is False


def test_missing_response_dimension_is_a_precise_unsupported_state(archives):
    archive = replay.load_archive(archives[0])
    writer = next(call for call in archive.calls if call.stage == "writer")
    from dataclasses import replace
    from src.two_bot.archive_reparse import reparse_call
    row = reparse_call(archive, replace(writer, attempts=()))
    assert row["replay_state"] == "unsupported" and row["reason"] == "response_not_captured"
    assert reparse_call(archive, replace(writer, stage="newsworthiness_verify"))["reason"] == "stage_parser_not_replayable"


def test_reparse_cli_runs_offline_in_a_fresh_process(archives):
    code, out, raw = cli("reparse", str(archives[0]))
    assert code == 0, raw
    assert out["states"] == {"reparsed": 4} and out["provider_io"] == "forbidden"
    assert FIXTURE["accepted_tweet"] not in raw  # Content-free summary: no retained text on stdout.


def test_news_model_call_without_actual_hooked_sdk_is_refused_in_an_open_scope(journey_env, tmp_path, monkeypatch):
    from google import genai
    from src.data import newsworthiness as news
    sent = []
    answer = SimpleNamespace(text='{"supported": true}', usage_metadata=None)
    def generate_content(**kw):
        sent.append(kw)
        return answer

    monkeypatch.setattr(genai, "Client", lambda **_k: SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content)))
    assert inv.archive_coverage()["newsworthiness_verify"] == "provider_call_seam"
    assert inv.archive_coverage()["writer"] == "provider_call_seam"
    root = private_root(tmp_path, "news")
    with request_archive.capture(root, operation="invented news rehearsal") as scope:
        with pytest.raises(request_archive.RequestArchiveRefused, match="archive_unobserved_transport"):
            news._call_verify_flash("Invented claim", 1, "Invented page")
        directory = Path(scope.directory)
    assert sent == []
    loaded = replay.load_archive(directory)
    assert any(record.get("type") == "call_refused" and record.get("data", {}).get("reason") == "archive_unobserved_transport" for record in loaded.records)
    # Outside a scope the default path is unchanged (capture stays default off).
    news._call_verify_flash("Invented claim", 1, "Invented page")
    assert len(sent) == 1
