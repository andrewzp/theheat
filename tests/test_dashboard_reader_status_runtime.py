"""Fresh processes verify both deployment entries before any archive import."""

import json
from pathlib import Path

import pytest

from scripts.gen_dashboard_graphic_runtime import ROOT
from tests.test_graphic_runtime_resources import app, fresh


@pytest.mark.parametrize("entry,allowed", [("graphic_preview.py", "POST"), ("graphic_reader_status.py", "GET")])
@pytest.mark.parametrize("failure", ["none", "preview-tamper", "status-tamper", "missing-archive", "loaded-src"])
def test_both_bound_entry_points_share_integrity_and_fail_closed(tmp_path, entry, allowed, failure):
    app(tmp_path)
    result = fresh('''
import runpy, types
from pathlib import Path
root, entry, failure = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if failure in {"preview-tamper", "status-tamper"}:
    name = "graphic_preview.py" if failure == "preview-tamper" else "graphic_reader_status.py"
    with (root / "api" / name).open("ab") as f: f.write(b"\\n")
elif failure == "missing-archive": (root / "graphic-runtime.zip").unlink()
elif failure == "loaded-src": sys.modules["src"] = types.SimpleNamespace()
loaded = runpy.run_path(str(root / "api" / entry))
handler = loaded["handler"]
unavailable = any(t.__name__ == "UnavailableHandler" for t in handler.__mro__)
print(json.dumps({"unavailable": unavailable, "allowed": getattr(handler, "_allowed_method", None),
    "sources": [m.__file__ for n,m in sys.modules.items() if n.startswith("src.") and getattr(m,"__file__",None)]}))
''', tmp_path, entry, failure)
    assert result["unavailable"] is (failure != "none")
    if failure == "none":
        assert result["allowed"] == allowed
        assert result["sources"] and all(name.startswith(str(tmp_path / "graphic-runtime.zip") + "/") for name in result["sources"])
    else:
        assert not result["sources"]


def test_missing_sibling_bootstrap_uses_private_fallback(tmp_path):
    app(tmp_path)
    (tmp_path / "api/graphic_preview.py").unlink()
    result = fresh('''
import runpy
loaded = runpy.run_path(sys.argv[1])
print(json.dumps({"unavailable": issubclass(loaded["handler"], loaded["UnavailableHandler"]),
    "src_imports": any(n == "src" or n.startswith("src.") for n in sys.modules)}))
''', tmp_path / "api/graphic_reader_status.py")
    assert result == {"unavailable": True, "src_imports": False}


def test_environment_cannot_select_reader_handler_for_preview_entry(tmp_path):
    app(tmp_path)
    result = fresh('''
import os,runpy
os.environ["_READER_STATUS_ENTRY"] = "1"
loaded = runpy.run_path(sys.argv[1])
print(json.dumps({"allowed":loaded["handler"]._allowed_method}))
''', tmp_path / "api/graphic_preview.py")
    assert result == {"allowed": "POST"}


def test_each_native_function_includes_the_bound_sibling_and_assets():
    functions = json.loads((ROOT / "dashboard/vercel.json").read_text())["functions"]
    for entry, sibling in [("graphic_preview.py", "graphic_reader_status.py"), ("graphic_reader_status.py", "graphic_preview.py")]:
        spec = functions["api/" + entry]
        assert spec["maxDuration"] == 30
        assert "api/" + sibling in spec["includeFiles"]
        assert all(name in spec["includeFiles"] for name in ("graphic-runtime.zip", "lib/graphic-runtime-manifest.json", "pyproject.toml", "uv.lock"))
        assert ".env*" in spec["excludeFiles"] and "node_modules/**" in spec["excludeFiles"]
