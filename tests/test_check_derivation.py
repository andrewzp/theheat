"""Real local check storage with explicitly seeded historical fixtures."""

from contextlib import closing
from copy import deepcopy
import json

import pytest

from src.commands import check_journal as checks, domain_journal
from src.commands.schema import canonical_json
from src.editorial.revisions import fingerprint, text_hash
from src.two_bot import candidate_derivation as derived, check_executor
from tests import test_check_journal as legacy, test_batch_result_journal as batches
from tests.two_bot.source_link_fixtures import bundle, TEXT, URL

store, inputs, case, NOW = legacy.store, legacy.inputs, legacy.case, legacy.NOW


def saved(case):
    return case["store"].check_execution("read", {"check_set_id": case["identity"]["check_set_id"]}, now=NOW)


@pytest.fixture
def review_module():
    return checks


def history_records(case, packet, at, terminal):
    raw = canonical_json(packet).encode()
    identity = fingerprint(packet)
    request = b'{"explicit_legacy_fixture":true}'
    binding = dict(check_set_id=identity, stage="deterministic", request_sha256=domain_journal._digest(request),
                   reservation=None, owner="worker-one", fence=1, begun_at=at)
    grant = fingerprint(binding)
    receipt = dict(grant_id=grant, request_sha256=binding["request_sha256"], execution_status="completed",
                   verdict="pass", result={"explicit_historical_fixture": True}, usage=None)
    return dict(packet=raw, identity=identity, request=request, binding=binding, grant=grant,
                receipt=receipt if terminal else None, completion=receipt)


@pytest.fixture
def rewrite_packet():
    def write(case, packet, *, terminal=True):
        # Fixture-only historical import. No production command can rewrite a set.
        with closing(case["store"]._connect()) as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM check_sets WHERE check_set_id=?", (case["identity"]["check_set_id"],)).fetchone()
            records = history_records(case, packet, old["recorded_at"], terminal)
            c.execute("DROP TRIGGER check_sets_no_delete")
            c.execute("DELETE FROM check_sets WHERE check_set_id=?", (old["check_set_id"],))
            c.execute(checks._objects()["check_sets_no_delete"])
            sha = domain_journal._artifact(c, records["packet"])
            c.execute("INSERT INTO check_sets VALUES(?,?,?,?,?)", (records["identity"], old["job_id"], old["custom_id"], sha, old["recorded_at"]))
            domain_journal._artifact(c, records["request"])
            binding_sha = domain_journal._artifact(c, canonical_json(records["binding"]).encode())
            c.execute("INSERT INTO check_attempts VALUES(?,?,?,?,?,?)", (records["grant"], records["identity"], "deterministic", binding_sha, None, old["recorded_at"]))
            if records["receipt"] is not None:
                receipt_sha = domain_journal._artifact(c, canonical_json(records["receipt"]).encode())
                c.execute("INSERT INTO check_receipts VALUES(?,?,?,?)", (records["grant"], receipt_sha, "passed", old["recorded_at"]))
            c.commit()
        case["identity"]["check_set_id"] = records["identity"]
        return records
    return write


def legacy_packet(case):
    packet = deepcopy(saved(case)["packet"])
    packet["schema_version"] = 1
    packet.pop("derivation")
    packet.pop("derivation_id")
    packet["text_sha256"] = text_hash(packet["candidate"]["tweet"])
    return packet


def test_intake_preserves_raw_result_and_formats_a_separate_checked_text(store, inputs, monkeypatch):
    inputs["bundle"] = bundle()
    inputs["bundle_sha256"] = fingerprint(inputs["bundle"].to_dict())
    original_rows = batches.rows
    raw_text = TEXT + " nhc.noaa.gov/text/SYN…"
    def rows(pair):
        result = original_rows(pair)
        output = json.loads(result[0]["result"]["message"]["content"][0]["text"])
        output["tweet"] = raw_text
        result[0]["result"]["message"]["content"][0]["text"] = json.dumps(output)
        return result
    monkeypatch.setattr(batches, "rows", rows)
    case = legacy.case.__wrapped__(store, inputs, monkeypatch)
    packet = saved(case)["packet"]
    assert packet["schema_version"] == 2
    assert packet["candidate"]["tweet"] == raw_text
    assert derived.checked_text(packet) == TEXT + "\n" + URL
    review = store.review_batch_results({k: case["payload"][k] for k in checks._REVIEW_FIELDS}, now=NOW)
    row = next(r for r in review["report"]["rows"] if r["custom_id"] == packet["custom_id"])
    assert row["candidate_id"] == packet["candidate_id"] and row["candidate"] == packet["candidate"]
    before = legacy.workers.snapshot(store)
    assert store.candidate_checks("intake", case["payload"], now=NOW)["reused"]
    assert legacy.workers.snapshot(store) == before


