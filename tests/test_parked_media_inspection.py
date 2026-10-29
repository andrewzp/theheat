"""Operation ownership over real retained readers and invented SQL rows.

No PostgreSQL/native/timing proof: the storage fixture supplies only explicit
rows; retained review/package/scientific validators execute without pass stubs.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from datetime import timedelta
from functools import partial
from types import SimpleNamespace
import hashlib
import json

import pytest

from src.commands import postgres_editor_media as editor, postgres_delivery as delivery
from src.commands.schema import CommandError, Principal, utc_text
from src.commands.media_journal import MediaJournalError
from src.posting.local_delivery import FixtureConfiguration
from src.storage import postgres_projection as p
from tests.test_joint_media_review import ACTOR
from tests.test_media_review_pair import make_case, prepare, retain
from tests.test_media_replay_reuse import NOW, current_inputs, preparation
from tests.test_media_replay_reuse import Rows


@pytest.fixture
def retained():
    case = make_case("temperature")
    retain(case, prepare(case))
    preparation(case)
    case["authority"].generation_configuration = lambda: dict(
        schema_version=2, current_inputs=[], reservations=dict(batch=None, synchronous=None))
    case["draft"] = case["after"]["drafts"][0]
    case["value"] = current_inputs(case)
    return case


def owned(case):
    scope = editor._open_passive_inspection(case["authority"], NOW)
    scope.bind(case["sql"], case["after"], 1, case["inputs"]["editorial_policy"], None)
    scope.start_inputs()
    return scope


def verify(scope, case):
    return scope.review(case["authority"], case["sql"], case["draft"], case["value"],
                        case["inputs"]["editorial_policy"], lambda subject: ACTOR)


def cached(scope, case, **changes):
    args = dict(authority=case["authority"], c=case["sql"], draft=case["draft"],
                value=case["value"], policy=case["inputs"]["editorial_policy"])
    return scope.parked_review(**(args | changes))


def test_owned_pair_uses_real_reader_once_and_next_operation_verifies_again(retained):
    case = retained
    case["sql"].package_reads = 0
    first = owned(case)
    try:
        package, record = verify(first, case)
        assert case["sql"].package_reads == 1
        assert cached(first, case) == package
        assert case["sql"].package_reads == 1
        assert record == case["transition"].review
        # Mutation of the caller's result cannot change the owned retained pair.
        package["assets"]["preview.png"] += b"invented caller mutation"
        assert cached(first, case)["assets"]["preview.png"] == case["assets"]["preview.png"]
        with pytest.raises(CommandError):
            verify(first, case)
    finally:
        first.close()
    second = owned(case)
    try:
        assert verify(second, case)[1] == record
        assert case["sql"].package_reads == 2
    finally:
        second.close()
    # Every operation must read actual retained bytes, even after an accepted one.
    digest = case["capture"]["asset_sha256"]["preview.png"]
    case["sql"].artifacts[digest] += b"invented retained corruption"
    third = owned(case)
    try:
        with pytest.raises(MediaJournalError, match="changed_media_staging_bytes"):
            verify(third, case)
        assert case["sql"].package_reads == 3
    finally:
        third.close()


@pytest.mark.parametrize("field", ["draft", "value", "policy"])
def test_exact_canonical_binding_refuses_changed_context(retained, field):
    case, scope = retained, owned(retained)
    try:
        verify(scope, case)
        original = case["inputs"]["editorial_policy"] if field == "policy" else case[field]
        changed = deepcopy(original)
        changed["invented_binding_counter"] = 1
        with pytest.raises(CommandError) as caught:
            cached(scope, case, **{field: changed})
        assert caught.value.code == "passive_inspection_context_changed"
    finally:
        scope.close()


def test_equal_python_numbers_do_not_match_canonical_input_identity(retained):
    case = retained
    case["value"]["invented_binding_counter"] = 1
    fresh = owned(case)
    try:
        verify(fresh, case)
        numeric = deepcopy(case["value"])
        numeric["invented_binding_counter"] = 1.0
        with pytest.raises(CommandError):
            cached(fresh, case, value=numeric)
    finally:
        fresh.close()


@pytest.mark.parametrize("attack", ["authority", "connection", "copy", "deepcopy", "closed", "thread"])
def test_foreign_copied_closed_and_thread_inspections_refuse(retained, attack):
    case, scope = retained, owned(retained)
    try:
        verify(scope, case)
        if attack == "authority":
            call = partial(cached, scope, case, authority=object())
        elif attack == "connection":
            call = partial(cached, scope, case, c=object())
        elif attack in {"copy", "deepcopy"}:
            try:
                foreign = (copy if attack == "copy" else deepcopy)(scope)
            except (TypeError, CommandError):
                return  # Copying itself may be explicitly forbidden.
            call = partial(cached, foreign, case)
        elif attack == "closed":
            scope.close()
            call = partial(cached, scope, case)
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(CommandError):
                    pool.submit(cached, scope, case).result()
            return
        with pytest.raises(CommandError):
            call()
    finally:
        scope.close()


def test_caller_objects_cannot_create_inspection_or_supply_verified_pair(retained):
    for token in (None, True, {}, {"passed": True}):
        with pytest.raises(CommandError):
            editor._PassiveInspection(token, retained["authority"], NOW)
    supplied_values: tuple[dict[str, object], ...] = ({"_inspection": {}}, {"package": {}}, {"record": {}})
    for supplied in supplied_values:
        with pytest.raises(TypeError):
            editor.reviewed(retained["authority"], retained["sql"], retained["draft"],
                            retained["value"], retained["inputs"]["editorial_policy"],
                            lambda subject: ACTOR, **supplied)


@pytest.mark.parametrize("elapsed", [-1.0, float("inf"), float("-inf"), float("nan")])
def test_operation_clock_rejects_nonfinite_or_regressed_elapsed(monkeypatch, elapsed):
    clock = [100.0]
    monkeypatch.setattr(editor, "_passive_monotonic", lambda: clock[0])
    scope = editor._open_passive_inspection(SimpleNamespace(environment="local"), NOW)
    try:
        clock[0] = 100.0 + elapsed
        with pytest.raises(CommandError) as caught:
            scope.now()
        assert caught.value.code == "invalid_time"
    finally:
        scope.close()


def test_clock_keeps_original_anchor_before_binding_and_never_resets(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(editor, "_passive_monotonic", lambda: clock[0])
    scope = editor._open_passive_inspection(SimpleNamespace(environment="local"), NOW)
    try:
        clock[0] += 7
        assert scope.now() == NOW + timedelta(seconds=7)
        scope.bind(object(), {}, 1, {}, None)
        clock[0] += 3
        assert scope.now() == NOW + timedelta(seconds=10)
        clock[0] -= 1
        with pytest.raises(CommandError) as caught:
            scope.now()
        assert caught.value.code == "invalid_time"
    finally:
        scope.close()
    with pytest.raises(CommandError):
        scope.now()


def test_failed_config_capture_preserves_missing_origin_failure_order(retained, monkeypatch):
    """Explicit absent storage rows, invalid config, actual projection ordering."""
    from src.two_bot.check_origin import SOURCE_NAMESPACE

    case = retained
    original_execute = case["sql"].execute

    def missing_origin(query, args=()):
        sql = " ".join(query.split())
        if sql.startswith("SELECT i.command_id FROM theheat_commands.intents i JOIN"):
            return Rows([])
        if sql == "SELECT 1 FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s" and args[0] == SOURCE_NAMESPACE:
            return Rows([])
        return original_execute(query, args)

    monkeypatch.setattr(case["sql"], "execute", missing_origin)
    case["authority"].generation_configuration = lambda: {}  # Invalid operator input, never a pass.
    expected = editor.projection(case["authority"], case["sql"], case["draft"]["id"],
        state=case["after"], version=1, policy=case["inputs"]["editorial_policy"],
        now=NOW, resolve_principal=lambda subject: ACTOR)
    assert expected["code"] == "saved_source_origin_unavailable"
    scope = editor._open_passive_inspection(case["authority"], NOW)
    try:
        scope.bind(case["sql"], case["after"], 1, case["inputs"]["editorial_policy"], None)
        actual = scope.project(case["draft"]["id"], lambda subject: ACTOR)
        assert p._canonical(actual) == p._canonical(expected)
        assert scope._pair is None and scope._proof is None
    finally:
        scope.close()


@pytest.mark.parametrize("change", ["unchanged", "before_final_read", "after_first_final_read"])
def test_real_delivery_configuration_pair_survives_capture_and_both_final_reads(
    tmp_path, monkeypatch, change
):
    """Real config/retained pair; explicit lifecycle fields are not stage proof.

    This component test calls finish directly with invented packet/approval/time
    fields. It proves neither a completed check set nor a parked DB transaction.
    Configuration, retained media/review and final guards run without pass stubs.
    """
    case = make_case("temperature", extended=False)
    retain(case, prepare(case))
    preparation(case)
    authority, sql = case["authority"], case["sql"]
    authority.generation_configuration = lambda: dict(
        schema_version=2, current_inputs=[], reservations=dict(batch=None, synchronous=None))
    case["draft"] = case["after"]["drafts"][0]
    case["value"] = current_inputs(case)
    case["value"]["source"] = dict(
        source_useful_until=utc_text(NOW + timedelta(minutes=4)),
        provenance_useful_until=utc_text(NOW + timedelta(minutes=4)))

    folder = tmp_path / "invented-private-delivery"
    folder.mkdir(mode=0o700)
    path = folder / "configuration.json"
    config = dict(schema_version=2, scope="local_http_fixture_v1", invented=True,
        instance_id="11111111-2222-4333-8444-555555555555", origin="http://127.0.0.1:39131",
        routes_version=1, actor="did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
        platform_profile="credentialless-loopback-v1")
    original_bytes = json.dumps(config).encode()
    path.write_bytes(original_bytes)
    path.chmod(0o600)
    original_inode = path.stat().st_ino
    loaded = FixtureConfiguration.load(path)
    authority.delivery_configuration = loaded
    real_pair = delivery.configuration(authority)
    assert type(real_pair) is tuple and real_pair == (config, hashlib.sha256(original_bytes).hexdigest())

    # Only an explicit invented state-pointer row supplements the existing SQL
    # fixture. The actual authority state/snapshot reader verifies its bytes.
    original_execute = sql.execute

    def state_pointer(query, args=()):
        if " ".join(query.split()).startswith(
            "SELECT version,namespace,snapshot_id FROM theheat_commands.state WHERE singleton=1"
        ):
            return Rows([(1, "command-core-v1", "1")])
        return original_execute(query, args)

    monkeypatch.setattr(sql, "execute", state_pointer)
    original_read = FixtureConfiguration.read
    read_calls: list[object] = []

    def read_real_file(configuration):
        read_calls.append(configuration)
        return original_read(configuration)

    monkeypatch.setattr(FixtureConfiguration, "read", read_real_file)
    scope = editor._open_passive_inspection(authority, NOW)
    try:
        scope.bind(sql, case["after"], 1, case["inputs"]["editorial_policy"], None)
        assert scope.start_inputs() is True
        assert len(read_calls) == 1 and scope._snapshot_ready
        assert scope._delivery_config == p._canonical(dict(configuration=config, sha256=real_pair[1]))
        _, record = verify(scope, case)  # Actual retained package and review verification.
        assert record == case["transition"].review

        # Explicit fields for this finalization-only component fixture; no
        # stages.completion, approval command, grant or journal result is faked.
        publisher = Principal("invented-final-publisher", "publisher", "offline-fixture-session")
        intent = "22222222-3333-4444-8555-666666666666"
        scope._draft["approval_binding"] = dict(
            publisher_subject=publisher.subject, requesting_actor=ACTOR.subject)
        scope._draft["publish_intent_id"] = intent
        deadline = utc_text(NOW + timedelta(minutes=3))
        scope.verified(dict(useful_until=utc_text(NOW + timedelta(minutes=4)),
            check_date=utc_text(NOW)[:10]), deadline)
        view: dict = dict(parked=True, review_current=True, checks_status="passed",
            publication_approved=False, delivery=dict(intents=[dict(intent_id=intent, current=True, reason=None)]))
        expected = deepcopy(view)
        role_calls: list[str] = []
        changed: list[bool] = []

        def change_same_file():
            assert not changed and authority.delivery_configuration is loaded
            path.write_text(json.dumps(config | {"instance_id": "33333333-4444-4555-8666-777777777777"}))
            assert path.stat().st_ino == original_inode
            changed.append(True)

        def resolve(subject):
            role_calls.append(subject)
            if change == "after_first_final_read" and subject == publisher.subject and not changed:
                assert len(read_calls) == 2  # Capture, then the first actual final read.
                change_same_file()
            return publisher if subject == publisher.subject else ACTOR

        if change == "before_final_read":
            change_same_file()
        scope.finish(view, resolve)
        assert scope._proof[1] == deadline  # Original bound never changes.
        if change == "unchanged":
            assert len(read_calls) == 3  # Capture plus BOTH actual final content reads.
            assert role_calls == [ACTOR.subject, publisher.subject, ACTOR.subject] * 2
            assert view == expected
        else:
            assert len(read_calls) == (2 if change == "before_final_read" else 3)
            assert view["parked"] is False and view["parked_status"] == "delivery_configuration_changed"
            assert view["delivery"]["intents"][0] == dict(
                intent_id=intent, current=False, reason="delivery_configuration_changed")
            assert view["review_current"] is True and view["publication_approved"] is False
        assert all(configuration is loaded for configuration in read_calls)
    finally:
        scope.close()
