"""Pure transport of existing final-refusal checks; no database/native execution."""
import ast
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.storage.scientific_supply import SupplyError
from tests import test_postgres_stage_revision_checks as stage


def parameters():
    return dict(check_command_id="invented-check-command", at="2026-10-28T12:00:00.123456Z",
                critic_expiry="2026-10-28T12:02:00.654321Z", boundary="proof", fault="expiry")


def test_adapter_preserves_the_original_exact_deadline_subjects_and_child_patches(monkeypatch, tmp_path):
    authority = object()
    config = {"generation": str(tmp_path / "invented-generation.json")}
    def resolver(subject):
        return "resolved-" + subject
    operators = SimpleNamespace(resolve=resolver)
    calls = []

    def inject(case, command, checking, resolve, at, expiry, patch, boundary, fault, *, source_file):
        calls.append((case, command, checking, resolve, at, expiry, boundary, fault, source_file))
        patch.setenv("THEHEAT_WRITER_SAMPLES", "3")
        assert resolve("checker") == "resolved-checker"

    monkeypatch.delenv("THEHEAT_WRITER_SAMPLES", raising=False)
    monkeypatch.setattr(stage, "inject_nonradar_approval_final_refusal", inject)
    value = stage.isolated_ghcn_approval_final_refusal(authority, operators, config, "approve", parameters())
    assert value == dict(status="refused", boundary="proof", fault="expiry")
    assert calls == [({"store": authority, "config": config}, "approve", "invented-check-command", resolver,
                      datetime(2026, 10, 28, 12, 0, 0, 123456, tzinfo=UTC),
                      datetime(2026, 10, 28, 12, 2, 0, 654321, tzinfo=UTC),
                      "proof", "expiry", Path(config["generation"]))]
    import os
    assert "THEHEAT_WRITER_SAMPLES" not in os.environ


def test_unexpected_scientific_refusal_is_not_reported_as_the_expected_fault(monkeypatch):
    def fail(*args, **kwargs):
        raise SupplyError("isolated_replay_process_required")

    monkeypatch.setattr(stage, "inject_nonradar_approval_final_refusal", fail)
    with pytest.raises(SupplyError, match="isolated_replay_process_required"):
        stage.isolated_ghcn_approval_final_refusal(object(), SimpleNamespace(resolve=object()),
                                                 {"generation": "invented.json"}, "approve", parameters())


def test_actual_worker_dispatches_the_existing_isolated_operation_without_replacing_the_consumer(monkeypatch):
    source = Path(__file__).parent / "fixtures/ghcn_generation_worker.py"
    branch = next(node for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "operation == 'approval_final_refusal'")
    authority, operators, config, result = object(), object(), {}, object()
    observed = []

    def adapter(*args):
        observed.append(args)
        return result

    monkeypatch.setattr(stage, "isolated_ghcn_approval_final_refusal", adapter)
    scope = dict(authority=authority, operators=operators, cfg=config, identity="approve",
                 fault=json.dumps(parameters()), json=json)
    exec(compile(ast.Module(body=branch.body, type_ignores=[]), str(source), "exec"), scope)
    assert observed == [(authority, operators, config, "approve", parameters())]
    assert scope["result"] is result
