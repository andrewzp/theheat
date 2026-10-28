"""Exact-input pure calculation reuse; actual readers over invented SQL/PNG.

No PostgreSQL, native rendering, timing, provider or platform execution evidence.
The SQL facade never substitutes a passing scientific or retained-review result.
"""
from contextlib import nullcontext
from copy import deepcopy
from threading import Thread

import pytest

from src.commands import postgres_media_commands as commands
from src.editorial.revisions import fingerprint
from src.media import temperature_graphic_adapter as adapter
from src.media.evidence_graphic import validate_graphic
from src.storage import postgres_projection as p
from tests import test_media_review_pair as pair
from tests.test_delivery_begin_passes import reviewed as reviewed, begin_reviewed, Stop


@pytest.fixture
def retained():
    case = pair.make_case("temperature")
    pair.retain(case, pair.prepare(case))
    return case


@pytest.fixture
def calls(monkeypatch):
    result = []
    original = adapter._qualified_snapshot

    def counted(bundle, snapshot, expected):
        result.append((deepcopy(bundle.to_dict()), expected))
        return original(bundle, snapshot, expected)

    monkeypatch.setattr(adapter, "_qualified_snapshot", counted)
    return result


def stored(case):
    row = case["inputs"]["graphic_spec"]["evidence"]["input_binding"]["bundles"][0]
    return adapter._StoredBundle(deepcopy(row["bundle"])), row["bundle_sha256"]


def read(case):
    return commands.read_with_package(case["sql"], case["command"], case["result"], "local")


def test_actual_schema3_reader_reduces_only_pure_qualification_with_identical_sql_and_output(retained, calls, monkeypatch):
    case = retained
    trace = []
    execute = case["sql"].execute

    def traced(query, args=()):
        trace.append((query, deepcopy(args)))
        return execute(query, args)

    monkeypatch.setattr(case["sql"], "execute", traced)
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "_retained_calculation_scope", nullcontext)
        expected = read(case)
    original_count, original_trace = len(calls), deepcopy(trace)
    calls.clear()
    trace.clear()
    actual = read(case)
    assert p._canonical(actual[0]) == p._canonical(expected[0])
    assert actual[1] == expected[1] and trace == original_trace
    assert original_count == 5 and len(calls) == 1
    assert actual[0]["review"]["schema_version"] == 3
    assert actual[0]["publication_approved"] is False
    assert actual[0]["production_attachment_authorized"] is False
    # A new reader, including before_call's independent reader, starts empty.
    assert read(case) == actual and len(calls) == 2
    actual[1]["capture"]["inputs"]["graphic_spec"]["evidence"]["location"] = "Changed return"
    assert read(case) == expected and len(calls) == 3


def test_no_scope_and_separate_scopes_do_not_inherit_a_success(retained, calls):
    bundle, sha = stored(retained)
    first = adapter._qualified(bundle, sha)
    assert adapter._qualified(bundle, sha) == first and len(calls) == 2
    for count in (3, 4):
        with adapter._retained_calculation_scope():
            assert adapter._qualified(bundle, sha) == first
            assert adapter._qualified(bundle, sha) == first
        assert len(calls) == count


