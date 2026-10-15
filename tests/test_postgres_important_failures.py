"""Bounded group failure receipts: no free retry, cache poisoning or ambiguous origin."""

import json

import pytest

from src.commands import postgres_important_variants as group
from src.commands.schema import CommandError, utc_text
from src.two_bot import negative_cache
from src.two_bot.batch_transport import AnthropicBatchTransport
from src.two_bot.provider_http import anthropic_httpx
from tests import test_postgres_important_variants as v
from tests.test_postgres_important_variants import (
    important as important,
    sourced as sourced,
    cluster as cluster,
    database as database,
    core as core,
    make_authority as make_authority,
    spend_store as spend_store,
    worker_store as worker_store,
    base_store as base_store,
    store as store,
    inputs as inputs,
)


def writer(case, variant):
    """Only response envelopes are invented; actual SDK and journals perform all work."""
    httpx = anthropic_httpx()
    sent = []

    def handle(request):
        sent.append((request.method, request.url.path))
        raw = case["store"].read_batch_plan(case["result"]["generation"]["job_id"])
        plan = json.loads(raw)
        ack = json.loads(v.worker.ack("msgbatch_failure", created_at=utc_text(v.NOW)))
        if request.method == "POST":
            assert json.loads(request.content) == dict(requests=plan["requests"])
            ack["request_counts"]["processing"] = 2
            return httpx.Response(200, json=ack)
        if request.url.path.endswith("/results"):
            rows = [v.batch_tests.result(raw, i) for i in range(2)]
            for i, row in enumerate(rows):
                output = json.loads(row["result"]["message"]["content"][0]["text"])
                output["tweet"] = (
                    v.executor.TEXT
                    if i == 0
                    else "In Mali, a satellite detected a 361 MW thermal signal."
                )
                if variant in {"both_kill", "one_kill", "missing_with_kill"} and (
                    i == 0 or variant == "both_kill"
                ):
                    output.update(
                        tweet=None,
                        kill_reason="Insufficient retained evidence",
                        kill_scope="evidence",
                        kill_code="insufficient_evidence",
                    )
                row["result"]["message"]["content"][0]["text"] = json.dumps(output)
                if variant == "both_invalid":
                    row["result"]["message"]["content"][0]["text"] = "invalid invented JSON"
            if variant == "missing_with_kill":
                rows.pop()
            if variant == "duplicate":
                rows[1]["custom_id"] = rows[0]["custom_id"]
            elif variant == "foreign":
                rows[1]["custom_id"] = "th_foreign"
            return httpx.Response(200, content=v.batch_tests.raw_rows(rows))
        ack.update(
            processing_status="ended",
            ended_at=utc_text(v.NOW),
            request_counts=dict(processing=0, succeeded=2, errored=0, canceled=0, expired=0),
        )
        return httpx.Response(200, json=ack)

    return sent, lambda: AnthropicBatchTransport(
        api_key="invented-offline", http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )


@pytest.mark.parametrize("variant", ["one_kill", "both_kill", "both_invalid", "missing_with_kill"])
def test_only_concordant_writer_evidence_kills_enter_negative_cache(
    important, monkeypatch, variant
):
    case = important
    v.start(case)
    sent, factory = writer(case, variant)
    assert v.sourced_tests.run(case, "submit", factory)["outcome"] == "submitted"
    assert v.sourced_tests.run(case, "collect", factory)["outcome"] == "reviewed"
    result = v.sourced_tests.run(case, "capture")
    expected = (
        "candidate_ready"
        if variant == "one_kill"
        else ("reconciliation_required" if variant == "missing_with_kill" else "blocked")
    )
    assert result["outcome"] == expected, result
    case["captured"] = result["candidate"]
    cache = negative_cache.should_skip(
        case["store"].read()[1], case["bundle"].event_id, case["bundle"], now=v.NOW
    )
    retained_cache = case["store"].read()[1].get("writer_negative_cache", {})
    # The existing cache threshold requires repeated group decisions. This one
    # actual group adds exactly one stamp; two items do not fake two attempts.
    assert cache is None
    assert (next(iter(retained_cache.values()))["kills"] if retained_cache else 0) == (
        1 if variant == "both_kill" else 0
    )
    if variant == "one_kill":
        assert case["captured"]["slots"][0]["candidate"] is None
        v.complete(v.enroll(case, 2), monkeypatch)
        assert v.consume(case, v.slate_command(case), at=v.AT)["status"] == "applied"
        assert [row["rank"] for row in case["store"].read()[1]["drafts"][-1]["candidates"]] == [2]
    else:
        assert all(slot["candidate"] is None for slot in case["captured"]["slots"])
        assert result["reason"] == (
            "important_results_incomplete"
            if variant == "missing_with_kill"
            else "important_no_eligible_writer_result"
        )
        before = case["store"].spending("status", {}, now=utc_text(v.NOW))
        projection = case["store"].generation_projection(now=v.NOW)
        brief = next(
            row for row in projection["briefs"] if row["brief_id"] == case["refs"]["brief_id"]
        )
        assert brief["status"] == expected and brief["reason"] == result["reason"]
        assert case["store"].generated_candidate_inputs() == ()
        assert case["store"].spending("status", {}, now=utc_text(v.NOW)) == before
    assert len(sent) == 3


@pytest.mark.parametrize("variant", ["duplicate", "foreign"])
def test_ambiguous_provider_member_id_cannot_capture_any_candidate(important, variant):
    case = important
    v.start(case)
    sent, factory = writer(case, variant)
    assert v.sourced_tests.run(case, "submit", factory)["outcome"] == "submitted"
    result = v.sourced_tests.run(case, "collect", factory)
    assert result["outcome"] in {"reviewed", "blocked"}, result
    before = case["store"].read()
    with pytest.raises(CommandError, match="unavailable"):
        v.sourced_tests.run(case, "capture")
    assert case["store"].read() == before and case["store"].generated_candidate_inputs() == ()
    assert len(sent) == 3


def test_lost_submit_ack_preserves_the_only_writer_hold(important, core):
    case = important
    v.start(case)
    sent, factory = v.transport(case, fail_post=True)
    result = v.sourced_tests.run(case, "submit", factory)
    assert result["outcome"] == "submission_uncertain" and len(sent) == 1
    held = case["store"].spending("status", {}, now=utc_text(v.NOW))
    assert held["totals"]["held_micro_usd"] == 20
    assert v.sourced_tests.run(case, "submit", factory)["outcome"] != "submitted"
    assert len(sent) == 1 and case["store"].spending("status", {}, now=utc_text(v.NOW)) == held
    assert v.admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_failed_collection_constructor_still_consumes_its_finite_cycle(important):
    case = important
    v.start(case)
    sent, factory = v.transport(case)
    assert v.sourced_tests.run(case, "submit", factory)["outcome"] == "submitted"
    attempted = []

    def unavailable():
        attempted.append(True)
        raise OSError("Invented unavailable client before any GET")

    for _ in range(4):
        result = v.sourced_tests.run(case, "collect", unavailable)
        assert result["outcome"] == "blocked", result
    result = v.sourced_tests.run(case, "collect", factory)
    assert result["outcome"] == "blocked" and len(attempted) == 4 and len(sent) == 1
    with case["store"].projections._connection() as c:
        assert group.exists(c, group.CYCLE, case["result"]["generation"]["job_id"] + ":4")
