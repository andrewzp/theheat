"""Invented source -> real offline SDK -> saved draft -> native PNG -> fresh checks."""

from datetime import timedelta
import json
import socket
from uuid import uuid4

import pytest

from src.commands import postgres_editor_media as domain
from src.commands.preview_media_worker import consume_media_once
from src.commands.reducer import _identity
from src.commands.schema import Command, canonical_json, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, approval_is_current, review_is_current
from src.media.joint_review import CONFIRMATIONS
from src.two_bot import check_requests
from src.two_bot.check_origin import spending_job
from src.voice import safety
from tests import (
    test_postgres_sourced_generation as sourced,
    test_postgres_candidate_admission as candidate,
)
from tests import test_check_executor as executor
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies

AT = candidate.AT


@pytest.fixture(autouse=True)
def offline_connections(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family != socket.AF_UNIX and (
            not isinstance(address, tuple) or address[0] != "127.0.0.1"
        ):
            raise AssertionError("External fixture connection refused")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def fact_pass(text):
    return json.dumps(
        dict(passed=True, extracted_claims=[dict(text=text, kind="comparison")], failures=[])
    )


@pytest.fixture(params=["modis", "pm25"])
def admitted(request, store, core, tmp_path, monkeypatch, native_dependencies):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-offline-key")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    if request.param == "modis":
        from tests.fire_graphic_helpers import graphic_bundle

        text = "MODIS detected a 500 MW thermal signal in an invented region."
        source_key = "firms"
    else:
        from src.data.air_quality import _parse_single_location, detect_pm25_hazard
        from src.two_bot.intern.air_quality import build_pm25_hazard_bundle
        from tests.air_quality_fixtures import payload

        def graphic_bundle():
            from src.data.places import resolve_place

            place = resolve_place("Kathmandu", "Nepal")
            day = "2026-06-08"
            data = payload(day=day, timezone="Asia/Kathmandu", offset=20700, lat=27.75, lon=85.25)
            data["hourly"]["pm2_5"] = list(range(160, 184))
            observation = _parse_single_location(
                data,
                "Kathmandu",
                "Nepal",
                place["lat"],
                place["lon"],
                day,
                requested_at=day + "T12:00:00Z",
                retrieved_at=day + "T12:00:01Z",
            )
            return build_pm25_hazard_bundle(detect_pm25_hazard(observation))

        text = "The PM2.5 forecast averages 172 micrograms per cubic metre in Kathmandu."
        source_key = "air_quality"
    bundle = graphic_bundle()
    save = dict(
        legacy_type=bundle.signal_kind,
        event_id=bundle.event_id,
        score=None,
        city="",
        tweet_date="",
        cooldown_exempt=False,
        review_context=None,
        evaluator_metadata=None,
    )
    value = dict(
        schema_version=1,
        source_key=source_key,
        source_revision="invented-qualified-one",
        captured_at=utc_text(sourced.NOW),
        useful_until=utc_text(sourced.NOW + timedelta(hours=8)),
        urgent=False,
        bundle=bundle.to_dict(),
        save=save,
    )
    refs = store.retain_generation_input(value)
    reserve = store.retain_generation_reservation(sourced.allowance_document(refs["brief_id"]))
    config = dict(current_inputs=[refs["brief_id"]], reservation=reserve)
    store.configure_sourced_generation(lambda: config)
    case = dict(store=store, refs=refs, value=value, config=config, bundle=bundle, text=text)
    assert sourced.request(case)["status"] == "applied"
    sent, factory = sourced.transport(case, output=text)
    assert sourced.run(case, "submit", factory)["outcome"] == "submitted"
    assert sourced.run(case, "collect", factory)["outcome"] == "reviewed"
    capture = sourced.run(case, "capture")
    assert capture["outcome"] == "candidate_ready", capture
    check_case = dict(store=store, refs=capture["candidate"])
    candidate.request(check_case)
    executor.provider(
        monkeypatch,
        [
            executor.envelope("NO"),
            executor.envelope(fact_pass(text)),
            executor.envelope(executor.CRITIC_PASS),
        ],
    )
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        checked = candidate.run_stage(check_case, stage)
        assert checked.get("checks", {}).get("stages", {}).get(stage) == "passed", (stage, checked)
    result = candidate.consume(check_case, candidate.command(check_case, "admit_checked_candidate"))
    assert result["status"] == "applied", result
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    core[2].initialize_revision_checks(now=AT)
    store.configure_editor_media(**native_dependencies, scratch=tmp_path / "native")
    case.update(draft_id=result["candidate"]["draft_id"], provider_requests=sent)
    return case


def view(case, *, now=AT, resolve=candidate.resolve, png=None):
    authority = case["store"]
    with authority.projections._connection() as c:
        authority._validate(c)
        version, state = authority._state(c, lock=True)
        return domain.projection(
            authority,
            c,
            case["draft_id"],
            state=state,
            version=version,
            policy=current_editorial_policy(),
            now=now,
            resolve_principal=resolve,
            png_proposal=png,
        )


def action(case, name, payload, *, actor=candidate.EDITOR, at=AT, target=None):
    store = case["store"]
    draft = next(d for d in store.read()[1]["drafts"] if d["id"] == case["draft_id"])
    command = Command.from_request(
        dict(
            command_id=str(uuid4()),
            action=name,
            requested_at=utc_text(at),
            expires_at=utc_text(at + timedelta(minutes=5)),
            targets=[target or _identity(draft)],
            payload=payload,
        ),
        actor,
        environment="local",
        now=at,
    )
    store.accept(command, actor, now=at)
    if name == "prepare_media_revision":
        result = consume_media_once(store, candidate.resolve, command_id=command.command_id, now=at)
    else:
        result = store.consume(candidate.resolve, command_id=command.command_id, now=at)
    return command, result


def prepare_and_attach(case):
    current = view(case)
    assert current["status"] == "ready", current
    prepare, result = action(
        case,
        "prepare_media_revision",
        {k: current[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
    )
    assert result["status"] == "unchanged", result
    assert (
        consume_media_once(case["store"], candidate.resolve, command_id=prepare.command_id, now=AT)
        == result
    )
    prepared = view(case)
    assert prepared["status"] == "prepared", prepared
    png = view(case, png=prepared["preparation"]["proposal_sha256"])
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 1000
    _, attached = action(
        case,
        "attach_media_revision",
        dict(
            proposal_sha256=prepared["preparation"]["proposal_sha256"],
            expected_policy_sha256=prepared["expected_policy_sha256"],
            expected_packet_sha256=prepared["packet"]["packet_sha256"],
            review=dict(
                decision="accept",
                confirmations={k: True for k in CONFIRMATIONS},
                reason="Invented source, text, labels and full alt reviewed together.",
            ),
        ),
    )
    assert attached["status"] == "applied", attached
    return prepared, png


def complete_revision(case, monkeypatch):
    current = view(case)
    _, result = action(
        case,
        "request_revision_checks",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
        ),
    )
    assert result["status"] == "unchanged", result
    sent, _ = executor.provider(
        monkeypatch,
        [
            executor.envelope("NO"),
            executor.envelope(fact_pass(case["text"])),
            executor.envelope(executor.CRITIC_PASS),
        ],
    )
    store = case["store"]
    packet = store.check_execution(
        "read", {"check_set_id": result["revision_checks"]["check_set_id"]}, now=utc_text(AT)
    )["packet"]
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        request = canonical_json(check_requests.prepare_request(packet, stage)).encode()
        reservation = (
            None
            if stage == "deterministic"
            else dict(
                intent_id="media-" + packet["enrollment_id"][:12] + "-" + stage,
                job_id=spending_job(packet),
                request_sha256=domain.p._sha(request),
                provider="google",
                role=stage,
                model=packet["policy"]["models"][stage],
                estimate_sha256="e" * 64,
                reserve_micro_usd=5,
            )
        )
        report = store.execute_revision_check_once(
            result["command_id"],
            candidate.resolve,
            clock=lambda: utc_text(AT),
            reservation=reservation,
            enabled=True,
        )
        assert report["outcome"] == "completed", report
        assert report["checks"]["stages"][stage] == "passed", report
    assert len(sent) == 3
    return result


def request_revision(case):
    current = view(case)
    command, result = action(
        case,
        "request_revision_checks",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
        ),
    )
    assert result["status"] == "unchanged", result
    packet = case["store"].check_execution(
        "read", {"check_set_id": result["revision_checks"]["check_set_id"]}, now=utc_text(AT)
    )["packet"]
    return command, result["revision_checks"]["check_set_id"], packet


def run_revision(
    case, command, packet, stage, *, clock=lambda: utc_text(AT), resolve=candidate.resolve
):
    raw = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    reservation = (
        None
        if stage == "deterministic"
        else dict(
            intent_id="media-" + packet["enrollment_id"][:12] + "-" + stage,
            job_id=spending_job(packet),
            request_sha256=domain.p._sha(raw),
            provider="google",
            role=stage,
            model=packet["policy"]["models"][stage],
            estimate_sha256="e" * 64,
            reserve_micro_usd=5,
        )
    )
    return case["store"].execute_revision_check_once(
        command.command_id, resolve, clock=clock, reservation=reservation, enabled=True
    )


def test_qualified_native_attachment_fresh_checks_single_park_and_edit(admitted, monkeypatch, core):
    case = admitted
    before = case["store"].read()
    prepared, png = prepare_and_attach(case)
    assert view(case)["review_current"] is True
    complete_revision(case, monkeypatch)
    current = view(case)
    assert current["checks_status"] == "passed", current
    _, result = action(
        case,
        "approve_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
            expected_check_completion_sha256=current["expected_check_completion_sha256"],
            reason="Park this invented local review only.",
        ),
        actor=candidate.PUBLISHER,
    )
    assert result["status"] == "applied", result
    parked = view(case)
    assert parked["parked"] is True, parked
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert (
        draft["status"] == "pending"
        and not approval_is_current(draft)
        and not review_is_current(draft)
    )
    assert not set(draft) & {"approved_at", "publish_requested_at", "auto_approve_at"}
    assert case["store"].read()[1]["drafts"][0] == before[1]["drafts"][0]
    assert len(case["provider_requests"]) == 3
    _, edited = action(
        case, "edit_revision", {"text": case["text"].replace(".", " in this invented test.")}
    )
    assert edited["status"] == "applied"
    stale = view(case)
    assert not stale["parked"] and not stale["review_current"]
    assert view(case, png=prepared["preparation"]["proposal_sha256"]) == png


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("drift", ["source", "role", "policy", "renderer", "state", "lease"])
def test_postgrant_drift_retains_exact_raw_unknown_charge_without_promotion(
    admitted, monkeypatch, drift
):
    from src.two_bot.check_transport import GoogleCheckTransport
    from src.commands.schema import CommandError

    case = admitted
    prepare_and_attach(case)
    command, identity, packet = request_revision(case)
    assert run_revision(case, command, packet, "deterministic")["outcome"] == "completed"
    raw = executor.envelope("NO")
    sent, _ = executor.provider(monkeypatch, [raw])
    now, revoked = [AT], [False]

    def resolve(subject):
        return (
            None
            if revoked[0] and subject == candidate.EDITOR.subject
            else candidate.resolve(subject)
        )

    original = GoogleCheckTransport.execute

    def execute(transport, request):
        if drift == "source":
            case["config"]["current_inputs"].clear()
        elif drift == "role":
            revoked[0] = True
        elif drift == "policy":
            monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
        elif drift == "renderer":
            old = domain.profile
            monkeypatch.setattr(domain, "profile", lambda *args: ("e" * 64, old(*args)[1]))
        elif drift == "state":
            _, result = action(
                case,
                "edit_revision",
                {"text": "MODIS detected a thermal signal in this invented test."},
            )
            assert result["status"] == "applied"
        else:
            now[0] += timedelta(seconds=301)
        return original(transport, request)

    monkeypatch.setattr(GoogleCheckTransport, "execute", execute)
    report = run_revision(
        case, command, packet, "safety", clock=lambda: utc_text(now[0]), resolve=resolve
    )
    assert report["outcome"] == "reconciliation_required", report
    retained = case["store"].check_execution(
        "read", {"check_set_id": identity}, now=utc_text(now[0])
    )
    attempt = retained["attempts"]["safety"]
    assert attempt["observation"]["raw_sha256"] == domain.p._sha(raw)
    assert case["store"].read_check_response(identity, "safety", attempt["grant_id"]) == raw
    with case["store"].projections._connection() as connection:
        assert domain.checks._terminal(connection, attempt) is None
    money = case["store"].spending("status", {}, now=utc_text(now[0]))
    assert money["totals"]["held_micro_usd"] >= 5 and money["accounting_complete"] is False
    try:
        blocked = run_revision(
            case, command, packet, "safety", clock=lambda: utc_text(now[0]), resolve=resolve
        )
    except CommandError:
        pass
    else:
        assert (
            blocked["outcome"] == "reconciliation_required"
            and not blocked["required_checks_completed"]
        )
    assert len(sent) == 1


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_edit_rereview_fresh_enrollment_cancel_and_remove(admitted, monkeypatch):
    case = admitted
    prepared, png = prepare_and_attach(case)
    initial = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    _, changed = action(
        case, "edit_revision", {"text": "MODIS detected a thermal signal in this invented test."}
    )
    assert changed["status"] == "applied"
    current = view(case)
    assert current["status"] == "attached" and not current["review_current"]
    _, result = action(
        case,
        "review_media_revision",
        dict(
            proposal_sha256=current["preparation"]["proposal_sha256"],
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            review=dict(
                decision="accept",
                confirmations={k: True for k in CONFIRMATIONS},
                reason="Reviewed the edited statement and unchanged qualified graphic.",
            ),
        ),
    )
    assert result["status"] == "applied", result
    updated = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert updated["content_revision"] == initial["content_revision"] + 1
    assert view(case)["review_current"]
    case["text"] = updated["text"]
    complete_revision(case, monkeypatch)
    current = view(case)
    _, result = action(
        case,
        "approve_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
            expected_check_completion_sha256=current["expected_check_completion_sha256"],
            reason="Local only",
        ),
        actor=candidate.PUBLISHER,
    )
    assert result["status"] == "applied"
    assert (
        action(case, "cancel_approval", {"reason": "Cancel the local parked decision"})[1]["status"]
        == "applied"
    )
    current = view(case)
    assert not current["parked"]
    _, removed = action(
        case,
        "remove_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_proposal_sha256=current["removal"]["expected_proposal_sha256"],
            confirmed=True,
            reason="Remove the graphic",
        ),
    )
    assert removed["status"] == "applied", removed
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert (
        "media_attachment" not in draft
        and "media_review_binding" not in draft
        and "approval_binding" not in draft
    )
    assert view(case, png=prepared["preparation"]["proposal_sha256"]) == png


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("outage", ["expired", "renderer", "delisted"])
def test_removal_remains_available_during_source_or_renderer_outage(admitted, monkeypatch, outage):
    case = admitted
    prepared, png = prepare_and_attach(case)
    at = AT
    if outage == "expired":
        at += timedelta(hours=9)
    elif outage == "delisted":
        case["config"]["current_inputs"].clear()
    else:
        monkeypatch.setattr(
            domain, "profile", lambda *args: domain.refuse(False, "native_renderer_unavailable")
        )
    current = view(case, now=at)
    assert current["status"] == "unavailable" and current["removal"]
    assert not current["review_current"] and not current["parked"]
    _, result = action(
        case,
        "remove_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_proposal_sha256=current["removal"]["expected_proposal_sha256"],
            confirmed=True,
            reason="Remove stale graphic",
        ),
        at=at,
    )
    assert result["status"] == "applied", result
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    assert (
        "media_attachment" not in draft
        and "media_review_binding" not in draft
        and "approval_binding" not in draft
    )
    assert view(case, now=at, png=prepared["preparation"]["proposal_sha256"]) == png


