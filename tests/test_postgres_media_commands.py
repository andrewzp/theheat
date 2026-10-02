"""Real PostgreSQL atomic graphics commands; synthetic evidence, no provider I/O."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from src.commands import postgres_media_commands as pg
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.reducer import reduce_command
from src.commands.schema import Command, CommandError, Principal, utc_text
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, review_is_current, approval_is_current
from src.media.attachment import build_media_attachment_proposal, build_media_removal_proposal
from src.storage import postgres_projection as p
from tests.test_joint_media_review import ACTOR, payload
from tests.test_media_attachment import AT, revision
from tests.test_media_journal import package as package, resolve
from tests.test_media_review_packet import seed as seed
from tests.test_postgres_command_authority import make_authority as make_authority, options
from tests.test_postgres_projection import (
    cluster as cluster,
    database as database,
    admin,
    wrap_connections,
)
from tests.test_postgres_batch_worker import no_provider as no_provider
from tests.test_postgres_media import case as case, stage, tables, unaffected, edit, NOW


@pytest.fixture
def ready(case):
    case["owner"].initialize_media_commands()
    stage(case)
    return case


def command_for(
    case, *, action="attach_media_revision", at=AT, overrides=None, actor=ACTOR, target=None
):
    state = case["store"].read()[1]
    draft = next(d for d in state["drafts"] if d["id"] == case["draft_id"])
    expected = revision(draft) if target is None else target
    if action == "attach_media_revision":
        value = dict(
            proposal_sha256=case["proposal"]["proposal_sha256"],
            expected_packet_sha256=case["proposal"]["packet"]["packet_sha256"],
            expected_policy_sha256=fingerprint(current_editorial_policy()),
            review=payload(),
        )
    else:
        proposal = build_media_removal_proposal(
            state, draft["id"], expected_revision=expected, at=at
        )
        value = dict(
            expected_proposal_sha256=proposal["proposal_sha256"],
            expected_policy_sha256=fingerprint(current_editorial_policy()),
            confirmed=True,
            reason="Synthetic removal.",
        )
    body = dict(
        command_id=str(uuid4()),
        action=action,
        requested_at=at,
        expires_at=utc_text(NOW + timedelta(hours=23)),
        targets=[expected],
        payload=value | (overrides or {}),
    )
    return Command.from_request(body, actor, environment="local", now=NOW)


def apply(case, cmd=None, *, resolver=resolve, now=NOW):
    cmd = command_for(case) if cmd is None else cmd
    case["store"].accept(cmd, ACTOR, now=NOW)
    return case["store"].consume(resolver, command_id=cmd.command_id, now=now)


def snapshot(case):
    return (
        unaffected(case),
        tables(case),
        admin(case["params"], f"SELECT * FROM {pg.SCHEMA}.reviews ORDER BY 1"),
    )


def restage(case, *, replace=False):
    state = case["store"].read()[1]
    draft = next(d for d in state["drafts"] if d["id"] == case["draft_id"])
    if replace:
        case["assets"]["preview.svg"] = b"different synthetic svg"
        case["request"]["renderer_manifest"]["files"]["preview.svg"] = p._sha(
            case["assets"]["preview.svg"]
        )
    case["request"]["expected_revision"] = revision(draft)
    case["proposal"] = build_media_attachment_proposal(
        state,
        draft["id"],
        expected_revision=revision(draft),
        editorial_policy=current_editorial_policy(),
        graphic_spec=case["request"]["graphic_spec"],
        renderer_manifest=case["request"]["renderer_manifest"],
        png_bytes=case["assets"]["preview.png"],
        at=AT,
    )
    case["request"]["expected_proposal_sha256"] = case["proposal"]["proposal_sha256"]
    stage(case)


def test_attach_replace_remove_and_reattach_preserve_history_and_unrelated_state(ready):
    initial = deepcopy(ready["initial"])
    cmd = command_for(ready)
    result = apply(ready, cmd)
    version, state = ready["store"].read()
    draft = state["drafts"][0]
    assert version == 1 and result["status"] == "applied"
    assert draft["content_revision"] == 2 and draft["status"] == "pending"
    assert draft["revision_history"][0]["text"] == initial["drafts"][0]["text"]
    assert {k: v for k, v in state.items() if k != "drafts"} == {
        k: v for k, v in initial.items() if k != "drafts"
    }
    assert state["drafts"][1:] == initial["drafts"][1:]
    assert not review_is_current(draft) and not approval_is_current(draft)
    assert (
        "review_binding" not in draft
        and "approval_binding" not in draft
        and "publish_intent_id" not in draft
    )
    assert (
        result["media"]["publication_approved"]
        is result["media"]["production_attachment_authorized"]
        is False
    )
    assert result["media"]["synthetic"] is True and result["publish_intent_id"] is None
    found = ready["store"].read_media_review(cmd.command_id)
    assert found["currentness"] == "not_evaluated" and found["status"] == "historical"
    assert (
        found["review"]["reviewer"]["authentication_context"]
        == resolve(ACTOR.subject).authentication_context
    )
    assert found["review"]["reviewed_at"] == AT and found["review"]["synthetic"] is True
    restage(ready, replace=True)
    second = apply(ready)
    assert (
        second["status"] == "applied"
        and second["media"]["proposal_sha256"] != result["media"]["proposal_sha256"]
    )
    removal = apply(ready, command_for(ready, action="remove_media_revision"))
    removed = ready["store"].read()[1]["drafts"][0]
    assert (
        removal["status"] == "applied"
        and "media_attachment" not in removed
        and "media_review_binding" not in removed
    )
    assert removed["content_revision"] == 4 and len(removed["revision_history"]) == 3
    assert ready["store"].read_media_review(cmd.command_id) == found
    no_op = apply(ready, command_for(ready, action="remove_media_revision"))
    assert no_op["status"] == "unchanged" and no_op["state_version"] == 3
    restage(ready)
    third = apply(ready)
    assert (
        third["status"] == "applied"
        and third["media"]["proposal_sha256"] != second["media"]["proposal_sha256"]
    )
    assert ready["store"].read()[1]["drafts"][0]["content_revision"] == 5
    assert ready["store"].read_media_review(cmd.command_id) == found
    assert ready["initial"] == initial


def test_identical_attachment_refused_but_committed_command_retry_is_exact(ready):
    cmd = command_for(ready)
    result = apply(ready, cmd)
    before = snapshot(ready)
    assert (
        ready["store"].consume(
            lambda _: None, command_id=cmd.command_id, now=NOW + timedelta(days=2)
        )
        == result
    )
    assert snapshot(ready) == before
    restage(ready)
    version, state = ready["store"].read()
    reviews = snapshot(ready)[2]
    rejected = apply(ready)
    assert rejected["code"] == "media_already_attached"
    assert ready["store"].read() == (version, state) and snapshot(ready)[2] == reviews


def test_text_edit_obsoletes_link_but_retains_historical_review(ready):
    cmd = command_for(ready)
    apply(ready, cmd)
    found = ready["store"].read_media_review(cmd.command_id)
    assert edit(ready, ready["store"].read()[1]["drafts"][0])["status"] == "applied"
    draft = ready["store"].read()[1]["drafts"][0]
    assert "media_review_binding" not in draft and "media_attachment" in draft
    assert draft["revision_history"][-1]["media_review_binding"]["command_id"] == cmd.command_id
    assert ready["store"].read_media_review(cmd.command_id) == found


@pytest.mark.parametrize("kind", ["viewer", "revoked", "different", "publisher", "editor"])
def test_current_actor_required_independently_of_staging(ready, kind):
    def resolver(s):
        return (
            None
            if kind == "revoked"
            else Principal(
                "different" if kind == "different" else s,
                "editor" if kind == "different" else kind,
                "fresh",
            )
        )

    before = ready["store"].read()
    result = apply(ready, resolver=resolver)
    if kind in ("publisher", "editor"):
        assert result["status"] == "applied"
    else:
        assert result["code"] == "forbidden" and ready["store"].read() == before
        assert not snapshot(ready)[2]


@pytest.mark.parametrize("mode", ["exception", "invalid-principal"])
def test_resolver_uncertainty_rolls_back_without_result(ready, mode):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    before = snapshot(ready)

    def unavailable(_):
        if mode == "exception":
            raise RuntimeError("private synthetic infrastructure detail")
        return {}

    with pytest.raises(CommandError, match="authorization is unavailable"):
        ready["store"].consume(unavailable, now=NOW)
    assert snapshot(ready) == before and ready["store"].result(cmd.command_id) is None
    assert ready["store"].consume(resolve, now=NOW)["status"] == "applied"


@pytest.mark.parametrize(
    "mode,code",
    [
        ("policy", "editorial_policy_changed"),
        ("packet", "invalid_media_revision"),
        ("missing", "media_package_not_found"),
        ("stale", "revision_conflict"),
        ("expired", "command_expired"),
        ("old-proposal", "media_proposal_expired"),
        ("future-clock", "invalid_time"),
        ("foreign", "media_proposal_changed"),
    ],
)
def test_exact_current_identities_and_time_refusals(ready, mode, code):
    overrides = (
        {"expected_policy_sha256": "f" * 64}
        if mode == "policy"
        else {"expected_packet_sha256": "f" * 64}
        if mode == "packet"
        else {"proposal_sha256": "f" * 64}
        if mode == "missing"
        else None
    )
    cmd = command_for(ready, overrides=overrides)
    now = NOW
    if mode == "stale":
        edit(ready, ready["initial"]["drafts"][0])
    elif mode == "expired":
        now += timedelta(hours=24)
    elif mode == "old-proposal":
        # A later valid command referencing an old staged proposal.
        body = cmd.as_dict()
        for key in ("schema_version", "environment", "actor_subject", "authentication_context"):
            body.pop(key)
        now = NOW + timedelta(hours=25)
        body.update(requested_at=utc_text(now), expires_at=utc_text(now + timedelta(hours=1)))
        cmd = Command.from_request(body, ACTOR, environment="local", now=now)
        ready["store"].accept(cmd, ACTOR, now=now)
    elif mode == "future-clock":
        now -= timedelta(minutes=6)
    elif mode == "foreign":
        body = cmd.as_dict()
        for key in ("schema_version", "environment", "actor_subject", "authentication_context"):
            body.pop(key)
        body["targets"] = [revision(ready["initial"]["drafts"][1])]
        cmd = Command.from_request(body, ACTOR, environment="local", now=NOW)
    before = ready["store"].read(), tables(ready), snapshot(ready)[2]
    if mode != "old-proposal":
        ready["store"].accept(cmd, ACTOR, now=NOW)
    result = ready["store"].consume(resolve, now=now)
    assert result["status"] == "rejected" and result["code"] == code
    assert (ready["store"].read(), tables(ready), snapshot(ready)[2]) == before


@pytest.mark.parametrize(
    "field",
    [
        "text_matches_data",
        "graphic_matches_data",
        "text_graphic_agree",
        "qualifications_visible",
        "alt_text_agrees",
    ],
)
@pytest.mark.parametrize("value", [False, None, 1, 1.0, "true"])
def test_explicit_confirmations_at_ingress(ready, field, value):
    review = payload()
    review["confirmations"][field] = value
    before = snapshot(ready)
    with pytest.raises(CommandError, match="complete explicit joint review"):
        command_for(ready, overrides={"review": review})
    assert snapshot(ready) == before


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "extra",
        "hash",
        "review-extra",
        "reject",
        "reason",
        "target-bool",
        "target-float",
        "viewer",
    ],
)
def test_malformed_ingress_never_mutates(ready, mode):
    cmd = command_for(ready)
    body = {
        k: v
        for k, v in cmd.as_dict().items()
        if k in {"command_id", "action", "requested_at", "expires_at", "targets", "payload"}
    }
    if mode == "missing":
        del body["payload"]["review"]
    if mode == "extra":
        body["payload"]["assets"] = {}
    if mode == "hash":
        body["payload"]["proposal_sha256"] = "F" * 64
    if mode == "review-extra":
        body["payload"]["review"]["reviewer"] = "invented"
    if mode == "reject":
        body["payload"]["review"]["decision"] = "reject"
    if mode == "reason":
        body["payload"]["review"]["reason"] = "x" * 2001
    if mode in ("target-bool", "target-float"):
        body["targets"][0]["content_revision"] = True if mode == "target-bool" else 1.0
    actor = Principal(ACTOR.subject, "viewer", "local") if mode == "viewer" else ACTOR
    before = snapshot(ready)
    with pytest.raises(CommandError):
        Command.from_request(body, actor, environment="local", now=NOW)
    assert snapshot(ready) == before


@pytest.mark.parametrize(
    "phase",
    [
        "review-artifact",
        "review-row",
        "projection-artifact",
        "projection-version",
        "projection-field",
        "pointer",
        "result",
        "event",
    ],
)
def test_every_transaction_write_rolls_back(ready, monkeypatch, phase):
    prefixes = {
        "review-artifact": "INSERT INTO theheat_media.artifacts",
        "review-row": "INSERT INTO theheat_media_commands.reviews",
        "projection-artifact": "INSERT INTO theheat_projection.artifacts",
        "projection-version": "INSERT INTO theheat_projection.versions",
        "projection-field": "INSERT INTO theheat_projection.fields",
        "pointer": "UPDATE theheat_commands.state",
        "result": "INSERT INTO theheat_commands.results",
        "event": "INSERT INTO theheat_commands.events",
    }
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    before = snapshot(ready)

    def fail(query, _):
        if query.startswith(prefixes[phase]):
            raise RuntimeError("synthetic write failure")

    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic write failure"):
            ready["store"].consume(resolve, now=NOW)
    assert snapshot(ready) == before and ready["store"].result(cmd.command_id) is None
    assert ready["store"].consume(resolve, now=NOW)["status"] == "applied"


@pytest.mark.parametrize("lost_ack", [False, True])
def test_killed_connection_and_lost_ack_recover_one_revision(ready, monkeypatch, lost_ack):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    before = snapshot(ready)
    with monkeypatch.context() as patch:
        kwargs = (
            {"lost_ack": True}
            if lost_ack
            else {
                "before_commit": lambda c: c.execute(
                    "SELECT pg_terminate_backend(pg_backend_pid())"
                )
            }
        )
        wrap_connections(patch, **kwargs)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            ready["store"].consume(resolve, now=NOW)
    assert (snapshot(ready) == before) is not lost_ack
    ready["store"] = PostgresCommandAuthority(**options(ready["params"]))
    result = ready["store"].consume(resolve, command_id=cmd.command_id, now=NOW)
    assert result["status"] == "applied" and result["state_version"] == 1
    assert ready["store"].consume(lambda _: None, command_id=cmd.command_id, now=NOW) == result
    assert len(snapshot(ready)[2]) == 1


def test_independent_connections_fifo_conflict_and_id_reuse(ready):
    first, second = command_for(ready), command_for(ready)
    for cmd in (first, second):
        ready["store"].accept(cmd, ACTOR, now=NOW)
    with pytest.raises(CommandError, match="earlier accepted command"):
        ready["store"].consume(resolve, command_id=second.command_id, now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: ready["store"].consume(resolve, command_id=first.command_id, now=NOW),
                range(2),
            )
        )
    assert results[0] == results[1] and results[0]["status"] == "applied"
    assert ready["store"].consume(resolve, now=NOW)["code"] == "revision_conflict"
    from dataclasses import replace

    different = command_for(ready, overrides={"expected_packet_sha256": "f" * 64})
    with pytest.raises(CommandError, match="already belongs"):
        ready["store"].accept(replace(different, command_id=first.command_id), ACTOR, now=NOW)
    assert ready["store"].read()[0] == 1


def test_sqlite_and_pure_reducers_refuse_and_fifo_continues(ready, tmp_path):
    cmd = command_for(ready)
    state = deepcopy(ready["initial"])
    with pytest.raises(CommandError, match="no atomic media authority"):
        reduce_command(state, cmd, ACTOR, now=NOW)
    sqlite = SQLiteAuthority(tmp_path / "media-unsupported.sqlite")
    sqlite.initialize(state)
    sqlite.accept(cmd, ACTOR, now=NOW)
    assert sqlite.consume(resolve, now=NOW)["code"] == "media_backend_unsupported"
    assert sqlite.read() == (0, state)
    copied = dict(ready, store=sqlite)
    assert edit(copied, state["drafts"][0])["status"] == "applied"


def test_missing_migration_is_uncertainty_then_owner_install_recovers(case):
    import psycopg

    stage(case)
    cmd = command_for(case)
    case["store"].accept(cmd, ACTOR, now=NOW)
    before = unaffected(case), tables(case)
    with pytest.raises(p.ProjectionError, match="media_command_migration_required"):
        case["store"].consume(resolve, now=NOW)
    assert (unaffected(case), tables(case)) == before
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        case["store"].initialize_media_commands()
    case["owner"].initialize_media_commands()
    case["owner"].initialize_media_commands()
    assert case["store"].consume(resolve, now=NOW)["status"] == "applied"
    for table in ("metadata", "reviews"):
        for sql in (f"DELETE FROM {pg.SCHEMA}.{table}", f"TRUNCATE {pg.SCHEMA}.{table}"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin(dict(case["params"], user="projection_runtime"), sql)
            with pytest.raises(
                psycopg.errors.RaiseException, match="immutable media command review"
            ):
                admin(case["params"], sql)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin(
            dict(case["params"], user="projection_runtime"),
            f"UPDATE {pg.SCHEMA}.reviews SET review_sha256=%s",
            ("f" * 64,),
        )


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE theheat_media_commands.reviews ADD COLUMN unexpected text",
        "ALTER TABLE theheat_media_commands.reviews DISABLE TRIGGER reviews_immutable",
        "GRANT CREATE ON SCHEMA theheat_media_commands TO projection_runtime",
        "GRANT EXECUTE ON FUNCTION theheat_media_commands.refuse_mutation() TO PUBLIC",
    ],
)
def test_schema_and_permissions_drift_cannot_become_terminal_rejection(ready, sql):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    admin(ready["params"], sql)
    before = snapshot(ready)
    with pytest.raises(p.ProjectionError, match="changed_media_command_schema"):
        ready["store"].consume(resolve, now=NOW)
    assert snapshot(ready) == before and ready["store"].result(cmd.command_id) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("environment", "preview"),
        ("runtime_role", "other"),
        ("owner_role", "other"),
    ],
)
def test_metadata_binding_refuses_wrong_environment_schema_or_roles(ready, field, value):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.metadata DISABLE TRIGGER metadata_immutable")
    admin(ready["params"], f"UPDATE {pg.SCHEMA}.metadata SET {field}=%s", (value,))
    admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.metadata ENABLE TRIGGER metadata_immutable")
    before = snapshot(ready)
    with pytest.raises(p.ProjectionError, match="schema|environment|role"):
        ready["store"].consume(resolve, now=NOW)
    assert snapshot(ready) == before


def test_corrupt_staged_package_never_records_deterministic_refusal(ready):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    retained = ready["store"].read_media_proposal(ready["proposal"]["proposal_sha256"])
    capture = retained["capture"]
    capture["proposal"]["changed"] = 1  # Rehashed, but not the canonical typed proposal.
    raw = p._canonical(capture)
    digest = p._sha(raw)
    admin(
        ready["params"],
        "INSERT INTO theheat_media.artifacts VALUES(%s,%s,%s)",
        (digest, raw, len(raw)),
    )
    admin(ready["params"], "ALTER TABLE theheat_media.packages DISABLE TRIGGER packages_immutable")
    admin(ready["params"], "UPDATE theheat_media.packages SET capture_sha256=%s", (digest,))
    admin(ready["params"], "ALTER TABLE theheat_media.packages ENABLE TRIGGER packages_immutable")
    before = snapshot(ready)
    with pytest.raises(RuntimeError, match="changed_media_staging_proposal"):
        ready["store"].consume(resolve, now=NOW)
    assert snapshot(ready) == before and ready["store"].result(cmd.command_id) is None


@pytest.mark.parametrize("mutation", ["reference", "numeric", "provenance", "reason"])
def test_historical_read_and_terminal_retry_detect_rehashed_tampering(ready, mutation):
    cmd = command_for(ready)
    apply(ready, cmd)
    found = ready["store"].read_media_review(cmd.command_id)
    if mutation == "reference":
        admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.reviews DISABLE TRIGGER reviews_immutable")
        admin(ready["params"], f"UPDATE {pg.SCHEMA}.reviews SET review_sha256=%s", ("f" * 64,))
        admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.reviews ENABLE TRIGGER reviews_immutable")
    else:
        record = deepcopy(found["review"])
        if mutation == "numeric":
            record["synthetic"] = 1
        if mutation == "provenance":
            record["reviewer"]["subject"] = "different"
        if mutation == "reason":
            record["reason"] = "Rewritten synthetic reason."
        record["review_sha256"] = fingerprint(
            {k: v for k, v in record.items() if k != "review_sha256"}
        )
        raw = p._canonical(record)
        digest = p._sha(raw)
        admin(
            ready["params"],
            "INSERT INTO theheat_media.artifacts VALUES(%s,%s,%s)",
            (digest, raw, len(raw)),
        )
        admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.reviews DISABLE TRIGGER reviews_immutable")
        admin(
            ready["params"],
            f"UPDATE {pg.SCHEMA}.reviews SET review_sha256=%s,artifact_sha256=%s",
            (record["review_sha256"], digest),
        )
        admin(ready["params"], f"ALTER TABLE {pg.SCHEMA}.reviews ENABLE TRIGGER reviews_immutable")

    def raw_snapshot():
        return {
            table: admin(ready["params"], f"SELECT * FROM {table} ORDER BY 1,2,3")
            for table in (
                "theheat_commands.state",
                "theheat_commands.intents",
                "theheat_commands.results",
                "theheat_commands.events",
                "theheat_projection.versions",
                "theheat_projection.artifacts",
                "theheat_projection.fields",
                "theheat_media.artifacts",
                "theheat_media.packages",
                "theheat_media_commands.reviews",
            )
        }

    before = raw_snapshot()
    for read in (
        lambda: ready["store"].read_media_review(cmd.command_id),
        lambda: ready["store"].journal(),
        lambda: ready["store"].consume(resolve, command_id=cmd.command_id, now=NOW),
    ):
        with pytest.raises(p.ProjectionError, match="media_command"):
            read()
    assert raw_snapshot() == before


@pytest.mark.parametrize("attachment", [None, {}, {"malformed": True}])
def test_malformed_present_attachment_removes_through_revision(
    make_authority, package, attachment, no_provider
):
    make, owner, params = make_authority
    draft = deepcopy(package["inputs"]["draft"])
    draft["media_attachment"] = attachment
    initial = dict(drafts=[draft], publish_ledger={})
    case = dict(
        store=make(initial), owner=owner, params=params, initial=initial, draft_id=draft["id"]
    )
    owner.initialize_media_staging()
    owner.initialize_media_commands()
    cmd = command_for(case, action="remove_media_revision")
    result = apply(case, cmd)
    after = case["store"].read()[1]["drafts"][0]
    assert (
        result["status"] == "applied" and after["content_revision"] == draft["content_revision"] + 1
    )
    assert (
        "media_attachment" not in after
        and after["revision_history"][-1]["media_attachment"] == attachment
    )


def test_joint_preview_never_allows_legacy_text_approval(ready):
    apply(ready)
    draft = ready["store"].read()[1]["drafts"][0]
    publisher = Principal(ACTOR.subject, "publisher", ACTOR.authentication_context)
    for action, value in (
        (
            "record_review",
            {
                "confirmed": True,
                "reason": "Synthetic",
                "expected_policy_sha256": fingerprint(current_editorial_policy()),
            },
        ),
        ("approve_revision", {"reason": "Synthetic"}),
    ):
        cmd = Command.from_request(
            dict(
                command_id=str(uuid4()),
                action=action,
                requested_at=AT,
                expires_at=utc_text(NOW + timedelta(hours=1)),
                targets=[revision(draft)],
                payload=value,
            ),
            publisher,
            environment="local",
            now=NOW,
        )
        ready["store"].accept(cmd, publisher, now=NOW)
        before = ready["store"].read()
        result = ready["store"].consume(lambda s: publisher, now=NOW)
        assert result["status"] == "rejected" and ready["store"].read() == before


def test_restore_preserves_exact_stage_review_command_and_projection(ready, cluster):
    import psycopg

    cmd = command_for(ready)
    result = apply(ready, cmd)
    found = ready["store"].read_media_review(cmd.command_id)
    before = snapshot(ready)
    params, run, root = cluster
    dump = root / ("media-command-" + uuid4().hex + ".dump")
    common = ["-h", params["host"], "-p", str(params["port"]), "-U", params["user"]]
    run("pg_dump", *common, "-Fc", "-f", str(dump), ready["params"]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(ready["params"], dbname=name)
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = dict(
            ready,
            store=PostgresCommandAuthority(**options(restored_params)),
            params=restored_params,
        )
        assert snapshot(restored) == before
        assert restored["store"].read_media_review(cmd.command_id) == found
        assert (
            restored["store"].consume(lambda _: None, command_id=cmd.command_id, now=NOW) == result
        )
        assert edit(restored, restored["store"].read()[1]["drafts"][1])["status"] == "applied"
        assert restored["store"].read_media_review(cmd.command_id) == found
    finally:
        admin(
            params,
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)),
        )


@pytest.mark.parametrize(
    "issue", ["unknown", "confirmed", "ambiguous", "source", "conflict", "checks"]
)
def test_authoritative_target_changes_and_obsolete_checks(
    make_authority, package, no_provider, issue
):
    from src.editorial.revisions import record_model_review, bind_reviewed_revision, text_hash

    make, owner, params = make_authority
    draft = deepcopy(package["inputs"]["draft"])
    policy = current_editorial_policy()
    if issue == "checks":
        proof = draft["review_context"]["two_bot"]
        proof.update(
            fact_check={"passed": True},
            critic={"passed": True},
            reviewed_text_sha256=text_hash(draft["text"]),
            reviewed_bundle_sha256=fingerprint(proof["bundle"]),
            reviewed_policy_sha256=fingerprint(policy),
        )
        record_model_review(draft, policy=policy)
        bind_reviewed_revision(
            draft, "manual", at=AT, intent_id="synthetic-old-intent", policy=policy
        )
        draft["status"] = "approved"
    original = deepcopy(draft)
    initial = dict(drafts=[draft], publish_ledger={})
    proposal = build_media_attachment_proposal(
        initial,
        draft["id"],
        expected_revision=revision(draft),
        editorial_policy=policy,
        graphic_spec=package["inputs"]["graphic_spec"],
        renderer_manifest=package["inputs"]["renderer_manifest"],
        png_bytes=package["assets"]["preview.png"],
        at=AT,
    )
    request = dict(
        expected_revision=revision(draft),
        expected_policy_sha256=fingerprint(policy),
        graphic_spec=package["inputs"]["graphic_spec"],
        renderer_manifest=package["inputs"]["renderer_manifest"],
        proposal_at=AT,
        expected_proposal_sha256=proposal["proposal_sha256"],
    )
    # Retained state changes can predate staging. Use a qualified stage captured
    # independently, then a newly projected authoritative state for execution.
    case = dict(
        store=make(initial),
        owner=owner,
        params=params,
        initial=deepcopy(initial),
        draft_id=draft["id"],
        proposal=proposal,
        request=request,
        assets=package["assets"],
    )
    owner.initialize_media_staging()
    owner.initialize_media_commands()
    stage(case)
    cmd = command_for(case)
    case["store"].accept(cmd, ACTOR, now=NOW)
    if issue != "checks":
        changed = deepcopy(initial)
        if issue == "unknown":
            changed["publish_ledger"][draft["event_id"]] = {"phase": "unknown"}
        if issue == "confirmed":
            changed["publish_ledger"][draft["event_id"]] = {"tweet_id": "synthetic-confirmed"}
        if issue == "ambiguous":
            changed["drafts"].append(deepcopy(draft))
        if issue == "source":
            changed["drafts"][0]["review_context"]["two_bot"]["bundle"]["value"] = 999
        if issue == "conflict":
            changed["drafts"][0]["revision_conflicts"] = [{"synthetic": True}]
        # Trusted fixture emulates another producer committing before consumption;
        # no production writer or mutable retained stage is used.
        with case["store"].projections._connection(writing=True) as c:
            case["store"]._state(c, lock=True)
            encoded, fields = p._snapshot(changed)
            case["store"].projections._record(c, "command-core-v1", "1", encoded, fields)
            c.execute(
                "UPDATE theheat_commands.state SET version=1,snapshot_id='1' WHERE singleton=1"
            )
        before = case["store"].read()
        result = case["store"].consume(resolve, now=NOW)
        assert result["status"] == "rejected" and case["store"].read() == before
        assert not snapshot(case)[2]
    else:
        result = case["store"].consume(resolve, now=NOW)
        assert result["status"] == "applied"
        after = case["store"].read()[1]["drafts"][0]
        assert (
            after["status"] == "pending"
            and not review_is_current(after)
            and not approval_is_current(after)
        )
        assert (
            "publish_intent_id" not in after
            and "approval_binding" not in after
            and "review_binding" not in after
        )
        assert set(after["review_context"]["two_bot"]) <= {"bundle", "signal_kind"}
        assert after["revision_history"][-1]["approval_binding"] == original["approval_binding"]


@pytest.mark.parametrize("action", ["attach_media_revision", "remove_media_revision"])
def test_unsupported_actions_and_removal_confirmation_bounds(ready, tmp_path, action):
    cmd = command_for(ready, action=action)
    sqlite = SQLiteAuthority(tmp_path / "unsupported-both.sqlite")
    sqlite.initialize(ready["initial"])
    sqlite.accept(cmd, ACTOR, now=NOW)
    assert sqlite.consume(resolve, now=NOW)["code"] == "media_backend_unsupported"
    assert sqlite.read() == (0, ready["initial"])
    if action == "remove_media_revision":
        for override in (
            {"confirmed": 1},
            {"confirmed": False},
            {"reason": ""},
            {"reason": "x" * 2001},
            {"expected_proposal_sha256": 1},
        ):
            with pytest.raises(CommandError):
                command_for(ready, action=action, overrides=override)
        before = ready["store"].read()
        assert (
            apply(
                ready,
                command_for(ready, action=action, overrides={"expected_proposal_sha256": "f" * 64}),
            )["code"]
            == "media_proposal_changed"
        )
        assert ready["store"].read() == before


def test_role_resolution_happens_after_state_lock_and_policy_change_refuses(ready, monkeypatch):
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    locked = False

    def after(query, _):
        nonlocal locked
        if "FROM theheat_commands.state" in query and "FOR UPDATE" in query:
            locked = True

    def resolver(_):
        assert locked
        return None  # Permission revoked while this accepted command waited.

    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=after)
        assert ready["store"].consume(resolver, now=NOW)["code"] == "forbidden"
    cmd = command_for(ready)
    ready["store"].accept(cmd, ACTOR, now=NOW)
    before = ready["store"].read()
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    assert ready["store"].consume(resolve, now=NOW)["code"] == "editorial_policy_changed"
    assert ready["store"].read() == before
