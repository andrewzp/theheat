"""Batch metadata/results lineage and strict offline replay of v2 route archives.

Everything is INVENTED and offline: the installed Anthropic SDK talks to an
httpx MockTransport, the batch authority is local SQLite, and replay runs in
fresh processes with no credentials. Tamper cases edit copies only. Nothing
here proves provider behavior, billing, model quality or candidate approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from src.commands.sqlite_authority import SQLiteAuthority
from src.two_bot import batch_collector as collect, batch_transport as batch
from src.two_bot import request_archive as archive, request_archive_replay as replay
from tests import test_batch_result_journal as receipts, test_batch_worker_journal as workers
from tests.test_request_archive_batch import (
    CANARIES, Clock, fresh_store, httpx, prepared, private_root, run as submit,
)
from tests.test_request_archive_sdk import run_journey, accepted_script, journey_env
from tests.two_bot import test_batch_contract as contracts

__all__ = ["prepared", "journey_env"]
inputs = contracts.inputs
store = workers.store
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/replay_request_archive.py"


class Provider:
    """Invented offline batch API: one POST then fixed GET routes; all witnessed."""

    def __init__(self, pair, *, metadata=None, results=None, ack=None):
        self.pair = pair
        self.requests: list = []
        self.metadata = metadata if metadata is not None else receipts.metadata()
        self.results = results if results is not None else contracts.raw_rows(receipts.rows(pair))
        self.ack = ack if ack is not None else workers.ack()

    def __call__(self, request):
        request.read()
        assert request.url.host == "api.anthropic.com", "external network trapped"
        self.requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, content=self.ack, headers={"content-type": "application/json"})
        body = self.results if request.url.path.endswith("/results") else self.metadata
        if callable(body):
            return body(request)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})


def factory(provider):
    def build():
        client = httpx.Client(transport=httpx.MockTransport(provider))
        return batch.AnthropicBatchTransport(api_key=CANARIES[0], http_client=client)
    return build


def collect_once(authority, pair, provider, **kwargs):
    return collect.collect_batch_once(authority, pair[1]["job_id"], current_context=contracts.context(pair[0]),
                                      owner="worker-one", clock=Clock(), enabled=kwargs.pop("enabled", True),
                                      transport_factory=factory(provider), **kwargs)


def lineage(scope) -> dict:
    loaded = replay.load_archive(scope.directory)
    return {"archive": loaded, **replay.route_lineage(loaded)}


def family(view, name):
    return [row for row in view["routes"] if row["family"] == name]


def cli(*args: str) -> tuple[int, dict]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-invented-home", "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1"}
    result = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True,
                            timeout=120, cwd="/")
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else {}


def tree(directory: Path) -> dict:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def test_submission_metadata_and_results_join_inside_one_scope(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path), operation="submit then collect", routes=True) as scope:
        assert submit(authority, pair, factory(provider))["outcome"] == "submitted"
        assert collect_once(authority, pair, provider)["outcome"] == "reviewed"
    assert provider.requests == [("POST", "/v1/messages/batches"),
                                 ("GET", "/v1/messages/batches/msgbatch_fixture"),
                                 ("GET", "/v1/messages/batches/msgbatch_fixture/results")]
    view = lineage(scope)
    assert view["archive"].status == "complete" and view["schema"] == archive.SCHEMA_V2
    sent, = family(view, "batch_submit")
    assert sent["provider_batch_id"] == "msgbatch_fixture" and sent["acknowledgment"] == "observed"
    assert sent["completion_evidence"] == "none" and sent["billable_usage_evidence"] == "none"
    meta, = family(view, "batch_metadata")
    assert meta["predecessor"] == "observed_in_scope" and meta["processing_status"] == "ended"
    assert meta["results_disposition"] == "results_fetched"
    rows, = family(view, "batch_results")
    custom = json.loads(pair[0])["requests"][0]["custom_id"]
    assert rows["predecessor"] == "observed_in_scope" and rows["results"]["status"] == "complete"
    assert rows["results"]["custom_id_join"] == "observed_in_scope" and rows["results"]["unknown_custom_ids"] == []
    assert rows["results"]["types"]["succeeded"] == 1 and rows["results"]["candidate_approval"] == "none"
    assert sent["custom_ids"] == [custom] and view["reused_provider_batch_ids"] == []
    assert all(row["billing"] == "unknown" for row in view["routes"])


def test_collection_in_a_later_scope_uses_only_the_durable_status_reference(store, inputs, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    pair, grant = receipts.started(store, inputs)
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path), operation="separate collection", routes=True) as scope:
        report = collect_once(store, pair, provider)
    assert report["outcome"] in ("reviewed", "retained")
    view = lineage(scope)
    meta, = family(view, "batch_metadata")
    rows, = family(view, "batch_results")
    assert meta["predecessor"] == rows["predecessor"] == "durable_status_reference"
    assert meta["binding"]["grant_id"] == {"value": grant["grant_id"], "source": "batch_results_status"}
    assert rows["results"]["custom_id_join"] == "unverified" and rows["results"]["unknown_custom_ids"] is None
    assert family(view, "batch_submit") == []


def test_unfinished_batch_needs_no_results_and_never_polls_again(store, inputs, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    pair, _ = receipts.started(store, inputs)
    provider = Provider(pair, metadata=workers.ack())
    with archive.capture(private_root(tmp_path), operation="pending", routes=True) as scope:
        assert collect_once(store, pair, provider)["outcome"] == "pending"
    assert provider.requests == [("GET", "/v1/messages/batches/msgbatch_fixture")]
    meta, = family(lineage(scope), "batch_metadata")
    assert meta["processing_status"] == "in_progress" and meta["results_disposition"] == "no_results_needed"


@pytest.mark.parametrize("kind", ["cut_final_line", "invalid_line", "duplicate_and_unknown", "midstream_failure"])
def test_result_streams_stay_partial_invalid_or_visible_never_merged(prepared, tmp_path, kind):
    authority, pair, _ = prepared
    good = contracts.raw_rows(receipts.rows(pair))
    if kind == "cut_final_line":
        body: object = good + b"\n" + good[: len(good) // 2]
    elif kind == "invalid_line":
        body = good + b"\n{not json}\n"
    elif kind == "duplicate_and_unknown":
        other = json.loads(good)
        other["custom_id"] = "invented-unknown-custom-id"
        other["result"] = {"type": "expired"}
        body = good + b"\n" + good + b"\n" + json.dumps(other).encode() + b"\n"
    else:
        def body(request):
            base: Any = httpx.SyncByteStream

            class Failing(base):
                def __iter__(self):
                    yield good[:20]
                    raise httpx.ReadError("invented midstream failure", request=request)
            return httpx.Response(200, stream=Failing())
    provider = Provider(pair, results=body)
    with archive.capture(private_root(tmp_path), operation=f"results {kind}", routes=True) as scope:
        submit(authority, pair, factory(provider))
        collect_once(authority, pair, provider)
    rows, = family(lineage(scope), "batch_results")
    result = rows["results"]
    if kind == "cut_final_line":
        # The entity itself ended normally, so its unparseable last line is a bad line, never a result.
        assert result["status"] == "invalid" and result["lines"] == 1 and result["invalid_lines"] == 1
    elif kind == "invalid_line":
        assert result["status"] == "invalid" and result["invalid_lines"] == 1
    elif kind == "duplicate_and_unknown":
        assert result["lines"] == 3 and result["duplicate_custom_ids"]
        assert result["unknown_custom_ids"] == ["invented-unknown-custom-id"]
        assert result["types"]["expired"] == 1 and result["types"]["succeeded"] == 2
    else:
        assert rows["entity_complete"] is False and result["status"] == "partial"
        # The SDK chunker still held the prefix when the read failed: zero bytes were kept.
        assert result["lines"] == 0 and rows["entity"] == "captured"
        assert rows["reason"] == "batch_read_unavailable"


def test_reused_provider_batch_ids_stay_visible_as_a_conflict(store, inputs, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-google-key")
    monkeypatch.setenv("WRITER_SAMPLES", "1")
    from src.editorial.policy import current_editorial_policy
    from src.voice import safety
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "fixture-loaded-safety-key")
    inputs["policy"] = current_editorial_policy()
    other = fresh_store(tmp_path, "second")
    jobs = [(store, workers.ready(store, inputs)), (other, workers.ready(other, inputs))]
    with archive.capture(private_root(tmp_path), operation="reused id", routes=True) as scope:
        for authority, pair in jobs:
            assert submit(authority, pair, factory(Provider(pair)))["outcome"] == "submitted"
    view = lineage(scope)
    assert view["reused_provider_batch_ids"] == ["msgbatch_fixture"]
    assert len(family(view, "batch_submit")) == 2


def test_disabled_collection_stays_disabled_inside_a_route_scope(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path), operation="disabled collect", routes=True) as scope:
        assert collect_once(authority, pair, provider, enabled=False)["outcome"] == "disabled"
    assert provider.requests == [] and lineage(scope)["routes"] == []


def copy_scope(scope, tmp_path, name="copy") -> Path:
    parent = private_root(tmp_path, name)
    target = parent / scope.directory.name
    shutil.copytree(scope.directory, target)
    for path in [target, *target.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    return target


def rewrite(target: Path, edit) -> None:
    """Edit decoded records, then re-chain honestly: only content checks can object."""
    lines = [archive.strict_json_loads(line) for line in (target / archive.MANIFEST).read_bytes().split(b"\n") if line]
    previous, out = archive.GENESIS, []
    for record in lines:
        edit(record)
        record["prev"] = previous
        line = archive.canonical_json(record)
        previous = archive.sha256_hex(line)
        out.append(line)
    (target / archive.MANIFEST).write_bytes(b"\n".join(out) + b"\n")


@pytest.fixture
def lineage_scope(prepared, tmp_path):
    authority, pair, _ = prepared
    provider = Provider(pair)
    with archive.capture(private_root(tmp_path), operation="tamper base", routes=True) as scope:
        submit(authority, pair, factory(provider))
        collect_once(authority, pair, provider)
    return scope


def test_changed_retained_bytes_or_ids_refuse_a_complete_replay(lineage_scope, tmp_path):
    scope = lineage_scope
    response = next(r for r in replay.load_archive(scope.directory).routes if r.family == "batch_results").response
    assert response.artifact is not None
    changed = copy_scope(scope, tmp_path, "artifact")
    (changed / archive.ARTIFACTS / response.artifact).write_bytes(b"invented replacement")
    assert replay.load_archive(changed).status == "invalid"

    def change_id(record):
        if record["type"] == "route_response" and "provider_batch_id" in record["data"]["observed"]:
            record["data"]["observed"]["provider_batch_id"] = "msgbatch_other"
    changed = copy_scope(scope, tmp_path, "identity")
    rewrite(changed, change_id)
    assert replay.load_archive(changed).problems[0].startswith("route_response_ids")

    def unknown_kind(record):
        if record["type"] == "route_bound":
            record["type"] = "route_invented"
    changed = copy_scope(scope, tmp_path, "kind")
    rewrite(changed, unknown_kind)
    assert replay.load_archive(changed).problems[0].startswith("record_type")


@pytest.mark.parametrize("schema", ["theheat.request-archive/v3", "mixed"])
def test_unknown_or_mixed_schema_versions_are_invalid(lineage_scope, tmp_path, schema):
    changed = copy_scope(lineage_scope, tmp_path)

    def edit(record):
        if schema != "mixed" or record["seq"] == 3:
            record["schema"] = schema if schema != "mixed" else archive.SCHEMA
    rewrite(changed, edit)
    loaded = replay.load_archive(changed)
    assert loaded.status == "invalid" and loaded.problems[0].startswith("record_schema")


def test_cut_manifest_tail_and_missing_result_are_never_complete(lineage_scope, tmp_path):
    changed = copy_scope(lineage_scope, tmp_path, "tail")
    raw = (changed / archive.MANIFEST).read_bytes()
    (changed / archive.MANIFEST).write_bytes(raw[:-30])
    assert replay.load_archive(changed).status in ("incomplete", "invalid")
    changed = copy_scope(lineage_scope, tmp_path, "unsealed")
    lines = (changed / archive.MANIFEST).read_bytes().split(b"\n")
    kept = [line for line in lines if line and b'"type":"scope_closed"' not in line and b'"route":3' not in line
            or (line and b'"type":"route_intent"' in line and b'"route":3' in line)]
    (changed / archive.MANIFEST).write_bytes(b"\n".join(kept) + b"\n")
    loaded = replay.load_archive(changed)
    assert loaded.status != "complete"


def test_v1_archives_are_read_exactly_as_before_and_never_gain_routes(journey_env, tmp_path):
    journey = run_journey(accepted_script(), root=private_root(tmp_path, "v1"))
    loaded = replay.load_archive(journey.archive)
    assert loaded.status == "complete" and loaded.schema == archive.SCHEMA and loaded.routes == ()
    assert "routes" not in replay.summary(loaded) and "schema" not in replay.summary(loaded)
    assert replay.route_lineage(loaded)["routes"] == []


def test_fresh_process_cli_reads_routes_without_credentials_or_mutation(lineage_scope):
    before = tree(lineage_scope.directory)
    code, inspected = cli("inspect", str(lineage_scope.directory))
    assert code == 0 and [r["family"] for r in inspected["routes"]] == ["batch_submit", "batch_metadata",
                                                                       "batch_results"]
    code, traced = cli("lineage", str(lineage_scope.directory))
    assert code == 0 and traced["routes"]["routes"][2]["results"]["status"] == "complete"
    assert tree(lineage_scope.directory) == before


def test_results_stream_that_never_opens_is_not_observed(store, inputs, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    pair, _ = receipts.started(store, inputs)
    provider = Provider(pair, results=lambda request: httpx.Response(500, json={"error": CANARIES[2]}))
    with archive.capture(private_root(tmp_path), operation="results unavailable", routes=True) as scope:
        collect_once(store, pair, provider)
    view = lineage(scope)
    rows, = family(view, "batch_results")
    assert rows["results"] == {"status": "not_observed"} and rows["http_status"] == 500
    assert family(view, "batch_metadata")[0]["results_disposition"] == "results_fetched"
    assert CANARIES[2].encode() not in (scope.directory / archive.MANIFEST).read_bytes()


def test_changed_predecessor_binding_stays_unverified(store, inputs, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARIES[0])
    pair, _ = receipts.started(store, inputs)
    with archive.capture(private_root(tmp_path), operation="binding", routes=True) as scope:
        collect_once(store, pair, Provider(pair))
    changed = copy_scope(scope, tmp_path)

    def edit(record):
        if record["type"] == "route_intent":
            record["data"]["binding"]["provider_batch_id"]["value"] = "msgbatch_invented_other"
    rewrite(changed, edit)
    loaded = replay.load_archive(changed)
    assert loaded.status == "complete"
    assert {row["predecessor"] for row in replay.route_lineage(loaded)["routes"]} == {"unverified"}
