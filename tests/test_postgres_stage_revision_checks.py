"""Protocol2 authority on real offline PostgreSQL/editor paths.

These cases require the existing PostgreSQL and native fixtures on Linux. Local
collection is not execution evidence. Provider responses are explicit SDK HTTP
fixtures; no production interpreter, request, clock window or verdict is stubbed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.commands import postgres_checks as checks, postgres_revision_checks as revisions
from src.commands import postgres_stage_revision_checks as stages
from src.commands.schema import Command, CommandError, canonical_json, utc_datetime, utc_text
from src.commands.spend_journal import SpendError
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from tests import test_check_executor as executor
from tests import test_postgres_candidate_admission as candidate
from tests import test_postgres_editor_media as editor
from tests import test_postgres_delivery as delivery
from tests import test_postgres_published_media as published
from tests import test_postgres_revision_checks as catalog
from tests import test_postgres_temperature_editor_media as temperature
from tests import test_postgres_temperature_delivery as temperature_delivery
from tests.stage_revision_check_helpers import assert_protocol, stage_rows
from tests.radar_editor_helpers import radar_case as radar_case
from tests.test_postgres_editor_media import admitted as admitted, offline_connections as offline_connections
from tests.test_postgres_projection import cluster as cluster, database as database, admin, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_temperature_editor_media import (
    compact_case as compact_case, positive_workflow_clock as positive_workflow_clock,
)


def retained(case, identity, *, at=editor.AT):
    return case["store"].check_execution("read", {"check_set_id": identity}, now=utc_text(at))


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_actual_protocol2_seal_removed_between_begin_passes_rolls_back_before_attempt(
    admitted, core, tmp_path, monkeypatch
):
    """Real owner-corrupted restore, not a runtime-role write or a send.

    MODIS is the smallest genuine fixture for this transaction boundary. The
    original compact-temperature journey separately exercises temperature reuse;
    this case does not claim a temperature calculation hit or a timing outcome.
    """
    import psycopg
    from src.commands import postgres_delivery as domain
    from src.posting.delivery_receipts import descriptor
    from src.posting.local_delivery import SCOPE

    case, authority = admitted, admitted["store"]
    _, png = editor.prepare_and_attach(case)
    core[2].initialize_delivery(now=editor.AT)
    delivery.configure(authority, tmp_path, dict(
        schema_version=2, platform_profile="credentialless-loopback-v1", scope=SCOPE,
        invented=True, instance_id=str(uuid4()), origin="http://127.0.0.1:1",
        routes_version=1, actor="did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"))
    delivery.bind_platform(case, monkeypatch)
    identity = editor.view(case)["check_set_id"]
    assert_protocol(authority, identity)
    _, parked = delivery.park(case)
    assert parked["status"] == "applied", parked
    intent = parked["delivery"]["intent_id"]
    before = editor.all_application_rows(core[3])
    assert admin(core[3], "SELECT count(*) FROM theheat_delivery.attempts") == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_delivery.leases") == [(0,)]

    # The normal runtime cannot remove an immutable stage seal.
    with pytest.raises(psycopg.Error):
        with authority.projections._connection(writing=True) as c:
            c.execute("DELETE FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,))
    assert editor.all_application_rows(core[3]) == before
    lease = dict(owner="invented-seal-boundary", fence=1,
                 expires_at=utc_text(editor.AT + timedelta(seconds=domain.LEASE_SECONDS)))
    request = descriptor("bluesky", "upload", "*/*", png)
    roles = []
    with psycopg.connect(**dict(core[3], autocommit=False)) as c:
        authority._validate(c)
        domain.validate(c, authority.environment)
        authority._pointer(c, lock=True)
        value = domain.read(c, intent)
        def resolve(subject):
            roles.append(subject)
            if len(roles) == 7:
                # Deliberately privileged owner corruption in this uncommitted
                # transaction. Ordinary runtime immutability was checked above.
                c.execute("SET LOCAL session_replication_role='replica'")
                removed = c.execute("DELETE FROM theheat_checks.stage_seals "
                    "WHERE check_set_id=%s AND stage='deterministic' RETURNING grant_id", (identity,)).fetchall()
                assert len(removed) == 1
            return candidate.resolve(subject)
        with pytest.raises(checks.checks.CheckJournalError, match="stage_seal_required"):
            domain.begin(authority, c, value, "bluesky", "upload", lease, request, png, resolve, editor.AT)
        assert len(roles) == 11
        assert c.execute("SELECT count(*) FROM theheat_delivery.attempts").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM theheat_delivery.leases").fetchone() == (0,)
        c.rollback()
    assert editor.all_application_rows(core[3]) == before

    # Rollback restores eligibility for an independent connection/complete read.
    with authority.projections._connection(writing=True) as c:
        authority._validate(c)
        domain.validate(c, authority.environment)
        authority._pointer(c, lock=True)
        value = domain.read(c, intent)
        grant = domain.begin(authority, c, value, "bluesky", "upload", lease, request, png,
                             candidate.resolve, editor.AT)
        assert grant["dispatch_granted"] is True
        assert c.execute("SELECT count(*) FROM theheat_delivery.attempts").fetchone() == (1,)
        c.rollback()
    assert editor.all_application_rows(core[3]) == before


def begin_case(case):
    editor.prepare_and_attach(case)
    command, identity, packet = editor.request_revision(case)
    assert_protocol(case["store"], identity)
    return command, identity, packet


def pass_prefix(case, command, packet, monkeypatch, count=4, *, offsets=None):
    sent, _ = executor.provider(monkeypatch, [
        executor.envelope("NO"), executor.envelope(editor.fact_pass(case["text"])),
        executor.envelope(executor.CRITIC_PASS),
    ])
    offsets = offsets or [0] * 4
    for index, stage in enumerate(checks.checks.STAGES[:count]):
        result = editor.run_revision(case, command, packet, stage,
            clock=lambda i=index: utc_text(editor.AT + timedelta(seconds=offsets[i])))
        assert result["outcome"] == "completed", (stage, result)
        assert result["checks"]["stages"][stage] == "passed", result
    return sent


def generic_payload(identity, packet, fence=1):
    return dict(check_set_id=identity, owner="revision-checks:" + packet["enrollment_id"], fence=fence,
        current_context=packet["current_context"], checker_state_sha256=packet["checker_state_sha256"])


def assert_unknown(case, *, at=editor.AT):
    money = case["store"].spending("status", {}, now=utc_text(at))
    assert money["totals"]["held_micro_usd"] >= 5
    assert money["accounting_complete"] is False


def test_catalog4_owner_atomic_idempotent_legacy_receipts_and_runtime_denial(store, core):
    core[2].initialize_synchronous_checks(now=catalog.NOW)
    before = catalog.catalogs(store)
    receipts = admin(core[3], "SELECT * FROM theheat_checks.schema_upgrades ORDER BY upgrade_version")
    core[2].initialize_stage_revision_checks(now=catalog.NOW)
    after = catalog.catalogs(store)
    assert after["theheat_checks"][0] == before["theheat_checks"][0]
    assert after["theheat_check_executions"] == before["theheat_check_executions"]
    assert after["theheat_checks"][1] != before["theheat_checks"][1]
    assert admin(core[3], "SELECT * FROM theheat_checks.schema_upgrades WHERE upgrade_version<4 ORDER BY upgrade_version") == receipts
    assert admin(core[3], "SELECT upgrade_version FROM theheat_checks.schema_upgrades ORDER BY 1") == [(2,), (3,), (4,)]
    rows = editor.all_application_rows(core[3])
    core[2].initialize_stage_revision_checks(now=catalog.NOW)
    core[2].initialize_synchronous_checks(now=catalog.NOW)
    core[2].initialize_revision_checks(now=catalog.NOW)
    assert editor.all_application_rows(core[3]) == rows
    with pytest.raises(p.ProjectionError):
        store.initialize_stage_revision_checks(now=catalog.NOW)
    for statement in (
        "UPDATE theheat_checks.sets SET authority_protocol=1",
        "DELETE FROM theheat_checks.stage_leases",
        "TRUNCATE theheat_checks.stage_seals",
        "ALTER TABLE theheat_checks.stage_leases ADD COLUMN injected integer",
        "GRANT UPDATE ON theheat_checks.stage_seals TO projection_runtime",
    ):
        with pytest.raises(Exception):
            with store.projections._connection(writing=True) as c:
                c.execute(statement)
    assert editor.all_application_rows(core[3]) == rows


def test_catalog4_concurrent_owner_install_retains_single_chain(store, core):
    core[2].initialize_synchronous_checks(now=catalog.NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(core[2].initialize_stage_revision_checks, now=catalog.NOW) for _ in range(2)]:
            future.result()
    with store.projections._connection() as c:
        checks.validate(c, "local")
    assert admin(core[3], "SELECT upgrade_version FROM theheat_checks.schema_upgrades ORDER BY 1") == [(2,), (3,), (4,)]


@pytest.mark.parametrize("boundary", [*range(14), "commit"])
def test_catalog4_every_installation_boundary_rolls_back(store, core, monkeypatch, boundary):
    core[2].initialize_synchronous_checks(now=catalog.NOW)
    before, rows = catalog.catalogs(store), editor.all_application_rows(core[3])
    hit = []
    groups = []

    def stop(query, connection):
        group = ("CREATE TABLE theheat_checks.stage_leases" in query
            or (query.startswith(("GRANT", "REVOKE", "Composed")) and any(name in query for name in (
                "stage_leases", "stage_seals", "stage_proof_artifacts", "check_stage_progress", "check_stage_seal", "check_legacy_protocol")))
            or query.startswith("INSERT INTO theheat_checks.schema_upgrades VALUES(4,"))
        if group:
            groups.append(query)
        if group and boundary != "commit" and len(groups) == boundary + 1:
            hit.append(query)
            raise RuntimeError("invented catalog4 boundary")

    def commit(connection):
        hit.append("commit")
        raise RuntimeError("invented catalog4 boundary")

    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=stop, before_commit=commit if boundary == "commit" else None)
        with pytest.raises(RuntimeError, match="invented catalog4 boundary"):
            core[2].initialize_stage_revision_checks(now=catalog.NOW)
    assert hit
    assert catalog.catalogs(store) == before and editor.all_application_rows(core[3]) == rows
    assert admin(core[3], "SELECT to_regclass('theheat_checks.stage_leases')") == [(None,)]


def test_frozen_previous_binary_refuses_catalog4_before_work(store, core):
    core[2].initialize_synchronous_checks(now=catalog.NOW)
    raw = Path(__file__).with_name("fixtures").joinpath("old_revision_catalog_validate.py.txt").read_bytes()
    assert p._sha(raw) == "286fbf81a69368c61ccf79e69726b241ba6efcb658b3c1d6298c4ea4f592c1c0"
    namespace = dict(vars(revisions))
    exec(compile(raw, "old_revision_catalog_validate.py.txt", "exec"), namespace)
    core[2].initialize_stage_revision_checks(now=catalog.NOW)
    rows = editor.all_application_rows(core[3])
    with store.projections._connection() as c:
        metadata = revisions.metadata(c, "theheat_checks")
        with pytest.raises(checks.checks.CheckJournalError):
            namespace["validate_catalog"](c, metadata, "local", (metadata["owner_role"], metadata["runtime_role"]))
    assert editor.all_application_rows(core[3]) == rows


@pytest.mark.parametrize("tamper", [
    "ALTER TABLE theheat_checks.stage_leases DISABLE TRIGGER ALL",
    "ALTER TABLE theheat_checks.stage_seals DISABLE TRIGGER ALL",
    "ALTER TABLE theheat_checks.sets DROP COLUMN authority_protocol CASCADE",
    "GRANT UPDATE ON theheat_checks.stage_leases TO projection_runtime",
    "DROP TABLE theheat_checks.stage_proof_artifacts CASCADE",
])
def test_catalog4_tamper_fails_closed_without_repair(store, core, tamper):
    core[2].initialize_stage_revision_checks(now=catalog.NOW)
    admin(core[3], tamper)
    rows = editor.all_application_rows(core[3])
    with pytest.raises(Exception):
        with store.projections._connection() as c:
            checks.validate(c, "local")
    with pytest.raises(Exception):
        core[2].initialize_stage_revision_checks(now=catalog.NOW)
    assert editor.all_application_rows(core[3]) == rows


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_genuine_v2_chain_exceeds_first_cap_and_generic_status_never_certifies(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    sent = pass_prefix(case, command, packet, monkeypatch, offsets=[0, 50, 100, 150])
    caps = stage_rows(core[3], identity)
    assert [row[0] for row in caps] == list(checks.checks.STAGES)
    assert [row[1] for row in caps] == [1, 2, 3, 4]
    assert all(utc_datetime(row[4]) - utc_datetime(row[3]) == timedelta(seconds=180) for row in caps)
    assert caps[0][4] < caps[-1][4] < packet["useful_until"]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.draft_leases WHERE check_set_id=%s", (identity,)) == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,)) == [(4,)]
    at = editor.AT + timedelta(seconds=181)
    current = editor.view(case, now=at)
    assert current["checks_status"] == "passed", current
    with case["store"].projections._connection() as c:
        proof = editor.domain.completed(c, identity, packet, at, "local")
    assert proof["schema_version"] == 2 and proof["authority_protocol"] == 2
    assert proof["packet_sha256"] == p._sha(canonical_json(packet).encode())
    assert proof["check_set_id"] == fingerprint(packet)
    for sha, raw, length in admin(core[3], "SELECT sha,payload,byte_count FROM theheat_checks.stage_proof_artifacts"):
        assert sha == p._sha(raw) and length == len(raw) <= 16384
        assert canonical_json(p._decode(raw)).encode() == raw
        assert sha != fingerprint(p._decode(raw))
    assert proof["final_ready_until"] == min(caps[-1][4], packet["useful_until"])
    payload = generic_payload(identity, packet, 4)
    status = case["store"].candidate_checks("status", payload, now=utc_text(at))
    assert not status["required_checks_completed"]
    assert status["blocked_reason"] == "scoped_revision_context_required"
    before = editor.all_application_rows(core[3])
    with pytest.raises(Exception):
        case["store"].acquire_check_lease(identity, payload["owner"], 180, now=utc_text(at))
    assert editor.all_application_rows(core[3]) == before
    with case["store"].projections._connection(writing=True) as c:
        with pytest.raises(checks.checks.CheckJournalError):
            revisions.acquire(c, identity, payload["owner"], 180, now=utc_text(at), environment="local")
    with pytest.raises(Exception):
        with case["store"].projections._connection(writing=True) as c:
            c.execute("INSERT INTO theheat_checks.draft_leases(check_set_id,origin_kind,fence,owner,recorded_at,expires_at) VALUES(%s,'saved_draft_revision_v1',1,%s,%s,%s)",
                (identity, payload["owner"], utc_text(at), utc_text(at+timedelta(seconds=180))))
    assert editor.all_application_rows(core[3]) == before
    for action in ("begin", "complete"):
        saved = retained(case, identity, at=at)["attempts"]["critic"]
        args = dict(payload, stage="critic")
        extra = {}
        if action == "begin":
            args["reservation"] = saved["binding"]["reservation"]
            extra["request"] = canonical_json(executor.check_requests.prepare_request(packet, "critic")).encode()
        else:
            args["grant_id"] = saved["grant_id"]
            with case["store"].projections._connection() as c:
                extra["receipt"] = checks._terminal(c, saved)["document"]
        with pytest.raises(Exception):
            case["store"].candidate_checks(action, args, now=utc_text(at), **extra)
        assert editor.all_application_rows(core[3]) == before
    report = editor.run_revision(case, command, packet, "critic", clock=lambda: utc_text(at))
    assert report["outcome"] == "checks_completed" and len(sent) == 3
    assert stage_rows(core[3], identity) == caps
    state = case["store"].read()
    approval = dict(**{key: current[key] for key in ("expected_policy_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256")},
        expected_packet_sha256=current["packet"]["packet_sha256"], reason="Invented v2 chain after first capability expiry.")
    _, refused = editor.action(case, "approve_media_revision", dict(approval, expected_check_completion_sha256="0"*64), actor=candidate.PUBLISHER, at=at)
    assert refused["status"] == "rejected" and case["store"].read() == state
    _, parked = editor.action(case, "approve_media_revision", approval, actor=candidate.PUBLISHER, at=at)
    assert parked["status"] == "applied" and editor.view(case, now=at)["parked"]
    assert stage_rows(core[3], identity) == caps
    expired = editor.view(case, now=utc_datetime(caps[-1][4]))
    assert expired["checks_status"] != "passed" and not expired["parked"]
    with case["store"].projections._connection() as c:
        with pytest.raises((CommandError, checks.checks.CheckJournalError)):
            editor.domain.completed(c, identity, packet, utc_datetime(caps[-1][4]), "local")


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_same_owner_initial_cap_race_and_unused_cap_cannot_renew(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    original = stages.apply
    observed = []

    def stop(c, action, payload, **kwargs):
        if action == "begin":
            observed.append(payload.copy())
            raise RuntimeError("invented stop after committed capability")
        return original(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", stop)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(lambda _: editor.run_revision(case, command, packet, "deterministic"), range(2)))
        assert all(report["outcome"] == "reconciliation_required" for report in reports)
        caps = stage_rows(core[3], identity)
        assert len(caps) == 1 and len(observed) == 2
        assert observed[0]["fence"] == observed[1]["fence"] == 1
        assert observed[0]["owner"] == observed[1]["owner"]
        editor.run_revision(case, command, packet, "deterministic")
        assert stage_rows(core[3], identity) == caps
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s", (identity,)) == [(0,)]
    before = editor.all_application_rows(core[3])
    report = editor.run_revision(case, command, packet, "deterministic", clock=lambda: caps[0][4])
    assert not report["required_checks_completed"] and report["outcome"] != "completed"
    assert editor.all_application_rows(core[3]) == before


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_same_owner_successor_cap_race_cannot_rotate_without_attempt(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    original = stages.apply
    payloads = []

    def stop(c, action, payload, **kwargs):
        if action == "begin":
            payloads.append(payload.copy())
            raise RuntimeError("invented stop before successor attempt")
        return original(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", stop)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(lambda _: editor.run_revision(case, command, packet, "safety"), range(2)))
        assert all(report["outcome"] == "reconciliation_required" for report in reports)
        caps = stage_rows(core[3], identity)
        assert [cap[0] for cap in caps] == ["deterministic", "safety"]
        assert len(payloads) == 2 and all(payload["fence"] == 2 for payload in payloads)
        editor.run_revision(case, command, packet, "safety")
        assert stage_rows(core[3], identity) == caps
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s", (identity,)) == [(1,)]
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: editor.run_revision(case, command, packet, "safety"), range(2)))
    assert len(sent) == 1 and any(result["outcome"] == "completed" for result in reports), reports
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='safety'", (identity,)) == [(1,)]


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("corruption", ["prefix", "before_completion", "at_predecessor_expiry", "future_start"])
def test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor(
    admitted, core, monkeypatch, corruption
):
    import psycopg

    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1, offsets=[10]*4)
    current_at = editor.AT+timedelta(seconds=10)
    original_apply = stages.apply
    stopped = []

    def stop_before_attempt(c, action, payload, **kwargs):
        if action == "begin":
            stopped.append(payload["stage"])
            raise RuntimeError("invented interruption after successor capability commit")
        return original_apply(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", stop_before_attempt)
        interrupted = editor.run_revision(case, command, packet, "safety", clock=lambda: utc_text(current_at))
    assert interrupted["outcome"] == "reconciliation_required" and stopped == ["safety"]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='safety'", (identity,)) == [(0,)]
    # A damaged restore can retain a valid artifact and a self-consistent cap
    # hash while rebinding the still-unused successor to the wrong prefix. No
    # passing result is fabricated; the real deterministic predecessor remains.
    with psycopg.connect(**dict(core[3], autocommit=False)) as c:
        cap = stages.lease(c, identity, 2)
        assert cap is not None and cap["stage"] == "safety"
        wrong = c.execute("SELECT predecessor_prefix_sha256 FROM theheat_checks.stage_leases WHERE check_set_id=%s AND stage='deterministic'", (identity,)).fetchone()[0]
        raw = c.execute("SELECT payload FROM theheat_checks.stage_proof_artifacts WHERE sha=%s", (wrong,)).fetchone()[0]
        assert p._sha(raw) == wrong and wrong != cap["predecessor_prefix_sha256"]
        assert p._decode(raw)["stages"] == []
        body = {key: value for key, value in cap.items() if key != "capability_id"}
        if corruption == "prefix":
            body["predecessor_prefix_sha256"] = wrong
        elif corruption == "before_completion":
            completed = c.execute("SELECT completed_at FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage='deterministic'", (identity,)).fetchone()[0]
            body["recorded_at"] = utc_text(utc_datetime(completed)-timedelta(microseconds=1))
        elif corruption == "at_predecessor_expiry":
            body["recorded_at"] = c.execute("SELECT expires_at FROM theheat_checks.stage_leases WHERE check_set_id=%s AND stage='deterministic'", (identity,)).fetchone()[0]
            current_at = utc_datetime(body["recorded_at"])
        else:
            body["recorded_at"] = utc_text(current_at+timedelta(seconds=1))
        body["expires_at"] = utc_text(min(utc_datetime(body["recorded_at"])+timedelta(seconds=180), utc_datetime(packet["useful_until"])))
        assert packet["captured_at"] <= body["recorded_at"] < body["expires_at"] <= packet["useful_until"]
        assert utc_datetime(body["expires_at"])-utc_datetime(body["recorded_at"]) == timedelta(seconds=180)
        changed_id = fingerprint(body)
        assert changed_id != cap["capability_id"]
        c.execute("SET LOCAL session_replication_role='replica'")
        c.execute("UPDATE theheat_checks.stage_leases SET predecessor_prefix_sha256=%s,recorded_at=%s,expires_at=%s,capability_id=%s WHERE check_set_id=%s AND stage='safety'", (body["predecessor_prefix_sha256"], body["recorded_at"], body["expires_at"], changed_id, identity))
    corrupted = editor.all_application_rows(core[3])
    corrupted_caps = stage_rows(core[3], identity)
    assert len(corrupted_caps) == 2 and corrupted_caps[-1][-1] == changed_id
    money = case["store"].spending("status", {}, now=utc_text(current_at))
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    for at in (utc_text(current_at), utc_text(current_at), body["expires_at"]):
        report = editor.run_revision(case, command, packet, "safety", clock=lambda: at)
        assert report["outcome"] == "reconciliation_required" and not report["required_checks_completed"], report
        assert sent == []
        assert editor.all_application_rows(core[3]) == corrupted
        assert stage_rows(core[3], identity) == corrupted_caps
        assert case["store"].spending("status", {}, now=utc_text(current_at)) == money
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='safety'", (identity,)) == [(0,)]


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_predecessor_expiring_during_real_prefix_work_rolls_back_successor(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    initial = stage_rows(core[3], identity)
    expiry = utc_datetime(initial[0][4])
    current, advanced = [expiry - timedelta(microseconds=1)], []
    before = editor.all_application_rows(core[3])
    original = stages._verify_prefix
    original_acquire = stages.acquire
    acquiring = []

    def acquire(*args, **kwargs):
        acquiring.append(True)
        try:
            return original_acquire(*args, **kwargs)
        finally:
            acquiring.pop()

    def verify(*args, **kwargs):
        value = original(*args, **kwargs)
        if acquiring:
            advanced.append(True)
            current[0] = expiry
        return value

    with monkeypatch.context() as patch:
        patch.setattr(stages, "_verify_prefix", verify)
        patch.setattr(stages, "acquire", acquire)
        report = editor.run_revision(case, command, packet, "safety", clock=lambda: utc_text(current[0]))
    assert advanced and report["outcome"] != "completed", report
    assert stage_rows(core[3], identity) == initial
    assert editor.all_application_rows(core[3]) == before


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_first_cap_issuance_uses_postproof_clock_and_reuse_never_refreshes_it(
    admitted, core, monkeypatch
):
    case = admitted
    command, identity, packet = begin_case(case)
    sent = pass_prefix(case, command, packet, monkeypatch, count=1)
    predecessor = stage_rows(core[3], identity)[0]
    original_verify, original_acquire, original_apply = stages._verify_prefix, stages.acquire, stages.apply
    current = [editor.AT]
    acquiring: list[bool] = []
    advanced: list[bool] = []

    def acquire(*args, **kwargs):
        acquiring.append(True)
        try:
            return original_acquire(*args, **kwargs)
        finally:
            acquiring.pop()

    def verify(*args, **kwargs):
        value = original_verify(*args, **kwargs)
        if acquiring and not advanced:
            current[0] = editor.AT+timedelta(seconds=30)
            advanced.append(True)
        return value

    def stop(c, action, payload, **kwargs):
        if action == "begin":
            raise RuntimeError("invented stop after original postproof issuance")
        return original_apply(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "acquire", acquire)
        patch.setattr(stages, "_verify_prefix", verify)
        patch.setattr(stages, "apply", stop)
        result = editor.run_revision(case, command, packet, "safety", clock=lambda: utc_text(current[0]))
        assert result["outcome"] == "reconciliation_required" and advanced == [True]
        caps = stage_rows(core[3], identity)
        assert len(caps) == 2 and caps[0] == predecessor
        assert caps[1][3] == utc_text(editor.AT+timedelta(seconds=30))
        assert caps[1][4] == min(utc_text(editor.AT+timedelta(seconds=210)), packet["useful_until"])
        assert caps[1][3] < predecessor[4]
        current[0] = editor.AT+timedelta(seconds=40)
        result = editor.run_revision(case, command, packet, "safety", clock=lambda: utc_text(current[0]))
        assert result["outcome"] == "reconciliation_required"
        assert stage_rows(core[3], identity) == caps
    assert sent == []
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s AND stage='safety'", (identity,)) == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents WHERE intent_id=%s", ("media-"+packet["enrollment_id"][:12]+"-safety",)) == [(0,)]


@pytest.mark.revision_check_protocol(1)
@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_catalog4_never_adopts_unused_legacy_semantic_enrollment(admitted, core):
    case = admitted
    editor.prepare_and_attach(case)
    command, identity, packet = editor.request_revision(case)
    before = editor.all_application_rows(core[3])
    core[2].initialize_stage_revision_checks(now=editor.AT)
    assert_protocol(case["store"], identity, 1)
    _, repeated, repeated_packet = editor.request_revision(case)
    assert repeated == identity and repeated_packet == packet
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets WHERE draft_enrollment_id=%s", (packet["enrollment_id"],)) == [(1,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_leases") == [(0,)]
    assert retained(case, identity)["attempts"] == {}
    after = editor.all_application_rows(core[3])
    for key, rows in before.items():
        if key == ("theheat_checks", "sets"):
            assert rows == [row[:-3] for row in after[key]]
        elif key == ("theheat_checks", "schema_upgrades"):
            assert rows == after[key][:1]
        elif key[0] not in {"theheat_commands"}:
            assert rows == after[key]
    assert case["store"].result(command.command_id)["status"] == "unchanged"


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_prefix_missing_corrupt_and_late_evidence_never_grants_readiness(admitted, core, monkeypatch):
    import psycopg

    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch)
    caps = stage_rows(core[3], identity)
    saved = retained(case, identity)
    grant = saved["attempts"]["safety"]["grant_id"]
    seal = admin(core[3], "SELECT prefix_sha256 FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage='safety'", (identity,))[0][0]
    cases = [
        ("missing raw", "DELETE FROM theheat_check_executions.raw_artifacts WHERE sha=(SELECT raw_sha256 FROM theheat_check_executions.observations WHERE grant_id=%s)", (grant,)),
        ("missing observation", "DELETE FROM theheat_check_executions.observations WHERE grant_id=%s", (grant,)),
        ("incomplete observation", None, ()),
        ("changed raw reference", "UPDATE theheat_check_executions.observations SET raw_sha256=%s WHERE grant_id=%s", ("0"*64, grant)),
        ("missing receipt", "DELETE FROM theheat_checks.receipts WHERE grant_id=%s", (grant,)),
        ("missing seal", "DELETE FROM theheat_checks.stage_seals WHERE grant_id=%s", (grant,)),
        ("missing cap", "DELETE FROM theheat_checks.stage_leases WHERE check_set_id=%s AND stage='safety'", (identity,)),
        ("missing prefix", "DELETE FROM theheat_checks.stage_proof_artifacts WHERE sha=%s", (seal,)),
        ("missing request", "DELETE FROM theheat_checks.request_artifacts WHERE sha=%s", (saved["attempts"]["safety"]["binding"]["request_sha256"],)),
        ("changed request reference", "UPDATE theheat_checks.attempts SET request_sha256=%s WHERE grant_id=%s", ("0"*64, grant)),
        ("late observation", "UPDATE theheat_check_executions.observations SET recorded_at=%s WHERE grant_id=%s", (caps[1][4], grant)),
        ("early observation", "UPDATE theheat_check_executions.observations SET recorded_at=%s WHERE grant_id=%s", (utc_text(editor.AT-timedelta(microseconds=1)), grant)),
        ("late receipt", "UPDATE theheat_checks.receipts SET recorded_at=%s WHERE grant_id=%s", (caps[1][4], grant)),
        ("late seal", "UPDATE theheat_checks.stage_seals SET completed_at=%s WHERE grant_id=%s", (caps[1][4], grant)),
        ("nonpass disposition", "UPDATE theheat_checks.receipts SET disposition='rejected' WHERE grant_id=%s", (grant,)),
        ("unresolved", "DELETE FROM theheat_checks.receipts WHERE grant_id=%s", (grant,)),
        ("wrong original dispatch", "UPDATE theheat_spending.events SET recorded_at=%s WHERE intent_id=%s AND kind='dispatched'", (utc_text(editor.AT+timedelta(microseconds=1)), saved["attempts"]["safety"]["intent_id"])),
        ("wrong seal hash", "UPDATE theheat_checks.stage_seals SET receipt_sha256=%s WHERE grant_id=%s", ("0"*64, grant)),
        ("wrong prefix hash", "UPDATE theheat_checks.stage_seals SET prefix_sha256=%s WHERE grant_id=%s", ("0"*64, grant)),
    ]
    before = editor.all_application_rows(core[3])
    for label, sql, values in cases:
        with psycopg.connect(**dict(core[3], autocommit=False)) as c:
            c.execute("SET LOCAL session_replication_role='replica'")
            if label == "incomplete observation":
                metadata = dict(saved["attempts"]["safety"]["observation"], complete=False, reason="transport_unavailable", http_status=None)
                encoded = canonical_json(metadata).encode()
                c.execute("INSERT INTO theheat_check_executions.metadata_artifacts VALUES(%s,%s,%s)", (p._sha(encoded), encoded, len(encoded)))
                c.execute("UPDATE theheat_check_executions.observations SET metadata_sha256=%s WHERE grant_id=%s", (p._sha(encoded), grant))
            else:
                c.execute(sql, values)
            # An owner-corrupted restore is deliberately outside the normal
            # write API. Real readers must refute it even with unchanged DDL.
            with pytest.raises(Exception) as caught:
                stages.completion(c, identity, packet, editor.AT, "local")
            assert caught.value is not None, label
            c.rollback()
        assert editor.all_application_rows(core[3]) == before, label


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_scope_is_connection_bound_and_untrusted_inputs_cannot_mint_cap(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    owner = "revision-checks:" + packet["enrollment_id"]
    before = editor.all_application_rows(core[3])
    with case["store"].projections._connection(writing=True) as c:
        version, state = case["store"]._state(c, lock=True)
        assert version == packet["state_version"] and state == packet["checker_state"]
        expected = stages.progression(c, identity, packet, "local")
        scope = stages._scope(c, identity, owner, lambda: utc_text(editor.AT), expected)
        with case["store"].projections._connection() as other:
            for bad in (None, {}, {"authority_protocol": 2, "scope": scope}, scope):
                with pytest.raises(checks.checks.CheckJournalError, match="scoped_revision_context_required"):
                    stages.acquire(other, identity, owner, 180, now=utc_text(editor.AT), environment="local", scope=bad)
        for foreign in ("wrong-owner", owner + ":foreign"):
            with pytest.raises(checks.checks.CheckJournalError):
                stages.acquire(c, identity, foreign, 180, now=utc_text(editor.AT), environment="local", scope=scope)
        scope.close()
        with pytest.raises(checks.checks.CheckJournalError, match="scoped_revision_context_required"):
            stages.acquire(c, identity, owner, 180, now=utc_text(editor.AT), environment="local", scope=scope)
    assert editor.all_application_rows(core[3]) == before
    pass_prefix(case, command, packet, monkeypatch, count=1)
    with case["store"].projections._connection(writing=True) as c:
        case["store"]._state(c, lock=True)
        scope = stages._scope(c, identity, owner, lambda: utc_text(editor.AT), expected)
        with pytest.raises(checks.checks.CheckJournalError, match="revision_check_progressed"):
            stages.acquire(c, identity, owner, 180, now=utc_text(editor.AT), environment="local", scope=scope)
        scope.close()
    assert len(stage_rows(core[3], identity)) == 1


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_exact_terminal_replay_is_history_and_cannot_reseal_corruption(admitted, core, monkeypatch):
    import psycopg

    case = admitted
    command, identity, packet = begin_case(case)
    sent = pass_prefix(case, command, packet, monkeypatch, count=2)
    attempt = retained(case, identity)["attempts"]["safety"]
    payload = dict(generic_payload(identity, packet, 2), stage="safety", grant_id=attempt["grant_id"])
    before = editor.all_application_rows(core[3])
    with case["store"].projections._connection(writing=True) as c:
        case["store"]._state(c, lock=True)
        receipt = checks._terminal(c, attempt)["document"]
        scope = stages._scope(c, identity, payload["owner"], lambda: utc_text(editor.AT), stages.progression(c, identity, packet, "local"))
        result = stages.apply(c, "complete", payload, now=utc_text(editor.AT), environment="local", receipt=receipt, scope=scope)
        assert result["reused"] is True and not result["publication_approved"]
        with pytest.raises(checks.checks.CheckJournalError, match="conflicting_check_completion"):
            stages.apply(c, "complete", payload, now=utc_text(editor.AT), environment="local", receipt=dict(receipt, result={"invented": True}), scope=scope)
        scope.close()
    assert editor.all_application_rows(core[3]) == before
    # Simulate an incomplete/corrupt restored database with a real retained
    # terminal receipt but no matching seal. Recovery may not manufacture it.
    with psycopg.connect(**dict(core[3], autocommit=False)) as c:
        c.execute("SET LOCAL session_replication_role='replica'")
        c.execute("DELETE FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage='safety'", (identity,))
    corrupt = editor.all_application_rows(core[3])
    report = editor.run_revision(case, command, packet, "fact_check")
    assert report["outcome"] == "reconciliation_required" and len(sent) == 1
    assert editor.all_application_rows(core[3]) == corrupt
    assert retained(case, identity)["attempts"]["safety"]["observation"] == attempt["observation"]
    assert_unknown(case)


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("drift", ["source", "role", "policy", "renderer"])
@pytest.mark.parametrize("boundary", ["before_lock", "during_prefix"])
def test_v2_current_authority_drift_cannot_create_successor(
    admitted, core, monkeypatch, drift, boundary
):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    before = editor.all_application_rows(core[3])
    inputs = list(case["config"]["current_inputs"])
    revoked: list[bool] = []
    changed = []
    original = stages._verify_prefix
    original_profile = editor.domain.profile

    def resolve(subject):
        return None if revoked and subject == candidate.EDITOR.subject else candidate.resolve(subject)

    def change(patch):
        changed.append(True)
        if drift == "source":
            case["config"]["current_inputs"].clear()
        elif drift == "role":
            revoked.append(True)
        elif drift == "policy":
            patch.setenv("THEHEAT_WRITER_SAMPLES", "3")
        else:
            patch.setattr(editor.domain, "profile", lambda *args: ("e"*64, original_profile(*args)[1]))

    try:
        with monkeypatch.context() as patch:
            def verify(*args, **kwargs):
                result = original(*args, **kwargs)
                if not changed:
                    change(patch)
                return result
            if boundary == "before_lock":
                change(patch)
            else:
                patch.setattr(stages, "_verify_prefix", verify)
            try:
                report = editor.run_revision(case, command, packet, "safety", resolve=resolve)
            except (CommandError, checks.checks.CheckJournalError):
                report = None
            assert changed
            assert report is None or report["outcome"] != "completed", report
    finally:
        case["config"]["current_inputs"][:] = inputs
    assert editor.all_application_rows(core[3]) == before


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_exact_reservation_request_and_stage_are_required_before_dispatch(admitted, core, monkeypatch):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    original_apply = stages.apply
    captured = []

    def inspect(c, action, payload, **kwargs):
        if action == "begin":
            captured.append((payload, kwargs))
            raise RuntimeError("invented stop after safety cap")
        return original_apply(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", inspect)
        assert editor.run_revision(case, command, packet, "safety")["outcome"] == "reconciliation_required"
    payload, kwargs = captured[0]
    before = editor.all_application_rows(core[3])
    for field, wrong in (("provider", "anthropic"), ("model", "invented-wrong"), ("role", "critic"),
                         ("job_id", "wrong-spending-job"), ("request_sha256", "0"*64)):
        with case["store"].projections._connection(writing=True) as c:
            case["store"]._state(c, lock=True)
            scope = stages._scope(c, identity, payload["owner"], lambda: utc_text(editor.AT), stages.progression(c, identity, packet, "local"))
            bad = dict(payload, reservation=dict(payload["reservation"], **{field: wrong}))
            with pytest.raises((checks.checks.CheckJournalError, SpendError)):
                original_apply(c, "begin", bad, now=utc_text(editor.AT), environment="local", request=kwargs["request"], scope=scope)
            scope.close()
        assert editor.all_application_rows(core[3]) == before
    for delta in ({"stage": "critic"}, {"owner": "foreign"}, {"fence": 1}, {"passed": True}):
        with case["store"].projections._connection(writing=True) as c:
            case["store"]._state(c, lock=True)
            scope = stages._scope(c, identity, payload["owner"], lambda: utc_text(editor.AT), stages.progression(c, identity, packet, "local"))
            with pytest.raises(checks.checks.CheckJournalError):
                original_apply(c, "begin", dict(payload, **delta), now=utc_text(editor.AT), environment="local", request=kwargs["request"], scope=scope)
            scope.close()
        assert editor.all_application_rows(core[3]) == before
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s", (identity,)) == [(1,)]


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("response", ["reject", "malformed", "unavailable", "truncated"])
def test_v2_nonpass_raw_is_terminal_and_cannot_rotate_or_resend(admitted, core, monkeypatch, response):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    raw = {
        "reject": executor.envelope("YES"),
        "malformed": b"{not a provider envelope",
        "unavailable": (503, b"invented unavailable"),
        "truncated": executor.envelope("NO", candidates=[dict(content=dict(role="model", parts=[dict(text="NO")]), finishReason="MAX_TOKENS", index=0)]),
    }[response]
    sent, _ = executor.provider(monkeypatch, [raw])
    report = editor.run_revision(case, command, packet, "safety")
    assert report["outcome"] == "completed" and report["checks"]["stages"]["safety"] != "passed", report
    assert len(sent) == 1
    saved = retained(case, identity)
    assert saved["attempts"]["safety"]["observation"] is not None
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,)) == [(1,)]
    before = editor.all_application_rows(core[3])
    replay = editor.run_revision(case, command, packet, "safety")
    assert replay["outcome"] != "completed" and not replay["required_checks_completed"]
    assert len(sent) == 1 and editor.all_application_rows(core[3]) == before
    assert_unknown(case)


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("boundary", ["preflight", "postgrant"])
@pytest.mark.parametrize("microseconds", [0, 1])
def test_v2_strict_request_window_equality_and_one_microsecond(
    admitted, core, monkeypatch, boundary, microseconds
):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    original = stages.apply
    with monkeypatch.context() as patch:
        def stop(c, action, payload, **kwargs):
            if action == "begin":
                raise RuntimeError("invented unused safety capability")
            return original(c, action, payload, **kwargs)
        patch.setattr(stages, "apply", stop)
        assert editor.run_revision(case, command, packet, "safety")["outcome"] == "reconciliation_required"
    cap = stage_rows(core[3], identity)[-1]
    assert cap[0] == "safety" and utc_datetime(cap[4])-utc_datetime(cap[3]) == timedelta(seconds=180)
    threshold = utc_datetime(cap[4])-timedelta(seconds=120)+timedelta(microseconds=-microseconds)
    current = [threshold if boundary == "preflight" else editor.AT]
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    with monkeypatch.context() as patch:
        def advance(c, action, payload, **kwargs):
            value = original(c, action, payload, **kwargs)
            if action == "begin":
                current[0] = threshold
            return value
        if boundary == "postgrant":
            patch.setattr(stages, "apply", advance)
        report = editor.run_revision(case, command, packet, "safety", clock=lambda: utc_text(current[0]))
    assert len(sent) == microseconds, report
    if microseconds:
        assert report["outcome"] == "completed" and report["checks"]["stages"]["safety"] == "passed"
    else:
        assert report["reason"] == ("insufficient_check_window" if boundary == "preflight" else "check_window_changed_before_execution")
        saved = retained(case, identity, at=threshold)
        assert ("safety" in saved["attempts"]) is (boundary == "postgrant")
        if boundary == "postgrant":
            assert saved["attempts"]["safety"]["observation"] is None
            assert_unknown(case, at=threshold)
    assert stage_rows(core[3], identity)[-1] == cap


@pytest.mark.parametrize("expired", [False, True])
def test_v2_explicit_sdk_original_raw_recovery_has_no_second_request(
    radar_case, core, monkeypatch, expired
):
    import httpx
    from src.two_bot import check_executor, check_transport, check_requests
    from src.two_bot.check_origin import spending_job

    case = radar_case
    published.attach(case)
    command, identity, packet = editor.request_revision(case)
    assert_protocol(case["store"], identity)
    store = case["store"]
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(check_executor, "GoogleCheckTransport", check_transport.GoogleCheckTransport)
    sent, current = [], [editor.AT]

    def respond(request):
        sent.append(request.content)
        assert request.method == "POST" and request.url.host == "generativelanguage.googleapis.com"
        return httpx.Response(200, stream=httpx.ByteStream(executor.envelope("NO")))

    def run(reservation=None, capability=None, enabled=True):
        return store.execute_revision_check_once(command.command_id, candidate.resolve,
            clock=lambda: utc_text(current[0]), reservation=reservation, enabled=enabled, transport_options=capability)

    class Unreadable(dict):
        def __iter__(self):
            raise AssertionError("Disabled/deterministic/passive inspected transport")

    assert run(capability=Unreadable(), enabled=False)["outcome"] == "disabled"
    assert run(capability=Unreadable())["checks"]["stages"]["deterministic"] == "passed"
    raw = canonical_json(check_requests.prepare_request(packet, "safety")).encode()
    reservation = dict(intent_id="explicit-v2-safety", job_id=spending_job(packet), request_sha256=p._sha(raw),
        provider="google", role="safety", model=packet["policy"]["models"]["safety"], estimate_sha256="e"*64, reserve_micro_usd=5)
    assert run(reservation, dict(api_key="invented", http_transport=object()))["reason"] == "invalid_check_transport_options"
    assert sent == []
    original = stages.apply

    def fail_terminal(c, action, payload, **kwargs):
        if action == "complete":
            raise CommandError("invented_after_raw", "Invented interruption after original raw")
        return original(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", fail_terminal)
        interrupted = run(reservation, dict(api_key="invented-explicit", http_transport=httpx.MockTransport(respond)))
        assert interrupted["outcome"] == "reconciliation_required"
    caps = stage_rows(core[3], identity)
    saved = retained(case, identity)
    attempt = saved["attempts"]["safety"]
    assert attempt["observation"]["complete"] and len(sent) == 1
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,)) == [(1,)]
    assert_unknown(case)
    if expired:
        current[0] = utc_datetime(caps[-1][4])
    recovered = run(reservation, Unreadable())
    assert stage_rows(core[3], identity) == caps and len(sent) == 1
    if expired:
        assert recovered["outcome"] != "completed" and not recovered["required_checks_completed"]
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.receipts WHERE grant_id=%s", (attempt["grant_id"],)) == [(0,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,)) == [(1,)]
    else:
        assert recovered["outcome"] == "completed" and recovered["checks"]["stages"]["safety"] == "passed"
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.receipts WHERE grant_id=%s", (attempt["grant_id"],)) == [(1,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s", (identity,)) == [(2,)]
    assert_unknown(case, at=current[0])


@pytest.mark.parametrize("field", ["checks_metadata", "observations_metadata"])
def test_catalog4_receipt_nested_numeric_metadata_is_byte_exact(store, core, field):
    import psycopg

    core[2].initialize_stage_revision_checks(now=catalog.NOW)
    before = editor.all_application_rows(core[3])
    with psycopg.connect(**dict(core[3], autocommit=False)) as c:
        c.execute("SET LOCAL session_replication_role='replica'")
        raw = c.execute("SELECT receipt_bytes FROM theheat_checks.schema_upgrades WHERE upgrade_version=4").fetchone()[0]
        value = p._decode(raw)
        assert type(value[field]["version"]) is int and value[field]["version"] == 1
        value[field]["version"] = 1.0
        changed = canonical_json(value).encode()
        assert changed != raw
        c.execute("UPDATE theheat_checks.schema_upgrades SET receipt_bytes=%s,byte_count=%s,sha=%s WHERE upgrade_version=4", (changed, len(changed), p._sha(changed)))
        with pytest.raises(checks.checks.CheckJournalError):
            checks.validate(c, "local")
        c.rollback()
    assert editor.all_application_rows(core[3]) == before


def test_v2_published_frame_minimum_bounds_every_cap_and_final_readiness(radar_case, core, monkeypatch):
    case = radar_case
    published.attach(case)
    command, identity, packet = editor.request_revision(case)
    assert_protocol(case["store"], identity)
    # Real source/frame constraints, unchanged clocks/window calculations: each
    # stage starts with >120s, while the original frame truncates its 180s cap.
    remaining = (utc_datetime(packet["useful_until"])-editor.AT).total_seconds()
    offsets = [remaining-150+i*5 for i in range(4)]
    sent = pass_prefix(case, command, packet, monkeypatch, offsets=offsets)
    caps = stage_rows(core[3], identity)
    assert len(caps) == 4 and len(sent) == 3
    assert all(cap[4] == packet["useful_until"] for cap in caps)
    assert all(120 < (utc_datetime(cap[4])-utc_datetime(cap[3])).total_seconds() < 180 for cap in caps)
    now = utc_datetime(packet["useful_until"])-timedelta(microseconds=1)
    with case["store"].projections._connection() as c:
        proof = stages.completion(c, identity, packet, now, "local")
        assert proof["authority_protocol"] == 2 and proof["final_ready_until"] == packet["useful_until"]
        with pytest.raises(checks.checks.CheckJournalError):
            stages.completion(c, identity, packet, utc_datetime(packet["useful_until"]), "local")
    before = editor.all_application_rows(core[3])
    next_day = editor.AT.replace(hour=0, minute=0, second=0)+timedelta(days=1)
    with pytest.raises(CommandError):
        editor.run_revision(case, command, packet, "critic", clock=lambda: utc_text(next_day))
    assert editor.all_application_rows(core[3]) == before


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_v2_full_park_restore_keeps_legacy_sets_and_exact_protocol_chain(admitted, core, cluster, monkeypatch):
    # The existing journey drives native preparation, four real offline checks,
    # approval, actual pg_dump/restore, replay and edit/outage invalidation.
    editor.park_dump_restore_journey(admitted, monkeypatch, core, cluster)
    sets = admin(core[3], "SELECT check_set_id,authority_protocol,origin_kind FROM theheat_checks.sets ORDER BY 1")
    assert any(row[1] == 1 and row[2] == "batch_candidate" for row in sets)
    revisions = [row for row in sets if row[2] == "saved_draft_revision_v1"]
    assert revisions and all(row[1] == 2 for row in revisions)
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals") == [(4,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.draft_leases") == [(0,)]


def test_v2_genuine_park_one_use_delivery_and_passive_original_cap_cost(
    radar_case, core, tmp_path, monkeypatch
):
    from src.commands import postgres_cost_projection as cost, postgres_delivery
    from tests.local_delivery_helpers import fixture_server
    from tests.test_postgres_cost_projection import passive_traps

    case = radar_case
    prepared, _ = published.attach(case)
    png = editor.view(case, png=prepared["preparation"]["proposal_sha256"])
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        delivery.configure(case["store"], tmp_path, config)
        delivery.bind_platform(case, monkeypatch)
        current = editor.view(case)
        identity = current["check_set_id"]
        assert_protocol(case["store"], identity)
        caps = stage_rows(core[3], identity)
        command, parked = delivery.park(case)
        assert parked["status"] == "applied" and editor.view(case)["parked"]
        intent = parked["delivery"]["intent_id"]
        assert case["store"].consume(candidate.resolve, command_id=command.command_id, now=editor.AT) == parked
        before_send = editor.all_application_rows(core[3])
        expired = delivery.run(case, intent, "x", "upload", at=utc_datetime(caps[-1][4]))
        assert expired["outcome"] != "confirmed" and expired["network_mutation"] is False
        assert trace == [] and not accepted and editor.all_application_rows(core[3]) == before_send
        for platform, phases in postgres_delivery.STAGES.items():
            for phase in phases:
                result = delivery.run(case, intent, platform, phase)
                assert result["outcome"] == "confirmed", result
                replay = delivery.run(case, intent, platform, phase)
                assert replay["outcome"] == "confirmed" and replay["network_mutation"] is False
        assert len(trace) == len(accepted) == 5
        before = editor.all_application_rows(core[3])
        with monkeypatch.context() as patch:
            passive_traps(patch)
            def forbidden(*args, **kwargs):
                pytest.fail("Passive cost called active protocol2 authority")
            for name in ("_verify_prefix", "apply", "acquire", "completion"):
                patch.setattr(stages, name, forbidden)
            value = case["store"].local_cost_projection(now=editor.AT+timedelta(days=100))
        assert value["status"] == "available", value
        requests = [row for row in value["requests"] if row["origin"]["check_set_id"] == identity]
        assert len(requests) == 3 and all(row["origin"]["raw_sha256"] for row in requests)
        assert all(row["recorded_settlement_micro_usd"] is None for row in requests)
        assert editor.all_application_rows(core[3]) == before and stage_rows(core[3], identity) == caps
        historical = delivery.run(case, intent, "x", "upload", at=utc_datetime(caps[-1][4]))
        assert historical["outcome"] == "confirmed" and historical["network_mutation"] is False
        assert len(trace) == 5
        # Independently wrong original cap evidence must not become a zero-cost
        # display. The helper changes only selected readback, never live tables.
        original_execute = cost.Read.execute
        touched = []
        def wrong_cap(reader, query, params=None):
            cursor = original_execute(reader, query, params)
            if "FROM theheat_checks.stage_leases" in query and params and params[0] == identity:
                row = cursor.fetchone()
                touched.append(True)
                class Result:
                    def fetchone(self):
                        if row is None:
                            return None
                        wrong = list(row)
                        wrong[4] = "foreign-original-owner"
                        return tuple(wrong)
                return Result()
            return cursor
        with monkeypatch.context() as patch:
            patch.setattr(cost.Read, "execute", wrong_cap)
            invalid = case["store"].local_cost_projection(now=editor.AT)
        assert touched and invalid["status"] == "unavailable", invalid
        assert editor.all_application_rows(core[3]) == before


def inject_transaction_fault(monkeypatch, identity, boundary, mode):
    """Interrupt a selected real fixture transaction, never emulate SQL writes."""
    import psycopg

    connect = psycopg.connect
    hit: list[str] = []
    writes = {
        "cap": "INSERT INTO theheat_checks.stage_leases",
        "hold": "INSERT INTO theheat_spending.intents",
        "attempt": "INSERT INTO theheat_checks.attempts",
        "raw": "INSERT INTO theheat_check_executions.raw_artifacts",
        "receipt": "INSERT INTO theheat_checks.receipts",
        "seal": "INSERT INTO theheat_checks.stage_seals",
        "prefix": "INSERT INTO theheat_checks.stage_proof_artifacts",
    }

    class Connection:
        def __init__(self, connection):
            self.connection, self.selected = connection, False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def has_safety(self, table):
            return self.connection.execute(f"SELECT 1 FROM {table} WHERE check_set_id=%s AND stage='safety'", (identity,)).fetchone() is not None

        def execute(self, query, *args, **kwargs):
            cursor = self.connection.execute(query, *args, **kwargs)
            text = str(query)
            selected = not hit and boundary in writes and text.startswith(writes[boundary])
            # A prefix is also written while acquiring a cap. This fault is the
            # completion prefix after the real terminal receipt was inserted.
            if selected and boundary == "prefix":
                selected = self.connection.execute("SELECT 1 FROM theheat_checks.receipts r JOIN theheat_checks.attempts a USING(grant_id) WHERE a.check_set_id=%s AND a.stage='safety'", (identity,)).fetchone() is not None
            if selected:
                hit.append(boundary)
                self.selected = True
                if mode == "raise":
                    raise RuntimeError("invented selected transaction interruption")
                if mode == "kill":
                    self.connection.execute("SELECT pg_terminate_backend(pg_backend_pid())")
            return cursor

        @contextmanager
        def transaction(self):
            with self.connection.transaction():
                yield
                if not hit and boundary == "final" and self.has_safety("theheat_checks.stage_seals"):
                    hit.append(boundary)
                    self.selected = True
                    if mode == "raise":
                        raise RuntimeError("invented selected transaction interruption")
                    if mode == "kill":
                        self.connection.execute("SELECT pg_terminate_backend(pg_backend_pid())")
            if self.selected and mode == "lost_ack":
                raise psycopg.OperationalError("invented selected commit acknowledgement lost")

    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: Connection(connect(**kwargs)))
    return hit


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("boundary", ["cap", "hold", "attempt", "raw", "receipt", "seal", "prefix", "final"])
@pytest.mark.parametrize("mode", ["raise", "kill", "lost_ack"])
def test_v2_transaction_interruptions_never_repurchase_or_repair_missing_seal(
    admitted, core, monkeypatch, boundary, mode
):
    case = admitted
    command, identity, packet = begin_case(case)
    pass_prefix(case, command, packet, monkeypatch, count=1)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    before = retained(case, identity)
    assert set(before["attempts"]) == {"deterministic"}
    with monkeypatch.context() as patch:
        hit = inject_transaction_fault(patch, identity, boundary, mode)
        report = editor.run_revision(case, command, packet, "safety")
    assert hit == [boundary] and report["outcome"] == "reconciliation_required", report
    saved = retained(case, identity)
    attempt = saved["attempts"].get("safety")
    cap_rows = stage_rows(core[3], identity)
    assert len(cap_rows) <= 2
    if boundary in {"cap", "hold", "attempt"}:
        assert sent == []
    else:
        assert len(sent) == 1
        assert attempt is not None
        assert_unknown(case)
        terminal = admin(core[3], "SELECT count(*) FROM theheat_checks.receipts WHERE grant_id=%s", (attempt["grant_id"],))[0][0]
        seals = admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage='safety'", (identity,))[0][0]
        assert terminal == seals == (1 if mode == "lost_ack" and boundary in {"receipt", "seal", "prefix", "final"} else 0)
    # After an uncertain grant the runner may observe history or finish the SAME
    # original live grant from retained raw; it may never buy that stage again.
    if attempt is not None:
        original_grant = attempt["grant_id"]
        count = len(sent)
        again = editor.run_revision(case, command, packet, "safety")
        assert len(sent) == count, again
        recovered = retained(case, identity)
        assert recovered["attempts"]["safety"]["grant_id"] == original_grant
        assert stage_rows(core[3], identity)[:len(cap_rows)] == cap_rows


@pytest.mark.parametrize("drift", ["frame_expired", "lease_expired", "clock_backward"])
def test_v2_completion_delay_rolls_back_critic_receipt_seal_keeps_raw_and_unknown_cost(
    radar_case, core, monkeypatch, drift
):
    case = radar_case
    published.attach(case)
    command, identity, packet = editor.request_revision(case)
    assert_protocol(case["store"], identity)
    sent = pass_prefix(case, command, packet, monkeypatch, count=3)
    original = stages.apply
    advanced, before, changed = [], [], []

    def apply(c, action, payload, **kwargs):
        if action == "complete" and payload.get("stage") == "critic":
            before.append(editor.all_application_rows(core[3]))
            value = original(c, action, payload, **kwargs)
            cap = c.execute("SELECT expires_at FROM theheat_checks.stage_leases WHERE check_set_id=%s AND stage='critic'", (identity,)).fetchone()[0]
            changed.append(packet["useful_until"] if drift == "frame_expired" else cap if drift == "lease_expired" else utc_text(editor.AT-timedelta(seconds=1)))
            advanced.append(True)
            return value
        return original(c, action, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stages, "apply", apply)
        report = editor.run_revision(case, command, packet, "critic", clock=lambda: changed[0] if advanced else utc_text(editor.AT))
    assert advanced and report["outcome"] == "reconciliation_required" and len(sent) == 3
    assert editor.all_application_rows(core[3]) == before[0]
    caps = stage_rows(core[3], identity)
    assert caps[-1][0] == "critic" and len(caps) == 4
    assert min(caps[-1][4], packet["useful_until"]) == caps[-1][4]
    attempt = retained(case, identity)["attempts"]["critic"]
    assert attempt["observation"]["complete"] is True
    raw = case["store"].read_check_response(identity, "critic", attempt["grant_id"])
    assert p._sha(raw) == attempt["observation"]["raw_sha256"]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.receipts WHERE grant_id=%s", (attempt["grant_id"],)) == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage='critic'", (identity,)) == [(0,)]
    assert_unknown(case)
    assert not editor.view(case)["parked"]


@pytest.mark.parametrize("drift", ["frame_expired", "lease_expired", "clock_backward"])
def test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park(
    radar_case, core, tmp_path, monkeypatch, drift
):
    from src.commands import postgres_authority as authority_module, postgres_delivery
    from tests.local_delivery_helpers import fixture_server

    case = radar_case
    prepared, _ = published.attach(case)
    png = editor.view(case, png=prepared["preparation"]["proposal_sha256"])
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        delivery.configure(case["store"], tmp_path, config)
        delivery.bind_platform(case, monkeypatch)
        current = editor.view(case)
        identity = current["check_set_id"]
        assert_protocol(case["store"], identity)
        packet = retained(case, identity)["packet"]
        caps = stage_rows(core[3], identity)
        critic_expiry = utc_datetime(caps[-1][4])
        assert caps[-1][0] == "critic" and len(caps) == 4
        assert editor.AT < critic_expiry < utc_datetime(packet["useful_until"])
        with case["store"].projections._connection() as c:
            proof = editor.domain.completed(c, identity, packet, editor.AT, "local")
        assert proof["authority_protocol"] == 2 and proof["final_ready_until"] == caps[-1][4]
        changed = utc_datetime(packet["useful_until"]) if drift == "frame_expired" else critic_expiry if drift == "lease_expired" else editor.AT-timedelta(seconds=1)
        draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
        command = Command.from_request(dict(command_id=str(uuid4()), action="approve_media_revision",
            requested_at=utc_text(editor.AT), expires_at=utc_text(editor.AT+timedelta(minutes=20)),
            targets=[editor._identity(draft)], payload=dict(
                **{key: current[key] for key in ("expected_policy_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256")},
                expected_packet_sha256=current["packet"]["packet_sha256"], reason="Invented protocol2 tail rollback.")),
            candidate.PUBLISHER, environment="local", now=editor.AT)
        case["store"].accept(command, candidate.PUBLISHER, now=editor.AT)
        before, state = editor.all_application_rows(core[3]), case["store"].read()
        original = postgres_delivery.enroll
        advanced = []

        def enroll(authority, c, value, resolve_principal, now, *, ghcn=None):
            enrolled = original(authority, c, value, resolve_principal, now, ghcn=ghcn)
            assert c.execute("SELECT count(*) FROM theheat_delivery.intents").fetchone()[0] == 1
            assert authority._result(c, command.command_id)["status"] == "applied"
            advanced.append(True)
            return enrolled

        with monkeypatch.context() as patch:
            patch.setattr(postgres_delivery, "enroll", enroll)
            patch.setattr(authority_module, "_clock", lambda now: changed if advanced else editor.AT)
            with pytest.raises(CommandError) as caught:
                case["store"].consume(candidate.resolve, command_id=command.command_id, now=editor.AT)
        assert caught.value.code == ("media_completion_clock_regressed" if drift == "clock_backward" else "media_completion_expired")
        assert advanced and editor.all_application_rows(core[3]) == before
        assert case["store"].read() == state and case["store"].result(command.command_id) is None
        assert admin(core[3], "SELECT count(*) FROM theheat_delivery.intents") == [(0,)]
        assert stage_rows(core[3], identity) == caps
        assert not editor.view(case)["parked"] and trace == [] and not accepted
        assert_unknown(case)


def assert_nonradar_approval_final_refusal(
    case, params, command_id, current, resolve, at, trace, accepted,
    monkeypatch, boundary, fault, *, source_file=None,
):
    """Fault a real approval after exact proof or after real outbox writes."""
    from src.commands import postgres_authority as authority_module, postgres_delivery

    authority = case["store"]
    identity = current["check_set_id"]
    assert_protocol(authority, identity)
    caps = stage_rows(params, identity)
    assert len(caps) == 4 and caps[-1][0] == "critic"
    critic_expiry = utc_datetime(caps[-1][4])
    assert at < critic_expiry
    with authority.projections._connection() as c:
        approving, _ = authority._intent(c, command_id)
        requesting, _ = authority._intent(c, current["check_command_id"])
    assert approving.actor_subject != requesting.actor_subject
    draft = next(row for row in authority.read()[1]["drafts"] if row["id"] == case["draft_id"])
    assert draft["type"] != "severe_weather"
    before, state = editor.all_application_rows(params), authority.read()
    raw = admin(params, "SELECT grant_id,raw_sha256 FROM theheat_check_executions.observations ORDER BY grant_id")
    assert len(raw) >= 4
    money = authority.spending("status", {}, now=utc_text(at))
    assert money["totals"]["held_micro_usd"] >= 5 and money["accounting_complete"] is False
    original_source = source_file.read_bytes() if source_file is not None else list(case["config"]["current_inputs"])
    original_verify, original_enroll = stages._verify_prefix, postgres_delivery.enroll
    original_clock = authority_module._clock
    armed: list[bool] = []

    def resolver(subject):
        denied = (fault == "editor" and subject == requesting.actor_subject
                  or fault == "publisher" and subject == approving.actor_subject)
        return None if armed and denied else resolve(subject)

    try:
        with monkeypatch.context() as patch:
            def drift():
                assert not armed
                armed.append(True)
                if fault == "source":
                    if source_file is None:
                        case["config"]["current_inputs"].clear()
                    else:
                        assert isinstance(original_source, bytes)
                        value = json.loads(original_source)
                        value["current_inputs"] = []
                        source_file.write_text(json.dumps(value))
                elif fault == "policy":
                    patch.setenv("THEHEAT_WRITER_SAMPLES", "3")

            def verify(*args, **kwargs):
                value = original_verify(*args, **kwargs)
                if kwargs.get("length") == 4 and not armed:
                    drift()
                return value

            def enroll(active, c, value, resolve_principal, now, *, ghcn=None):
                enrolled = original_enroll(active, c, value, resolve_principal, now, ghcn=ghcn)
                assert c.execute("SELECT count(*) FROM theheat_delivery.intents").fetchone()[0] == 1
                assert c.execute("SELECT count(*) FROM theheat_delivery.work_items").fetchone()[0] == 2
                assert active._result(c, command_id)["status"] == "applied"
                drift()
                return enrolled

            if boundary == "proof":
                patch.setattr(stages, "_verify_prefix", verify)
            else:
                patch.setattr(postgres_delivery, "enroll", enroll)
            patch.setattr(authority_module, "_clock", lambda now: critic_expiry if armed and fault == "expiry" else original_clock(now))
            with pytest.raises(CommandError) as refused:
                authority.consume(resolver, command_id=command_id, now=at)
            expected_code = {"expiry": "media_completion_expired", "source": "media_source_not_allowlisted",
                "editor": "forbidden", "publisher": "forbidden", "policy": "editorial_policy_changed"}[fault]
            if source_file is not None and boundary == "proof" and fault == "policy":
                expected_code = "ghcn_execution_context_changed"
            assert refused.value.code == expected_code and armed == [True]
    finally:
        if source_file is None:
            assert isinstance(original_source, list)
            case["config"]["current_inputs"][:] = original_source
        else:
            assert isinstance(original_source, bytes)
            source_file.write_bytes(original_source)
    assert editor.all_application_rows(params) == before
    assert authority.read() == state and authority.result(command_id) is None
    assert stage_rows(params, identity) == caps
    assert admin(params, "SELECT grant_id,raw_sha256 FROM theheat_check_executions.observations ORDER BY grant_id") == raw
    assert authority.spending("status", {}, now=utc_text(at)) == money
    assert admin(params, "SELECT count(*) FROM theheat_delivery.intents") == [(0,)]
    assert trace == [] and not accepted
    assert not next(row for row in authority.read()[1]["drafts"] if row["id"] == case["draft_id"]).get("approval_binding")
    return caps


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("boundary", ["proof", "outbox"])
@pytest.mark.parametrize("fault", ["expiry", "source", "editor", "publisher", "policy"])
def test_v2_modis_approval_final_bound_and_reauthorization_roll_back_all_writes(
    admitted, core, tmp_path, monkeypatch, boundary, fault
):
    from tests.local_delivery_helpers import fixture_server

    case = admitted
    prepared, png = editor.prepare_and_attach(case)
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        delivery.configure(case["store"], tmp_path, config)
        delivery.bind_platform(case, monkeypatch)
        current = editor.view(case)
        draft = next(row for row in case["store"].read()[1]["drafts"] if row["id"] == case["draft_id"])
        command = Command.from_request(dict(command_id=str(uuid4()), action="approve_media_revision",
            requested_at=utc_text(editor.AT), expires_at=utc_text(editor.AT+timedelta(minutes=20)),
            targets=[editor._identity(draft)], payload=dict(
                **{key: current[key] for key in ("expected_policy_sha256", "expected_renderer_profile_sha256", "expected_review_sha256", "expected_check_completion_sha256")},
                expected_packet_sha256=current["packet"]["packet_sha256"], reason="Invented MODIS final-bound refusal.")),
            candidate.PUBLISHER, environment="local", now=editor.AT)
        case["store"].accept(command, candidate.PUBLISHER, now=editor.AT)
        caps = assert_nonradar_approval_final_refusal(case, core[3], command.command_id, current,
            candidate.resolve, editor.AT, trace, accepted, monkeypatch, boundary, fault)
        before_edit = case["store"].read()
        with pytest.raises(CommandError) as pending:
            editor.action(case, "edit_revision", {"text": case["text"]+" Invented follow-up."})
        assert pending.value.code == "command_pending"
        assert case["store"].read() == before_edit
        assert stage_rows(core[3], current["check_set_id"]) == caps
        assert case["store"].result(command.command_id) is None and trace == [] and not accepted


@pytest.mark.parametrize("compact_case", [("all_time_low",)], indirect=True)
@pytest.mark.parametrize("boundary", ["proof", "outbox"])
@pytest.mark.parametrize("fault", ["expiry", "source", "editor", "publisher", "policy"])
def test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes(
    compact_case, tmp_path, monkeypatch, boundary, fault
):
    from tests.local_delivery_helpers import fixture_server
    from tests.test_postgres_preview_command_ingress import http

    case = compact_case
    field = "all_time_low"
    draft_id = temperature.admit_compact(case, field)
    temperature.assert_compact_saved_claim(case, draft_id, field)
    case.update(draft_id=draft_id, store=case["authority"], text=temperature.saved_draft(case, draft_id)["text"])
    case["owner"].initialize_delivery(now=datetime.now(UTC))
    ready = temperature.media_view(case, draft_id)
    prepare = temperature.editor_command(case, draft_id, "prepare_media_revision", {key: ready[key] for key in temperature.PREPARE_KEYS})
    assert temperature.submit_command(case, prepare)["status"] == "unchanged"
    prepared = temperature.media_view(case, draft_id)
    png = temperature.png_bytes(case["authority"], draft_id, prepared["preparation"]["proposal_sha256"], case["operators"])
    with fixture_server(png, case["text"]) as (config, trace, accepted):
        path = delivery.configure(case["authority"], tmp_path, config)
        temperature_delivery.configure_child(case, path)
        prepared = temperature.media_view(case, draft_id)
        assert prepared["platform_description"]["status"] == "fits_local_limits"
        attach = temperature.editor_command(case, draft_id, "attach_media_revision", temperature_delivery.review_payload(prepared))
        assert temperature.submit_command(case, attach)["status"] == "applied"
        current = temperature.media_view(case, draft_id)
        request = temperature.editor_command(case, draft_id, "request_revision_checks", temperature.checked_payload(current))
        requested = temperature.submit_command(case, request)
        assert requested["status"] == "unchanged"
        for stage in checks.checks.STAGES:
            result = temperature.ghcn_worker(case, stage, request["command_id"])
            assert result["outcome"] == "completed" and result["checks"]["stages"][stage] == "passed", result
        current = temperature.media_view(case, draft_id)
        assert current["checks_status"] == "passed"
        approve = temperature.editor_command(case, draft_id, "approve_media_revision", temperature.checked_payload(current,
            expected_check_completion_sha256=current["expected_check_completion_sha256"], reason="Invented GHCN final-bound refusal."))
        code, _, _ = http(case["port"], "/commands", method="POST", value=approve, role="publisher")
        assert code == 202
        caps = assert_nonradar_approval_final_refusal(case, case["params"], approve["command_id"], current,
            case["operators"].resolve, datetime.now(UTC), trace, accepted, monkeypatch, boundary, fault,
            source_file=Path(case["config"]["generation"]))
        edit = temperature.editor_command(case, draft_id, "edit_revision", {"text": case["text"]+" Invented follow-up."})
        code, _, _ = http(case["port"], "/commands", method="POST", value=edit, role="editor")
        assert code == 202
        before_edit = case["authority"].read()
        with pytest.raises(CommandError) as pending:
            case["authority"].consume(case["operators"].resolve, command_id=edit["command_id"], now=datetime.now(UTC))
        assert pending.value.code == "command_pending"
        assert case["authority"].read() == before_edit
        assert stage_rows(case["params"], current["check_set_id"]) == caps
        assert case["authority"].result(approve["command_id"]) is None and trace == [] and not accepted
