"""Real transactional media staging; synthetic bytes, no providers or approval."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from src.commands import postgres_media as pg
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import Command, CommandError, Principal, utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from tests.test_command_authority import story
from tests.test_joint_media_review import ACTOR
from tests.test_media_attachment import AT, proposal, revision
from tests.test_media_journal import package as package, resolve
from tests.test_media_review_packet import seed as seed
from tests.test_postgres_command_authority import make_authority as make_authority, options, table_counts
from tests.test_postgres_projection import cluster as cluster, database as database, admin, counts, wrap_connections
from tests.test_postgres_batch_worker import no_provider as no_provider

NOW = utc_datetime(AT)


@pytest.fixture
def case(make_authority, package, no_provider, request):
    make, owner, params = make_authority
    initial = dict(drafts=[package["inputs"]["draft"], story("unrelated")],
                   publish_ledger={"unrelated-receipt": {"phase": "unknown"}},
                   publication_control={"enabled": False}, retained={"keep": True})
    proposed = proposal(package["inputs"], state=initial)
    req = dict(expected_revision=revision(package["inputs"]["draft"]),
               expected_policy_sha256=fingerprint(package["inputs"]["editorial_policy"]),
               graphic_spec=package["inputs"]["graphic_spec"],
               renderer_manifest=package["inputs"]["renderer_manifest"],
               proposal_at=AT, expected_proposal_sha256=proposed["proposal_sha256"])
    issue = getattr(request, "param", None)
    target = initial["drafts"][0]
    if issue == "unknown_send":
        initial["publish_ledger"][target["event_id"]] = {"phase": "unknown"}
    elif issue == "receipt":
        initial["publish_ledger"][target["event_id"]] = {"tweet_id": "synthetic-receipt"}
    elif issue == "ambiguous":
        initial["drafts"].append(deepcopy(target))
    elif issue == "changed_source":
        target["review_context"]["two_bot"]["bundle"]["value"] = 12345
    store = make(initial)
    owner.initialize_media_staging()
    return dict(store=store, owner=owner, params=params, request=req, assets=package["assets"],
                draft_id=package["inputs"]["draft"]["id"], initial=initial, proposal=proposed)


def stage(case, **overrides):
    arguments = dict(assets=case["assets"], resolve_principal=resolve, now=NOW)
    return case["store"].stage_media_proposal(case["draft_id"], case["request"], ACTOR,
                                             **(arguments | overrides))


def saved(case):
    return case["store"].read_media_proposal(case["request"]["expected_proposal_sha256"])


def tables(case):
    return {name: admin(case["params"], f"SELECT * FROM {pg.SCHEMA}.{name} ORDER BY 1")
            for name in ("metadata", "artifacts", "packages")}


def unaffected(case):
    return case["store"].read(), case["store"].journal(), counts(case["params"]), table_counts(case["params"])


def edit(case, draft):
    body = dict(command_id=str(uuid4()), action="edit_revision", targets=[revision(draft)],
                payload={"text": "A distinct synthetic edited sentence."},
                requested_at=AT, expires_at=utc_text(NOW + timedelta(hours=1)))
    command = Command.from_request(body, ACTOR, environment="local", now=NOW)
    case["store"].accept(command, ACTOR, now=NOW)
    return case["store"].consume(resolve, now=NOW)


def test_roundtrip_no_mutation_and_idempotency_after_unrelated_edit(case):
    baseline, inputs = unaffected(case), deepcopy((case["request"], case["assets"]))
    receipt = stage(case)
    found = saved(case)
    assert found["assets"] == case["assets"] and found["capture"]["proposal"] == case["proposal"]
    assert found["receipt"] == receipt and receipt["synthetic"] is True
    assert receipt["status"] == "staged" and receipt["currentness"] == "not_evaluated"
    assert receipt["publication_approved"] is receipt["production_attachment_authorized"] is False
    assert found["capture"]["predecessor_state"]["drafts"] == [case["initial"]["drafts"][0]]
    assert unaffected(case) == baseline and (case["request"], case["assets"]) == inputs
    original = tables(case)
    case["owner"].initialize_media_staging()
    assert tables(case) == original
    assert edit(case, case["initial"]["drafts"][1])["status"] == "applied"
    assert stage(case, now=NOW + timedelta(hours=1)) == receipt
    assert tables(case) == original and saved(case) == found
    assert case["store"].read()[0] == 1 and receipt["authority_version_at_staging"] == 0


@pytest.mark.parametrize("role", ["editor", "publisher"])
def test_current_role_retained_with_original_authenticated_context(case, role):
    receipt = stage(case, resolve_principal=lambda s: Principal(s, role, "new-context"))
    provenance = saved(case)["capture"]["submitter"]
    assert provenance == dict(subject=ACTOR.subject, role_at_staging=role,
                              authentication_context=ACTOR.authentication_context)
    assert receipt["production_attachment_authorized"] is False


def test_revocation_failure_wrong_subject_and_viewer_never_write(case):
    def unavailable(_):
        raise RuntimeError("private auth infrastructure detail")
    before = unaffected(case), tables(case)
    for resolver in (lambda _: None, lambda s: Principal(s, "viewer", "new"),
                     lambda _: Principal("different", "editor", "new"), lambda _: {}, unavailable):
        with pytest.raises(CommandError) as exc:
            stage(case, resolve_principal=resolver)
        assert exc.value.code in ("forbidden", "authorization_unavailable")
        assert "private auth" not in str(exc.value)
        assert (unaffected(case), tables(case)) == before
    for actor in (None, Principal(ACTOR.subject, "viewer", "viewer")):
        with pytest.raises(CommandError):
            case["store"].stage_media_proposal(case["draft_id"], case["request"], actor,
                assets=case["assets"], resolve_principal=resolve, now=NOW)
    assert (unaffected(case), tables(case)) == before


def test_request_asset_identity_and_size_matrix_never_writes(case, monkeypatch):
    before = unaffected(case), tables(case)
    requests = [dict(case["request"], **{key: value}) for key, value in (
        ("expected_proposal_sha256", "f"*64), ("expected_policy_sha256", "f"*64),
        ("expected_revision", {}), ("proposal_at", "2026-10-01"),
        ("proposal_at", "2026-10-01T18:00:00.000000Z"), ("renderer_manifest", {}),
        ("graphic_spec", {}), ("unexpected", True), ("expected_proposal_sha256", None))]
    requests += [{k:v for k,v in case["request"].items() if k != "proposal_at"}]
    for req in requests:
        with pytest.raises((ValueError, RuntimeError)):
            stage(dict(case, request=req))
        assert (unaffected(case), tables(case)) == before
    for assets in (None, {}, dict(case["assets"], extra=b"unexpected"),
                   dict(case["assets"], **{"preview.svg": bytearray(b"synthetic svg")}),
                   dict(case["assets"], **{"preview.png": b"wrong"}),
                   dict(case["assets"], **{"input.json": b""}),
                   dict(case["assets"], **{"preview.png": b"x"*(8*1024*1024+1)})):
        with pytest.raises((ValueError, RuntimeError)):
            stage(case, assets=assets)
        assert (unaffected(case), tables(case)) == before
    with monkeypatch.context() as patch:
        patch.setattr(pg, "MAX_METADATA_BYTES", 100)
        with pytest.raises(RuntimeError, match="metadata_bound"):
            stage(case)
    assert (unaffected(case), tables(case)) == before


@pytest.mark.parametrize("delta,allowed", [(-301, False), (-300, True), (86400, True), (86401, False)])
def test_proposal_time_window(case, delta, allowed):
    if allowed:
        assert stage(case, now=NOW + timedelta(seconds=delta))["status"] == "staged"
    else:
        before = tables(case)
        with pytest.raises(RuntimeError, match="expired"):
            stage(case, now=NOW + timedelta(seconds=delta))
        assert tables(case) == before


def test_clock_is_explicit_and_aware(case):
    before = tables(case)
    for clock in (None, AT, NOW.replace(tzinfo=None)):
        with pytest.raises(CommandError, match="clock|aware"):
            stage(case, now=clock)
    assert tables(case) == before


def test_current_draft_and_policy_are_not_historical_permission(case, monkeypatch):
    stage(case)
    found = saved(case)
    assert edit(case, case["initial"]["drafts"][0])["status"] == "applied"
    before = tables(case)
    with pytest.raises(ValueError, match="predecessor"):
        stage(case)
    assert saved(case) == found and tables(case) == before
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    with pytest.raises(RuntimeError, match="policy_changed"):
        stage(case)
    assert saved(case) == found


@pytest.mark.parametrize("case", ["unknown_send", "receipt", "ambiguous", "changed_source"], indirect=True)
def test_independent_current_state_refuses_unsafe_or_obsolete_target(case):
    before = unaffected(case), tables(case)
    with pytest.raises(ValueError):
        stage(case)
    assert (unaffected(case), tables(case)) == before


def test_owner_migration_runtime_privileges_and_missing_schema(make_authority, package):
    import psycopg
    make, owner, params = make_authority
    store = make({"drafts": [package["inputs"]["draft"]]})
    with pytest.raises(RuntimeError, match="migration_required"):
        store.read_media_proposal("f"*64)
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        store.initialize_media_staging()
    owner.initialize_media_staging()
    for table in ("metadata", "artifacts", "packages"):
        # CASCADE reaches the immutable trigger even for referenced artifacts;
        # without it PostgreSQL's earlier foreign-key guard would reject first.
        for action in (f"DELETE FROM {pg.SCHEMA}.{table}", f"TRUNCATE {pg.SCHEMA}.{table} CASCADE"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin(dict(params, user="projection_runtime"), action)
            with pytest.raises(psycopg.errors.RaiseException, match="immutable media staging"):
                admin(params, action)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin(dict(params, user="projection_runtime"), f"UPDATE {pg.SCHEMA}.metadata SET version=2")
    with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
        owner.read_media_proposal("f"*64)


@pytest.mark.parametrize("sql", [
    "ALTER TABLE theheat_media.packages ADD COLUMN unexpected text",
    "ALTER TABLE theheat_media.artifacts DISABLE TRIGGER artifacts_immutable",
    "GRANT CREATE ON SCHEMA theheat_media TO projection_runtime",
    "GRANT EXECUTE ON FUNCTION theheat_media.refuse_mutation() TO PUBLIC",
])
def test_schema_and_permission_drift_blocks_stage_and_read(case, sql):
    stage(case)
    admin(case["params"], sql)
    before = unaffected(case), tables(case)
    for operation in (stage, saved):
        with pytest.raises(RuntimeError, match="changed_media_staging_schema"):
            operation(case)
    assert (unaffected(case), tables(case)) == before


@pytest.mark.parametrize("field", ["environment", "owner_role", "runtime_role", "version"])
def test_schema_metadata_is_bound_to_authority(case, field):
    value = 2 if field == "version" else "preview" if field == "environment" else "wrong-role"
    admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.metadata DISABLE TRIGGER metadata_immutable")
    admin(case["params"], f"UPDATE {pg.SCHEMA}.metadata SET {field}=%s", (value,))
    admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.metadata ENABLE TRIGGER metadata_immutable")
    with pytest.raises(RuntimeError, match="schema|environment|role"):
        stage(case)


@pytest.mark.parametrize("mutation", ["numeric_type", "proposal", "missing_asset", "bad_size"])
def test_historical_read_detects_changed_capture_or_asset_bytes(case, mutation):
    import psycopg
    stage(case)
    found = saved(case)
    if mutation in ("numeric_type", "proposal"):
        capture = deepcopy(found["capture"])
        if mutation == "numeric_type":
            capture["schema_version"] = 1.0
        else:
            capture["proposal"]["changed"] = 1
        raw = p._canonical(capture)
        digest = p._sha(raw)
        admin(case["params"], f"INSERT INTO {pg.SCHEMA}.artifacts VALUES(%s,%s,%s)", (digest, raw, len(raw)))
        admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.packages DISABLE TRIGGER packages_immutable")
        admin(case["params"], f"UPDATE {pg.SCHEMA}.packages SET capture_sha256=%s", (digest,))
        admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.packages ENABLE TRIGGER packages_immutable")
    elif mutation == "missing_asset":
        digest = found["capture"]["asset_sha256"]["preview.svg"]
        admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.artifacts DISABLE TRIGGER artifacts_immutable")
        admin(case["params"], f"DELETE FROM {pg.SCHEMA}.artifacts WHERE sha=%s", (digest,))
        admin(case["params"], f"ALTER TABLE {pg.SCHEMA}.artifacts ENABLE TRIGGER artifacts_immutable")
    else:
        # SQL independently enforces byte count and SHA even for the trusted owner.
        for digest, raw, size in (("f"*64, b"wrong", 5), (p._sha(b"wrong"), b"wrong", 4)):
            with pytest.raises(psycopg.errors.CheckViolation):
                admin(case["params"], f"INSERT INTO {pg.SCHEMA}.artifacts VALUES(%s,%s,%s)", (digest, raw, size))
        assert saved(case) == found
        return
    with pytest.raises((ValueError, RuntimeError)):
        saved(case)


@pytest.mark.parametrize("write_number", range(1, 8))
def test_each_artifact_capture_and_package_write_rolls_back(case, monkeypatch, write_number):
    before = unaffected(case), tables(case)
    seen = 0
    def fail(query, _):
        nonlocal seen
        if query.startswith(f"INSERT INTO {pg.SCHEMA}."):
            seen += 1
            if seen == write_number:
                raise RuntimeError("synthetic interrupted media write")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="interrupted media write"):
            stage(case)
    assert seen == write_number and (unaffected(case), tables(case)) == before


@pytest.mark.parametrize("lost_ack", [False, True])
def test_killed_connection_and_lost_commit_ack_recover_exact_package(case, monkeypatch, lost_ack):
    before = unaffected(case), tables(case)
    with monkeypatch.context() as patch:
        kwargs = {"lost_ack": True} if lost_ack else {"before_commit": lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())")}
        wrap_connections(patch, **kwargs)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            stage(case)
    assert unaffected(case) == before[0]
    assert (tables(case) == before[1]) is not lost_ack
    case["store"] = PostgresCommandAuthority(**options(case["params"]))
    receipt = stage(case)
    retained = tables(case)
    assert stage(case) == receipt and tables(case) == retained
    assert saved(case)["assets"] == case["assets"]


def test_independent_connections_stage_identical_package_once(case):
    baseline = unaffected(case)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: stage(case), range(2)))
    assert receipts[0] == receipts[1] and len(tables(case)["packages"]) == 1
    assert unaffected(case) == baseline


def test_caller_mutation_after_first_sql_cannot_change_the_request(case, monkeypatch):
    expected = deepcopy(case)
    touched = False
    def mutate(query, _):
        nonlocal touched
        if not touched and query.startswith("SELECT version,migration_sha"):
            touched = True
            case["request"]["graphic_spec"].clear()
            case["assets"]["preview.svg"] = b"caller replacement"
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=mutate)
        receipt = stage(case)
    assert touched and receipt["proposal_sha256"] == expected["request"]["expected_proposal_sha256"]
    assert saved(expected)["assets"] == expected["assets"]


def test_dump_restore_retains_bytes_proposal_and_core_state(case, cluster):
    import psycopg
    receipt = stage(case)
    found, original, unchanged = saved(case), tables(case), unaffected(case)
    params, run, root = cluster
    dump = root / ("media-" + uuid4().hex + ".dump")
    common = ["-h", params["host"], "-p", str(params["port"]), "-U", params["user"]]
    run("pg_dump", *common, "-Fc", "-f", str(dump), case["params"]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = {**case["params"], "dbname": name}
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = dict(case, store=PostgresCommandAuthority(**options(restored_params)), params=restored_params)
        assert saved(restored) == found and stage(restored) == receipt
        assert tables(restored) == original and unaffected(restored) == unchanged
        owner = PostgresCommandAuthority(**options(restored_params, user="projection_owner"))
        owner.initialize_media_staging()
        assert tables(restored) == original
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
