"""Regression guards for the source -> triage -> writer boundary."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_ROOT = REPO_ROOT / "src" / "orchestrator"
ALLOWED_DIRECT_WRITER_CALLS = {
    ORCHESTRATOR_ROOT / "common.py",
    ORCHESTRATOR_ROOT / "draft_save.py",
    ORCHESTRATOR_ROOT / "two_bot_dispatch.py",
}
FORBIDDEN_SOURCE_CALLS = {
    "_try_two_bot_draft",
    "generate_draft",
    "generate_fire_draft",
    "save_draft",
}


def test_only_central_drain_calls_try_two_bot_draft_in_production_code():
    """Sources submit candidates. The drain is the only writer gateway."""
    offenders: list[str] = []
    for path in ORCHESTRATOR_ROOT.rglob("*.py"):
        if path in ALLOWED_DIRECT_WRITER_CALLS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_SOURCE_CALLS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_SOURCE_CALLS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert offenders == []
