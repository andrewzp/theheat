"""Onboarding's next commands name real, current entry points (offline; --help only)."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import operator_onboarding  # noqa: E402


def test_every_python_next_command_resolves_to_an_existing_subcommand():
    report = operator_onboarding.preflight(ROOT, run_generators=False)
    commands = report["next_commands"]
    assert any("tests/final_closure/" in command for command in commands)
    checked = 0
    for command in commands:
        script = re.match(r"python (scripts/\S+\.py) ([a-z-]+)", command)
        module = re.match(r"python -m (\S+) .*?\s([a-z][a-z-]+) --output", command)
        if script:
            argv = [str(ROOT / script[1]), script[2], "--help"]
            assert (ROOT / script[1]).is_file(), command
        elif module:
            argv = ["-m", module[1], "--database", "/nonexistent/unused.sqlite", module[2], "--help"]
        else:
            continue
        done = subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"})
        assert done.returncode == 0, (command, done.stderr[-400:])
        checked += 1
    assert checked >= 3
