"""Existing preview TLS identity through one invented, real-clock workflow.

No Neon connection, account data, provider network, public delivery or clock freeze.
The operator review is simulated, not independent human/scientific evidence.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
import requests
import responses

from src.commands import (
    hosted_fixture,
    postgres_delivery as delivery,
    postgres_published_media as published,
)
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators, PreviewServer
from src.commands.preview_media_worker import consume_media_once
from src.commands.preview_delivery_worker import execute_delivery_once
from src.commands.schema import canonical_json, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.media import published_radar as radar
from src.media.joint_review import CONFIRMATIONS
from src.storage import hosted_staging as h, postgres_projection as p
from src.two_bot import check_requests
from src.two_bot.check_origin import spending_job
from tests import published_radar_fixtures as f, test_postgres_hosted_staging as tls
from tests import (
    test_postgres_sourced_generation as source,
    test_postgres_synchronous_generation as sync,
)
from tests import test_postgres_editor_media as editor, test_check_executor as executor
from tests import test_postgres_delivery as delivery_tests
from tests.local_delivery_helpers import fixture_server
from tests.test_spend_journal import LIMITS
from tests.test_postgres_hosted_staging import (
    tls_cluster as tls_cluster,
    tls_database as base_tls_database,
)
from tests.test_postgres_hosted_staging import isolated_environment as isolated_environment
from tests.native_profile_helpers import native_dependencies as native_dependencies

SCHEMAS = (
    "theheat_projection",
    "theheat_commands",
    "theheat_spending",
    "theheat_batches",
    "theheat_batch_work",
    "theheat_batch_results",
    "theheat_checks",
    "theheat_check_executions",
    "theheat_media",
    "theheat_media_commands",
    "theheat_delivery",
)


@pytest.fixture
def tls_database(tls_cluster, monkeypatch, tmp_path):
    # Capture every physical PostgreSQL connection from before this database's
    # bootstrap, including libpq children. Cluster creation is a separate local
    # test prerequisite, and post-test DROP cleanup is not a hosted operation.
    log = tls_cluster[0] / "server.log"
    (tmp_path / "connection-log-start").write_text(str(log.stat().st_size))
    fixture = base_tls_database.__wrapped__(tls_cluster, monkeypatch)
    value = next(fixture)
    try:
        yield value
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


RESTART_CHILD = """import json,sys,psycopg
from datetime import datetime,UTC
from src.storage import hosted_staging as h
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators
from src.commands import postgres_delivery
from src.commands.preview_delivery_worker import execute_delivery_once
from src.commands.schema import utc_text
v=json.load(sys.stdin);h._PORT=v['port'];calls=[];original=psycopg.connect
def counted(*args,**kwargs):
    calls.append(dict(host=kwargs.get('host'),database=kwargs.get('dbname'),user=kwargs.get('user')))
    return original(*args,**kwargs)
psycopg.connect=counted
a=PostgresCommandAuthority.for_hosted_staging(h.HostedStagingConfig.load(v['config'],trusted_identity=v['identity']))
o=Operators(v['operators'])
if v['operation']=='reconcile':
    postgres_delivery.configure(a,v['delivery'])
    result=execute_delivery_once(a,v['intent'],'bluesky','create',o.resolve,owner='invented-h2-restarted',clock=lambda:utc_text(datetime.now(UTC)),enabled=True,reconcile=True)
    assert result['outcome']=='confirmed' and result['reconciled']
elif v['operation']=='inspect':
    result=dict(state=a.read(),costs=a.local_cost_projection(now=datetime.now(UTC)))
else:
    assert v['operation']=='resume'
    result=a.consume(o.resolve,command_id=v['pending'])
    assert result['status']=='applied'
    assert a.consume(o.resolve,command_id=v['pending'])==result
