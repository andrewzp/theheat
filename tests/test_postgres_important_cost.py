"""Real two-item grants and passive cost readback; no provider or billing calls."""

from datetime import timedelta
import json

import pytest

from src.commands import postgres_cost_projection as cost
from src.commands.schema import utc_datetime, utc_text
from src.two_bot import retained_usage
from tests import test_postgres_important_variants as important_tests
from tests import test_postgres_cost_projection as old_cost
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
from tests.test_postgres_important_native import important_native as important_native
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_editor_media import offline_connections as offline_connections


def rows(*usages):
    return b"\n".join(
        json.dumps(
            dict(
                custom_id="slot" + str(i + 1),
                result=dict(type="succeeded", message=dict(model="invented", usage=value)),
            )
        ).encode()
        for i, value in enumerate(usages)
    )


def aggregate(raw):
    return retained_usage.important_batch(
        raw,
        ["slot1", "slot2"],
        stage="writer",
        model="invented",
        observed_at="2026-10-15T00:00:00.000000Z",
    )


def test_fieldwise_sum_preserves_nulls_categories_and_categorical_equality():
    value = aggregate(
        rows(
            dict(
                input_tokens=3,
                output_tokens=0,
                cache_creation_input_tokens=10,
                cache_creation=dict(ephemeral_1h_input_tokens=10),
                service_tier="batch",
            ),
            dict(
                input_tokens=4,
                cache_creation_input_tokens=20,
                cache_creation=dict(ephemeral_1h_input_tokens=20),
                service_tier="batch",
            ),
        )
    )
    assert value["status"] == "present" and value["counts"]["input_tokens"] == 7
    assert value["counts"]["output_tokens"] is None
    assert value["counts"]["cache_creation_input_tokens"] == 30
    assert value["counts"]["cache_creation.ephemeral_1h_input_tokens"] == 30
    assert value["labels"]["service_tier"] == "batch" and value["resolved_model"] == "invented"
    unequal = aggregate(
        rows(
            dict(input_tokens=0, service_tier="batch"),
            dict(input_tokens=0, service_tier="standard"),
        )
    )
    assert unequal["counts"]["input_tokens"] == 0 and unequal["labels"]["service_tier"] is None


@pytest.mark.parametrize(
    "second", [None, dict(input_tokens=True), dict(input_tokens=-1), dict(output_tokens=9)]
)
def test_unknown_or_invalid_item_never_uses_first_as_whole_total(second):
    value = aggregate(rows(dict(input_tokens=3), second))
    assert value["counts"]["input_tokens"] is None
    assert value["status"] in {"absent", "invalid", "present"}
    assert value["counts"]["output_tokens"] is None


@pytest.mark.parametrize(
    "kind", ["missing", "error", "duplicate", "foreign", "corrupt", "overflow"]
)
def test_missing_error_ambiguous_and_overflow_are_not_zero(kind):
    raw = rows(dict(input_tokens=3), dict(input_tokens=4))
    if kind == "missing":
        raw = raw.splitlines()[0]
    elif kind == "error":
        raw = (
            raw.splitlines()[0]
            + b"\n"
            + json.dumps(dict(custom_id="slot2", result=dict(type="errored", error={}))).encode()
        )
    elif kind == "duplicate":
        raw = b"\n".join([raw.splitlines()[0]] * 2)
    elif kind == "foreign":
        raw = raw.replace(b"slot2", b"slot3")
    elif kind == "corrupt":
        raw = b"{"
    else:
        raw = rows(dict(input_tokens=10**12), dict(input_tokens=1))
    value = aggregate(raw)
    assert value["counts"]["input_tokens"] is None
    assert value["status"] in {"unavailable", "invalid", "absent"}


