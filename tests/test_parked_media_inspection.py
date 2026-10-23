"""Operation ownership over real retained readers and invented SQL rows.

No PostgreSQL/native/timing proof: the storage fixture supplies only explicit
rows; retained review/package/scientific validators execute without pass stubs.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from datetime import timedelta
from functools import partial
from types import SimpleNamespace

import pytest

from src.commands import postgres_editor_media as editor
from src.commands.schema import CommandError
from src.commands.media_journal import MediaJournalError
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