print(json.dumps(dict(result=result,dials=calls)))
"""


def restart(config, *, port, operators, operation, **values):
    packet = dict(config=str(config.config_path), identity=str(config.identity_path),
                  port=port, operators=str(operators), operation=operation, **values)
    child = subprocess.run([sys.executable, "-c", RESTART_CHILD], input=json.dumps(packet),
                           text=True, capture_output=True, check=True, timeout=30)
    return json.loads(child.stdout)


def connection_receipt(tls_cluster, tmp_path, in_process, children):
    log = tls_cluster[0] / "server.log"
    offset = int((tmp_path / "connection-log-start").read_text())
    raw = log.read_bytes()[offset:]
    (tmp_path / "physical-connections.log").write_bytes(raw)
    received = [line for line in raw.decode().splitlines() if "connection received:" in line]
    authorized = [line for line in raw.decode().splitlines() if "connection authorized:" in line]
    assert len(received) == len(authorized)  # No uncounted failed/ongoing dial.
    roles = {}
    for line in authorized:
        user = re.search(r"user=(\S+)", line)[1]
        roles[user] = roles.get(user, 0) + 1
    child_count = sum(len(item["dials"]) for item in children)
    # One source-database bootstrap before the in-process counter, and one
    # physical connection for each non-parallel pg_dump/pg_restore invocation.
    assert len(received) == len(in_process) + child_count + 3
    return dict(physical_dials=len(received), in_process_dials=len(in_process),
                child_dials=child_count, bootstrap_dials=1, dump_restore_dials=2,
                roles=roles, server_log_sha256=hashlib.sha256(raw).hexdigest(),
                post_test_local_cleanup_excluded=True)


def now():
    return datetime.now(UTC)


def clock():
    return utc_text(now())


def install(tls_database, *, full=True):
    owner, runtime, args = tls.authorities(tls_database)
    owner.initialize(
        {"drafts": [], "unknown_fixture": {"typed": [1, 1.0, None, -0.0]}},
        runtime_role="fixture_runtime",
    )
    if full:
        for name in (
            "spending",
            "batches",
            "batch_workers",
            "batch_results",
            "candidate_checks",
            "check_executions",
            "media_staging",
            "media_commands",
        ):
            getattr(owner, "initialize_" + name)()
        owner.initialize_synchronous_checks(now=now())
    else:
        owner.initialize_media_staging()
    owner.initialize_delivery(now=now())
    if full:
        runtime.spending("configure", LIMITS, now=clock())
    return owner, runtime, args


@contextmanager
def server(authority, tmp_path):
    operators = Operators(
        tls.private_json(
            tmp_path / "operators.json",
            {
                "operators": [
                    dict(
                        username=role,
                        password="invented-" + role,
                        subject="invented-" + role,
                        role=role,
                    )
                    for role in ("editor", "publisher", "viewer")
                ]
            },
        )
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(probe.getsockname()[1])
    listener = PreviewServer.for_hosted_fixture(authority, operators, port=0, origin=origin)
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    trace = []

    def http(method, route, *, role="editor", body=None, status=200, headers=None):
        response = requests.request(
            method,
            f"http://127.0.0.1:{listener.server_port}" + route,
            auth=None if role is None else (role, "invented-" + role),
            json=body,
            headers={"Origin": origin, **(headers or {})},
            timeout=20,
        )
        trace.append((method, route, response.status_code))
        assert response.status_code == status, response.text
        return response

    http.origin = origin
    http.port = listener.server_port
    try:
        yield http, operators, trace
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(5)
        assert not thread.is_alive()


def action(http, authority, operators, name, payload, *, draft=None, role="editor", consume=True):
    at = now()
    body = dict(
        command_id=str(uuid4()),
        action=name,
        requested_at=utc_text(at),
        expires_at=utc_text(at + timedelta(minutes=10)),
        targets=[] if draft is None else [editor._identity(draft)],
        payload=payload,
    )
    http("POST", "/commands", role=role, body=body, status=202)
    if not consume:
        return body, None
    if name == "prepare_media_revision":
        result = consume_media_once(authority, operators.resolve, command_id=body["command_id"])
    else:
        result = authority.consume(operators.resolve, command_id=body["command_id"])
    assert result["status"] in {"applied", "unchanged"}, result
    actual = http("GET", "/commands/" + body["command_id"]).json()
    assert actual["result"] == result
    return body, result


def check_stages(authority, operators, command, identity, text, *, revision):
    packet = authority.check_execution("read", {"check_set_id": identity}, now=clock())["packet"]
    sent = []
    messages = iter(
        (
            executor.envelope("NO"),
            executor.envelope(editor.fact_pass(text)),
            executor.envelope(executor.CRITIC_PASS),
        )
    )

    def respond(request):
        assert request.method == "POST" and request.url.host == "generativelanguage.googleapis.com"
        sent.append(request.content)
        return httpx.Response(200, stream=httpx.ByteStream(next(messages)))

    options = dict(api_key="invented-explicit-only", http_transport=httpx.MockTransport(respond))
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        raw = canonical_json(check_requests.prepare_request(packet, stage)).encode()
        reservation = (
            None
            if stage == "deterministic"
            else dict(
                intent_id=("revision-" if revision else "initial-") + stage,
                job_id=spending_job(packet),
                request_sha256=hashlib.sha256(raw).hexdigest(),
                provider="google",
                role=stage,
                model=packet["policy"]["models"][stage],
                estimate_sha256="e" * 64,
                reserve_micro_usd=5,
            )
        )
        execute = (
            authority.execute_revision_check_once
            if revision
            else authority.execute_candidate_check_once
        )
        result = execute(
            command["command_id"],
            operators.resolve,
            clock=clock,
            reservation=reservation,
            enabled=True,
            transport_options=options,
        )
        assert result["outcome"] == "completed" and result["checks"]["stages"][stage] == "passed", (
            result
        )
    assert len(sent) == 3
    return sent


def actual_bundle(at):
    # Reuse the accepted captured-feature constructor; only this new invented
    # event's acquisition/issuance interval changes. Production clocks stay real.
    item = f.feature(at)
    properties = item["properties"]
    for key in ("sent", "effective", "onset"):
        properties[key] = utc_text(at - timedelta(minutes=2))
    properties["expires"] = utc_text(at + timedelta(minutes=45))
    properties["ends"] = utc_text(at + timedelta(minutes=30))
    from src.data.nws_alerts import fetch_alerts
    from src.two_bot.intern.disasters import build_severe_weather_bundle

    with responses.RequestsMock() as calls:
        calls.add(responses.GET, radar.ALERT_URL, json={"features": [item]}, status=200)
        alerts = fetch_alerts(strict=True)
        assert len(calls.calls) == 1 and len(alerts) == 1
    return build_severe_weather_bundle(alerts[0])


def snapshot(args):
    """Bounded exact application rows plus catalogs, ACL/default ACL and sequences."""
    with psycopg.connect(**args) as c:
        actual = tuple(
            v[0]
            for v in c.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'theheat_%' ORDER BY 1"
            )
        )
        assert actual == tuple(sorted(SCHEMAS))
        relations = c.execute(
            "SELECT n.nspname,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','S') ORDER BY 1,2",
            (list(SCHEMAS),),
        ).fetchall()
        rows = {}
        total = 0
        size = 0
        for schema, name, kind in relations:
            query = psycopg.sql.SQL("SELECT * FROM {}.{} LIMIT 4097").format(
                psycopg.sql.Identifier(schema), psycopg.sql.Identifier(name)
            )
            values = c.execute(query).fetchall()
            if kind == "S":
                # pg_restore may normalize an unused sequence's physical last
                # value; the next effective number remains the durable meaning.
                last, log_count, called = values[0]
                values = [(last + 1 if called else last,)]
            total += len(values)
            assert total <= 4096
            rows[(schema, name)] = sorted(values, key=repr)
            size += sum(len(repr(v).encode()) for v in values)
            assert size <= 16 * 1024 * 1024
        catalogs = {s: p._catalog(c, s) for s in SCHEMAS}
        acls = c.execute(
            "SELECT n.nspname,c.relname,c.relacl::text,pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2",
            (list(SCHEMAS),),
        ).fetchall()
        defaults = c.execute(
            "SELECT pg_get_userbyid(d.defaclrole),n.nspname,d.defaclobjtype,d.defaclacl::text FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2,3",
            (list(SCHEMAS),),
        ).fetchall()
        memberships = c.execute("SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),admin_option,inherit_option,set_option FROM pg_auth_members WHERE pg_get_userbyid(member) IN ('fixture_owner','fixture_runtime') ORDER BY 1,2").fetchall()
        assert memberships == []
        roles = c.execute(
            "SELECT rolname,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,rolinherit,rolconnlimit FROM pg_roles WHERE rolname IN ('fixture_owner','fixture_runtime') ORDER BY 1"
        ).fetchall()
    return dict(
        rows=rows,
        catalogs=catalogs,
        acls=acls,
        defaults=defaults,
        roles=roles,
        memberships=memberships,
        row_count=total,
        bytes=size,
    )


def test_continuous_preview_tls_source_radar_delivery_cost_restore(
    tls_database, tls_cluster, tmp_path, monkeypatch, native_dependencies, record_property
):
    started = time.monotonic()
    from src.voice import safety

    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-availability-only")
    original_connect = psycopg.connect
    dials = []
    children = []
    phases = []

    def phase(name):
        offset = int((tmp_path / "connection-log-start").read_text())
        raw = (tls_cluster[0] / "server.log").read_bytes()[offset:]
        total = raw.count(b"connection received:")
        phases.append(dict(name=name, total=total,
                           dials=total - (phases[-1]["total"] if phases else 0)))


    def counted(*args, **kwargs):
        dials.append(
            dict(host=kwargs.get("host"), dbname=kwargs.get("dbname"), user=kwargs.get("user"))
        )
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", counted)
    original_socket = socket.socket.connect

    def guarded(sock, address):
        assert sock.family == socket.AF_UNIX or (
            isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}
        ), address
        return original_socket(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    from tests import test_postgres_cost_projection as cost_tests

    original_cost = PostgresCommandAuthority.local_cost_projection

    def passive_cost(authority, *, now):
        with monkeypatch.context() as patch:
            cost_tests.published_cost_traps(patch)
            return original_cost(authority, now=now)

    monkeypatch.setattr(PostgresCommandAuthority, "local_cost_projection", passive_cost)
    owner, store, args = install(tls_database)
    phase("source_database_bootstrap_and_catalog_install")
    at = now().replace(second=0, microsecond=0)
    bundle = actual_bundle(at)
    value = dict(
        schema_version=1,
        source_key="nws_alerts",
        source_revision="invented-h2-warning",
        captured_at=utc_text(at),
        useful_until=utc_text(at + timedelta(minutes=30)),
        urgent=True,
        bundle=bundle.to_dict(),
        save=dict(
            legacy_type=bundle.signal_kind,
            event_id=bundle.event_id,
            score=None,
            city="",
            tweet_date="",
            cooldown_exempt=False,
            review_context=None,
            evaluator_metadata=None,
        ),
    )
    refs = store.retain_generation_input(value)
    reserve = store.retain_generation_reservation(
        source.allowance_document(
            refs["brief_id"],
            now=at,
            schema_version=2,
            execution_mode="synchronous",
            samples=1,
            max_attempts=1,
            read_budget_seconds=180,
        )
    )
    config = dict(
        schema_version=2,
        current_inputs=[refs["brief_id"]],
        reservations=dict(batch=None, synchronous=reserve),
    )
    store.configure_sourced_generation(lambda: config)
    store.configure_editor_media(**native_dependencies, scratch=tmp_path / "native")
    doc, original, references, receipt = f.input_document(at=at)
    retained = published.retain(store, doc, original, references, receipt)
    selection = dict(schema_version=1, selections={refs["brief_id"]: retained["input_sha256"]})
    published.configure(store, lambda: selection)
    phase("retained_source_reservation_and_media_configuration")
    text = "The NWS has issued a tornado warning for the invented test area."
    with server(store, tmp_path) as (http, operators, http_trace):
        http("GET", "/state", role=None, status=401)
        http("GET", "/state", headers={"Origin": "http://invalid.example"}, status=403)
        command, result = action(
            http,
            store,
            operators,
            "request_sourced_generation",
            dict(
                refs,
                expected_state_version=store.read()[0],
                expected_policy_sha256=fingerprint(current_editorial_policy()),
            ),
        )
        assert http("POST", "/commands", role="viewer", body=command, status=403).json()["code"] == "forbidden"
        sent, factory = sync.transport(dict(text=text))
        assert (
            store.execute_sourced_generation_once(
                command["command_id"],
                operators.resolve,
                operation="write",
                clock=clock,
                transport_factory=factory,
                enabled=True,
            )["outcome"]
            == "response_retained"
        )
        assert (
            store.execute_sourced_generation_once(
                command["command_id"],
                operators.resolve,
                operation="write",
                clock=clock,
                transport_factory=factory,
                enabled=True,
            )["outcome"]
            == "reconciliation_required"
        )
        captured = store.execute_sourced_generation_once(
            command["command_id"], operators.resolve, operation="capture", clock=clock, enabled=True
        )
        assert captured["outcome"] == "candidate_ready", captured
        candidate = captured["candidate"]
        checks, result = action(http, store, operators, "request_candidate_checks", candidate)
        initial_calls = check_stages(
            store, operators, checks, result["candidate"]["check_set_id"], text, revision=False
        )
        view = store.candidate_projection(
            (candidate["admission_input_id"],), now=now(), resolve_principal=operators.resolve
        )[0]
        _, result = action(
            http,
            store,
            operators,
            "admit_checked_candidate",
            dict(candidate, **{k: view[k] for k in ("check_set_id", "expected_completion_sha256")}),
        )
        draft_id = result["candidate"]["draft_id"]
        phase("authenticated_source_writer_initial_checks_saved_draft")

        def draft():
            return next(v for v in store.read()[1]["drafts"] if v["id"] == draft_id)

        def media():
            return http("GET", f"/drafts/{draft_id}/media").json()

        view = media()
        assert view["status"] == "ready", view
        _, result = action(
            http,
            store,
            operators,
            "prepare_media_revision",
            {k: view[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
            draft=draft(),
        )
        view = media()
        assert view["status"] == "prepared", view
        proposal = view["preparation"]["proposal_sha256"]
        png = http("GET", f"/drafts/{draft_id}/media/{proposal}/preview.png").content
        assert http("GET", f"/drafts/{draft_id}/media/{proposal}/original.gif").content == original
        assert png == radar.convert(original, doc)[0]
        _, result = action(
            http,
            store,
            operators,
            "attach_media_revision",
            dict(
                proposal_sha256=proposal,
                expected_policy_sha256=view["expected_policy_sha256"],
                expected_packet_sha256=view["packet"]["packet_sha256"],
                review=dict(
                    decision="accept",
                    confirmations={k: True for k in CONFIRMATIONS | radar.EXTRA_CONFIRMATIONS},
                    reason="Simulated operator review of invented labels; no human or source-truth evidence.",
                ),
            ),
            draft=draft(),
        )
        view = media()
        checks, result = action(
            http,
            store,
            operators,
            "request_revision_checks",
            dict(
                **{
                    k: view[k]
                    for k in (
                        "expected_policy_sha256",
                        "expected_renderer_profile_sha256",
                        "expected_review_sha256",
                    )
                },
                expected_packet_sha256=view["packet"]["packet_sha256"],
            ),
            draft=draft(),
        )
        phase("native_original_graphic_joint_review_revision_enrollment")
        revision_calls = check_stages(
            store, operators, checks, result["revision_checks"]["check_set_id"], text, revision=True
        )
        phase("revision_checks")
        with fixture_server(png, text, mode={("bluesky", "create"): "drop"}) as (
            delivery_config,
            trace,
            accepted,
        ):
            delivery_path = delivery_tests.configure(store, tmp_path, delivery_config)
            view = media()
            _, result = action(
                http,
                store,
                operators,
                "approve_media_revision",
                dict(
                    **{
                        k: view[k]
                        for k in (
                            "expected_policy_sha256",
                            "expected_renderer_profile_sha256",
                            "expected_review_sha256",
                            "expected_check_completion_sha256",
                        )
                    },
                    expected_packet_sha256=view["packet"]["packet_sha256"],
                    reason="Invented staging fixture only.",
                ),
                draft=draft(),
                role="publisher",
            )
            assert media()["parked"] is True
            intent = draft()["approval_binding"]["publish_intent_id"]
            phase("fixture_configuration_and_parked_approval")
            for platform, stages in delivery.STAGES.items():
                for stage in stages:
                    result = execute_delivery_once(
                        store,
                        intent,
                        platform,
                        stage,
                        operators.resolve,
                        owner="invented-h2",
                        clock=clock,
                        enabled=True,
                    )
                    if (platform, stage) == ("bluesky", "create"):
                        assert result["outcome"] == "unknown", result
                        child = restart(tls_database[0][1], port=args["port"],
                                        operators=operators.path, operation="reconcile",
                                        delivery=str(delivery_path), intent=intent)
                        children.append(child)
                        result = child["result"]
                    assert result["outcome"] == "confirmed", result
            # Replay the reconciled final stage once. Exhaustive per-stage
            # passive retries remain in the unchanged delivery tests.
            again = execute_delivery_once(store, intent, "bluesky", "create", operators.resolve,
                                          owner="invented-h2", clock=clock, enabled=True)
            assert again["outcome"] == "confirmed" and again["network_mutation"] is False
            assert (
                len(accepted) == 5
                and [v["method"] for v in trace].count("POST") == 5
                and [v["method"] for v in trace].count("GET") == 1
            )
            phase("five_posts_restart_receipt_get_and_no_resend")
            before = snapshot(args)
            costs = http("GET", "/state").json()["local_cost"]
            assert costs["status"] == "available" and costs["scope"] == "hosted_staging_fixture", (
                costs
            )
            assert (
                costs["total_intents"] == 7
                and costs["summary"]["commitments_micro_usd"]["held"] == "50"
            )
            assert all(v["recorded_settlement_micro_usd"] is None for v in costs["requests"])
            assert snapshot(args) == before
            # Explicit future observation only; active commands always use the
            # real clock. This does not claim a 15-minute wait or latency SLA.
            expired_cost = store.local_cost_projection(now=at + timedelta(minutes=16))
            assert expired_cost["requests"] == costs["requests"]
            assert expired_cost["summary"]["commitments_micro_usd"] == costs["summary"]["commitments_micro_usd"]
            assert snapshot(args) == before
            with store.projections._connection() as c:
                identities = c.execute(
                    "SELECT a.intent_id,a.grant_id,a.request_sha256,o.raw_sha256,o.recorded_at FROM theheat_checks.attempts a JOIN theheat_check_executions.observations o USING(grant_id) WHERE a.stage!='deterministic'"
                ).fetchall()
                commands = c.execute("SELECT command_bytes FROM theheat_commands.intents").fetchall()
                assert commands and all(json.loads(row[0])["environment"] == "preview" for row in commands)
                assert len(identities) == 6
                for intent, grant, request_sha, raw_sha, observed_at in identities:
                    row = next(v for v in costs["requests"] if v["intent_id"] == intent)
                    assert (
                        row["origin"]["grant_id"],
                        row["origin"]["request_sha256"],
                        row["origin"]["raw_sha256"],
                    ) == (grant, request_sha, raw_sha)
                    assert row["usage"]["observed_at"] == observed_at
            from tests.test_postgres_preview_command_ingress import clean_environment

            cost_tests.cost_component_http(
                dict(environment=clean_environment(), origin=http.origin),
                http.port,
                costs,
                tmp_path / "cost-http.json",
            )
            phase("passive_cost_identity_expiry_http_and_preservation")
            _, result = action(
                http,
                store,
                operators,
                "cancel_approval",
                dict(reason="Invented cancellation"),
                draft=draft(),
                role="publisher",
            )
            assert not media()["parked"]
            _, result = action(
                http,
                store,
                operators,
                "edit_revision",
                dict(text="An edited invented warning for this local staging case."),
                draft=draft(),
            )
            assert not media()["review_current"]
            pending, _ = action(
                http,
                store,
                operators,
                "edit_revision",
                dict(text="One pending edit applied after exact restore."),
                draft=draft(),
                consume=False,
            )
            preserved = snapshot(args)
            state = store.read()
            assert (
                http("GET", f"/drafts/{draft_id}/media/{proposal}/original.gif").content == original
            )
            assert http("GET", f"/drafts/{draft_id}/media/{proposal}/preview.png").content == png
            case = dict(
                config=config,
                selection=selection,
                native=store.editor_media_configuration,
                delivery=str(delivery_path),
                operators=str(operators.path),
                draft_id=draft_id,
                proposal=proposal,
                pending=pending,
                source_state=state,
                costs=costs,
                original=original,
                png=png,
            )
            phase("cancellation_edit_pending_command_and_source_inventory")
            child = restart(tls_database[0][1], port=args["port"],
                            operators=operators.path, operation="inspect")
            children.append(child)
            assert child["result"]["state"] == list(state)
            assert child["result"]["costs"]["requests"] == costs["requests"]
            phase("fresh_process_source_state_and_passive_cost")
            restored = restore(tls_database, tls_cluster, tmp_path, case, preserved, children)
            phase("restore_database_dump_restore_restart_once_and_passive_assets")
            assert snapshot(args) == preserved and store.read() == state
            phase("final_source_preservation")
            assert len(sent) == 1 and len(initial_calls) == len(revision_calls) == 3
            record_property(
                "hosted_local_workflow",
                json.dumps(
                    dict(
                        phases=phases,
                        real_clock=True,
                        hosted_calls=0,
                        writer_posts=1,
                        initial_check_posts=3,
                        revision_check_posts=3,
                        fixture_posts=5,
                        receipt_gets=1,
                        http_requests=len(http_trace),
                        tls_application_dials=len([v for v in dials if v["host"] == "localhost"]),
                        all_in_process_connections=len(dials),
                        physical_connections=connection_receipt(tls_cluster, tmp_path, dials, children),
                        restart_before_reconciliation=True,
                        restart_before_dump=True,
                        passive_expiry_probe="explicit future time, not a wall-clock wait",
                        seconds=time.monotonic() - started,
                        row_count=preserved["row_count"],
                        retained_repr_bytes=preserved["bytes"],
                        restored=restored,
                        source_preserved=True,
                        unknown_cost=True,
                    )
                ),
            )


def restore(tls_database, tls_cluster, tmp_path, case, preserved, children):
    configs, args = tls_database
    root, admin, run, cert, data = tls_cluster
    name = "h2_restore_" + uuid4().hex
    with psycopg.connect(**admin) as c:
        c.execute(
            psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("REVOKE CREATE,TEMP ON DATABASE {} FROM PUBLIC").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT,CREATE ON DATABASE {} TO fixture_owner").format(
                psycopg.sql.Identifier(name)
            )
        )
        c.execute(
            psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO fixture_runtime").format(
                psycopg.sql.Identifier(name)
            )
        )
    folder = configs[0].config_path.parent
    passfile = folder / "h2-passfile"
    passfile.write_text(
        "\n".join(
            f"localhost:{args['port']}:{db}:fixture_owner:{'a' * 48}"
            for db in (args["dbname"], name)
        )
    )
    passfile.chmod(0o600)
    env = {
        **os.environ,
        "PGPASSFILE": str(passfile),
        "PGSSLMODE": "verify-full",
        "PGCHANNELBINDING": "require",
        "PGSSLROOTCERT": str(cert),
        "PGSSLCERTMODE": "disable",
        "PGGSSENCMODE": "disable",
        "PGSSLCRL": str(folder / "absent"),
        "PGSSLCRLDIR": str(folder / "absent"),
    }
    bindir = Path(os.environ["THEHEAT_POSTGRES_BINDIR"])
    common = ["-h", "localhost", "-p", str(args["port"]), "-U", "fixture_owner", "-w"]
    dump = tmp_path / "h2.dump"
    dump.touch(mode=0o600)
    try:
        subprocess.run(
            [
                str(bindir / "pg_dump"),
                *common,
                "-Fc",
                *[f"--schema={s}" for s in SCHEMAS],
                "-f",
                str(dump),
                args["dbname"],
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        assert 0 < dump.stat().st_size <= 16 * 1024 * 1024
        subprocess.run(
            [
                str(bindir / "pg_restore"),
                *common,
                "--single-transaction",
                "--exit-on-error",
                "-d",
                name,
                str(dump),
            ],
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        identity = json.loads(configs[1].identity_path.read_text())
        identity["database"] = name
        identity_path = tls.private_json(folder / "h2-restored-identity.json", identity)
        config_path = tls.private_json(
            folder / "h2-restored.json", dict(identity, password="b" * 48)
        )
        config = h.HostedStagingConfig.load(config_path, trusted_identity=identity_path)
        authority = PostgresCommandAuthority.for_hosted_staging(config)
        restored_args = dict(args, dbname=name)
        assert snapshot(restored_args) == preserved
        assert authority.read() == tuple(case["source_state"])
        assert authority.local_cost_projection(now=now())["requests"] == case["costs"]["requests"]
        # A genuine fresh Python process reconstructs only pinned configuration;
        # original pending command ID is consumed once with a real trusted clock.
        child = restart(config, port=args["port"], operators=case["operators"],
                        operation="resume", pending=case["pending"]["command_id"])
        children.append(child)
        result = child["result"]
        assert result["status"] == "applied" and authority.read()[0] == case["source_state"][0] + 1
        current = authority.read()[1]["drafts"][0]
        assert (
            current["text"] == "One pending edit applied after exact restore."
            and "approval_binding" not in current
        )
        assert authority.local_cost_projection(now=now())["requests"] == case["costs"]["requests"]
        # Passive originals do not require reconfiguring a renderer/source or a
        # current approval, and cannot grant promotion authority.
        operators = Operators(case["operators"])
        assert (
            authority.editor_media_projection(
                case["draft_id"],
                operators.resolve,
                now=now(),
                png_proposal=case["proposal"],
                original=True,
            )
            == case["original"]
        )
        assert (
            authority.editor_media_projection(
                case["draft_id"], operators.resolve, now=now(), png_proposal=case["proposal"]
            )
            == case["png"]
        )
        return dict(
            dump_bytes=dump.stat().st_size,
            schemas=len(SCHEMAS),
            exact_rows_catalog_acl_sequences=True,
            pending_once=True,
            actual_process_restart=True,
        )
    finally:
        with psycopg.connect(**admin) as c:
            c.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


def test_preview_profile_is_explicit_atomic_and_old_reader_refuses(tls_database, monkeypatch):
    owner, runtime, args = install(tls_database, full=False)
    with runtime.projections._connection() as c:
        original = c.execute("SELECT * FROM theheat_commands.metadata").fetchone()
        receipt = c.execute(
            "SELECT receipt_bytes FROM theheat_commands.delivery_upgrade"
        ).fetchone()[0]
        value = p._decode(receipt)
        assert value["version"] == 2 and value["environment"] == "preview"
        assert value["migration_sha256"] == p._sha(delivery.MIGRATION.read_bytes())
        assert value["preview_migration_sha256"] == p._sha(delivery.PREVIEW_MIGRATION.read_bytes())
        # Exact d142 validator bytes; independent of Git history in shallow CI.
        source_bytes = Path(__file__).with_name("fixtures").joinpath("old_delivery_catalog_validate.py.txt").read_bytes()
        assert p._sha(source_bytes) == "36a92b1cdb6174c46d71175177f75b46f84064abd17b319f4ff60f2207a9ce08"
        namespace = dict(vars(delivery))
        exec(compile(source_bytes, "old_delivery_catalog_validate.py.txt", "exec"), namespace)
        with pytest.raises(p.ProjectionError, match="changed_delivery_upgrade"):
            namespace["validate_core_catalog"](c, original[1:], "preview")
    owner.initialize_delivery(now=now())
    with runtime.projections._connection() as c:
        assert (
            c.execute("SELECT receipt_bytes FROM theheat_commands.delivery_upgrade").fetchone()[0]
            == receipt
        )
    with pytest.raises(p.ProjectionError, match="explicit_staging_config_required"):
        runtime.initialize_delivery(now=now())
    bare = PostgresCommandAuthority(
        socket_directory=args["host"],
        database=args["dbname"],
        user="fixture_runtime",
        port=args["port"],
        environment="preview",
    )
    assert not hosted_fixture.allowed(bare)
    with pytest.raises(ValueError, match="explicit_staging_config_required"):
        PreviewServer.for_hosted_fixture(bare, None, port=0, origin="http://127.0.0.1:3137")
    with pytest.raises(ValueError, match="local_authority_required"):
        PreviewServer(runtime, None, port=0, origin="http://127.0.0.1:3137")
    assert runtime.local_cost_projection(now=now())["status"] == "unconfigured"


def test_preview_missing_profile_and_install_failure_are_atomic(
    tls_database, monkeypatch, tmp_path
):
    owner, runtime, args = tls.authorities(tls_database)
    owner.initialize({"drafts": []}, runtime_role="fixture_runtime")
    owner.initialize_media_staging()
    before = runtime.read()
    with pytest.raises(delivery.CommandError) as missing:
        PreviewServer.for_hosted_fixture(runtime, None, port=0, origin="http://127.0.0.1:3137")
    assert missing.value.code == "delivery_migration_required"
    with runtime.projections._connection() as c:
        metadata = c.execute("SELECT * FROM theheat_commands.metadata").fetchone()
        catalog = p._catalog(c, "theheat_commands")
        for module in (
            __import__("src.commands.postgres_sync_checks", fromlist=["current"]),
            __import__("src.commands.postgres_revision_checks", fromlist=["current"]),
        ):
            with pytest.raises(delivery.CommandError) as check:
                module.current(c, {}, {}, clock(), "preview")
            assert check.value.code == "delivery_migration_required"
    original = Path.read_text

    def broken(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return value + "\nSELECT 1/0;\n" if path == delivery.PREVIEW_MIGRATION else value

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", broken)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            owner.initialize_delivery(now=now())
    assert runtime.read() == before
    with runtime.projections._connection() as c:
        assert c.execute(
            "SELECT to_regnamespace('theheat_delivery'),to_regclass('theheat_commands.delivery_upgrade')"
        ).fetchone() == (None, None)
        assert c.execute("SELECT * FROM theheat_commands.metadata").fetchone() == metadata
        assert p._catalog(c, "theheat_commands") == catalog
    owner.initialize_delivery(now=now())
    assert runtime.read() == before
    # No implicit migration, guessed endpoint or changed config accepts a sender.
    with pytest.raises(delivery.CommandError) as absent:
        delivery.configuration(runtime)
    assert absent.value.code == "delivery_fixture_configuration_required"
    with fixture_server(b"invented-png", "invented") as (config, trace, accepted):
        path = delivery_tests.configure(runtime, tmp_path, config)
        value = json.loads(path.read_text())
        value["instance_id"] = str(uuid4())
        path.write_text(json.dumps(value))
        with pytest.raises(delivery.CommandError) as changed:
            delivery.configuration(runtime)
        assert changed.value.code == "delivery_configuration_changed"
        assert trace == [] and accepted == {}


@pytest.mark.parametrize(
    "drift",
    [
        "version",
        "bool",
        "missing_extension",
        "extension_hash",
        "environment",
        "owner",
        "legacy_preview",
        "catalog",
    ],
)
def test_preview_unknown_or_mixed_receipt_refuses(tls_database, drift):
    owner, runtime, args = install(tls_database, full=False)
    with runtime.projections._connection() as c:
        original = c.execute(
            "SELECT receipt_bytes FROM theheat_commands.delivery_upgrade"
        ).fetchone()[0]
    value = p._decode(original)
    if drift == "version":
        value["version"] = 3
    elif drift == "bool":
        value["version"] = True
    elif drift == "missing_extension":
        value.pop("preview_migration_sha256")
    elif drift == "extension_hash":
        value["preview_migration_sha256"] = "0" * 64
    elif drift == "environment":
        value["environment"] = "local"
    elif drift == "owner":
        value["owner_role"] = "other_owner"
    elif drift == "catalog":
        value["delivery_catalog_sha256"] = "0" * 64
    else:
        value["version"] = 1
        for key in ("preview_migration_sha256", "environment", "owner_role", "runtime_role"):
            value.pop(key)
    raw = p._canonical(value)
    # Deliberate corruption by this disposable DB's administrator, never a
    # production mutator or a permission granted to the runtime role.
    with psycopg.connect(**args) as c:
        c.execute(
            "ALTER TABLE theheat_commands.delivery_upgrade DISABLE TRIGGER delivery_upgrade_immutable"
        )
        c.execute(
            "UPDATE theheat_commands.delivery_upgrade SET receipt_bytes=%s,sha=%s",
            (raw, p._sha(raw)),
        )
        c.execute(
            "ALTER TABLE theheat_commands.delivery_upgrade ENABLE TRIGGER delivery_upgrade_immutable"
        )
    with pytest.raises(p.ProjectionError, match="changed_delivery_(upgrade|catalog)"):
        runtime.read()
    with pytest.raises(p.ProjectionError, match="changed_delivery_(upgrade|catalog)"):
        owner.initialize_delivery(now=now())
    assert runtime.local_cost_projection(now=now())["status"] == "unavailable"


@pytest.mark.parametrize("drift", ["owner_at_runtime", "bare_repository", "wrong_config_type", "changed_config"])
def test_preview_capability_refusal_does_not_dial(tls_database, monkeypatch, drift):
    owner, runtime, _ = tls.authorities(tls_database)
    from types import SimpleNamespace
    authority = runtime
    if drift == "owner_at_runtime":
        authority = owner
    elif drift == "bare_repository":
        authority.projections = SimpleNamespace(environment="preview", user="fixture_runtime")
    elif drift == "wrong_config_type":
        authority.projections._hosted_config = SimpleNamespace(parameters=lambda: {})
    else:
        config = authority.projections._hosted_config
        config.config_path.write_text("{}")
    def no_dial(*args, **kwargs):
        raise AssertionError("Refused preview capability attempted a PostgreSQL connection")
    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", no_dial)
        if drift == "changed_config":
            with pytest.raises(p.ProjectionError, match="staging_configuration_changed"):
                hosted_fixture.allowed(authority)
        else:
            assert not hosted_fixture.allowed(authority)
            with pytest.raises(ValueError, match="explicit_staging_config_required"):
                PreviewServer.for_hosted_fixture(authority, None, port=0, origin="http://127.0.0.1:3137")