def all_application_rows(params):
    names = admin(
        params,
        "SELECT schemaname,tablename FROM pg_tables WHERE schemaname LIKE %s ORDER BY 1,2",
        ("theheat_%",),
    )
    return {
        (schema, table): admin(params, f'SELECT * FROM "{schema}"."{table}" ORDER BY 1,2')
        for schema, table in names
    }


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_complete_native_check_park_dump_restore_and_resumption(
    admitted, monkeypatch, core, cluster
):
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options

    case = admitted
    prepared, png = prepare_and_attach(case)
    complete_revision(case, monkeypatch)
    current = view(case)
    cmd, park = action(
        case,
        "approve_media_revision",
        dict(
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_renderer_profile_sha256=current["expected_renderer_profile_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            expected_review_sha256=current["expected_review_sha256"],
            expected_check_completion_sha256=current["expected_check_completion_sha256"],
            reason="Invented restored review only",
        ),
        actor=candidate.PUBLISHER,
    )
    assert park["status"] == "applied" and view(case)["parked"]
    before = all_application_rows(core[3])
    state = case["store"].read()
    projected = view(case)
    params, run, directory = cluster
    dump = directory / ("full-media-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = dict(core[3], dbname=name)
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        authority = PostgresCommandAuthority(**options(restored_params))
        authority.configure_sourced_generation(lambda: case["config"])
        authority.configure_editor_media(**case["store"].editor_media_configuration)
        restored = dict(case, store=authority)
        assert authority.read() == state and all_application_rows(restored_params) == before
        assert view(restored) == projected and view(restored)["parked"]
        assert view(restored, png=prepared["preparation"]["proposal_sha256"]) == png
        assert authority.consume(candidate.resolve, command_id=cmd.command_id, now=AT) == park
        assert all_application_rows(restored_params) == before
        owner = PostgresCommandAuthority(**options(restored_params, "projection_owner"))
        owner.initialize_revision_checks(now=AT)
        assert all_application_rows(restored_params) == before
        # Resumption preserves the same approval authority; editing invalidates it.
        assert (
            action(
                restored,
                "edit_revision",
                {"text": "An edited statement after a complete invented restore."},
            )[1]["status"]
            == "applied"
        )
        assert not view(restored)["parked"]
        assert view(restored, png=prepared["preparation"]["proposal_sha256"]) == png
    finally:
        admin(
            params,
            psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)),
        )


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
def test_saved_origin_union_constraints_and_concurrent_expiring_leases(admitted, core):
    from concurrent.futures import ThreadPoolExecutor
    from src.commands.check_journal import CheckJournalError

    case = admitted
    prepare_and_attach(case)
    _, identity, packet = request_revision(case)
    params = core[3]
    store = case["store"]
    before = all_application_rows(params)
    row = admin(params, "SELECT * FROM theheat_checks.sets WHERE check_set_id=%s", (identity,))[0]
    columns = [
        r[0]
        for r in admin(
            params,
            "SELECT column_name FROM information_schema.columns WHERE table_schema='theheat_checks' AND table_name='sets' ORDER BY ordinal_position",
        )
    ]
    values = dict(zip(columns, row, strict=True))
    negatives = [
        dict(draft_namespace=None),
        dict(draft_enrollment_id=None),
        dict(origin_kind=None),
        dict(origin_kind="unrecognized"),
        dict(origin_kind="batch_candidate"),
        dict(draft_namespace="another-namespace"),
        dict(job_id="fake-job"),
        dict(custom_id="fake-custom"),
        dict(draft_enrollment_id="f" * 64),
        {},
    ]
    for change in negatives:
        altered = dict(
            values,
            check_set_id=__import__("hashlib").sha256(str(change).encode()).hexdigest(),
            **change,
        )
        with pytest.raises(Exception):
            admin(
                params,
                "INSERT INTO theheat_checks.sets("
                + ",".join(columns)
                + ") VALUES("
                + ",".join(["%s"] * len(columns))
                + ")",
                tuple(altered[k] for k in columns),
            )
    assert all_application_rows(params) == before
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: store.acquire_check_lease(identity, "revision-one", 5, now=utc_text(AT)),
                range(2),
            )
        )
    assert results[0] == results[1] and results[0]["lease"]["fence"] == 1
    with pytest.raises(CheckJournalError, match="revision_check_lease_busy"):
        store.acquire_check_lease(identity, "revision-two", 5, now=utc_text(AT))
    second = store.acquire_check_lease(
        identity, "revision-two", 5, now=utc_text(AT + timedelta(seconds=5))
    )
    assert second["lease"]["fence"] == 2
    assert admin(
        params,
        "SELECT fence FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence",
        (identity,),
    ) == [(1,), (2,)]
    with pytest.raises(Exception):
        admin(
            params,
            "INSERT INTO theheat_checks.draft_leases(check_set_id,fence,owner,recorded_at,expires_at) VALUES(%s,4,'bad','2026-09-29T12:05:12.000000Z','2026-09-29T12:05:17.000000Z')",
            (identity,),
        )