def test_both_begin_passes_keep_exact_reads_callbacks_and_audits_with_six_independent_readers(
    reviewed, calls, monkeypatch
):
    """Real schema3 readers; approval/check completion remains a named model."""
    trace, audits = [], []
    execute, audit = reviewed.sql.execute, adapter.audit_story_bundle
    def traced(query, args=()):
        trace.append((query, deepcopy(args)))
        return execute(query, args)
    def audited(bundle):
        audits.append(bundle.event_id)
        return audit(bundle)
    monkeypatch.setattr(reviewed.sql, "execute", traced)
    monkeypatch.setattr(adapter, "audit_story_bundle", audited)
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "_retained_calculation_scope", nullcontext)
        with pytest.raises(Stop):
            begin_reviewed(reviewed)
    baseline = dict(trace=deepcopy(trace), roles=deepcopy(reviewed.control["roles"]),
        calls=deepcopy(reviewed.control["calls"]), leases=deepcopy(reviewed.control["leases"]),
        audits=deepcopy(audits), calculations=len(calls), packages=reviewed.sql.package_reads)
    trace.clear()
    audits.clear()
    calls.clear()
    reviewed.control.update(roles=[], calls=[], leases=[])
    reviewed.sql.package_reads = 0
    with pytest.raises(Stop):
        begin_reviewed(reviewed)
    assert trace == baseline["trace"] and audits == baseline["audits"]
    assert reviewed.control["roles"] == baseline["roles"] and len(baseline["roles"]) == 12
    assert reviewed.control["calls"] == baseline["calls"]
    assert reviewed.control["leases"] == baseline["leases"] and len(baseline["leases"]) == 1
    assert reviewed.sql.package_reads == baseline["packages"] == 6
    assert baseline["calculations"] - len(calls) == 24  # 6 distinct readers, 5 -> 1 each


def test_detached_outputs_nested_scopes_and_exception_cleanup(retained, calls):
    bundle, sha = stored(retained)
    expected = adapter._qualified(bundle, sha)
    calls.clear()
    with adapter._retained_calculation_scope():
        first = adapter._qualified(bundle, sha)
        first["snapshot"]["where"] = "Changed returned snapshot"
        assert adapter._qualified(bundle, sha) == expected and len(calls) == 1
        with adapter._retained_calculation_scope():
            assert adapter._qualified(bundle, sha) == expected and len(calls) == 2
        assert adapter._qualified(bundle, sha) == expected and len(calls) == 2
    with pytest.raises(RuntimeError, match="invented stop"):
        with adapter._retained_calculation_scope():
            assert adapter._qualified(bundle, sha) == expected
            raise RuntimeError("invented stop")
    assert adapter._RETAINED_CALCULATION.get() is None
    assert adapter._qualified(bundle, sha) == expected and len(calls) == 4


@pytest.mark.parametrize("change", ["nested", "float", "bool", "expected", "invalid"])
def test_same_object_changed_values_and_failure_then_restore_never_reuse_old_row(retained, calls, change):
    bundle, sha = stored(retained)
    before = deepcopy(bundle.snapshot)
    with adapter._retained_calculation_scope():
        expected = adapter._qualified(bundle, sha)
        changed_sha = sha
        if change == "nested":
            bundle.snapshot["raw_signal_dump"]["evidence"]["baseline"]["variables"]["temperature_2m_max"]["sample_count"] -= 1
            changed_sha = fingerprint(bundle.snapshot)
        elif change in {"float", "bool"}:
            baseline = bundle.snapshot["raw_signal_dump"]["evidence"]["baseline"]
            baseline["schema_version"] = 2.0 if change == "float" else True
            changed_sha = fingerprint(bundle.snapshot)
        elif change == "expected":
            changed_sha = "0" * 64
        else:
            bundle.snapshot["raw_signal_dump"]["evidence"]["variables"]["TMAX"]["qflag"] = "S"
            changed_sha = fingerprint(bundle.snapshot)
        # The original pure calculation remains the refusal oracle.
        with pytest.raises(ValueError) as old:
            adapter._qualified_value(bundle, changed_sha)
        with pytest.raises(type(old.value)) as actual:
            adapter._qualified(bundle, changed_sha)
        assert str(actual.value) == str(old.value)
        after_refusal = len(calls)
        bundle.snapshot = before
        assert adapter._qualified(bundle, sha) == expected
        assert len(calls) == after_refusal + 1  # A -> refused B -> freshly rebuilt A