def test_actual_two_items_one_hold_and_separate_six_checks(important, monkeypatch, core):
    case = important
    sent, _ = important_tests.capture(case)
    first, second = important_tests.enroll(case, 1), important_tests.enroll(case, 2)
    calls = important_tests.complete(first, monkeypatch) + important_tests.complete(
        second, monkeypatch
    )
    assert len(sent) == 3 and len(calls) == 6
    admitted = important_tests.consume(
        case, important_tests.slate_command(case), at=important_tests.AT
    )
    assert admitted["status"] == "applied", admitted
    from tests.test_postgres_editor_media import all_application_rows, action
    from src.editorial.revisions import fingerprint

    before = all_application_rows(core[3])
    with monkeypatch.context() as local:
        old_cost.passive_traps(local)
        value = case["store"].local_cost_projection(now=important_tests.AT)
    assert value["status"] == "available", value
    assert len(value["requests"]) == 7 and value["summary"]["commitments_micro_usd"]["held"] == "50"
    writer = [r for r in value["requests"] if r["role"] == "writer"]
    assert len(writer) == 1 and writer[0]["reserve_micro_usd"] == "20"
    assert writer[0]["usage"]["counts"]["input_tokens"] == 34
    assert writer[0]["usage"]["counts"]["cache_creation.ephemeral_1h_input_tokens"] == 100
    assert all(r["origin"]["brief_id"] == case["refs"]["brief_id"] for r in value["requests"])
    assert len({r["origin"]["grant_id"] for r in value["requests"]}) == 7
    assert (
        len({r["origin"]["check_set_id"] for r in value["requests"] if r["role"] != "writer"}) == 2
    )
    assert all(r["recorded_settlement_micro_usd"] is None for r in value["requests"])
    assert all_application_rows(core[3]) == before
    case["draft_id"] = admitted["candidate"]["draft_id"]
    draft = case["store"].read()[1]["drafts"][-1]
    selected = draft["candidates"][1]
    assert (
        action(
            case, "select_candidate", dict(candidate_rank=2, candidate_sha256=fingerprint(selected))
        )[1]["status"]
        == "applied"
    )
    after = all_application_rows(core[3])
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options

    reopened = PostgresCommandAuthority(**options(core[3]))
    historical = reopened.local_cost_projection(now=important_tests.AT + timedelta(days=100))
    assert historical["requests"] == value["requests"] and historical["summary"] == value["summary"]
    assert all_application_rows(core[3]) == after


def test_actual_missing_writer_sibling_stays_unknown_and_held(important, monkeypatch, core):
    case = important
    sent, _ = important_tests.capture(case, missing_second=True)
    before = case["store"].spending("status", {}, now=utc_text(important_tests.AT))
    with monkeypatch.context() as local:
        old_cost.passive_traps(local)
        value = case["store"].local_cost_projection(now=important_tests.AT)
    assert value["status"] == "available", value
    assert len(value["requests"]) == 1 and len(sent) == 3
    row = value["requests"][0]
    assert row["usage"]["status"] == "unavailable" and row["usage"]["reason"] == "response_missing"
    assert all(v is None for v in row["usage"]["counts"].values())
    assert row["held_micro_usd"] == "20" and row["recorded_settlement_micro_usd"] is None
    assert case["store"].spending("status", {}, now=utc_text(important_tests.AT)) == before


