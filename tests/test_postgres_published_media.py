"""Actual local PG/SDK/native published-media authority; invented inputs only."""

from copy import deepcopy
from datetime import timedelta
import json
from uuid import uuid4

import pytest

from src.commands import postgres_published_media as published, postgres_media
from src.commands.schema import utc_text, Command, CommandError
from src.editorial.revisions import fingerprint
from src.media import published_radar as radar
from src.media.joint_review import CONFIRMATIONS
from src.storage import postgres_projection as p
from tests import published_radar_fixtures as f
from tests import test_postgres_synchronous_generation as sync
from tests import test_postgres_sourced_generation as sourced, test_postgres_editor_media as editor
from tests import test_postgres_candidate_admission as candidate
from tests import test_postgres_delivery as delivery
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import (
    core as core,
    make_authority as make_authority,
    options,
)
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.native_profile_helpers import native_dependencies as native_dependencies
from tests.test_postgres_editor_media import offline_connections as offline_connections


@pytest.fixture
def radar_case(store, core, monkeypatch, tmp_path, native_dependencies):
    from src.voice import safety

    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    core[2].initialize_synchronous_checks(now=sourced.NOW)
    bundle = f.bundle(monkeypatch, at=sourced.NOW)
    value = dict(
        schema_version=1,
        source_key="nws_alerts",
        source_revision="invented-tornado-alert-one",
        captured_at=utc_text(sourced.NOW),
        useful_until="2026-09-29T12:30:00Z",
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
        sourced.allowance_document(
            refs["brief_id"],
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
    case = dict(
        store=store,
        refs=refs,
        value=value,
        config=config,
        bundle=bundle,
        text="The NWS has issued a tornado warning for the invented test area.",
    )
    assert sourced.request(case)["status"] == "applied"
    sent, factory = sync.transport(case)
    assert sourced.run(case, "write", factory)["outcome"] == "response_retained"
    sync.checked(case, monkeypatch)
    assert len(sent) == 1
    core[2].initialize_media_staging()
    core[2].initialize_media_commands()
    core[2].initialize_revision_checks(now=editor.AT)
    store.configure_editor_media(**native_dependencies, scratch=tmp_path / "native")
    doc, raw, references, receipt = f.input_document(at=sourced.NOW)
    retained = published.retain(store, doc, raw, references, receipt)
    selection = dict(schema_version=1, selections={refs["brief_id"]: retained["input_sha256"]})
    published.configure(store, lambda: selection)
    case.update(
        radar_input=doc,
        original=raw,
        reference_bytes=references,
        receipt_bytes=receipt,
        published_config=selection,
        provider_requests=sent,
    )
    return case


def attach(case):
    current = editor.view(case)
    assert current["status"] == "ready", current
    command, result = editor.action(
        case,
        "prepare_media_revision",
        {k: current[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
    )
    assert result["status"] == "unchanged", result
    prepared = editor.view(case)
    assert prepared["status"] == "prepared" and prepared["packet"]["schema_version"] == 2, prepared
    _, result = editor.action(
        case,
        "attach_media_revision",
        dict(
            proposal_sha256=prepared["preparation"]["proposal_sha256"],
            expected_policy_sha256=prepared["expected_policy_sha256"],
            expected_packet_sha256=prepared["packet"]["packet_sha256"],
            review=dict(
                decision="accept",
                confirmations={k: True for k in CONFIRMATIONS | radar.EXTRA_CONFIRMATIONS},
                reason="Simulated operator attestation of invented raster labels and point context; no real human or source-truth evidence.",
            ),
        ),
    )
    assert result["status"] == "applied", result
    return prepared, command


def original(case, proposal):
    return case["store"].editor_media_projection(
        case["draft_id"], candidate.resolve, now=editor.AT, png_proposal=proposal, original=True
    )


def test_retained_input_exact_retry_changed_bytes_and_native_review(radar_case, core):
    case = radar_case
    before = editor.all_application_rows(core[3])
    ref = published.retain(
        case["store"],
        case["radar_input"],
        case["original"],
        case["reference_bytes"],
        case["receipt_bytes"],
    )
    assert editor.all_application_rows(core[3]) == before
    with pytest.raises(radar.RadarHold, match="radar_original_changed"):
        published.retain(
            case["store"],
            case["radar_input"],
            case["original"] + b"X",
            case["reference_bytes"],
            case["receipt_bytes"],
        )
    assert editor.all_application_rows(core[3]) == before
    prepared, command = attach(case)
    proposal = prepared["preparation"]["proposal_sha256"]
    assert original(case, proposal) == case["original"]
    assert editor.view(case, png=proposal).startswith(b"\x89PNG")
    assert editor.view(case)["review_current"] is True
    with case["store"].projections._connection() as c:
        package = postgres_media.read(c, proposal, "local")
        assert package["capture"]["schema_version"] == 2 and set(package["assets"]) == set(
            radar.LIMITS
        )
    assert ref["input_sha256"] == prepared["packet"]["published"]["input_sha256"]
    assert case["store"].consume(
        candidate.resolve, command_id=command.command_id, now=editor.AT
    ) == case["store"].result(command.command_id)


def test_published_deadline_packet_six_and_park_expiry(radar_case, monkeypatch, record_property):
    case = radar_case
    attach(case)
    result = editor.complete_revision(case, monkeypatch)
    packet = case["store"].check_execution(
        "read", {"check_set_id": result["revision_checks"]["check_set_id"]}, now=utc_text(editor.AT)
    )["packet"]
    assert packet["schema_version"] == 6 and packet["useful_until"] == "2026-09-29T12:14:00.000000Z"
    from src.two_bot.check_origin import packet_verification

    assert packet_verification(packet) == "verified_saved_draft_revision"
    record_property("published_revision_packet", json.dumps(packet, sort_keys=True))
    old = {**packet, "schema_version": 3}
    with pytest.raises(ValueError, match="invalid_revision_check_origin"):
        packet_verification(old)
    _, parked = delivery.park(case)
    assert parked["status"] == "applied" and editor.view(case)["parked"] is True
    expired = editor.view(case, now=editor.AT + timedelta(minutes=14))
    assert expired["status"] == "unavailable" and expired["parked"] is False


@pytest.mark.parametrize("drift", ["selection", "registry", "source", "role"])
def test_current_drift_refuses_but_original_and_png_survive(radar_case, monkeypatch, drift):
    case = radar_case
    prepared, _ = attach(case)
    proposal = prepared["preparation"]["proposal_sha256"]
    png = editor.view(case, png=proposal)
    if drift == "selection":
        case["published_config"]["selections"] = {}
    if drift == "source":
        case["config"]["current_inputs"] = []
    if drift == "registry":
        monkeypatch.setattr(radar, "POINT", {**radar.POINT, "latitude": 36.0})
    resolve = (lambda subject: None) if drift == "role" else candidate.resolve
    current = editor.view(case, resolve=resolve)
    assert current["status"] == "unavailable" or current["review_current"] is False
    assert original(case, proposal) == case["original"] and editor.view(case, png=proposal) == png


def test_incomplete_published_attestation_cannot_attach(radar_case):
    case = radar_case
    current = editor.view(case)
    _, result = editor.action(
        case,
        "prepare_media_revision",
        {k: current[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
    )
    assert result["status"] == "unchanged"
    current = editor.view(case)
    before = case["store"].read()
    _, result = editor.action(
        case,
        "attach_media_revision",
        dict(
            proposal_sha256=current["preparation"]["proposal_sha256"],
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            review=dict(
                decision="accept",
                confirmations={k: True for k in CONFIRMATIONS},
                reason="Missing explicit raster attestation must refuse.",
            ),
        ),
    )
    assert result["status"] == "rejected" and case["store"].read() == before


def test_expiry_after_shared_state_write_rolls_back_every_effect(radar_case, monkeypatch, core):
    from src.commands import postgres_authority as authority_module

    case = radar_case
    current = editor.view(case)
    _, result = editor.action(
        case,
        "prepare_media_revision",
        {k: current[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
    )
    assert result["status"] == "unchanged"
    current = editor.view(case)
    draft = next(d for d in case["store"].read()[1]["drafts"] if d["id"] == case["draft_id"])
    request = dict(
        command_id=str(uuid4()),
        action="attach_media_revision",
        requested_at=utc_text(editor.AT),
        expires_at=utc_text(editor.AT + timedelta(minutes=5)),
        targets=[editor._identity(draft)],
        payload=dict(
            proposal_sha256=current["preparation"]["proposal_sha256"],
            expected_policy_sha256=current["expected_policy_sha256"],
            expected_packet_sha256=current["packet"]["packet_sha256"],
            review=dict(
                decision="accept",
                confirmations={k: True for k in CONFIRMATIONS | radar.EXTRA_CONFIRMATIONS},
                reason="Invented late-boundary rollback case.",
            ),
        ),
    )
    command = Command.from_request(request, candidate.EDITOR, environment="local", now=editor.AT)
    case["store"].accept(command, candidate.EDITOR, now=editor.AT)
    rows = editor.all_application_rows(core[3])
    before = case["store"].read()
    clocks = iter([editor.AT, editor.AT + timedelta(minutes=14)])
    with monkeypatch.context() as patch:
        patch.setattr(authority_module, "_clock", lambda now: next(clocks))
        with pytest.raises(CommandError, match="expired"):
            case["store"].consume(candidate.resolve, command_id=command.command_id, now=editor.AT)
    assert editor.all_application_rows(core[3]) == rows and case["store"].read() == before
    result = case["store"].consume(
        candidate.resolve, command_id=command.command_id, now=editor.AT + timedelta(minutes=14)
    )
    assert result["status"] == "rejected" and case["store"].read() == before


def test_native_timeout_is_held_without_partial_package(radar_case, monkeypatch, core):
    import subprocess
    from src.commands import preview_media_worker

    case = radar_case
    current = editor.view(case)
    before = case["store"].read()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("invented-owned-child", 45)

    monkeypatch.setattr(preview_media_worker, "run_native", timeout)
    _, result = editor.action(
        case,
        "prepare_media_revision",
        {k: current[k] for k in ("expected_policy_sha256", "expected_renderer_profile_sha256")},
    )
    assert result["status"] == "rejected" and result["code"] == "native_render_timeout"
    assert case["store"].read() == before and admin(
        core[3], "SELECT count(*) FROM theheat_media.packages"
    ) == [(0,)]


def test_published_unknown_delivery_ack_never_resends(radar_case, core, tmp_path, monkeypatch):
    from tests.local_delivery_helpers import fixture_server

    case = radar_case
    prepared, _ = attach(case)
    editor.complete_revision(case, monkeypatch)
    png = editor.view(case, png=prepared["preparation"]["proposal_sha256"])
    core[2].initialize_delivery(now=editor.AT)
    with fixture_server(png, case["text"], mode="drop") as (config, trace, accepted):
        delivery.configure(case["store"], tmp_path, config)
        _, parked = delivery.park(case)
        assert parked["status"] == "applied"
        for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        first = delivery.run(case, parked["delivery"]["intent_id"], "x", "upload")
        assert first["outcome"] == "unknown"
        repeat = delivery.run(case, parked["delivery"]["intent_id"], "x", "upload")
        assert repeat["outcome"] == "unknown" and repeat["network_mutation"] is False
        assert len(trace) == len(accepted) == 1


def test_overbound_alert_never_reserves_or_grants(store, core, monkeypatch):
    item = f.feature(sourced.NOW)
    item["properties"]["instruction"] = "x" * 40000
    from src.two_bot.intern.disasters import build_severe_weather_bundle

    bundle = build_severe_weather_bundle(f.parsed(monkeypatch, item, at=sourced.NOW)[0])
    value = dict(
        schema_version=1,
        source_key="nws_alerts",
        source_revision="invented-overbound",
        captured_at=utc_text(sourced.NOW),
        useful_until="2026-09-29T12:30:00Z",
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
    before = editor.all_application_rows(core[3])
    with pytest.raises(CommandError) as caught:
        store.retain_generation_input(value)
    assert caught.value.code == "generation_evidence_not_ready"
    assert editor.all_application_rows(core[3]) == before


def test_actual_pointer_wait_crossing_frame_deadline_has_no_new_authority(
    radar_case, core, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, get_ident
    import time

    case = radar_case
    attach(case)
    command, identity, packet = editor.request_revision(case)
    before = editor.all_application_rows(core[3])
    expired, entering = Event(), Event()
    main_thread = get_ident()
    original_state = case["store"]._state

    def state(connection, *, lock=False):
        if get_ident() != main_thread:
            entering.set()
        return original_state(connection, lock=lock)

    monkeypatch.setattr(case["store"], "_state", state)

    def clock():
        return packet["useful_until"] if expired.is_set() else utc_text(editor.AT)

    with ThreadPoolExecutor(max_workers=1) as workers:
        with case["store"].projections._connection(writing=True) as connection:
            original_state(connection, lock=True)
            future = workers.submit(
                editor.run_revision, case, command, packet, "deterministic", clock=clock
            )
            assert entering.wait(timeout=10)
            observed_lock_wait = False
            for _ in range(100):
                if admin(
                    core[3],
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'",
                )[0][0]:
                    observed_lock_wait = True
                    break
                time.sleep(0.01)
            assert observed_lock_wait and not future.done()
            expired.set()
        with pytest.raises(CommandError):
            future.result(timeout=30)
    assert editor.all_application_rows(core[3]) == before
    assert admin(
        core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE check_set_id=%s", (identity,)
    ) == [(0,)]


@pytest.mark.parametrize("drift", ["frame_expired", "lease_expired", "clock_backward"])
def test_completion_delay_rolls_back_pass_but_keeps_original_raw(
    radar_case, core, monkeypatch, drift
):
    from src.commands import postgres_checks
    from tests import test_check_executor as executor

    case = radar_case
    attach(case)
    command, identity, packet = editor.request_revision(case)
    assert editor.run_revision(case, command, packet, "deterministic")["outcome"] == "completed"
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    original_apply = postgres_checks.apply
    advanced = False
    prior_rows = None

    def apply(c, operation, payload, **kwargs):
        nonlocal advanced, prior_rows
        if operation == "complete" and payload.get("stage") == "safety":
            # This snapshot already contains the actual SDK response and original
            # grant, committed by passive observation before interpretation.
            prior_rows = editor.all_application_rows(core[3])
            value = original_apply(c, operation, payload, **kwargs)
            advanced = True
            return value
        return original_apply(c, operation, payload, **kwargs)

    monkeypatch.setattr(postgres_checks, "apply", apply)
    changed = (
        packet["useful_until"]
        if drift == "frame_expired"
        else utc_text(editor.AT + timedelta(seconds=301 if drift == "lease_expired" else -1))
    )
    report = editor.run_revision(
        case, command, packet, "safety", clock=lambda: changed if advanced else utc_text(editor.AT)
    )
    assert report["outcome"] == "reconciliation_required" and advanced and len(sent) == 1
    assert prior_rows is not None and editor.all_application_rows(core[3]) == prior_rows
    saved = case["store"].check_execution(
        "read", {"check_set_id": identity}, now=utc_text(editor.AT)
    )
    assert saved["attempts"]["safety"]["observation"] is not None
    assert admin(
        core[3],
        "SELECT count(*) FROM theheat_checks.receipts WHERE grant_id=%s",
        (saved["attempts"]["safety"]["grant_id"],),
    ) == [(0,)]
