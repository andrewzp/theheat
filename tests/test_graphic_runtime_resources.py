"""Real archive reads, scientific reconstruction and dependency failure boundaries."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from scripts import gen_dashboard_graphic_runtime as package
from src.data import places


def fresh(code, *args):
    preamble = '''
import json, sys, socket
def no_network(*a, **k): raise AssertionError("network during archive validation")
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.getaddrinfo = no_network
'''
    result = subprocess.run([sys.executable, "-I", "-c", preamble + code, *map(str, args)],
                            capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def archive(tmp_path, *, damage=None):
    content, _ = package.generate()
    path = tmp_path / "runtime.zip"
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(path, "w") as target:
        for name in source.namelist():
            if damage == "missing" and name.endswith("registry/place_registry.json"):
                continue
            data = source.read(name)
            if damage == "corrupt" and name.endswith("registry/place_registry.json"):
                data = b"{broken"
            target.writestr(name, data)
    return path


def app(tmp_path):
    for name in (*package.DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package.ROOT / "dashboard" / name, target)
    return tmp_path / "api/graphic_preview.py"


def test_archive_and_checkout_keep_known_alias_and_unregistered_place_identities(tmp_path):
    rows = places.registry()
    row = next(row for row in rows if row["aliases"])
    alias = row["aliases"][0]
    queries = [[row["city"], row["country"], row["lat"], row["lon"]],
               [alias["city"], alias["country"], alias["lat"], alias["lon"]],
               ["Invented Location", "Example Country", 27.7, 85.3]]
    expected = [places.resolve_place(*query) for query in queries]
    actual = fresh('''
sys.path.insert(0, sys.argv[1])
from src.data.places import resolve_place
print(json.dumps([resolve_place(*q) for q in json.loads(sys.argv[2])]))
''', archive(tmp_path), json.dumps(queries))
    assert actual == expected


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_embedded_registry_cannot_borrow_checkout_data(tmp_path, damage):
    result = fresh('''
sys.path.insert(0, sys.argv[1])
from src.data.places import registry
try:
    registry()
except (OSError, ValueError) as exc:
    print(json.dumps({"failure": type(exc).__name__}))
else:
    raise AssertionError("invalid registry accepted")
''', archive(tmp_path, damage=damage))
    assert result["failure"] == ("NotADirectoryError" if damage == "missing" else "JSONDecodeError")


def test_public_registry_assets_are_bound_by_archive_and_policy():
    from src.editorial.policy import source_manifest

    content, manifest_bytes = package.generate()
    manifest = json.loads(manifest_bytes)
    policy = source_manifest()
    assert manifest["identity"]["resource_sources"] == dict(package.RESOURCES)
    with zipfile.ZipFile(BytesIO(content)) as source:
        for destination, origin in package.RESOURCES:
            raw = (package.ROOT / origin).read_bytes()
            assert source.read(destination) == raw
            assert manifest["identity"]["files"][destination] == sha256(raw).hexdigest()
            assert policy["files"][origin] == sha256(raw).hexdigest()


def test_changed_public_asset_invalidates_the_runtime_identity(monkeypatch):
    original_bytes, original_manifest = package.generate()
    original_read = Path.read_bytes
    changed_path = package.ROOT / "data/country_codes.json"

    def changed_read(path):
        raw = original_read(path)
        return raw + b"\n" if path == changed_path else raw

    monkeypatch.setattr(Path, "read_bytes", changed_read)
    changed_bytes, changed_manifest = package.generate()
    assert changed_bytes != original_bytes
    assert json.loads(changed_manifest)["runtime_sha256"] != json.loads(original_manifest)["runtime_sha256"]


@pytest.mark.parametrize("name", ["../private", "/absolute", "src//alias", "src/a\\b", ".", "src/a\x00b"])
def test_generator_rejects_unsafe_resource_paths_before_reading(monkeypatch, name):
    monkeypatch.setattr(package, "RESOURCES", ((name, "data/place_registry.json"),))
    with pytest.raises(ValueError, match="Unsafe"):
        package.generate()


def test_generator_refuses_duplicate_destination(monkeypatch):
    monkeypatch.setattr(package, "RESOURCES", ((package.SOURCES[0], "data/place_registry.json"),))
    with pytest.raises(ValueError, match="Duplicate"):
        package.generate()


@pytest.mark.parametrize("failure", ["missing", "wrong-version", "unreadable-data"])
def test_native_bootstrap_fails_before_source_import_when_timezone_package_is_unavailable(tmp_path, failure):
    result = fresh('''
import runpy, importlib.abc, types, zoneinfo
failure = sys.argv[2]
if failure == "missing":
    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "tzdata": raise ModuleNotFoundError("fixture missing tzdata")
    sys.meta_path.insert(0, Block())
elif failure == "wrong-version":
    sys.modules["tzdata"] = types.SimpleNamespace(__version__="unapproved")
else:
    import zoneinfo._common
    def unreadable(key): raise OSError("fixture damaged timezone data")
    zoneinfo._common.load_tzdata = unreadable
loaded = runpy.run_path(sys.argv[1])
print(json.dumps({"unavailable": loaded["PreviewHandler"] is loaded["UnavailableHandler"],
                  "source_loaded": any(n == "src" or n.startswith("src.") for n in sys.modules)}))
''', app(tmp_path), failure)
    assert result == {"unavailable": True, "source_loaded": False}


def test_complete_forecast_renders_from_archive_with_only_locked_timezone_data(tmp_path):
    from tests.air_quality_graphic_helpers import graphic_bundle
    from src.editorial.revisions import fingerprint
    from src.media.air_quality_graphic_adapter import pm25_graphic_spec
    from src.media.evidence_graphic_render import render_svg

    bundle = graphic_bundle()
    expected = render_svg(**pm25_graphic_spec(bundle, expected_bundle_sha256=fingerprint(bundle.to_dict()),
                                            expected_window_sha256=fingerprint(bundle.raw_signal_dump["forecast_window"]),
                                            synthetic=True))
    packet = tmp_path / "invented.json"
    packet.write_text(json.dumps(bundle.to_dict()))
    result = fresh('''
import runpy, zoneinfo
from pathlib import Path
from hashlib import sha256
# Startup must also discard an already populated host timezone cache.
zoneinfo.ZoneInfo("UTC")
loaded = runpy.run_path(sys.argv[1])
assert loaded["PreviewHandler"] is not loaded["UnavailableHandler"]
assert zoneinfo.TZPATH == ()
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import _StoredBundle
from src.media.air_quality_graphic_adapter import pm25_graphic_spec
from src.media.evidence_graphic_render import render_svg
from src.data.air_quality_contract import _bounds
b = json.loads(Path(sys.argv[2]).read_text())
spec = pm25_graphic_spec(_StoredBundle(b), expected_bundle_sha256=fingerprint(b),
                        expected_window_sha256=fingerprint(b["raw_signal_dump"]["forecast_window"]), synthetic=True)
r = render_svg(**spec)
for day, offset in [("2026-03-08", -18000), ("2026-11-01", -14400)]:
    try: _bounds(day, "America/New_York", offset)
    except ValueError as exc: assert str(exc) == "not a 24-hour day"
    else: raise AssertionError("DST day accepted")
print(json.dumps({"sha": sha256(r["svg"]).hexdigest(), "start": spec["evidence"]["valid_start"],
                  "end": spec["evidence"]["valid_end"],
                  "sources": [str(getattr(m, "__file__", "")) for n, m in sys.modules.items()
                              if n == "src" or n.startswith("src.")]}))
''', app(tmp_path), packet)
    assert result["sha"] == expected["svg_sha256"]
    assert (result["start"], result["end"]) == ("2026-06-07T18:15:00Z", "2026-06-08T18:15:00Z")
    assert all(path.startswith(str(tmp_path / "graphic-runtime.zip") + "/") for path in result["sources"])


def test_map_renders_from_exact_archive_without_checkout_resources(tmp_path):
    from tests.fire_graphic_helpers import graphic_bundle
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(graphic_bundle().to_dict()))
    result = fresh('''
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from src.dashboard_preview.preview import qualified_spec
from src.media.evidence_graphic_render import render_svg
spec,_,_=qualified_spec(json.loads(Path(sys.argv[2]).read_text()),synthetic=True)
image=render_svg(**spec)
print(json.dumps(dict(template=spec["template"],length=len(image["svg"]),sha=image["svg_sha256"])))
''', archive(tmp_path), source)
    assert result["template"] == "modis_thermal_detection_map" and 0 < result["length"] <= 1_000_000


def test_packaged_map_resources_cannot_borrow_valid_checkout_on_tamper(tmp_path):
    content, _ = package.generate()
    path = tmp_path / "damaged-map.zip"
    with zipfile.ZipFile(BytesIO(content)) as original, zipfile.ZipFile(path, "w") as target:
        for name in original.namelist():
            data = original.read(name)
            if name.endswith("maps/manifest.json"):
                data += b" "
            target.writestr(name, data)
    result = fresh('''
sys.path.insert(0, sys.argv[1])
from src.media.fire_map_graphic_adapter import basemap,MapQualificationError
try:basemap()
except MapQualificationError as e:print(json.dumps({"code":e.code}))
else:raise AssertionError("tampered map resource accepted")
''', path)
    assert result["code"] == "graphic_map_basemap_unavailable"


def test_viirs_map_renders_from_exact_archive_and_refuses_tampered_shared_locator(tmp_path):
    from tests.viirs_graphic_helpers import viirs_bundle
    source = tmp_path / "bundle.json"
    source.write_text(json.dumps(viirs_bundle().to_dict()))
    code = '''
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from src.dashboard_preview.preview import qualified_spec
from src.media.evidence_graphic import validate_graphic
from src.media.evidence_graphic_render import render_svg
bundle = json.loads(Path(sys.argv[2]).read_text())
spec,source,context=qualified_spec(bundle,synthetic=True,include_viirs=True)
image=render_svg(**spec)
print(json.dumps(dict(template=spec["template"],source=source,kind=context["kind"],length=len(image["svg"]),
                      evidence=spec["expected_evidence_sha256"],spec=spec)))
'''
    clean = fresh(code, archive(tmp_path), source)
    assert (clean["template"], clean["source"], clean["kind"]) == (
        "viirs_thermal_detection_map", "NASA FIRMS · VIIRS", "viirs_acquisition")
    assert 0 < clean["length"] <= 1_000_000
    # Change only the shared locator module inside a copy of the archive: the
    # already-qualified evidence no longer reconstructs and a fresh spec differs.
    content, _ = package.generate()
    damaged = tmp_path / "damaged-locator.zip"
    with zipfile.ZipFile(BytesIO(content)) as original, zipfile.ZipFile(damaged, "w") as target:
        for name in original.namelist():
            data = original.read(name)
            if name == "src/media/fire_map_graphic_adapter.py":
                data += b"\n# changed shared locator bytes\n"
            target.writestr(name, data)
    (tmp_path / "spec.json").write_text(json.dumps(clean["spec"]))
    result = fresh('''
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from src.media.evidence_graphic import validate_graphic
spec = json.loads(Path(sys.argv[2]).read_text())
try:
    validate_graphic(**spec)
except ValueError as exc:
    print(json.dumps({"refused": True}))
else:
    raise AssertionError("evidence bound to old shared locator bytes accepted")
''', damaged, tmp_path / "spec.json")
    assert result == {"refused": True}
