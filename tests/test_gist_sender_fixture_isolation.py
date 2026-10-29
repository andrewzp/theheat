"""Collecting the sender tests must not install a clock in unrelated modules."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PROBE = '''from datetime import datetime, timezone
def test_unrelated_clock_not_overridden():
    assert datetime.now(timezone.utc).isoformat() == "2040-01-02T03:04:05+00:00"
'''
RUN = '''from freezegun import freeze_time
import pytest,sys
with freeze_time("2040-01-02T03:04:05Z"):
    raise SystemExit(pytest.main([sys.argv[1],sys.argv[2],"-q","-k","test_unrelated_clock_not_overridden","-p","no:cacheprovider"]))
'''


def test_sender_fixture_clock_does_not_escape_its_module(tmp_path):
    probe = tmp_path / "test_independent_clock.py"
    probe.write_text(PROBE)
    result = subprocess.run(
        [sys.executable, "-c", RUN, str(ROOT / "tests/test_gist_sender_preflight.py"), str(probe)],
        cwd=ROOT, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
                       "LC_ALL": "C", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHON_DOTENV_DISABLED": "1", "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 6 deselected" in result.stdout
