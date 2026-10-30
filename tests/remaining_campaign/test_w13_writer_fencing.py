"""W13.5: offline all-writer inventory, fail-closed compatibility, no activation."""
from __future__ import annotations

import ast
import importlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from src.commands import writer_fencing as fencing
from src.commands.command_roles import RoleError

ROOT = Path(__file__).resolve().parents[2]


def test_every_declared_writer_names_a_real_call_site():
    assert {w.kind for w in fencing.WRITERS} >= {"source", "editor", "archive", "batch", "check", "metrics", "sender"}
    for writer in fencing.WRITERS:
        site, name = writer.call_site.rsplit(":", 1)
        if site.endswith(".js"):
            assert f"export async function {name}(" in (ROOT / site).read_text(), writer.name
        elif site.endswith(".py"):
            tree = ast.parse((ROOT / site).read_text())
            assert name in {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}, writer.name
        else:
            target = importlib.import_module(site)
            for part in name.split("."):
                target = getattr(target, part)
            assert callable(target), writer.name
        assert writer.store in fencing.STORES and writer.kind in fencing.KINDS


def test_compatibility_fails_closed_while_any_gist_or_platform_writer_is_unfenced():
    for target in fencing.TARGETS:
        result = fencing.compatibility(target)
        assert result["compatible"] is False and result["activation"] == "not_performed"
        assert result["gist_transactional"] is False
        codes = {(b["writer"], b["code"]) for b in result["blockers"]}
        assert ("dashboard_editor", "gist_writer_not_rerouted") in codes
        assert ("metrics", "gist_writer_not_rerouted") in codes
        assert ("x_sender", "platform_sender_unfenced") in codes
        assert not any(b["writer"].startswith("command_authority:") for b in result["blockers"])
    with pytest.raises(RoleError) as unknown:
        fencing.compatibility("hosted_gist_transactions")
    assert unknown.value.code == "unknown_cutover_target"


def test_registry_refuses_unknown_writers_and_cli_is_offline_output_only():
    with pytest.raises(RoleError) as unknown:
        fencing.WriterGenerationRegistry(authorized={"invented_writer": {"g"}})
    assert unknown.value.code == "unknown_writer"
    out = io.StringIO()
    with redirect_stdout(out):
        assert fencing.main(["--target", "command_authority_postgres"]) == 0
    payload = json.loads(out.getvalue())
    assert payload["compatibility"]["compatible"] is False
    assert len(payload["inventory"]) == len(fencing.WRITERS)