def test_actual_immutable_parent_and_raw_identity_faults_refuse_without_mutation(
    important, monkeypatch, core
):
    from copy import deepcopy
    from src.commands import postgres_important_variants as group, postgres_batch_results as results
    from tests.test_postgres_editor_media import all_application_rows

    case = important
    important_tests.capture(case)
    before = all_application_rows(core[3])
    projection, artifact = cost.Read.projection, cost.Read.artifact
    for fault in (
        "allowance",
        "command",
        "claim",
        "slots",
        "duplicate_raw",
        "foreign_raw",
        "corrupt_raw",
    ):

        def changed_projection(self, namespace, identity, **kwargs):
            found = projection(self, namespace, identity, **kwargs)
            if found is None:
                return found
            receipt, value = found
            value = deepcopy(value)
            if fault == "allowance" and namespace == group.ALLOWANCE:
                value["writer_reservation"]["reserve_micro_usd"] += 1
            elif fault == "command" and namespace == group.JOB:
                value["command_id"] = "not-the-initiating-command"
            elif fault == "claim" and namespace == group.CLAIM:
                value["job_id"] = "iv_" + "f" * 64
            elif fault == "slots" and namespace == group.JOB:
                value["slots"][1]["custom_id"] = value["slots"][0]["custom_id"]
            return receipt, value

        def changed_artifact(self, schema, table, *args, **kwargs):
            raw = artifact(self, schema, table, *args, **kwargs)
            if schema == results.SCHEMA and table == "result_artifacts":
                if fault == "duplicate_raw":
                    return b"\n".join([raw.splitlines()[0]] * 2)
                if fault == "foreign_raw":
                    rows = [json.loads(line) for line in raw.splitlines()]
                    rows[1]["custom_id"] = "foreign"
                    return b"\n".join(json.dumps(row).encode() for row in rows)
                if fault == "corrupt_raw":
                    return b"{"
            return raw

        with monkeypatch.context() as local:
            old_cost.passive_traps(local)
            local.setattr(cost.Read, "projection", changed_projection)
            local.setattr(cost.Read, "artifact", changed_artifact)
            assert (
                case["store"].local_cost_projection(now=important_tests.AT) == cost.unavailable()
            ), fault
        assert all_application_rows(core[3]) == before