def test_exact_bytes_distinguish_numeric_representations_and_unsupported_objects_bypass(retained):
    bundle, sha = stored(retained)
    bundle.snapshot["invented_extra"] = 1
    integer = adapter._calculation_key(bundle, sha)
    bundle.snapshot["invented_extra"] = 1.0
    assert fingerprint({"n": 1}) == fingerprint({"n": 1.0})
    assert adapter._calculation_key(bundle, sha) != integer
    bundle.snapshot["invented_extra"] = True
    assert adapter._calculation_key(bundle, sha) != integer
    for extra in ((1,), {1: "key"}, float("nan"), object()):
        bundle.snapshot["invented_extra"] = extra
        assert adapter._calculation_key(bundle, sha) is None
    class Custom(dict):
        pass
    bundle.snapshot = Custom(bundle.snapshot)
    assert adapter._calculation_key(bundle, sha) is None


@pytest.mark.parametrize("change", ["function", "constant", "mapping"])
def test_calculation_identity_changes_force_reconstruction(retained, calls, monkeypatch, change):
    bundle, sha = stored(retained)
    with adapter._retained_calculation_scope():
        expected = adapter._qualified(bundle, sha)
        if change == "function":
            original = adapter.story_bundle_snapshot
            monkeypatch.setattr(adapter, "story_bundle_snapshot", lambda bundle: original(bundle))
        elif change == "constant":
            monkeypatch.setattr(adapter, "MIN_ARCHIVE_YEARS", adapter.MIN_ARCHIVE_YEARS - 1)
        else:
            monkeypatch.setattr(adapter, "_KINDS", dict(adapter._KINDS, unused=("high", "all_time")))
        assert adapter._qualified(bundle, sha) == expected and len(calls) == 2


def test_thread_and_closed_context_cannot_inherit_calculation(retained, calls):
    bundle, sha = stored(retained)
    errors = []
    with adapter._retained_calculation_scope():
        calculation = adapter._RETAINED_CALCULATION.get()
        expected = adapter._qualified(bundle, sha)
        def other_thread():
            token = adapter._RETAINED_CALCULATION.set(calculation)
            try:
                assert adapter._qualified(bundle, sha) == expected
            except BaseException as exc:
                errors.append(exc)
            finally:
                adapter._RETAINED_CALCULATION.reset(token)
        thread = Thread(target=other_thread)
        thread.start()
        thread.join(5)
        assert not thread.is_alive() and not errors and len(calls) == 2
    token = adapter._RETAINED_CALCULATION.set(calculation)
    try:
        assert adapter._qualified(bundle, sha) == expected and len(calls) == 3
        assert calculation is not None and calculation.key is calculation.value is None
    finally:
        adapter._RETAINED_CALCULATION.reset(token)


def test_chart_projection_is_still_checked_after_successful_bundle_calculation(retained, calls):
    spec = deepcopy(retained["inputs"]["graphic_spec"])
    with adapter._retained_calculation_scope():
        assert validate_graphic(spec["template"], spec["evidence"],
            expected_evidence_sha256=spec["expected_evidence_sha256"]) == spec["evidence"]
        # The source bundle is identical; only the caller's proposed plot lies.
        spec["evidence"]["points"][0]["value"] += 1
        with pytest.raises(ValueError, match="graphic projection differs"):
            validate_graphic(spec["template"], spec["evidence"],
                expected_evidence_sha256=fingerprint(spec["evidence"]))
        assert len(calls) == 1


def test_dynamic_domain_validator_still_runs_and_refuses_after_a_pure_hit(retained, calls, monkeypatch):
    from src.data import temperature_evidence
    bundle, sha = stored(retained)
    original = temperature_evidence.temperature_aggregate_failures
    trace = []
    def failures(value):
        trace.append(value.event_id)
        return original(value) if len(trace) == 1 else ["Invented changed domain validator"]
    monkeypatch.setattr(temperature_evidence, "temperature_aggregate_failures", failures)
    with adapter._retained_calculation_scope():
        adapter._qualified(bundle, sha)
        with pytest.raises(ValueError, match="temperature_aggregate_unqualified"):
            adapter._qualified(bundle, sha)
        assert len(trace) == 2 and len(calls) == 1
