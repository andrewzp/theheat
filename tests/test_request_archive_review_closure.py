"""G8 closure of four archive review findings, with actual SDK MockTransport streams.

All data is INVENTED and offline: the installed Anthropic and google-genai SDKs
talk to httpx MockTransports, batch authority is local SQLite, replay runs in
fresh processes without credentials. These fixtures prove evidence completeness,
lineage and counting rules, never provider truth, billed tokens or an invoice.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import permutations
import json
from typing import Any

import httpx as google_http
import pytest

from src.evaluation import archive_usage
from src.two_bot import check_transport, request_archive as archive, request_archive_replay as replay
from src.two_bot.usage_cost_scenario import SCENARIO
from tests import test_batch_result_journal as receipts, test_batch_worker_journal as workers
from tests.test_check_executor import envelope
from tests.test_request_archive_batch import (
    CANARIES, fresh_store, httpx as anthropic_http, prepared, private_root, run as submit,
)
from tests.test_request_archive_batch_replay import (
    Provider, cli, collect_once, copy_scope, factory, family, rewrite,
)
from tests.test_request_archive_sdk import accepted_script, journey_env, run_journey
from tests.two_bot import test_batch_contract as contracts

__all__ = ["prepared", "journey_env"]
inputs = contracts.inputs
store = workers.store


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])


def collected(tmp_path, inputs, name, *, results=None, metadata=None):
    """One later collection in its own scope and store; returns (scope, report, provider)."""
    authority = fresh_store(tmp_path, name)
    pair, _ = receipts.started(authority, inputs)
    provider = Provider(pair, results=results, metadata=metadata)
    with archive.capture(private_root(tmp_path, f"{name}-root"), operation=f"collect {name}", routes=True) as scope:
        report = collect_once(authority, pair, provider)
    return scope, report, provider, pair


def jsonl(*rows) -> bytes:
    return b"\n".join(json.dumps(row).encode() for row in rows)


def line(pair, **message):
    return contracts.result(pair[0], 0, **message)


def custom_id(pair) -> str:
    return json.loads(pair[0])["requests"][0]["custom_id"]


# ------------------------------------------------ 1. incomplete entities

def _interrupted(good):
    base: Any = anthropic_http.SyncByteStream

    def respond(request):
        class Failing(base):
            def __iter__(self):
                yield good + b"\n" + b"x" * 8192
                raise anthropic_http.ReadError("invented interruption", request=request)
        return anthropic_http.Response(200, stream=Failing())
    return respond


def stream_case(kind, pair):
    good = contracts.raw_rows(receipts.rows(pair))
    if kind in ("complete", "late_cleanup"):
        return good
    if kind == "missing":
        return lambda request: anthropic_http.Response(500, json={"error": "invented"})
    if kind == "empty":
        return b""
    if kind == "partial_jsonl":
        return good + b"\n" + good[: len(good) // 2]
    return _interrupted(good)


def late_cleanup(monkeypatch):
    """The stream's own end-of-read close succeeds; the transport's finally close fails."""
    original = anthropic_http.Response.close

    def close(self):
        if getattr(self, "_invented_closed_once", False):
            raise RuntimeError("invented late cleanup failure")
        self._invented_closed_once = True
        return original(self)
    monkeypatch.setattr(anthropic_http.Response, "close", close)


@pytest.mark.parametrize("kind,complete", [("complete", True), ("empty", True), ("missing", False),
                                           ("partial_jsonl", False), ("midstream_error", False),
                                           ("late_cleanup", False)])
def test_incomplete_result_entities_never_validate_as_complete_replay(store, inputs, keyed, tmp_path, monkeypatch,
                                                                     kind, complete):
    if kind == "late_cleanup":
        late_cleanup(monkeypatch)
    off_store = fresh_store(tmp_path, "off")
    off_pair, _ = receipts.started(off_store, inputs)
    off = collect_once(off_store, off_pair, Provider(off_pair, results=stream_case(kind, off_pair)))
    scope, on, provider, pair = collected(tmp_path, inputs, "on", results=stream_case(kind, off_pair))
    # The authority's own result is unchanged by capture, and nothing is fetched again.
    assert (on["outcome"], on.get("reason")) == (off["outcome"], off.get("reason"))
    # A late metadata cleanup failure already makes metadata incomplete: results are never read.
    assert [method for method, _ in provider.requests] == ["GET"] * (1 if kind == "late_cleanup" else 2)
    code, validated = cli("validate", str(scope.directory))
    assert (code == 0) is complete and (validated["status"] == "complete") is complete
    results = [archive.strict_json_loads(raw)["data"] for raw in
               (scope.directory / archive.MANIFEST).read_bytes().split(b"\n") if b'"type":"route_result"' in raw]
    if complete:
        assert all(r["archival"] == "complete" and r["evidence_gap"] is None for r in results)
        rows = family(replay.route_lineage(replay.load_archive(scope.directory)), "batch_results")
        assert rows[0]["results"]["status"] == ("empty" if kind == "empty" else "complete")
    else:
        assert results[-1]["archival"] == "incomplete" and results[-1]["evidence_gap"] is not None
        assert any(p.startswith(f"route_evidence_incomplete:{len(results)}") for p in validated["problems"])
    assert scope.held is None  # Incomplete provider evidence is labeled, never a recorder hold.


def test_hash_consistent_contradictory_complete_flag_still_refuses_complete(store, inputs, keyed, tmp_path,
                                                                          monkeypatch):
    scope, *_ = collected(tmp_path, inputs, "flag", results=_interrupted(b'{"custom_id":"x","result":{"type":"expired"}}'))
    changed = copy_scope(scope, tmp_path)

    def claim_complete(record):
        if record["type"] == "route_result":
            record["data"]["archival"] = "complete"
            record["data"]["evidence_gap"] = None
    rewrite(changed, claim_complete)
    loaded = replay.load_archive(changed)
    assert loaded.status == "incomplete"
    assert any(p.startswith("route_archival_flag_contradicted:2") for p in loaded.problems)
    code, validated = cli("validate", str(changed))
    assert code == 1 and validated["status"] == "incomplete"


@pytest.mark.parametrize("bounded", [False, True])
def test_archives_written_before_evidence_gap_are_read_strictly_never_rewritten(store, inputs, keyed, tmp_path,
                                                                                 bounded):
    results = _interrupted(b'{"custom_id":"x","result":{"type":"expired"}}') if bounded else None
    scope, *_ = collected(tmp_path, inputs, "old", results=results)
    old = copy_scope(scope, tmp_path)

    def as_written_before(record):
        # The G3-G6 recorder wrote no evidence_gap and labeled every retained prefix complete.
        if record["type"] == "route_result":
            record["data"].pop("evidence_gap", None)
            record["data"]["archival"] = "complete"
    rewrite(old, as_written_before)
    before = (old / archive.MANIFEST).read_bytes()
    loaded = replay.load_archive(old)
    assert loaded.status == ("incomplete" if bounded else "complete")
    assert [r.evidence_gap for r in loaded.routes] == [None, "entity_bounded_prefix" if bounded else None]
    assert (old / archive.MANIFEST).read_bytes() == before


@pytest.mark.parametrize("claimed", ["entity_bounded_prefix", "unknown_gap_code"])
def test_recorded_gap_without_matching_observation_is_never_trusted(store, inputs, keyed, tmp_path, claimed):
    scope, *_ = collected(tmp_path, inputs, "claim")
    changed = copy_scope(scope, tmp_path)

    def claim_gap(record):
        if record["type"] == "route_result" and record["data"]["family"] == "batch_results":
            record["data"]["evidence_gap"] = claimed
    rewrite(changed, claim_gap)
    loaded = replay.load_archive(changed)
    if claimed == "unknown_gap_code":
        # An unknown gap code is a shape violation (integrity), not an evidence-completeness label.
        assert loaded.status == "invalid" and loaded.problems[0].startswith("route_result_shape:")
    else:
        assert loaded.status == "incomplete" and "route_archival_flag_contradicted:2" in loaded.problems


def test_fully_retained_negative_check_response_is_complete_evidence(tmp_path):
    def reply(request):
        return google_http.Response(500, request=request, stream=google_http.ByteStream(b'{"error":"invented"}'))
    with archive.capture(private_root(tmp_path), operation="negative", routes=True) as scope:
        transport = check_transport.GoogleCheckTransport(api_key="invented", model="gemini-test",
                                                         http_transport=google_http.MockTransport(reply))
        try:
            route = scope.begin_route("command_check", client=transport._http,
                                      expected_path="/v1beta/models/gemini-test:generateContent", binding={})
            observed = transport.execute(dict(model="gemini-test", contents="invented"))
            route.finish("returned")
        finally:
            transport.close()
    assert observed.complete and observed.http_status == 500
    assert replay.load_archive(scope.directory).status == "complete"


# ------------------------------------------------ 2. returned batch identity

@pytest.mark.parametrize("case", ["matching", "missing", "wrong_id", "invalid_id", "reused_id"])
def test_metadata_lineage_compares_requested_and_returned_batch_ids(prepared, tmp_path, case):
    authority, pair, values = prepared
    meta = json.loads(receipts.metadata())
    if case == "missing":
        del meta["id"]
    elif case == "wrong_id":
        meta["id"] = "msgbatch_invented_other"
    elif case == "invalid_id":
        meta["id"] = "not a provider batch id"
    provider = Provider(pair, metadata=json.dumps(meta).encode())
    with archive.capture(private_root(tmp_path), operation=f"identity {case}", routes=True) as scope:
        submit(authority, pair, factory(provider))
        if case == "reused_id":
            other = fresh_store(tmp_path, "other")
            other_pair = workers.ready(other, values)
            submit(other, other_pair, factory(Provider(other_pair)))
        collect_once(authority, pair, provider)
    gets = [path for method, path in provider.requests if method == "GET"]
    meta_row, = family(replay.route_lineage(replay.load_archive(scope.directory)), "batch_metadata")
    assert meta_row["requested_batch_id"] == "msgbatch_fixture"
    if case in ("matching", "reused_id"):
        assert meta_row["batch_identity"] == "matching" and meta_row["processing_status"] == "ended"
        assert meta_row["predecessor"] == ("observed_in_scope" if case == "matching" else "conflicting_in_scope")
        assert len(gets) == 2
    else:
        assert meta_row["batch_identity"] == {"missing": "missing", "invalid_id": "invalid"}.get(case, "mismatched")
        assert meta_row["returned_batch_id"] == ("msgbatch_invented_other" if case == "wrong_id" else None)
        # B's "ended" is never certified for A, and the collector still refuses to read results.
        assert meta_row["processing_status"] is None and meta_row["returned_processing_status"] == "ended"
        assert meta_row["results_disposition"] == "unresolved" and len(gets) == 1
    code, traced = cli("lineage", str(scope.directory))
    cli_meta, = [row for row in traced["routes"]["routes"] if row["family"] == "batch_metadata"]
    assert code == 0 and cli_meta["batch_identity"] == meta_row["batch_identity"]


def test_mismatched_returned_id_without_predecessor_stays_unresolved(store, inputs, keyed, tmp_path):
    meta = json.loads(receipts.metadata())
    meta["id"] = "msgbatch_invented_other"
    scope, report, provider, _ = collected(tmp_path, inputs, "nopred", metadata=json.dumps(meta).encode())
    row, = family(replay.route_lineage(replay.load_archive(scope.directory)), "batch_metadata")
    assert row["predecessor"] == "durable_status_reference" and row["batch_identity"] == "mismatched"
    assert row["processing_status"] is None and len(provider.requests) == 1


# ------------------------------------------------ 3. one capture counted once

def check_scope(tmp_path, name, contents="identical invented prompt"):
    def reply(request):
        return google_http.Response(200, request=request, stream=google_http.ByteStream(envelope("NO")))
    with archive.capture(private_root(tmp_path, name), operation=f"check {name}", routes=True) as scope:
        transport = check_transport.GoogleCheckTransport(api_key="invented", model="gemini-test",
                                                         http_transport=google_http.MockTransport(reply))
        try:
            route = scope.begin_route("command_check", client=transport._http,
                                      expected_path="/v1beta/models/gemini-test:generateContent",
                                      binding={"stage": archive.route_entry("safety", "check_lease"),
                                               "model": archive.route_entry("gemini-test", "check_packet")})
            transport.execute(dict(model="gemini-test", contents=contents))
            route.finish("returned")
        finally:
            transport.close()
    return replay.load_archive(scope.directory)


def counts(usage) -> tuple:
    d = usage["route_denominators"]
    return (d["physical_route_sends"], d["command_check_operations"], d["model_generations_with_observed_response"],
            d["result_lines_counted"], sum(g["responses"] for g in usage["route_token_totals"]),
            sum(g["counts"].get("input_tokens", 0) + g["counts"].get("prompt_tokens", 0)
                for g in usage["route_token_totals"]))


def test_identical_or_copied_captures_count_once_and_distinct_sends_twice(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path, "batch"), operation="families", routes=True) as batch:
        submit(authority, pair, factory(provider))
        collect_once(authority, pair, provider)
    a = replay.load_archive(batch.directory)
    a_copy = replay.load_archive(copy_scope(batch, tmp_path, "batch-copy"))
    c1, c2 = check_scope(tmp_path, "c1"), check_scope(tmp_path, "c2")
    once = archive_usage.archive_usage([a, c1, c2])
    assert counts(once)[:3] == (5, 2, 2)  # submit+meta+results, plus two distinct identical-body checks
    supplied = [a, a_copy, a, c1, c1, c2]
    for permutation in set(permutations(range(6))):
        repeated = archive_usage.archive_usage([supplied[index] for index in permutation])
        assert counts(repeated) == counts(once)
        assert sum(1 for source in repeated["sources"] if source.get("duplicate_of_input") is not None) == 3
        assert repeated["identity_reconciliation"]["duplicate_inputs"] == 3
    # The diagnosis route section lists one retained capture once, however often it is supplied.
    from src.evaluation import operator_diagnosis as diagnosis
    from tests.test_operator_diagnosis import AS_OF
    archives = [a, a_copy, c1, a]
    components, usable = diagnosis.verify_components(archives=archives, reconciliation=None, copy_private=None,
                                                     copy_import=None, readers=None, state=None, as_of=AS_OF)
    report = diagnosis.diagnose(archives=archives, components=components, usable=usable, as_of=AS_OF, input_files=[])
    assert sorted(scope["scope_id"] for scope in report["routes"]["scopes"]) == sorted([a.scope_id, c1.scope_id])
    assert report["routes"]["identity_reconciliation"]["duplicate_inputs"] == 2


def test_conflicting_records_claiming_one_capture_identity_are_unresolved(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path, "batch"), operation="conflict", routes=True) as batch:
        submit(authority, pair, factory(provider))
        collect_once(authority, pair, provider)
    exported = copy_scope(batch, tmp_path, "exported")
    raw = (exported / archive.MANIFEST).read_bytes().split(b"\n")
    (exported / archive.MANIFEST).write_bytes(b"\n".join(raw[:-2]) + b"\n")  # same scope ID, other contents
    original, changed = replay.load_archive(batch.directory), replay.load_archive(exported)
    assert original.scope_id == changed.scope_id and original.manifest_sha256 != changed.manifest_sha256
    for order in ([original, changed], [changed, original]):
        usage = archive_usage.archive_usage(order)
        assert usage["route_denominators"]["route_operations"] == 0
        assert usage["identity_reconciliation"]["conflicting_scope_ids"] == [original.scope_id]
        assert all(source["used"] is False and source["identity_conflict_with"] for source in usage["sources"])


def test_repeated_v1_archive_counts_once_in_fresh_process_reconciliation(journey_env, tmp_path):
    from tests.test_archive_reconciliation_cli import AS_OF, cli as reconcile_cli
    v1 = run_journey(accepted_script(), root=private_root(tmp_path, "v1")).archive
    outputs = []
    for name, archives in (("once", [v1]), ("twice", [v1, v1])):
        out = private_root(tmp_path, f"out-{name}")
        args = ["reconcile", "--as-of", AS_OF, "--output-dir", str(out)]
        for path in archives:
            args += ["--archive", str(path)]
        code, emitted, _ = reconcile_cli(*args)
        assert code in (0, 1)
        outputs.append(emitted["denominators"])
    assert outputs[0] == outputs[1] and outputs[0]["physical_attempts"] >= 1


# ------------------------------------------------ 4. contradictory results

def _usage(pair, tokens):
    message = line(pair)["result"]["message"]
    return dict(message["usage"], input_tokens=tokens)


def contradictory(pair, kind):
    first = line(pair, usage=_usage(pair, 100))
    if kind == "tokens":
        second = line(pair, usage=_usage(pair, 1000))
    elif kind == "expired":
        second = {"custom_id": custom_id(pair), "result": {"type": "expired"}}
    elif kind == "model":
        second = line(pair, usage=_usage(pair, 100), model="claude-invented-other")
    elif kind == "missing_usage":
        second = deepcopy(first)
        del second["result"]["message"]["usage"]
    else:
        second = line(pair, usage=dict(_usage(pair, 100), input_tokens="100"))
    return first, second


@pytest.mark.parametrize("kind", ["tokens", "expired", "model", "missing_usage", "type_value"])
def test_contradictory_results_across_archives_are_conflicts_in_every_order(store, inputs, keyed, tmp_path, kind):
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    first, second = contradictory(pair, kind)
    x = replay.load_archive(collected(tmp_path, inputs, "x", results=jsonl(first))[0].directory)
    y = replay.load_archive(collected(tmp_path, inputs, "y", results=jsonl(second))[0].directory)
    views = [archive_usage.archive_usage(order) for order in ([x, y], [y, x])]
    for usage in views:
        lines = usage["route_result_lines"]
        assert {row["usage_status"] for row in lines} == {"conflict"} and not any(row["counted"] for row in lines)
        conflict, = usage["route_conflicts"]
        assert conflict["custom_id"] == custom_id(pair) and len(conflict["sources"]) == 2
        assert usage["route_denominators"]["result_lines_counted"] == 0
        assert usage["route_totals_status"] == "incomplete" and usage["billing"] == "unknown"
    assert views[0]["route_conflicts"] == views[1]["route_conflicts"]
    assert views[0]["route_token_totals"] == views[1]["route_token_totals"]


def test_conflict_inside_one_entity_and_exact_duplicates_collapse(store, inputs, keyed, tmp_path):
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    first, second = contradictory(pair, "tokens")
    inside = replay.load_archive(collected(tmp_path, inputs, "inside", results=jsonl(first, second))[0].directory)
    usage = archive_usage.archive_usage([inside])
    assert [row["usage_status"] for row in usage["route_result_lines"]] == ["conflict", "conflict"]
    x = replay.load_archive(collected(tmp_path, inputs, "x", results=jsonl(first))[0].directory)
    x_again = replay.load_archive(collected(tmp_path, inputs, "x-again", results=jsonl(first))[0].directory)
    totals = []
    for order in ([x, x_again], [x_again, x]):
        usage = archive_usage.archive_usage(order)
        assert sorted(row["usage_status"] for row in usage["route_result_lines"]) == ["duplicate_not_counted",
                                                                                    "present"]
        assert usage["route_denominators"]["result_lines_counted"] == 1 and usage["route_conflicts"] == []
        totals.append(usage["route_token_totals"])
    assert totals[0] == totals[1] and totals[0][0]["counts"]["input_tokens"] == 100


def test_missing_usage_is_unknown_never_zero_and_conflicts_reach_diagnosis(store, inputs, keyed, tmp_path):
    from src.evaluation import operator_diagnosis as diagnosis
    from tests.test_operator_diagnosis import AS_OF
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    first, second = contradictory(pair, "missing_usage")
    lone = replay.load_archive(collected(tmp_path, inputs, "lone", results=jsonl(second))[0].directory)
    usage = archive_usage.archive_usage([lone])
    row, = usage["route_result_lines"]
    assert row["usage_status"] == "absent" and usage["route_token_totals"] == []
    assert usage["route_totals_status"] == "incomplete"
    priced = archive_usage.priced_scenario(usage, SCENARIO)
    assert priced["actual_cost_known"] is False and priced["billed_amount"] is None
    x = replay.load_archive(collected(tmp_path, inputs, "x", results=jsonl(first))[0].directory)
    archives = [x, lone]
    components, usable = diagnosis.verify_components(archives=archives, reconciliation=None, copy_private=None,
                                                     copy_import=None, readers=None, state=None, as_of=AS_OF)
    report = diagnosis.diagnose(archives=archives, components=components, usable=usable, as_of=AS_OF,
                                input_files=[])
    conflict, = report["routes"]["result_conflicts"]
    assert {source["scope_id"] for source in conflict["sources"]} == {x.scope_id, lone.scope_id}
