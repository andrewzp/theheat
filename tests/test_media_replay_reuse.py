"""Pure replay over invented SQL rows and structural PNGs, not native/PG proof."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from src.commands import postgres_editor_media as editor
from src.commands import postgres_media as media
from src.commands import postgres_media_commands as commands
from src.commands.media_journal import MediaJournalError
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_datetime
from src.editorial.revisions import draft_identity, fingerprint
from src.media.joint_review import record_joint_media_review
from src.storage import postgres_projection as p
from tests.test_joint_media_review import ACTOR, payload
from tests.test_media_attachment import AT, proposal, revision
from tests.test_media_journal import package as package
from tests.test_media_review_packet import seed as seed

NOW = utc_datetime(AT)
OWNER, RUNTIME = "invented_owner", "invented_reader"


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class SqlRows:
    """Storage boundary only: real readers verify every byte, guard and transition.

    There is no driver or server. Unknown SQL, including unexpected writes,
    fails rather than silently supplying a successful domain result.
    """

    def __init__(self):
        self.artifacts = {}
        self.packages = {}
        self.reviews = {}
        self.snapshots = {}
        self.intents = {}
        self.results = {}
        self.events = {}
        self.package_reads = 0
        self.catalog_revision = {media.SCHEMA: 0, commands.SCHEMA: 0}
        self.catalog_queries = []
        self.metadata = {}
        for module in (media, commands):
            self.metadata[module.SCHEMA] = [
                1, p._sha(module.MIGRATION.read_bytes()), p._catalog(self, module.SCHEMA),
                "local", OWNER, RUNTIME,
            ]

    def pipeline(self):
        return nullcontext()

    def artifact(self, raw):
        digest = p._sha(raw)
        self.artifacts[digest] = raw
        return digest

    def snapshot(self, namespace, identity, state):
        raw, fields = p._snapshot(state)
        self.snapshots[namespace, identity] = (
            (p._sha(raw), len(raw), len(fields), NOW),
            [(name, self.artifact(value), len(value)) for name, value in fields.items()],
        )

    def command(self, command, result):
        raw = p._canonical(command.as_dict())
        sequence = len(self.intents) + 1
        self.intents[command.command_id] = (sequence, command.digest, raw, AT)
        receipt = dict(command_id=command.command_id, sequence=sequence,
                       accepted_at=AT, digest=command.digest)
        for event, at, value in (("accepted", AT, receipt),
                                 ("completed", result["completed_at"], result)):
            encoded = p._canonical(value)
            self.events[command.command_id, event] = (at, encoded, p._sha(encoded))
        encoded = p._canonical(result)
        version = result["state_version"]
        self.results[command.command_id] = (
            encoded, p._sha(encoded), version, "command-core-v1", str(version),
        )

    def execute(self, query, args=()):
        sql = " ".join(query.split())
        # These are invented catalog query results, not schema/privilege proof.
        # The real catalog digest and both real validators still run each time.
        if "WHERE n.nspname=%s" in sql:
            assert len(args) == 1 and args[0] in self.catalog_revision
            self.catalog_queries.append((args[0], sql))
            return Rows([(args[0], sql, self.catalog_revision[args[0]])])
        if sql == "SELECT 1 FROM pg_namespace WHERE nspname=%s":
            return Rows([(1,)] if args[0] in self.metadata else [])
        if sql.startswith("SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM "):
            return Rows([tuple(self.metadata[sql.split()[3].split('.')[0]])])
        if sql == "SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1":
            return Rows([(OWNER, RUNTIME)])
        if sql == "SELECT 1 FROM theheat_media.packages WHERE proposal_sha256=%s":
            return Rows([(1,)] if args[0] in self.packages else [])
        if sql == "SELECT capture_sha256,staged_at FROM theheat_media.packages WHERE proposal_sha256=%s":
            self.package_reads += 1
            return Rows([self.packages[args[0]]] if args[0] in self.packages else [])
        if sql == "SELECT byte_count,octet_length(payload) FROM theheat_media.artifacts WHERE sha=%s":
            raw = self.artifacts.get(args[0])
            return Rows([(len(raw), len(raw))] if raw is not None else [])
        if sql == "SELECT payload FROM theheat_media.artifacts WHERE sha=%s":
            return Rows([(self.artifacts[args[0]],)])
        if sql.startswith("INSERT INTO theheat_media.artifacts VALUES"):
            digest, raw, count = args
            assert count == len(raw) and digest == p._sha(raw)
            self.artifacts.setdefault(digest, raw)
            return Rows([])
        if sql.startswith("INSERT INTO theheat_media_commands.reviews VALUES"):
            self.reviews[args[0]] = tuple(args[1:])
            return Rows([])
        if sql.startswith("SELECT proposal_sha256,review_sha256,artifact_sha256,reviewed_at FROM theheat_media_commands.reviews "):
            return Rows([self.reviews[args[0]]] if args[0] in self.reviews else [])
        if sql.startswith("SELECT canonical_sha,byte_count,field_count,created_at FROM theheat_projection.versions "):
            found = self.snapshots.get(tuple(args))
            return Rows([found[0]] if found else [])
        if sql.startswith("SELECT f.name_json,f.artifact_sha,a.byte_count FROM theheat_projection.fields "):
            return Rows(self.snapshots[tuple(args[:2])][1])
        if sql.startswith("SELECT a.sha, CASE WHEN octet_length(a.payload)=wanted.byte_count THEN a.payload END FROM theheat_projection.artifacts "):
            return Rows([(digest, self.artifacts[digest] if len(self.artifacts[digest]) == size else None)
                         for digest, size in zip(args[0], args[1]) if digest in self.artifacts])
        if sql.startswith("SELECT sequence,digest,command_bytes,accepted_at FROM theheat_commands.intents "):
            return Rows([self.intents[args[0]]] if args[0] in self.intents else [])
        if sql.startswith("SELECT result_bytes,digest,state_version,namespace,snapshot_id FROM theheat_commands.results "):
            return Rows([self.results[args[0]]] if args[0] in self.results else [])
        if sql.startswith("SELECT recorded_at,data_bytes,digest FROM theheat_commands.events "):
            return Rows([self.events[tuple(args)]] if tuple(args) in self.events else [])
        raise AssertionError(f"Unexpected SQL boundary: {sql}")


def make_command(draft, identity, packet, *, action="attach_media_revision", number=1):
    return Command.from_request(dict(
        command_id=str(UUID(int=number)), action=action, requested_at=AT,
        expires_at="2026-10-02T17:00:00Z", targets=[revision(draft)],
        payload=dict(proposal_sha256=identity, expected_packet_sha256=packet,
                     expected_policy_sha256=fingerprint(draft_policy()), review=payload()),
    ), ACTOR, environment="local", now=NOW, allow_legacy_review=True)


def draft_policy():
    from src.editorial.policy import current_editorial_policy
    return current_editorial_policy()


def outcome(command, transition, version):
    return dict(status="applied", command_id=command.command_id, digest=command.digest,
                actor_subject=command.actor_subject, completed_at=AT, state_version=version,
                media=transition.references, changed_ids=list(transition.reduction.changed_ids),
                identities=list(transition.reduction.identities), publish_intent_id=None)


@pytest.fixture
def replay(package):
    inputs, assets = package["inputs"], package["assets"]
    before = dict(drafts=[deepcopy(inputs["draft"])], publish_ledger={}, unrelated={"preserve": True})
    staged = proposal(inputs, state=before)
    capture = dict(
        schema_version=1,
        predecessor_state=dict(drafts=[deepcopy(inputs["draft"])], publish_ledger={}, posted_events=[]),
        inputs=dict(expected_revision=revision(inputs["draft"]), editorial_policy=inputs["editorial_policy"],
                    graphic_spec=inputs["graphic_spec"], renderer_manifest=inputs["renderer_manifest"], at=AT),
        proposal=staged, asset_sha256={name: p._sha(raw) for name, raw in assets.items()},
        authority_version=0, staged_at=AT,
        submitter=dict(subject=ACTOR.subject, role_at_staging=ACTOR.role,
                       authentication_context=ACTOR.authentication_context),
    )
    sql = SqlRows()
    for raw in assets.values():
        sql.artifact(raw)
    sql.packages[staged["proposal_sha256"]] = (sql.artifact(p._canonical(capture)), AT)
    command = make_command(inputs["draft"], staged["proposal_sha256"], staged["packet"]["packet_sha256"])
    transition = commands.prepare(sql, before, command, ACTOR, now=NOW,
                                  editorial_policy=inputs["editorial_policy"], environment="local")
    result = outcome(command, transition, 1)
    commands.retain(sql, command, transition)
    sql.snapshot("command-core-v1", "0", before)
    sql.snapshot("command-core-v1", "1", transition.reduction.state)
    sql.command(command, result)
    authority = PostgresCommandAuthority.__new__(PostgresCommandAuthority)
    authority.environment = "local"
    authority.projections = p.PostgresProjectionRepository.__new__(p.PostgresProjectionRepository)
    return dict(sql=sql, command=command, result=result, before=before,
                after=transition.reduction.state, transition=transition, authority=authority,
                inputs=inputs, assets=assets, capture=capture)


def independent_review(case):
    proposed = case["capture"]["proposal"]["proposed_draft"]
    return record_joint_media_review(
        proposed, payload=payload(), principal=ACTOR, reviewed_at=AT,
        expected_packet_sha256=case["command"].payload["expected_packet_sha256"],
        expected_draft_identity=draft_identity(proposed),
        **{name: case["inputs"][name] for name in ("editorial_policy", "graphic_spec", "renderer_manifest", "png_bytes")},
    )


def saved_review(case, record):
    sql, command = case["sql"], case["command"]
    prior = sql.reviews[command.command_id]
    sql.reviews[command.command_id] = (prior[0], record["review_sha256"], sql.artifact(p._canonical(record)), prior[3])


def current_inputs(case):
    return dict(profile_sha256="c" * 64, spec=deepcopy(case["inputs"]["graphic_spec"]),
                renderer=deepcopy(case["inputs"]["renderer_manifest"]["binding"]["renderer"]))


def preparation(case):
    draft = case["before"]["drafts"][0]
    cmd = Command.from_request(dict(
        command_id=str(UUID(int=90)), action="prepare_media_revision", requested_at=AT,
        expires_at="2026-10-02T17:00:00Z", targets=[revision(draft)],
        payload=dict(expected_policy_sha256=fingerprint(case["inputs"]["editorial_policy"]),
                     expected_renderer_profile_sha256="c" * 64),
    ), ACTOR, environment="local", now=NOW)
    retained = dict(command_id=cmd.command_id, draft_id=draft["id"],
                    proposal_sha256=case["command"].payload["proposal_sha256"],
                    renderer_profile_sha256="c" * 64)
    result = dict(status="unchanged", command_id=cmd.command_id, digest=cmd.digest,
                  actor_subject=cmd.actor_subject, completed_at=AT, state_version=0,
                  media_preparation=retained)
    case["sql"].snapshot(editor.PREPARATION, retained["proposal_sha256"], retained)
    case["sql"].command(cmd, result)
    return retained


def test_legacy_read_output_matches_independent_joint_review_and_exact_staged_assets(replay):
    case = replay
    expected = independent_review(case)
    assert case["transition"].review == expected
    retained, verified = commands.read_with_package(case["sql"], case["command"], case["result"], "local")
    assert retained == dict(
        command_id=case["command"].command_id, review=expected,
        artifact_sha256=p._sha(p._canonical(expected)),
        proposal_sha256=case["capture"]["proposal"]["proposal_sha256"],
        currentness="not_evaluated", status="historical",
        publication_approved=False, production_attachment_authorized=False,
    )
    assert set(verified) == {"receipt", "capture", "assets"}
    assert verified["capture"] == case["capture"] and verified["assets"] == case["assets"]
    assert commands.read(case["sql"], case["command"], case["result"], "local") == retained
    assert case["after"]["drafts"][0]["media_attachment"] == case["capture"]["proposal"]["proposed_draft"]["media_attachment"]
    assert case["after"]["unrelated"] == {"preserve": True}


def test_each_read_verifies_package_once_and_never_accepts_supplied_package(replay):
    sql = replay["sql"]
    sql.package_reads = 0
    first = commands.read_with_package(sql, replay["command"], replay["result"], "local")
    assert sql.package_reads == 1
    second = commands.read_with_package(sql, replay["command"], replay["result"], "local")
    assert sql.package_reads == 2 and second == first and second[1] is not first[1]
    first[1]["capture"]["proposal"]["proposal_sha256"] = "0" * 64
    assert second[1]["capture"] == replay["capture"]
    supplied = {"package": second[1]}
    with pytest.raises(TypeError, match="package"):
        commands.read_with_package(sql, replay["command"], replay["result"], "local", **supplied)
    assert sql.package_reads == 2
    digest = replay["capture"]["asset_sha256"]["preview.png"]
    sql.artifacts[digest] += b"changed between reads"
    with pytest.raises((p.ProjectionError, MediaJournalError)):
        commands.read_with_package(sql, replay["command"], replay["result"], "local")
    assert sql.package_reads == 3


@pytest.mark.parametrize("mode", ["fresh", "historical"])
@pytest.mark.parametrize("guard,code", [
    ("actor", "forbidden"), ("role", "forbidden"), ("expiry", "command_expired"),
    ("future_request", "invalid_time"), ("policy", "editorial_policy_changed"),
    ("catalog", "changed_media_command_schema"),
])
def test_command_guards_remain_on_fresh_execution_and_historical_replay(replay, mode, guard, code):
    case, command, actor = replay, replay["command"], ACTOR
    if guard == "actor":
        command = replace(command, actor_subject="different-invented-subject")
    elif guard == "role":
        actor = Principal(ACTOR.subject, "viewer", ACTOR.authentication_context)
        record = deepcopy(case["transition"].review)
        record["reviewer"]["role_at_review"] = "viewer"
        saved_review(case, record)
    elif guard == "expiry":
        command = replace(command, expires_at=AT)
    elif guard == "future_request":
        future = "2026-10-01T18:06:00Z"
        command = replace(command, requested_at=future)
        row = case["sql"].reviews[command.command_id]
        case["sql"].reviews[command.command_id] = (*row[:3], future)
    elif guard == "policy":
        command = replace(command, payload_json=canonical_json(command.payload | {"expected_policy_sha256": "0" * 64}))
    else:
        case["sql"].catalog_revision[commands.SCHEMA] += 1
    if mode == "fresh":
        with pytest.raises((CommandError, p.ProjectionError)) as caught:
            commands.prepare(case["sql"], case["before"], command, actor, now=NOW,
                             editorial_policy=case["inputs"]["editorial_policy"], environment="local")
        assert getattr(caught.value, "code", str(caught.value)) == code
    else:
        with pytest.raises(p.ProjectionError, match=(code if guard == "catalog" else "corrupt_media_command_review")) as caught:
            commands.read_with_package(case["sql"], command, case["result"], "local")
        if guard != "catalog":
            assert isinstance(caught.value.__context__, CommandError)
            assert caught.value.__context__.code == code


@pytest.mark.parametrize("mutation", ["review_bytes", "review_record", "proposal", "source", "renderer", "after", "references", "identity"])
def test_retained_corruption_and_rehashed_counterexamples_refuse(replay, mutation):
    case, sql = replay, replay["sql"]
    if mutation == "review_bytes":
        sql.artifacts[sql.reviews[case["command"].command_id][2]] += b" "
    elif mutation == "review_record":
        record = deepcopy(case["transition"].review)
        record["reason"] = "Different retained invented decision."
        record["review_sha256"] = fingerprint({k: v for k, v in record.items() if k != "review_sha256"})
        saved_review(case, record)
    elif mutation in {"proposal", "source", "renderer"}:
        capture = deepcopy(case["capture"])
        if mutation == "proposal":
            capture["proposal"]["proposal_sha256"] = "0" * 64
        elif mutation == "source":
            capture["inputs"]["graphic_spec"]["evidence"]["event_id"] += "-changed"
        else:
            capture["inputs"]["renderer_manifest"]["binding"]["renderer"]["implementation_sha256"] = "0" * 64
        sql.packages[case["command"].payload["proposal_sha256"]] = (sql.artifact(p._canonical(capture)), AT)
    elif mutation == "after":
        changed = deepcopy(case["after"])
        changed["unrelated"]["preserve"] = False
        sql.snapshot("command-core-v1", "1", changed)
    elif mutation == "references":
        case["result"]["media"] = case["result"]["media"] | {"proposal_sha256": "0" * 64}
    else:
        case["result"]["identities"] = [case["result"]["identities"][0] | {"content_revision": 99}]
    with pytest.raises((p.ProjectionError, MediaJournalError)):
        commands.read_with_package(sql, case["command"], case["result"], "local")


def test_reviewed_returns_legacy_package_shape_and_verified_record_without_extra_package_read(replay):
    case = replay
    preparation(case)
    draft, value = case["after"]["drafts"][0], current_inputs(case)
    case["sql"].package_reads = 0
    package, record = editor._reviewed(case["authority"], case["sql"], draft, value,
                                       case["inputs"]["editorial_policy"], lambda subject: ACTOR)
    assert case["sql"].package_reads == 1 and record == independent_review(case)
    assert package["capture"] == case["capture"] and package["assets"] == case["assets"]
    assert editor.reviewed(case["authority"], case["sql"], draft, value,
                           case["inputs"]["editorial_policy"], lambda subject: ACTOR) == package
    assert case["sql"].package_reads == 2


@pytest.mark.parametrize("mutation,code", [
    ("proposal", "media_preparation_not_retained"),
    ("source", "media_source_or_renderer_changed"),
    ("renderer", "media_source_or_renderer_changed"),
    ("profile", "native_renderer_changed"),
    ("record", "joint_media_review_changed"),
    ("role", "forbidden"),
])
def test_current_review_still_binds_exact_package_source_renderer_record_and_role(replay, mutation, code):
    case = replay
    preparation(case)
    draft, value = deepcopy(case["after"]["drafts"][0]), current_inputs(case)
    principal = ACTOR
    if mutation == "proposal":
        draft["media_review_binding"]["proposal_sha256"] = "0" * 64
    elif mutation == "source":
        value["spec"]["evidence"]["event_id"] += "-changed"
    elif mutation == "renderer":
        value["renderer"]["implementation_sha256"] = "0" * 64
    elif mutation == "profile":
        value["profile_sha256"] = "0" * 64
    elif mutation == "record":
        draft["media_review_binding"]["review_sha256"] = "0" * 64
    else:
        principal = Principal(ACTOR.subject, "viewer", "revoked-invented-context")
    with pytest.raises(CommandError) as caught:
        editor.reviewed(case["authority"], case["sql"], draft, value,
                        case["inputs"]["editorial_policy"], lambda subject: principal)
    assert caught.value.code == code


def test_later_review_replays_its_own_before_after_and_policy(replay):
    case = replay
    before = deepcopy(case["after"])
    draft = before["drafts"][0]
    package = media.read(case["sql"], case["command"].payload["proposal_sha256"], "local")
    packet = editor.packet_for(draft, package, case["inputs"]["editorial_policy"])
    command = make_command(draft, case["command"].payload["proposal_sha256"], packet["packet_sha256"],
                           action="review_media_revision", number=2)
    transition = commands.prepare(case["sql"], before, command, ACTOR, now=NOW,
                                  editorial_policy=case["inputs"]["editorial_policy"], environment="local")
    result = outcome(command, transition, 2)
    commands.retain(case["sql"], command, transition)
    case["sql"].snapshot("command-core-v1", "2", transition.reduction.state)
    retained, verified = commands.read_with_package(case["sql"], command, result, "local")
    assert retained["review"] == transition.review
    assert retained["proposal_sha256"] == case["command"].payload["proposal_sha256"]
    assert verified["capture"] == case["capture"]
    assert result["media"]["editorial_policy"] == case["inputs"]["editorial_policy"]
    changed = deepcopy(result)
    changed["media"]["editorial_policy"]["execution_sha256"] = "0" * 64
    with pytest.raises(p.ProjectionError, match="corrupt_media_command_review"):
        commands.read_with_package(case["sql"], command, changed, "local")