def test_actual_unknown_check_is_independent_of_surviving_sibling(important, monkeypatch, core):
    from src.commands import postgres_check_observations as observations
    from src.editorial.revisions import fingerprint

    case = important
    important_tests.capture(case)
    first, second = important_tests.enroll(case, 1), important_tests.enroll(case, 2)
    assert important_tests.run_stage(first, "deterministic")["outcome"] == "completed"
    sent, _ = important_tests.executor.provider(
        monkeypatch, [important_tests.executor.envelope("NO")]
    )
    apply = observations.apply

    def lost(c, action, *args, **kwargs):
        if action == "observe":
            raise RuntimeError("Invented observation lost before commit")
        return apply(c, action, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(observations, "apply", lost)
        assert important_tests.run_stage(first, "safety")["outcome"] == "reconciliation_required"
    assert len(sent) == 1
    important_tests.complete(second, monkeypatch)
    assert (
        important_tests.consume(case, important_tests.slate_command(case), at=important_tests.AT)[
            "status"
        ]
        == "applied"
    )
    before = case["store"].spending("status", {}, now=utc_text(important_tests.AT))
    with monkeypatch.context() as local:
        old_cost.passive_traps(local)
        value = case["store"].local_cost_projection(now=important_tests.AT)
    assert value["status"] == "available", value
    identity = "ic_" + fingerprint(
        dict(job_id=case["result"]["generation"]["job_id"], slot=1, stage="safety")
    )
    unknown = next(r for r in value["requests"] if r["intent_id"] == identity)
    assert len(value["requests"]) == 5 and value["summary"]["commitments_micro_usd"]["held"] == "40"
    assert unknown["usage"]["reason"] == "response_missing" and unknown["held_micro_usd"] == "5"
    assert (
        unknown["origin"]["check_set_id"] == first["check_set_id"]
        and unknown["recorded_settlement_micro_usd"] is None
    )
    assert case["store"].spending("status", {}, now=utc_text(important_tests.AT)) == before


def test_legacy_schema1_prefix_does_not_require_important_group(store, inputs, monkeypatch, core):
    """A pre-existing valid identifier is not proof of a new plan contract."""
    from functools import partial
    from tests import test_postgres_candidate_admission as candidate
    from tests.test_postgres_editor_media import all_application_rows

    inputs["job_id"] = "iv_" + "b" * 64
    # The older fixture helper defaults these two real operations to job-fixture.
    # Bind them to this exact test job without replacing any authority behavior.
    workers = candidate.batches.workers
    monkeypatch.setattr(workers, "acquire", partial(workers.acquire, job=inputs["job_id"]))
    monkeypatch.setattr(workers, "adopt", partial(workers.adopt, job=inputs["job_id"]))
    case = candidate.unchecked.__wrapped__(store, inputs, monkeypatch, core)
    sent = candidate.complete(case, monkeypatch)
    assert len(sent) == 3
    before = all_application_rows(core[3])
    with monkeypatch.context() as local:
        old_cost.passive_traps(local)
        value = store.local_cost_projection(now=candidate.AT)
    assert value["status"] == "available", value
    assert len(value["requests"]) == 4
    checked = [row for row in value["requests"] if row["role"] != "writer"]
    assert len(checked) == 3 and len({row["origin"]["grant_id"] for row in checked}) == 3
    assert all(row["origin"]["kind"] == "required_check" for row in checked)
    assert all(row["usage"]["status"] in {"present", "absent"} for row in checked)
    assert all_application_rows(core[3]) == before


def test_identical_checked_texts_keep_both_histories_through_later_revision_costs(
    important, monkeypatch, core, tmp_path, native_dependencies
):
    from functools import partial
    from src.commands import postgres_authority as authority_module
    from src.commands import postgres_important_variants as group
    from tests import test_postgres_editor_media as editor
    from tests.fire_graphic_helpers import graphic_bundle

    text = "MODIS detected a 500 MW thermal signal in an invented region."
    case = important_tests.nominate_source(important, graphic_bundle(), "firms", [text, text])
    sent, _ = important_tests.capture(case, duplicate_text=True)
    first, second = important_tests.enroll(case, 1), important_tests.enroll(case, 2)
    calls = important_tests.complete(first, monkeypatch) + important_tests.complete(
        second, monkeypatch
    )
    assert len(sent) == 3 and len(calls) == 6
    initial_check_sets = {first["check_set_id"], second["check_set_id"]}
    assert len(initial_check_sets) == 2

    # A real admission must retain its final sampled time in the durable result.
    # The existing planner still performs all checks; only its fixture clock advances.
    at = important_tests.AT
    fresh = at + timedelta(microseconds=1)
    sampled = [at]
    actual_plan = important_tests.candidate.admission.plan_draft_admission

    def advancing_plan(*args, **kwargs):
        planned = actual_plan(*args, **kwargs)
        sampled[0] = fresh
        return planned

    cmd = important_tests.slate_command(case)
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(
            important_tests.candidate.admission, "plan_draft_admission", advancing_plan
        )
        clock_patch.setattr(authority_module, "_clock", lambda supplied: sampled[0])
        admitted = important_tests.consume(case, cmd, at=at)
    assert admitted["status"] == "applied", admitted
    case["draft_id"] = admitted["candidate"]["draft_id"]
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert [c["rank"] for c in draft["candidates"]] == [1]
    with case["store"].projections._connection() as c:
        membership = group.read(c, group.ADMISSION, case["result"]["generation"]["job_id"])
    assert set(membership["proofs"]) == {str(c["rank"]) for c in membership["candidates"]} == {"1"}
    assert membership["admitted_at"] == utc_text(fresh)
    assert at < utc_datetime(membership["admitted_at"]) <= utc_datetime(admitted["completed_at"])
    slots = membership["completion_snapshot"]["slots"]
    assert len(slots) == 2 and {s["check_set_id"] for s in slots} == initial_check_sets
    assert all(s["disposition"] == "valid" and s["completion_sha256"] for s in slots)

    later = fresh + timedelta(seconds=1)
    # Compare whole rows within one installed schema. Revision initialization
    # adds origin columns to existing immutable check-set rows.
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    core[2].initialize_revision_checks(now=later)
    initial_rows = editor.all_application_rows(core[3])
    with monkeypatch.context() as passive:
        old_cost.passive_traps(passive)
        initial = case["store"].local_cost_projection(now=later)
    assert initial["status"] == "available", initial
    assert len(initial["requests"]) == 7
    assert initial["summary"]["commitments_micro_usd"]["held"] == "50"
    assert editor.all_application_rows(core[3]) == initial_rows
    original_requests = {r["intent_id"]: r for r in initial["requests"]}
    writer = [r for r in initial["requests"] if r["role"] == "writer"]
    assert len(writer) == 1 and writer[0]["reserve_micro_usd"] == "20"
    assert writer[0]["usage"]["counts"]["input_tokens"] == 34
    assert {
        r["origin"]["check_set_id"] for r in initial["requests"] if r["role"] != "writer"
    } == initial_check_sets

    case["store"].configure_editor_media(
        **native_dependencies, scratch=tmp_path / "deduplicated-native"
    )
    # Existing helpers use a fixed fixture time; advance that whole follow-on
    # chain past the actual final admission sample rather than moving it backward.
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(editor, "view", partial(editor.view, now=later))
        clock_patch.setattr(editor, "action", partial(editor.action, at=later))
        clock_patch.setattr(editor, "AT", later)
        _, png = editor.prepare_and_attach(case)
        revision = editor.complete_revision(case, monkeypatch)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    revision_check_set = revision["revision_checks"]["check_set_id"]
    assert revision_check_set not in initial_check_sets
    before_read = editor.all_application_rows(core[3])
    for table, rows_before in initial_rows.items():
        if table[0] in {
            "theheat_spending",
            "theheat_checks",
            "theheat_check_executions",
            "theheat_batch_results",
            "theheat_batches",
            "theheat_batch_work",
        }:
            assert all(row in before_read[table] for row in rows_before), table
    with monkeypatch.context() as passive:
        old_cost.passive_traps(passive)
        final = case["store"].local_cost_projection(now=later)
    assert final["status"] == "available" and final["reason"] is None, final
    assert len(final["requests"]) == 10
    assert final["summary"]["commitments_micro_usd"]["held"] == "65"
    final_requests = {r["intent_id"]: r for r in final["requests"]}
    assert all(final_requests[key] == value for key, value in original_requests.items())
    added = [r for r in final["requests"] if r["intent_id"] not in original_requests]
    assert {r["role"] for r in added} == {"safety", "fact_check", "critic"}
    assert {r["origin"]["check_set_id"] for r in added} == {revision_check_set}
    assert len({r["origin"]["grant_id"] for r in final["requests"]}) == 10
    assert all(r["origin"]["raw_sha256"] and r["reserve_micro_usd"] == "5" for r in added)
    assert all(r["recorded_settlement_micro_usd"] is None for r in final["requests"])
    assert editor.all_application_rows(core[3]) == before_read


@pytest.mark.parametrize("important_native", ["modis"], indirect=True)
def test_actual_saved_revision_cancel_restart_restore_cost_lineage(
    important_native, monkeypatch, core, cluster
):
    from uuid import uuid4
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options
    from tests.test_postgres_projection import admin
    from tests import test_postgres_important_native as native, test_postgres_editor_media as editor

    case = important_native
    native.park(case, monkeypatch)
    before = editor.all_application_rows(core[3])
    with monkeypatch.context() as local:
        old_cost.passive_traps(local)
        value = case["store"].local_cost_projection(now=important_tests.AT)
    assert value["status"] == "available", value
    assert (
        len(value["requests"]) == 10 and value["summary"]["commitments_micro_usd"]["held"] == "65"
    )
    assert all(r["origin"]["brief_id"] == case["refs"]["brief_id"] for r in value["requests"])
    assert (
        len({r["origin"]["check_set_id"] for r in value["requests"] if r["role"] != "writer"}) == 3
    )
    assert editor.all_application_rows(core[3]) == before
    assert (
        editor.action(case, "cancel_approval", dict(reason="Invented cancellation"))[1]["status"]
        == "applied"
    )
    before = editor.all_application_rows(core[3])
    reopen = PostgresCommandAuthority(**options(core[3]))
    assert (
        reopen.local_cost_projection(now=important_tests.AT + timedelta(days=100))["requests"]
        == value["requests"]
    )
    assert editor.all_application_rows(core[3]) == before
    params, run, directory = cluster
    dump = directory / ("important-cost-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "cost_restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(core[3], dbname=name)
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        assert editor.all_application_rows(restored_params) == before
        assert (
            restored.local_cost_projection(now=important_tests.AT + timedelta(days=100))["requests"]
            == value["requests"]
        )
        assert editor.all_application_rows(restored_params) == before
    finally:
        admin(
            params,
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)),
        )