@pytest.mark.parametrize("admitted", ["modis"], indirect=True)
@pytest.mark.parametrize("phase", ["package", "result", "timeout", "lost_ack", "source_drift"])
def test_native_failures_restart_without_partial_asset_or_false_success(
    admitted, core, monkeypatch, phase
):
    from src.commands import preview_media_worker as worker
    from tests.test_postgres_projection import wrap_connections

    case = admitted
    store = case["store"]
    current = view(case)
    draft = next(d for d in store.read()[1]["drafts"] if d["id"] == case["draft_id"])
    cmd = Command.from_request(
        dict(
            command_id=str(uuid4()),
            action="prepare_media_revision",
            requested_at=utc_text(AT),
            expires_at=utc_text(AT + timedelta(minutes=5)),
            targets=[_identity(draft)],
            payload={
                k: current[k]
                for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")
            },
        ),
        candidate.EDITOR,
        environment="local",
        now=AT,
    )
    store.accept(cmd, candidate.EDITOR, now=AT)
    before = all_application_rows(core[3])
    state = store.read()
    if phase in {"package", "result"}:
        table = "theheat_media.packages" if phase == "package" else "theheat_commands.results"

        def fail(query, c):
            if query.startswith("INSERT INTO " + table):
                raise RuntimeError("native commit interrupted")

        with monkeypatch.context() as patch:
            wrap_connections(patch, after_execute=fail)
            with pytest.raises(RuntimeError, match="native commit interrupted"):
                consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)
        assert all_application_rows(core[3]) == before
        assert (
            consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)[
                "status"
            ]
            == "unchanged"
        )
    elif phase == "timeout":
        with monkeypatch.context() as patch:

            def timeout(*args, **kwargs):
                raise worker.subprocess.TimeoutExpired("invented native child", 45)

            patch.setattr(worker, "run_native", timeout)
            result = consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)
        assert result["status"] == "rejected" and result["code"] == "native_render_timeout"
        assert admin(core[3], "SELECT count(*) FROM theheat_media.packages") == [(0,)]
    elif phase == "source_drift":
        original = worker.run_native

        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            case["config"]["current_inputs"].clear()
            return result

        with monkeypatch.context() as patch:
            patch.setattr(worker, "run_native", change)
            result = consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)
        assert result["status"] == "rejected"
        assert admin(core[3], "SELECT count(*) FROM theheat_media.packages") == [(0,)]
    else:
        original = store.consume

        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("acknowledgement lost")

        with monkeypatch.context() as patch:
            patch.setattr(store, "consume", lost)
            with pytest.raises(OSError, match="acknowledgement lost"):
                consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)
        retained = store.result(cmd.command_id)
        with monkeypatch.context() as patch:
            patch.setattr(
                worker,
                "run_native",
                lambda *a, **k: pytest.fail("An accepted package must not render again"),
            )
            assert (
                consume_media_once(store, candidate.resolve, command_id=cmd.command_id, now=AT)
                == retained
            )
    assert store.read() == state
