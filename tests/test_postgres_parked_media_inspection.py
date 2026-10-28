"""Real passive PostgreSQL proofs; collect only without explicit Linux fixtures.

One compact source/check/approval setup is reused through restored read faults.
No successful verifier, scientific qualification or provider verdict is stubbed.
The existing production Node eight-second journey remains a separate CI gate.
"""
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import os
import subprocess

import pytest

from src.commands import postgres_editor_media as editor, postgres_delivery as delivery
from src.commands import postgres_stage_revision_checks as stages
from src.commands.schema import CommandError, utc_datetime
from src.storage import postgres_projection as p
from tests import test_postgres_editor_media as media
from tests import test_postgres_temperature_editor_media as temperature
from tests import test_postgres_temperature_delivery as compact_delivery
from tests.stage_revision_check_helpers import assert_protocol
from tests import test_postgres_delivery as radar_delivery
from tests import test_postgres_candidate_admission as candidate
from tests.local_delivery_helpers import fixture_server
from tests.parked_media_phase_witness import body_phase
from tests.radar_editor_helpers import radar_case as radar_case
from tests.test_postgres_delivery import admitted as admitted
from tests.test_postgres_preview_command_ingress import ORIGIN
from tests.test_postgres_projection import admin
from tests.test_postgres_temperature_editor_media import (
    compact_case as compact_case, cluster as cluster, database as database,
    core as core, make_authority as make_authority, spend_store as spend_store,
    worker_store as worker_store, base_store as base_store, store as store,
    inputs as inputs, native_dependencies as native_dependencies,
    positive_workflow_clock as positive_workflow_clock, offline_connections as offline_connections,
)


