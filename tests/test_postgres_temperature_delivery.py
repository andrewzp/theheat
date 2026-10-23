"""Connected invented compact GHCN delivery; no real platform or model calls."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

from src.commands import postgres_delivery as delivery
from src.commands.preview_delivery_worker import execute_delivery_once
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_sourced_generation import private_configuration
from src.commands.schema import CommandError, utc_text
from src.media import platform_description as descriptions
from src.storage import postgres_projection as projection
from tests import test_postgres_temperature_editor_media as temperature
from tests import test_postgres_delivery as transport
from tests import test_postgres_cost_projection as costs
from tests.test_postgres_preview_command_ingress import http
from tests.test_postgres_editor_media import all_application_rows
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import admin
from tests.test_postgres_temperature_editor_media import (
    compact_case as compact_case, cluster as cluster, database as database,
    core as core, make_authority as make_authority, spend_store as spend_store,
    worker_store as worker_store, base_store as base_store, store as store,
    inputs as inputs, native_dependencies as native_dependencies,
    positive_workflow_clock as positive_workflow_clock, offline_connections as offline_connections,
)


@contextmanager
def diagnostic_workers(case):
    if os.environ.get("THEHEAT_T4_DIAGNOSTICS") != "1":
        yield
        return
    from tests import t4_timing_helpers as timing
    case["config"]["t4_timing_diagnostics"] = True
    case["config_path"].write_text(json.dumps(case["config"]))
    original = temperature.ghcn_worker
    def observed(case, operation, identity="", fault=""):
        return timing.timed(case["config"]["trace"], operation, "parent_worker_launch", original,
                            case, operation, identity, fault)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(temperature, "ghcn_worker", observed)
        yield


def configure_child(case, path):
    case["config"].update(delivery=str(path), t4_owner=case["params"], delivery_draft_id=case["draft_id"])
    case["config_path"].write_text(json.dumps(case["config"]))


def review_payload(current):
    value = temperature.attach_payload(current, "Invented full station comparator and local destinations reviewed.")
    value["review"]["confirmations"][descriptions.CONFIRMATION] = True
    value["review"]["expected_platform_description_sha256"] = current["platform_description"]["record"]["description_sha256"]
    return value


def passive_cost(case, expected_count, tmp_path, label):
    before = all_application_rows(case["params"])
    with pytest.MonkeyPatch.context() as patch:
        costs.passive_traps(patch)
        value = case["authority"].local_cost_projection(now=datetime.now(UTC))
    status, body, _ = http(case["port"], role="viewer")
    assert status == 200 and body["local_cost"]["requests"] == value["requests"]
    costs.cost_component_http(case, case["port"], value, tmp_path / (label + ".json"))
    assert all_application_rows(case["params"]) == before
    assert value["status"] == "available" and len(value["requests"]) == expected_count, value
    evidence = os.environ.get("THEHEAT_T4_EVIDENCE")
    if evidence:
        folder = Path(evidence)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (label + ".json")).write_text(json.dumps(value, sort_keys=True, indent=2))
    assert all(row["origin"]["brief_id"] == case["briefs"][case["config"]["selection"]["signal_field"]]
               and row["origin"]["source_run_id"] == case["config"]["run_id"] for row in value["requests"]), json.dumps(value, sort_keys=True)
    assert len({row["origin"]["grant_id"] for row in value["requests"]}) == expected_count
    assert all(row["usage"]["status"] == "present" and row["recorded_settlement_micro_usd"] is None
               and row["charge_status"] == "unreconciled" for row in value["requests"])
    assert value["summary"]["reservation_counts"]["settled"] == 0
    assert int(value["summary"]["commitments_micro_usd"]["held"]) > 0
    return value


def child_delivery_run(authority, operators, config, intent, parameters):
    """Real active preparation stays in the already isolated credentialless child."""
    if parameters.get("restart"):
        authority = PostgresCommandAuthority(**config["authority"])
        authority.configure_delivery(config["delivery"])
    elif parameters.get("missing_source"):
        del authority.ghcn_baseline
    if parameters.get("postgrant_outage"):
        original = delivery.before_call
        def outage(authority, connection, value, binding, resolve, now, *, ghcn=None):
            del authority.ghcn_baseline
            return original(authority, connection, value, binding, resolve, now, ghcn=ghcn)
        delivery.before_call = outage
    return execute_delivery_once(authority, intent, parameters["platform"], parameters["stage"],
        operators.resolve, owner="t4-owned-local-worker", clock=lambda: datetime.now(UTC),
        enabled=True, reconcile=parameters.get("reconcile", False))


def run_delivery(case, intent, stage, *, authority=None, reconcile=False, platform="x", postgrant_outage=False):
    parameters = dict(stage=stage, platform=platform, reconcile=reconcile, restart=authority is not None,
        missing_source=not hasattr(case["authority"], "ghcn_baseline"), postgrant_outage=postgrant_outage)
    return temperature.ghcn_worker(case, "delivery_run", intent, json.dumps(parameters))


@contextmanager
def current_source_outage(configuration, *, enabled=True):
    """Reachable current-input removal; original retained archives stay immutable."""
    if not enabled:
        yield
        return
    original = configuration.read_bytes()
    changed = json.loads(original)
    changed["current_inputs"] = []
    try:
        configuration.write_text(json.dumps(changed))
        yield
    finally:
        configuration.write_bytes(original)


def isolated_refusals(case, path, *, boundaries=("acquire", "begin")):
    before = all_application_rows(case["params"])
    trace = deepcopy(path["trace"])
    configuration = Path(case["config"]["generation"])
    original = configuration.read_bytes()
    result, failure = [], None
    try:
        result = temperature.ghcn_worker(case, "delivery_refusals", path["intent"], json.dumps(list(boundaries)))
    except Exception as exc:
        # Keep the test failing, but let an unchanged positive journey expose
        # its own result before reporting an unrelated negative-fixture error.
        failure = dict(boundaries=list(boundaries), type=type(exc).__name__, message=str(exc))
    # Any unexpected mutation stops immediately rather than entering transport.
    assert all_application_rows(case["params"]) == before and path["trace"] == trace
    assert configuration.read_bytes() == original
    return dict(refusals=result, failure=failure)


def source_refusal_matrix(path, *, boundaries=("acquire", "begin"), saved=None):
    """One real retained source/approval; rejected gates create no new dispatch."""
    case, intent = path["case"], path["intent"]
    authority = case["authority"]
    context = delivery.prepare_context(authority, intent_id=intent)
    results = []
    trace_before = deepcopy(path["trace"])
    for boundary in boundaries:
        for fault in ("role", "source", "baseline", "station", "day", "field", "policy", "draft", "profile", "description", "checkpoint"):
            before = all_application_rows(case["params"])
            with current_source_outage(Path(case["config"]["generation"]), enabled=fault == "source"), pytest.MonkeyPatch.context() as patch:
                proof = context
                resolve = case["operators"].resolve
                if fault == "role":
                    def resolve(subject):
                        return None
                elif fault == "baseline":
                    patch.delattr(authority, "ghcn_baseline")
                elif fault in {"station", "day", "field"}:
                    reference = deepcopy(context.claim.reference)
                    key, value = {"station": ("station_id", "USC99999999"), "day": ("signal_date", "1900-01-01"),
                                  "field": ("signal_field", "all_time_high")}[fault]
                    reference["selection"][key] = value
                    proof = replace(context, claim=replace(context.claim, reference=reference))
                elif fault == "policy":
                    policy = delivery.current_editorial_policy()
                    assert policy is not None
                    patch.setattr(delivery, "current_editorial_policy", lambda: {**policy, "fixture_drift": True})
                elif fault == "profile":
                    patch.delattr(authority, "editor_media_configuration")
                elif fault == "checkpoint":
                    proof = replace(context, checkpoint={**context.checkpoint, "state_version": -1})
                with pytest.raises(CommandError) as held:
                    with authority.projections._connection(writing=True) as connection, connection.transaction(force_rollback=True):
                        authority._validate(connection)
                        version, state = authority._state(connection, lock=True)
                        if fault == "draft":
                            draft = next(row for row in state["drafts"] if row.get("id") == case["draft_id"])
                            draft["text"] += " Later invented revision."
                            encoded, fields = projection._snapshot(state)
                            authority.projections._record(connection, "command-core-v1", str(version + 1), encoded, fields)
                            connection.execute("UPDATE theheat_commands.state SET version=%s,snapshot_id=%s WHERE singleton=1", (version + 1, str(version + 1)))
                        value = delivery.read(connection, intent)
                        if fault == "description":
                            value = deepcopy(value)
                            value["platform_description"]["description_sha256"] = "f" * 64
                        if boundary == "acquire":
                            delivery.acquire(authority, connection, value, "x", "upload", "t4-owned-local-worker",
                                resolve, datetime.now(UTC), ghcn=proof)
                        elif boundary == "before_call":
                            delivery.before_call(authority, connection, value, saved, resolve, datetime.now(UTC), ghcn=proof)
                        else:
                            delivery.begin(authority, connection, value, "x", "upload", {"owner": "t4-owned-local-worker"},
                                {}, b"", resolve, datetime.now(UTC), ghcn=proof)
                if fault == "source":
                    assert held.value.code == "media_source_not_allowlisted"
                results.append(dict(boundary=boundary, fault=fault, code=held.value.code))
            assert all_application_rows(case["params"]) == before
            assert path["trace"] == trace_before
    if saved is not None:
        with authority.projections._connection() as connection:
            delivery.before_call(authority, connection, delivery.read(connection, intent), saved,
                                 case["operators"].resolve, datetime.now(UTC), ghcn=context)
        return results
    # An otherwise unchanged real context still cannot grant a forged lease.
    before = all_application_rows(case["params"])
    with pytest.raises(CommandError) as held:
        with authority.projections._connection(writing=True) as connection, connection.transaction(force_rollback=True):
            value = delivery.read(connection, intent)
            delivery.begin(authority, connection, value, "x", "upload", {"owner": "t4-owned-local-worker", "fence": 999},
                {}, b"", case["operators"].resolve, datetime.now(UTC), ghcn=context)
    assert held.value.code == "delivery_stale_fence"
    assert all_application_rows(case["params"]) == before
    return results


def restored_history(case, path, expected, cost_value, cluster, tmp_path):
    import psycopg
    params = case["params"]
    _, tool, _ = cluster
    dump = tmp_path / "connected-temperature.dump"
    common = ["-h", params["host"], "-p", str(params["port"]), "-U", params["user"]]
    before = all_application_rows(params)
    tool("pg_dump", *common, "-Fc", "-f", str(dump), params["dbname"])
    name = "restore_t4_" + hashlib.sha256(str(dump).encode()).hexdigest()[:16]
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(params, dbname=name)
    try:
        tool("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        assert all_application_rows(restored_params) == before
        # No source, renderer or generation capability is configured on restart.
        assert restored.delivery_content(case["draft_id"], path["intent"]) == expected
        original = case["server"].authority
        try:
            case["server"].authority = restored
            readback = http(case["port"], f'/drafts/{case["draft_id"]}/media/delivery/{path["intent"]}', role="viewer")
            assert readback[0] == 200 and readback[1]["media"] == expected["media"]
            view = http(case["port"], role="viewer")[1]["local_cost"]
            assert view["requests"] == cost_value["requests"] and view["summary"] == cost_value["summary"]
            costs.cost_component_http(case, case["port"], view, tmp_path / "restored-cost.json")
        finally:
            case["server"].authority = original
        assert all_application_rows(restored_params) == before
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
    assert all_application_rows(params) == before


@contextmanager
def ready_delivery(case, tmp_path, *, mode="normal"):
    field = case["config"]["selection"]["signal_field"]
    draft_id = temperature.admit_compact(case, field)
    temperature.assert_compact_saved_claim(case, draft_id, field)
    case.update(draft_id=draft_id, store=case["authority"], text=temperature.saved_draft(case, draft_id)["text"])
    passive_cost(case, 4, tmp_path, "initial-check-cost")
    case["owner"].initialize_delivery(now=datetime.now(UTC))
    current = temperature.media_view(case, draft_id)
    command = temperature.editor_command(case, draft_id, "prepare_media_revision",
        {k: current[k] for k in temperature.PREPARE_KEYS})
    assert temperature.submit_command(case, command)["status"] == "unchanged"
    prepared = temperature.media_view(case, draft_id)
    png = temperature.png_bytes(case["authority"], draft_id, prepared["preparation"]["proposal_sha256"], case["operators"])
    with transport.fixture_server(png, case["text"], mode=mode) as (config, trace, accepted):
        configure_child(case, transport.configure(case["authority"], tmp_path, config))
        prepared = temperature.media_view(case, draft_id)
        description = prepared["platform_description"]
        assert description["status"] == "fits_local_limits", description
        assert description["record"]["derivation"] == "full_raw_alt"
        assert len(description["wire_text"].encode()) <= 1000 and description["wire_text"].endswith("\n")
        attached = temperature.submit_command(case, temperature.editor_command(case, draft_id,
            "attach_media_revision", review_payload(prepared)))
        assert attached["status"] == "applied", attached
        current = temperature.media_view(case, draft_id)
        request = temperature.editor_command(case, draft_id, "request_revision_checks", temperature.checked_payload(current))
        assert temperature.submit_command(case, request)["status"] == "unchanged"
        for stage in ("deterministic", "safety", "fact_check", "critic"):
            checked = temperature.ghcn_worker(case, stage, request["command_id"])
            assert checked["outcome"] == "completed" and checked["checks"]["stages"][stage] == "passed", json.dumps(checked, sort_keys=True)
        current = temperature.media_view(case, draft_id)
        approve = temperature.editor_command(case, draft_id, "approve_media_revision", temperature.checked_payload(
            current, expected_check_completion_sha256=current["expected_check_completion_sha256"],
            reason="Invented fitting full comparator, local transport only."))
        result = temperature.submit_command(case, approve, role="publisher")
        assert result["status"] == "applied" and "delivery" in result, result
        if os.environ.get("THEHEAT_T4_EVIDENCE"):
            identity = case["authority"].result(request["command_id"])["revision_checks"]["check_set_id"]
            packet = case["authority"].check_execution("read", {"check_set_id": identity},
                now=temperature.utc_text(datetime.now(UTC)))["packet"]
            (Path(os.environ["THEHEAT_T4_EVIDENCE"]) / "retained-revision-packet.json").write_text(json.dumps(packet))
        value = passive_cost(case, 7, tmp_path, "post-media-cost")
        yield dict(case=case, png=png, description=description, command=approve, result=result,
                   intent=result["delivery"]["intent_id"], trace=trace, accepted=accepted, cost=value)


@pytest.mark.parametrize("compact_case", [("all_time_low",)], indirect=True)
def test_genuine_compact_temperature_delivery_recovery_history_and_cost(compact_case, tmp_path, cluster):
    case = compact_case
    with diagnostic_workers(case), ready_delivery(case, tmp_path, mode={("x", "create"): "drop"}) as path:
        assert set(path["result"]["delivery"]["obligations"]) == {"x", "bluesky"}
        assert path["trace"] == []
        before = all_application_rows(case["params"])
        current = temperature.media_view(case, case["draft_id"])
        assert current["delivery"]["intents"][0]["current"] is True
        assert all_application_rows(case["params"]) == before
        negative = isolated_refusals(case, path)
        refusals, negative_failures = negative["refusals"], [negative["failure"]] if negative["failure"] else []
        original = case["authority"].read()
        result = run_delivery(case, path["intent"], "upload")
        assert result["outcome"] == "confirmed", result
        with case["authority"].projections._connection() as connection:
            saved = delivery.attempt(connection, delivery.read(connection, path["intent"]), "x", "upload")
        negative = isolated_refusals(case, path, boundaries=("before_call",))
        refusals.extend(negative["refusals"])
        if negative["failure"]:
            negative_failures.append(negative["failure"])
        # A real grant cannot send after a source outage. The no-call raw
        # observation is retained independently of any new scientific context.
        held = run_delivery(case, path["intent"], "upload", platform="bluesky", postgrant_outage=True)
        assert held["outcome"] == "not_sent", held
        assert len(path["trace"]) == 1
        assert run_delivery(case, path["intent"], "upload", platform="bluesky")["outcome"] == "not_sent"
        baseline = case["authority"].ghcn_baseline
        del case["authority"].ghcn_baseline
        try:
            before = all_application_rows(case["params"])
            # A missing source refuses a new phase, yet the unedited original
            # approval and its threaded passive history remain readable.
            assert run_delivery(case, path["intent"], "alt")["outcome"] == "withheld"
            with pytest.MonkeyPatch.context() as patch:
                def command_preparation_forbidden(*args, **kwargs):
                    pytest.fail("Command preparation reached from passive media/history GET")
                patch.setattr(delivery, "prepare_context", command_preparation_forbidden)
                view = temperature.media_view(case, case["draft_id"])
                assert view["delivery"]["intents"][0]["current"] is False
                history = http(case["port"], f'/drafts/{case["draft_id"]}/media/delivery/{path["intent"]}', role="viewer")
                assert history[0] == 200 and history[1]["media"]["alt_text"] == path["description"]["wire_text"]
            assert all_application_rows(case["params"]) == before
        finally:
            case["authority"].ghcn_baseline = baseline
        with case["authority"].projections._connection() as connection:
            value = delivery.read(connection, path["intent"])
            saved = delivery.attempt(connection, value, "bluesky", "upload")
            raw_rows = connection.execute("SELECT metadata_sha,raw_sha FROM theheat_delivery.observations WHERE attempt_id=%s", (saved["attempt_id"],)).fetchall()
            assert len(raw_rows) == 1
            metadata = delivery.document(connection, raw_rows[0][0])
            assert metadata["source"] == "no_call" and metadata["reason"] == "currentness_refused"
            assert delivery.raw(connection, raw_rows[0][1]) == b""
            assert delivery.outcome(connection, saved)["status"] == "not_sent"
        result = run_delivery(case, path["intent"], "alt")
        assert result["outcome"] == "confirmed", result
        unknown = run_delivery(case, path["intent"], "create")
        assert unknown["outcome"] == "unknown", unknown
        assert len(path["trace"]) == 3 and all(row["method"] == "POST" for row in path["trace"])
        # The exact original immutable upload/alt/create requests remain distinct.
        assert len({row["attempt_id"] for row in path["trace"]}) == 3
        assert len({row["request_sha256"] for row in path["trace"]}) == 3
        assert case["authority"].read() == original
        historical = case["authority"].delivery_content(case["draft_id"], path["intent"])
        assert historical["text"] == case["text"] and historical["media"]["png_sha256"] == hashlib.sha256(path["png"]).hexdigest()
        assert historical["media"]["alt_text"] == path["description"]["wire_text"]
        assert historical["media"]["alt_text"].endswith("\n")
        reopened = PostgresCommandAuthority(**options(case["params"]))
        reopened.configure_delivery(case["config"]["delivery"])
        replay = run_delivery(case, path["intent"], "create", authority=reopened)
        assert replay["outcome"] == "unknown" and replay["network_mutation"] is False
        assert len(path["trace"]) == 3
        recovered = run_delivery(case, path["intent"], "create", authority=reopened, reconcile=True)
        assert recovered["outcome"] == "confirmed" and recovered["reconciled"] is True, recovered
        assert [row["method"] for row in path["trace"]] == ["POST", "POST", "POST", "GET"]
        assert case["authority"].read() == original
        # Edit/cancel removes current eligibility; original bytes and costs survive.
        cancel = temperature.editor_command(case, case["draft_id"], "cancel_approval", {"reason": "Invented local cancellation after retained receipt."})
        assert temperature.submit_command(case, cancel, role="publisher")["status"] == "applied"
        edit = temperature.editor_command(case, case["draft_id"], "edit_revision", {"text": "A later invented station statement."})
        assert temperature.submit_command(case, edit)["status"] == "applied"
        expected = case["authority"].delivery_content(case["draft_id"], path["intent"])
        assert expected["text"] == historical["text"] and expected["media"] == historical["media"]
        before = all_application_rows(case["params"])
        baseline = case["authority"].ghcn_baseline
        del case["authority"].ghcn_baseline
        try:
            current = temperature.media_view(case, case["draft_id"])
            assert current["delivery"]["intents"][0]["current"] is False
            readback = http(case["port"], f'/drafts/{case["draft_id"]}/media/delivery/{path["intent"]}', role="viewer")
            assert readback[0] == 200 and readback[1]["media"] == expected["media"]
            assert case["authority"].delivery_content(case["draft_id"], path["intent"]) == expected
            value = passive_cost(case, 7, tmp_path, "historical-cost")
            assert value["requests"] == path["cost"]["requests"]
            assert run_delivery(case, path["intent"], "create", platform="bluesky")["outcome"] == "withheld"
        finally:
            case["authority"].ghcn_baseline = baseline
        assert all_application_rows(case["params"]) == before
        assert len(path["trace"]) == 4
        restored_history(case, path, expected, value, cluster, tmp_path)
        evidence = os.environ.get("THEHEAT_T4_EVIDENCE")
        if evidence:
            trace = [{**row, "body": None, "body_sha256": hashlib.sha256(row["body"]).hexdigest()} if "body" in row else row for row in path["trace"]]
            receipt = dict(native_png_sha256=hashlib.sha256(path["png"]).hexdigest(), native_png_bytes=len(path["png"]),
                alt_utf8_bytes=len(expected["media"]["alt_text"].encode()), alt_sha256=expected["media"]["alt_text_sha256"],
                description_derivation=path["description"]["record"]["derivation"], transport=trace, refusals=refusals, negative_fixture_failures=negative_failures,
                initial_requests=4, post_media_requests=7, final_requests=7, unknown_create=unknown, reconciliation=recovered,
                historical_and_restored_rows_preserved=True, model_posts=[row for row in temperature.trace_rows(case) if row["kind"] == "model_post"])
            (Path(evidence) / "connected-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2))
        assert not negative_failures, json.dumps(negative_failures, sort_keys=True)


@pytest.mark.parametrize("compact_case", [("all_time_high",)], indirect=True)
def test_opposite_high_compact_delivery_source_and_comparator_control(compact_case):
    case = compact_case
    draft = temperature.admit_compact(case, "all_time_high")
    temperature.assert_compact_saved_claim(case, draft, "all_time_high")
    case["config"].update(delivery_draft_id=draft, t4_owner=case["params"])
    case["config_path"].write_text(json.dumps(case["config"]))
    before = all_application_rows(case["params"])
    result = temperature.ghcn_worker(case, "delivery_high_control")
    assert result["selection"] == case["config"]["selection"]
    assert result["field_swap_refused"] and result["full_story_preserved"]
    assert result["comparator"] == "all_time" and result["direction"] == "high"
    assert all_application_rows(case["params"]) == before
    assert len([row for row in temperature.trace_rows(case) if row["kind"] == "model_post"]) == 4


@pytest.mark.parametrize("raises", [False, True], ids=["return_unchanged", "exception_unchanged"])
def test_diagnostic_span_preserves_outcome_and_records_independent_clocks(tmp_path, monkeypatch, raises):
    from tests import t4_timing_helpers as timing
    samples = iter([dict(monotonic=100.0, wall=1000.0), dict(monotonic=102.0, wall=1602.0)])
    monkeypatch.setattr(timing, "sample", lambda: next(samples))
    sentinel = object()
    error = RuntimeError("invented diagnostic control")
    def operation(argument):
        assert argument is sentinel
        if raises:
            raise error
        return sentinel
    trace = tmp_path / "spans.jsonl"
    if raises:
        with pytest.raises(RuntimeError) as caught:
            timing.timed(trace, "fact_check", "control", operation, sentinel)
        assert caught.value is error
    else:
        assert timing.timed(trace, "fact_check", "control", operation, sentinel) is sentinel
    value = json.loads(trace.read_text())
    assert value["monotonic_seconds"] == 2.0 and value["wall_seconds"] == 602.0
    assert value["outcome"] == ("raised" if raises else "returned")
    assert value["error_type"] == ("RuntimeError" if raises else None)


@pytest.mark.parametrize("raises", [False, True], ids=["keyword_return", "keyword_exception"])
def test_diagnostic_span_forwards_keywords_that_match_its_metadata(tmp_path, raises):
    from tests import t4_timing_helpers as timing
    sentinel = object()
    error = RuntimeError("invented keyword-forwarding control")
    def operation(**kwargs):
        assert kwargs == dict(operation=sentinel, trace=sentinel, label=sentinel, call=sentinel)
        if raises:
            raise error
        return sentinel
    trace = tmp_path / "spans.jsonl"
    def run():
        return timing.timed(trace, "write", "control", operation,
                           operation=sentinel, trace=sentinel, label=sentinel, call=sentinel)
    if raises:
        with pytest.raises(RuntimeError) as caught:
            run()
        assert caught.value is error
    else:
        assert run() is sentinel
    row = json.loads(trace.read_text())
    assert row["operation"] == "write" and row["label"] == "control"
    assert row["outcome"] == ("raised" if raises else "returned")


@pytest.mark.parametrize("raises", [False, True], ids=["outage_restored", "outage_restored_on_error"])
def test_reachable_source_outage_restores_exact_configuration(tmp_path, raises):
    path = tmp_path / "generation.json"
    original = b'{\n  "schema_version":2, "current_inputs":["original-retained-brief"], "reservations":{"batch":null,"synchronous":"original"}\n}\n'
    path.write_bytes(original)
    path.chmod(0o600)
    error = RuntimeError("invented outage-control failure")
    def exercise():
        with current_source_outage(path):
            value = json.loads(path.read_bytes())
            assert value["current_inputs"] == []
            assert value["reservations"] == json.loads(original)["reservations"]
            if raises:
                raise error
    if raises:
        with pytest.raises(RuntimeError) as caught:
            exercise()
        assert caught.value is error
    else:
        exercise()
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o600
