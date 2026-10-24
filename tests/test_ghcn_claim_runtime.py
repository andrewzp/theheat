"""Real compact/full temperature validation using only a fresh sealed package."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from scripts.gen_dashboard_graphic_runtime import generate
from src.editorial.revisions import fingerprint
from src.two_bot import ghcn_claim_contract as passive
from tests.ghcn_claim_contract_helpers import VARIANTS, pair

GOLDEN = json.loads((Path(__file__).parent / "fixtures/ghcn_claim_contract_v1.json").read_text())


def test_actual_sealed_adapter_preserves_compact_full_projection_and_refusals(tmp_path):
    archive, manifest_bytes = generate()
    manifest = json.loads(manifest_bytes)
    extracted = tmp_path / "sealed"
    with zipfile.ZipFile(BytesIO(archive)) as packaged:
        names = packaged.namelist()
        assert "src/two_bot/ghcn_claim_contract.py" in names
        assert "src/two_bot/ghcn_claim_view.py" not in names
        assert not any(name.startswith(("src/commands/", "src/storage/", "src/orchestrator/")) for name in names)
        for name in names:
            assert sha256(packaged.read(name)).hexdigest() == manifest["identity"]["files"][name]
        packaged.extractall(extracted)
    cases = []
    for direction, tier in VARIANTS:
        _, full, view, _ = pair(passive, direction, tier)
        cases.append(dict(name=f"valid_{direction}_{tier}", full=full, view=view,
                          expected_full_sha256=fingerprint(full)))
    base = cases[0]
    for change in ("view_value", "selection", "reference_hash", "codec", "extra_field", "oversize", "qflag", "date_string", "date_integer"):
        case = deepcopy(base)
        case["name"] = change
        view, full = case["view"], case["full"]
        ref = view["raw_signal_dump"]["ghcn_claim_view"]
        if change == "view_value":
            view["headline_metric"]["value"] += 1
        elif change == "selection":
            ref["selection"]["signal_field"] = "monthly_high"
        elif change == "reference_hash":
            ref["full_story"]["sha256"] = "0" * 64
        elif change == "codec":
            ref["full_story"]["codec"] = "another-codec"
        elif change == "extra_field":
            view["unknown"] = True
        elif change == "oversize":
            view["current_facts"].append(dict(label="invented", value="x" * 32768))
        elif change in {"date_string", "date_integer"}:
            ref["selection"]["signal_date"] = "not-a-date" if change == "date_string" else 123
        else:
            full["raw_signal_dump"]["evidence"]["variables"]["TMAX"]["qflag"] = "S"
            case["expected_full_sha256"] = fingerprint(full)
        cases.append(case)
    fixture = tmp_path / "invented-cases.json"
    fixture.write_text(json.dumps(cases))
    code = '''
import importlib.abc, json, sys
from hashlib import sha256
from pathlib import Path
class BlockOwners(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        roots = ("src.commands", "src.storage", "src.orchestrator", "anthropic", "google", "psycopg", "psycopg2")
        if any(fullname == root or fullname.startswith(root + ".") for root in roots):
            raise AssertionError("forbidden sealed dependency:" + fullname)
sys.meta_path.insert(0, BlockOwners())
def offline(event, args):
    if event.startswith("socket.") and event not in {"socket.__new__", "socket.gethostname"}:
        raise AssertionError("network unavailable:" + event)
    if event in {"sqlite3.connect", "subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}:
        raise AssertionError("execution unavailable:" + event)
sys.addaudithook(offline)
sys.path.insert(0, sys.argv[1])
from src.media.temperature_graphic_adapter import temperature_claim_graphic_spec, _StoredBundle
from src.media.evidence_graphic import validate_graphic
from src.editorial.revisions import fingerprint
results = {}
for case in json.loads(Path(sys.argv[2]).read_text()):
    try:
        spec = temperature_claim_graphic_spec(case["view"], _StoredBundle(case["full"]),
            expected_full_sha256=case["expected_full_sha256"], synthetic=True)
    except ValueError as exc:
        results[case["name"]] = dict(status="refused", message=str(exc))
        continue
    validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=spec["expected_evidence_sha256"])
    raw = json.dumps(spec, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    results[case["name"]] = dict(status="returned", value=dict(sha256=sha256(raw).hexdigest(),
        byte_length=len(raw), fingerprint=fingerprint(spec)))
    spec["evidence"]["input_binding"]["claim_view"]["view_sha256"] = "0" * 64
    try:
        validate_graphic(spec["template"], spec["evidence"], expected_evidence_sha256=fingerprint(spec["evidence"]))
    except ValueError:
        results[case["name"] + "_tampered_binding"] = dict(status="refused")
    else:
        raise AssertionError("tampered compact/full binding passed")
origins = [str(getattr(module, "__file__", "")) for name, module in sys.modules.items()
           if name == "src" or name.startswith("src.")]
print(json.dumps(dict(results=results, origins=origins)))
'''
    run = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(extracted), str(fixture)],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "no_proxy": "*", "NO_PROXY": "*",
            "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, check=True, timeout=30)
    result = json.loads(run.stdout)
    (tmp_path / "sealed-result.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    assert result["origins"] and all(path.startswith(str(extracted) + "/") for path in result["origins"])
    for direction, tier in VARIANTS:
        name = f"valid_{direction}_{tier}"
        assert result["results"][name] == dict(status="returned", value=GOLDEN["valid"][direction + "_" + tier]["spec"])
        assert result["results"][name + "_tampered_binding"] == dict(status="refused")
    assert all(result["results"][case["name"]]["status"] == "refused" for case in cases[6:])
    assert len(result["results"]) == 21