def observe(patch, counts):
    """Count actual completed invocations, including failures, without passing them."""
    for module, name, key in ((editor, "_reviewed", "pair"),
                              (stages, "_verify_prefix", "prefix"),
                              (editor, "inputs", "inputs")):
        original = getattr(module, name)

        def counted(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        patch.setattr(module, name, counted)


def read_current(case, *, resolve=None, at=None):
    return case["authority"].editor_media_projection(case["draft_id"],
        resolve or case["operators"].resolve, now=at or case.get("inspection_at") or datetime.now(UTC))


def current_intent(view, identity):
    return next(row for row in view["delivery"]["intents"] if row["intent_id"] == identity)


def standalone_full_view(case):
    """Original public projections, with their independent real verification."""
    authority = case["authority"]
    claim = editor.view_claim(authority, case["draft_id"])
    with authority.projections._connection() as c:
        authority._validate(c)
        version, state = authority._state(c, lock=True)
        value = editor.projection(authority, c, case["draft_id"], state=state, version=version,
            policy=editor.current_editorial_policy(), now=case["inspection_at"],
            resolve_principal=case["operators"].resolve, claim=claim)
        value["delivery"] = delivery.projection(authority, c, case["draft_id"],
            case["operators"].resolve, case["inspection_at"], claim=claim)
        return value


def assert_passive(case, path, before, history):
    assert media.all_application_rows(case["params"]) == before
    assert path["trace"] == [] and not path["accepted"]
    assert case["authority"].delivery_content(case["draft_id"], path["intent"]) == history


@pytest.mark.parametrize("compact_case", [("all_time_low",)], indirect=True)
def test_compact_owned_get_real_proofs_fresh_operations_and_restored_faults(
    compact_case, tmp_path, monkeypatch
):
    case = compact_case
    with compact_delivery.ready_delivery(case, tmp_path) as path:
        with body_phase("body_clock"):
            case["inspection_at"] = datetime.now(UTC)
        with body_phase("body_draft"):
            authority, resolve = case["authority"], case["operators"].resolve
            draft = temperature.saved_draft(case, case["draft_id"])
        with body_phase("body_binding"):
            binding = draft["approval_binding"]
            identity = binding["completion"]["check_set_id"]
        with body_phase("body_protocol"):
            assert_protocol(authority, identity)
        with body_phase("body_binding"):
            assert draft["decision_revision"] == binding["decision_revision"]
            assert binding["resulting_state_version"] == binding["consumed_state_version"] + 1
        with body_phase("body_rows"):
            before = media.all_application_rows(case["params"])
        with body_phase("body_history"):
            history = authority.delivery_content(case["draft_id"], path["intent"])
        with body_phase("body_config"):
            node_config = tmp_path / "parked-read-http.json"
            node_config.write_text(json.dumps(dict(endpoint=f'http://127.0.0.1:{case["port"]}',
                origin=ORIGIN, draft_id=case["draft_id"], intent=path["intent"])))
            node_config.chmod(0o600)
        with body_phase("body_node"):
            node = subprocess.run([os.environ.get("THEHEAT_NODE24", "node"), "--test",
                "tests/parked-media-read-http.test.js"], cwd=Path(__file__).resolve().parents[1] / "dashboard",
                env={**case["environment"], "LC_ALL": "C", "LANG": "C", "NETRC": "/dev/null",
                    "NO_PROXY": "*", "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "THEHEAT_PARKED_READ_HTTP_CONFIG": str(node_config)},
                capture_output=True, text=True, timeout=20)
        with body_phase("body_node_checks"):
            assert node.returncode == 0, node.stdout + node.stderr
            assert any(line.strip() in {"# pass 1", "ℹ pass 1"} for line in node.stdout.splitlines()), node.stdout
            assert any(line.strip() in {"# skipped 0", "ℹ skipped 0"} for line in node.stdout.splitlines()), node.stdout
        with body_phase("body_passive_check"):
            assert_passive(case, path, before, history)
        with body_phase("body_passive_reads"):
            counts = dict(pair=0, prefix=0, inputs=0)
            scopes = []
            original_open = editor._open_passive_inspection

            def opened(*args, **kwargs):
                scope = original_open(*args, **kwargs)
                scopes.append(scope)
                return scope

            with monkeypatch.context() as patch:
                observe(patch, counts)
                patch.setattr(editor, "_open_passive_inspection", opened)
                for operation in range(2):
                    previous = dict(counts)
                    view = read_current(case)
                    assert view["parked"] and view["review_current"] and view["checks_status"] == "passed"
                    assert current_intent(view, path["intent"])["current"] is True
                    assert view["publication_approved"] is False
                    assert {k: counts[k] - previous[k] for k in counts} == dict(pair=1, prefix=1, inputs=2)
                    assert scopes[-1]._closed and scopes[-1]._pair is None and scopes[-1]._proof is None
                    assert len(scopes) == operation + 1
                    assert_passive(case, path, before, history)

        with body_phase("body_intent_controls"):
            # Only the exact current intent consumes once; copied identifiers are
            # not authority. The first consume still performs its real guard path.
            original_consume = editor._PassiveInspection.consume
            consumed = []

            def consume(scope, active, c, active_draft, state, version, value, policy, claim, intent, resolver):
                for changed in (dict(intent, intent_id="00000000-0000-4000-8000-000000000001"),
                                dict(intent, approval_binding={**intent["approval_binding"], "decision_revision": -1})):
                    assert not scope.matches(active, c, changed)
                    with pytest.raises(CommandError):
                        original_consume(scope, active, c, active_draft, state, version, value, policy, claim, changed, resolver)
                for foreign_authority, foreign_c in ((object(), c), (active, object())):
                    with pytest.raises(CommandError):
                        original_consume(scope, foreign_authority, foreign_c, active_draft, state, version,
                            value, policy, claim, intent, resolver)
                args = (active, c, active_draft, state, version, value, policy, claim, intent, resolver)
                result = original_consume(scope, *args)
                consumed.append(intent["intent_id"])
                with pytest.raises(CommandError):
                    original_consume(scope, *args)
                return result

            with monkeypatch.context() as patch:
                patch.setattr(editor._PassiveInspection, "consume", consume)
                assert current_intent(read_current(case), path["intent"])["current"] is True
            assert consumed == [path["intent"]]
            assert_passive(case, path, before, history)

        with body_phase("body_fault_matrix"):
            with authority.projections._connection() as c:
                reviewer = authority._intent(c, draft["media_review_binding"]["command_id"])[0].actor_subject
            targets = dict(reviewer=reviewer, requester=binding["requesting_actor"], publisher=binding["publisher_subject"])
            critic_expiry = utc_datetime(binding["completion"]["final_ready_until"])

            # All faults happen after real full proof or real full description work.
            # Each new read starts from immutable retained rows and a fresh owner.
            for boundary in ("proof", "description"):
                faults = ["reviewer", "requester", "publisher", "policy", "source", "profile", "state", "expiry"]
                if boundary == "description":
                    faults += ["late_reviewer", "late_publisher"]
                for fault in faults:
                    armed: list[str] = []
                    revoked: list[bool] = []
                    elapsed = [0.0]
                    start = case["inspection_at"]
                    original_verify = stages._verify_prefix
                    original_description = delivery._description_preflight
                    original_state = authority._state
                    original_loader = authority.generation_configuration
                    original_configuration = Path(case["config"]["generation"]).read_bytes()
                    with monkeypatch.context() as patch:
                        patch.setattr(editor, "_passive_monotonic", lambda: elapsed[0])

                        def drift():
                            if armed:
                                return
                            armed.append(fault)
                            if fault == "policy":
                                patch.setenv("THEHEAT_WRITER_SAMPLES", "3")
                            elif fault == "source":
                                # Actual owner-only configuration file, reread by production.
                                changed = json.loads(original_configuration)
                                changed["current_inputs"] = []
                                Path(case["config"]["generation"]).write_text(json.dumps(changed))
                            elif fault == "profile":
                                changed = deepcopy(authority.editor_media_configuration)
                                changed["scratch"] += "-changed"
                                patch.setattr(authority, "editor_media_configuration", changed)
                            elif fault == "expiry":
                                elapsed[0] = (critic_expiry - start).total_seconds()

                        def verified(*args, **kwargs):
                            result = original_verify(*args, **kwargs)
                            if kwargs.get("length") in (None, 4):
                                drift()
                            return result

                        def described(*args, **kwargs):
                            result = original_description(*args, **kwargs)
                            drift()
                            return result

                        def resolver(subject):
                            denied = armed and targets.get(fault) == subject
                            late = revoked and targets.get(fault.removeprefix("late_")) == subject
                            return None if denied or late else resolve(subject)

                        def load_after_description():
                            value = original_loader()
                            if armed and fault.startswith("late_"):
                                revoked.append(True)
                            return value

                        def state_after_callback(c, *, lock=False):
                            version, state = original_state(c, lock=lock)
                            if armed and fault == "state":
                                state = deepcopy(state)
                                state["drafts"] = [dict(row, text=row["text"] + " Changed callback state.")
                                    if row.get("id") == case["draft_id"] else row for row in state["drafts"]]
                            return version, state

                        patch.setattr(authority, "_state", state_after_callback)
                        patch.setattr(authority, "generation_configuration", load_after_description)
                        patch.setattr(stages, "_verify_prefix", verified) if boundary == "proof" else patch.setattr(
                            delivery, "_description_preflight", described)
                        try:
                            refused = read_current(case, resolve=resolver, at=start)
                            assert armed == [fault], (boundary, fault)
                            assert not refused["parked"], (boundary, fault, refused)
                            assert current_intent(refused, path["intent"])["current"] is False, (boundary, fault, refused)
                            if fault in targets or fault.startswith("late_"):
                                assert current_intent(refused, path["intent"])["reason"] == "forbidden"
                                if fault in {"reviewer", "late_reviewer"}:
                                    assert refused["review_current"] is False
                        finally:
                            Path(case["config"]["generation"]).write_bytes(original_configuration)
                    assert_passive(case, path, before, history)

        with body_phase("body_refusal_order"):
            # REPAIR-1 I1: inspection capture cannot reorder the original source
            # refusal or erase already attached preparation/packet/source fields.
            import psycopg
            from src.two_bot.check_origin import SOURCE_NAMESPACE
            from src.editorial.revisions import fingerprint

            origin_key = (SOURCE_NAMESPACE, fingerprint(dict(draft_id=case["draft_id"])))
            origin = admin(case["params"], "SELECT * FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s", origin_key)
            assert len(origin) == 1
            # Fixture params autocommit by default. Keep SET LOCAL and each
            # privileged damaged-restore write in the same explicit transaction.
            try:
                with psycopg.connect(**dict(case["params"], autocommit=False)) as c:
                    c.execute("SET LOCAL session_replication_role='replica'")
                    c.execute("DELETE FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s", origin_key)
                missing_origin_rows = media.all_application_rows(case["params"])
                with monkeypatch.context() as patch:
                    patch.setattr(authority, "generation_configuration", lambda: {})
                    expected = standalone_full_view(case)
                    actual = read_current(case)
                    assert expected["code"] == actual["code"] == "saved_source_origin_unavailable"
                    assert p._canonical(actual) == p._canonical(expected)
                    assert current_intent(actual, path["intent"])["current"] is False
                    assert media.all_application_rows(case["params"]) == missing_origin_rows
                    assert path["trace"] == [] and not path["accepted"]
            finally:
                with psycopg.connect(**dict(case["params"], autocommit=False)) as c:
                    c.execute("SET LOCAL session_replication_role='replica'")
                    c.execute("INSERT INTO theheat_projection.versions VALUES(%s,%s,%s,%s,%s,%s)", origin[0])
            assert_passive(case, path, before, history)

        with body_phase("body_delivery_file"):
            delivery_file = authority.delivery_configuration.path
            delivery_bytes = delivery_file.read_bytes()
            try:
                delivery_file.write_bytes(b"{}")
                expected = standalone_full_view(case)
                actual = read_current(case)
                assert expected["status"] == "attached"
                assert expected["preparation"] is not None and expected["packet"] is not None
                assert expected["source_label"] and expected["source_context"]
                assert p._canonical(actual) == p._canonical(expected)
                assert not actual["parked"] and not current_intent(actual, path["intent"])["current"]
                assert media.all_application_rows(case["params"]) == before
                assert path["trace"] == [] and not path["accepted"]
            finally:
                delivery_file.write_bytes(delivery_bytes)
            assert_passive(case, path, before, history)

        with body_phase("body_generation_file"):
            # REPAIR-1 I2: a valid final role callback changes the same file after
            # the first final content read, without changing its loader identity.
            generation_file = Path(case["config"]["generation"])
            original_bytes, original_inode = generation_file.read_bytes(), generation_file.stat().st_ino
            original_loader, original_description = authority.generation_configuration, delivery._description_preflight
            description_done: list[bool] = []
            final_reads: list[bool] = []
            changed_by_role: list[str] = []
            counts = dict(pair=0, prefix=0, inputs=0)
            with monkeypatch.context() as patch:
                observe(patch, counts)

                def description_complete(*args, **kwargs):
                    value = original_description(*args, **kwargs)
                    description_done.append(True)
                    return value

                def same_loader():
                    value = original_loader()
                    if description_done:
                        final_reads.append(True)
                    return value

                def role_changes_same_file(subject):
                    principal = resolve(subject)
                    if final_reads and not changed_by_role and subject == binding["publisher_subject"]:
                        changed = json.loads(original_bytes)
                        changed["current_inputs"] = []
                        generation_file.write_text(json.dumps(changed))
                        changed_by_role.append(subject)
                    return principal

                patch.setattr(delivery, "_description_preflight", description_complete)
                patch.setattr(authority, "generation_configuration", same_loader)
                try:
                    actual = read_current(case, resolve=role_changes_same_file)
                    assert description_done and final_reads and changed_by_role == [binding["publisher_subject"]]
                    assert authority.generation_configuration is same_loader
                    assert generation_file.stat().st_ino == original_inode
                    assert counts == dict(pair=1, prefix=1, inputs=2)
                    assert not actual["parked"]
                    held = current_intent(actual, path["intent"])
                    assert held["current"] is False and held["reason"] == "media_source_not_allowlisted"
                finally:
                    generation_file.write_bytes(original_bytes)
            assert_passive(case, path, before, history)

        with body_phase("body_exception_cleanup"):
            # Exception cleanup cannot seed an accepted result for the next request.
            original_verify = stages._verify_prefix
            with monkeypatch.context() as patch:
                def interrupted(*args, **kwargs):
                    original_verify(*args, **kwargs)
                    raise RuntimeError("invented failure after actual prefix proof")
                patch.setattr(editor, "_open_passive_inspection", opened)
                patch.setattr(stages, "_verify_prefix", interrupted)
                with pytest.raises(RuntimeError, match="actual prefix"):
                    read_current(case)
                assert scopes[-1]._closed and scopes[-1]._pair is None and scopes[-1]._proof is None
            assert current_intent(read_current(case), path["intent"])["current"] is True
            assert_passive(case, path, before, history)

        with body_phase("body_standalone"):
            # Standalone passive and active APIs independently replay the real proof.
            counts = dict(pair=0, prefix=0, inputs=0)
            with monkeypatch.context() as patch:
                observe(patch, counts)
                standalone = authority.delivery_projection(case["draft_id"], resolve, now=case["inspection_at"])
                assert standalone["intents"][0]["current"] is True
                assert counts["pair"] >= 2 and counts["prefix"] == 1 and counts["inputs"] == 1
                prepared = delivery.prepare_context(authority, intent_id=path["intent"])
                prior = dict(counts)
                with authority.projections._connection() as c:
                    delivery.context(authority, c, delivery.read(c, path["intent"]), resolve, case["inspection_at"], ghcn=prepared)
                assert counts["pair"] >= prior["pair"] + 2 and counts["prefix"] == prior["prefix"] + 1
            assert_passive(case, path, before, history)


        with body_phase("body_restore_matrix"):
            # A damaged restore after accepted GETs must be seen by the next real
            # engine read. Commit corruption as owner, preserve the damaged snapshot,
            # and restore exactly afterward; runtime roles never gain a write bypass.
            import psycopg
            grant = admin(case["params"], "SELECT grant_id FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='safety'", (identity,))[0][0]
            other_raw = admin(case["params"], "SELECT raw_sha256 FROM theheat_check_executions.observations WHERE grant_id IN "
                "(SELECT grant_id FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='deterministic')", (identity,))[0][0]
            for table, column, wrong in (
                ("theheat_check_executions.observations", "raw_sha256", other_raw),
                ("theheat_checks.stage_seals", "receipt_sha256", "0" * 64),
                ("theheat_checks.stage_seals", "prefix_sha256", "0" * 64),
                ("theheat_checks.receipts", "disposition", "rejected"),
            ):
                original = admin(case["params"], f"SELECT {column} FROM {table} WHERE grant_id=%s", (grant,))[0][0]
                assert original != wrong
                try:
                    with psycopg.connect(**dict(case["params"], autocommit=False)) as c:
                        c.execute("SET LOCAL session_replication_role='replica'")
                        c.execute(f"UPDATE {table} SET {column}=%s WHERE grant_id=%s", (wrong, grant))
                    corrupted = media.all_application_rows(case["params"])
                    try:
                        refused = read_current(case)
                    except (CommandError, ValueError, p.ProjectionError):
                        pass
                    else:
                        assert not refused["parked"] and not current_intent(refused, path["intent"])["current"]
                    assert media.all_application_rows(case["params"]) == corrupted
                    assert path["trace"] == [] and not path["accepted"]
                finally:
                    with psycopg.connect(**dict(case["params"], autocommit=False)) as c:
                        c.execute("SET LOCAL session_replication_role='replica'")
                        c.execute(f"UPDATE {table} SET {column}=%s WHERE grant_id=%s", (original, grant))
                assert_passive(case, path, before, history)

        with body_phase("body_passive_history"):
            with monkeypatch.context() as patch:
                def forbidden(*args, **kwargs):
                    raise AssertionError("Passive history attempted current/active proof")
                patch.setattr(editor, "_reviewed", forbidden)
                patch.setattr(stages, "_verify_prefix", forbidden)
                patch.setattr(delivery, "prepare_context", forbidden)
                assert authority.delivery_content(case["draft_id"], path["intent"]) == history
            assert_passive(case, path, before, history)


@pytest.mark.revision_check_protocol(1)
def test_legacy_shared_fence_owned_view_replays_all_four_proofs_once(
    admitted, core, tmp_path, monkeypatch
):
    case = admitted
    _, png = media.prepare_and_attach(case)
    core[2].initialize_delivery(now=media.AT)
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        radar_delivery.configure(case["store"], tmp_path, config)
        radar_delivery.bind_platform(case, monkeypatch)
        _, result = radar_delivery.park(case)
        assert result["status"] == "applied"
        draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
        identity = draft["approval_binding"]["completion"]["check_set_id"]
        assert_protocol(case["store"], identity, 1)
        assert set(draft["approval_binding"]["completion"]["stages"]) == {"deterministic", "safety", "fact_check", "critic"}
        caps = admin(core[3], "SELECT * FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence", (identity,))
        before = media.all_application_rows(core[3])
        counts = dict(pair=0, prefix=0, inputs=0)
        verified = []
        original = editor.checks.verified_stage_receipts

        def full(*args, **kwargs):
            value = original(*args, **kwargs)
            assert set(value[0]) == {"deterministic", "safety", "fact_check", "critic"}
            verified.append(identity)
            return value

        with monkeypatch.context() as patch:
            observe(patch, counts)
            patch.setattr(editor.checks, "verified_stage_receipts", full)
            view = case["store"].editor_media_projection(case["draft_id"], candidate.resolve, now=media.AT)
            assert view["parked"] and current_intent(view, result["delivery"]["intent_id"])["current"]
            assert counts == dict(pair=1, prefix=0, inputs=2)
            assert verified == [identity]
        assert admin(core[3], "SELECT * FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence", (identity,)) == caps
        assert media.all_application_rows(core[3]) == before and trace == [] and not accepted
