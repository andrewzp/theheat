from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from scripts.gen_dashboard_graphic_runtime import ROOT, SOURCES, DEPLOYMENT_FILES, generate


def test_archive_is_exact_reproducible_public_allowlist():
    archive, raw_manifest = generate()
    assert (archive, raw_manifest) == generate()
    assert archive == (ROOT / "dashboard/graphic-runtime.zip").read_bytes()
    assert raw_manifest == (ROOT / "dashboard/lib/graphic-runtime-manifest.json").read_bytes()
    manifest = json.loads(raw_manifest)
    assert manifest["identity"]["archive_sha256"] == sha256(archive).hexdigest()
    with zipfile.ZipFile(BytesIO(archive)) as z:
        assert z.namelist() == list(SOURCES)
        for info in z.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.filename.startswith("src/") and ".." not in info.filename
            assert sha256(z.read(info)).hexdigest() == manifest["identity"]["files"][info.filename]
            assert "__pycache__" not in info.filename


@pytest.mark.parametrize("tamper", [None, "archive", "wrapper", "lock", "manifest", "missing"])
def test_sealed_entrypoint_loads_only_verified_zip_and_fails_closed(tmp_path, tamper):
    for name in (*DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "dashboard" / name, target)
    if tamper in {"archive", "wrapper", "lock"}:
        name = {"archive": "graphic-runtime.zip", "wrapper": "api/graphic_preview.py", "lock": "uv.lock"}[tamper]
        with (tmp_path / name).open("ab") as output:
            output.write(b"\n# changed")
    elif tamper == "manifest":
        manifest = json.loads((tmp_path / "lib/graphic-runtime-manifest.json").read_text())
        manifest["identity"]["format"] = "unexpected"
        (tmp_path / "lib/graphic-runtime-manifest.json").write_text(json.dumps(manifest))
    elif tamper == "missing":
        (tmp_path / "graphic-runtime.zip").unlink()
    # A fresh, isolated interpreter cannot borrow source imports from this suite.
    code = '''
import runpy, sys, json, socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
m = runpy.run_path(sys.argv[1])
print(json.dumps({"unavailable": m["PreviewHandler"] is m["UnavailableHandler"],
                  "sources": [str(getattr(mod, "__file__", "")) for key, mod in sys.modules.items()
                              if key == "src" or key.startswith("src.")]}))
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path / "api/graphic_preview.py")],
                            capture_output=True, text=True, check=True, timeout=15)
    payload = json.loads(result.stdout)
    assert payload["unavailable"] is (tamper is not None)
    if tamper:
        assert payload["sources"] == []
    else:
        assert payload["sources"] and all(name.startswith(str(tmp_path / "graphic-runtime.zip") + "/")
                                           for name in payload["sources"])