def test_current_row_candidate_must_match_even_if_raw_id_is_repeated(case, review_module, monkeypatch):
    original = review_module._review
    def changed(*args, **kwargs):
        review = deepcopy(original(*args, **kwargs))
        review["report"]["rows"][0]["candidate"]["tweet"] = "A substituted fixture."
        return review
    monkeypatch.setattr(review_module, "_review", changed)
    before = legacy.workers.snapshot(case["store"])
    assert legacy.status(case)["blocked_reason"] == "check_context_not_current"
    with pytest.raises(checks.CheckJournalError, match="candidate_no_longer_current"):
        legacy.start(case)
    assert legacy.workers.snapshot(case["store"]) == before


@pytest.mark.parametrize("field", ["bundle", "memory", "checker_state"])
def test_intake_detaches_evidence_before_sql_reuses_caller_inputs(case, review_module, monkeypatch, field):
    payload = deepcopy(case["payload"])
    before = legacy.workers.snapshot(case["store"])
    original = review_module._at
    changed = []
    def mutate(*args, **kwargs):
        at = original(*args, **kwargs)
        payload[field]["external_mutation"] = True
        changed.append(True)
        return at
    monkeypatch.setattr(review_module, "_at", mutate)
    assert case["store"].candidate_checks("intake", payload, now=NOW)["reused"]
    assert changed and "external_mutation" not in saved(case)["packet"][field]
    assert legacy.workers.snapshot(case["store"]) == before


def test_unavailable_formatter_keeps_history_but_cannot_issue_another_grant(case, monkeypatch):
    started = legacy.start(case)
    identity = derived.formatter_identity()
    monkeypatch.setattr(derived, "formatter_identity", lambda: dict(identity, source_sha256="f" * 64))
    before = legacy.workers.snapshot(case["store"])
    assert saved(case)["derivation_verification"] == "formatter_unavailable"
    assert legacy.status(case)["blocked_reason"] == "formatter_unavailable"
    with pytest.raises(checks.CheckJournalError, match="formatter_unavailable"):
        legacy.start(case)
    assert legacy.workers.snapshot(case["store"]) == before
    # A late trusted adapter receipt is retained as stale, never as current pass.
    assert legacy.finish(case, started)["disposition"] == "stale"
    assert not legacy.status(case)["required_checks_completed"]


@pytest.mark.parametrize("terminal", [True, False], ids=["past-pass", "late-completion"])
def test_legacy_reads_late_bytes_and_receipts_do_not_grant_current_permission(case, rewrite_packet, monkeypatch, terminal):
    old = legacy_packet(case)
    records = rewrite_packet(case, old, terminal=terminal)
    before_state = case["store"].read()
    view = saved(case)
    assert view["packet"] == old and view["derivation_verification"] == "legacy_check_packet"
    status = legacy.status(case)
    assert status["blocked_reason"] == "legacy_check_packet" and not status["required_checks_completed"]
    assert status["stages"]["deterministic"] == ("passed" if terminal else "unresolved")
    with pytest.raises(checks.CheckJournalError, match="legacy_check_packet"):
        legacy.start(case)
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_candidate"):
        case["store"].candidate_checks("intake", case["payload"], now=NOW)
    raw = b'{"explicit_legacy_observation":true}'
    metadata = dict(check_set_id=records["identity"], stage="deterministic", grant_id=records["grant"],
                    request_sha256=records["binding"]["request_sha256"], raw_sha256=domain_journal._digest(raw),
                    http_status=None, complete=True, reason="local")
    assert case["store"].check_execution("observe", metadata, raw=raw, now=NOW)["raw_retained"]
    assert case["store"].read_check_response(records["identity"], "deterministic", records["grant"]) == raw
    result = case["store"].candidate_checks("complete", dict(case["identity"], stage="deterministic", grant_id=records["grant"]),
                                           receipt=records["completion"], now=NOW)
    assert result["disposition"] == ("passed" if terminal else "stale")
    assert result["reused"] is terminal
    # Refuse before acquiring a new lease or constructing any provider transport.
    monkeypatch.setattr(case["store"], "batch_work", lambda *a, **k: pytest.fail("Legacy lease acquired"))
    monkeypatch.setattr(check_executor, "GoogleCheckTransport", lambda **k: pytest.fail("Legacy provider constructed"))
    result = check_executor.execute_check_once(case["store"], records["identity"], current_context=case["payload"]["current_context"],
        checker_state=case["payload"]["checker_state"], owner="worker-one", clock=lambda: NOW, enabled=True)
    assert result["outcome"] == "blocked" and result["reason"] == "legacy_check_packet"
    assert case["store"].read() == before_state and not legacy.status(case)["required_checks_completed"]
