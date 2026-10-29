"""Portable exact PNG bytes for every native Gist family (canonical profile, schema 2).

Golden vectors are invented data. Their decoded RGB digests are the .46 renderer's
pixels; their PNG digests must reproduce on any host with the same rasterization.
A mocked version string is never treated as a different real build.
"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import shutil
import subprocess
import sys
import zlib

from PIL import Image
import pytest

from scripts.gen_dashboard_graphic_runtime import DEPLOYMENT_FILES, ROOT
from src.media import canonical_png, gist_hazard_media as hazard, gist_media, gist_temperature_media as temperature
from tests.gist_png_vectors import CASES, GOLDEN


def _digest(raw):
    return sha256(raw).hexdigest()


def _render(name):
    family, build, synthetic = CASES[name]
    return (temperature if family == "temperature" else hazard).prepare_media(build(), synthetic=synthetic)


def _png_identity(prepared):
    descriptor = prepared["descriptor"]
    return descriptor["png_sha256"] if descriptor["kind"] == temperature.KIND else descriptor["image"]["png_sha256"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_vectors_keep_46_pixels_and_fix_exact_bytes(name):
    prepared = _render(name)
    png = prepared["png"]
    rgb_sha256, png_sha256, size = GOLDEN[name]
    with Image.open(BytesIO(png)) as image:
        image.load()
        assert image.format == "PNG" and image.mode == "RGB" and image.size == (1200, 1500)
        rgb = image.tobytes()
    assert _digest(rgb) == rgb_sha256
    assert _digest(png) == png_sha256 == _png_identity(prepared)
    assert len(png) == size <= 750_000
    assert canonical_png.inspect(png, max_bytes=750_000) == (1200, 1500, "RGB")
    # Exact bytes follow from the pixels alone: an independent re-encode is identical.
    assert canonical_png.encode("RGB", 1200, 1500, rgb, max_bytes=750_000) == png


@pytest.mark.parametrize("name", ["temperature-low-monthly", "pm25-flat", "modis-dateline", "viirs-noaa21-dateline"])
def test_host_compressors_cannot_choose_family_bytes(name, monkeypatch):
    expected = _render(name)

    def trap(*args, **kwargs):
        raise AssertionError("host compressor used")
    original = Image._getencoder

    def raw_only(mode, encoder, *args, **kwargs):
        if encoder != "raw":
            raise AssertionError("host image encoder used")
        return original(mode, encoder, *args, **kwargs)
    monkeypatch.setattr(zlib, "compress", trap)
    monkeypatch.setattr(zlib, "compressobj", trap)
    monkeypatch.setattr(Image.Image, "save", trap)
    monkeypatch.setattr(Image, "_getencoder", raw_only)
    assert _render(name) == expected


def test_renderer_identities_bind_the_codec_not_the_host_zlib():
    for kind in hazard.FAMILIES:
        identity = hazard.renderer_identity(kind)
        assert "zlib" not in identity and identity["png_codec"] == canonical_png.PROFILE
        assert identity["version"] == "gist-hazard-png-2"
        assert identity["files"]["src/media/canonical_png.py"] == _digest(
            (ROOT / "src/media/canonical_png.py").read_bytes())
    identity = temperature.renderer_identity()
    assert "zlib" not in identity and identity["png_codec"] == canonical_png.PROFILE
    assert identity["codec_sha256"] == _digest((ROOT / "src/media/canonical_png.py").read_bytes())


def _old_schema(descriptor):
    old = deepcopy(descriptor)
    old["schema_version"] = 1
    renderer = old["renderer"]
    renderer.pop("png_codec")
    renderer.pop("codec_sha256", None)
    renderer["zlib"] = "1.2.11"
    if "files" in renderer:
        renderer["version"] = "gist-hazard-png-1"
        renderer["files"].pop("src/media/canonical_png.py")
    return old


@pytest.mark.parametrize("name", ["temperature-high-all_time", "pm25-sendable-varying", "modis-four", "viirs-noaa20-four"])
def test_old_profile_and_codec_mutations_refuse_without_upgrade(name, monkeypatch):
    family, build, _ = CASES[name]
    bundle, prepared = build(), _render(name)
    descriptor = prepared["descriptor"]
    module = temperature if family == "temperature" else hazard
    with pytest.raises(ValueError, match="render profile changed") as caught:
        module.validate_descriptor(_old_schema(descriptor), bundle)
    if module is hazard:
        assert caught.value.code == "media_renderer_changed"
    changed = deepcopy(descriptor)
    changed["renderer"]["png_codec"] = "canonical-png-fixed-huffman-0"
    with pytest.raises(ValueError, match="render profile changed"):
        module.validate_descriptor(changed, bundle)
    module.validate_descriptor(deepcopy(descriptor), bundle)
    monkeypatch.setattr(canonical_png, "PROFILE", "canonical-png-fixed-huffman-2")
    with pytest.raises(ValueError, match="render profile changed"):
        module.validate_descriptor(deepcopy(descriptor), bundle)


def test_codec_source_change_refuses_every_family(monkeypatch):
    real_resource = hazard._resource

    def edited(path):
        raw = real_resource(path)
        return raw + b"\n# edited\n" if path == "src/media/canonical_png.py" else raw
    for name in ("pm25-flat", "modis-four", "viirs-noaa20-four"):
        family, build, _ = CASES[name]
        bundle, descriptor = build(), _render(name)["descriptor"]
        monkeypatch.setattr(hazard, "_resource", edited)
        with pytest.raises(hazard.MediaWithheld) as caught:
            hazard.validate_descriptor(deepcopy(descriptor), bundle)
        assert caught.value.code == "media_renderer_changed"
        monkeypatch.setattr(hazard, "_resource", real_resource)

    class Edited:
        def __init__(self, inner):
            self.inner = inner

        def joinpath(self, name):
            inner = self.inner.joinpath(name)
            if name != "canonical_png.py":
                return inner
            return type("Edited", (), {"read_bytes": lambda _self: inner.read_bytes() + b"\n# edited\n"})()
    bundle, descriptor = CASES["temperature-low-calendar"][1](), _render("temperature-low-calendar")["descriptor"]
    real_files = temperature.files
    monkeypatch.setattr(temperature, "files", lambda package: Edited(real_files(package)))
    with pytest.raises(ValueError, match="render profile changed"):
        temperature.validate_descriptor(deepcopy(descriptor), bundle)


@pytest.mark.parametrize("name", ["temperature-low-all_time", "pm25-extreme-spike", "modis-three-default", "viirs-three-default"])
def test_sender_rebuild_returns_the_exact_previewed_bytes_and_refuses_rehashed_tampering(name):
    family, build, _ = CASES[name]
    bundle, prepared = build(), _render(name)
    draft = {"review_context": {"two_bot": {"bundle": bundle}}, "media_attachment": deepcopy(prepared["descriptor"])}
    if family == "temperature":
        from datetime import date
        png, text = temperature.media_for_draft(draft, today=date.fromisoformat(prepared["descriptor"]["valid_date"]))
        assert text == prepared["descriptor"]["alt_text"]
    else:
        png, text = gist_media.media_for_draft(draft, now=hazard_now(bundle))
        assert text == prepared["delivery_text"]
    assert png == prepared["png"] and _digest(png) == GOLDEN[name][1]
    other = deepcopy(prepared["descriptor"])
    if family == "temperature":
        other["png_sha256"] = "0" * 64
    else:
        other["image"]["png_sha256"] = "0" * 64
    tampered = {**draft, "media_attachment": other}
    with pytest.raises(ValueError):
        if family == "temperature":
            from datetime import date
            temperature.media_for_draft(tampered, today=date.fromisoformat(other["valid_date"]))
        else:
            gist_media.media_for_draft(tampered, now=hazard_now(bundle))


def hazard_now(bundle):
    from datetime import datetime, timezone
    from tests.gist_hazard_helpers import CLOCKS
    key = "pm25" if bundle["signal_kind"] == "air_quality_hazard" else "modis"
    return datetime.fromisoformat(CLOCKS[key][0].replace("Z", "+00:00")).astimezone(timezone.utc)


PACKAGED = r'''
import hashlib, json, runpy, sys, socket, time
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
entry = runpy.run_path(sys.argv[1])
assert entry["PreviewHandler"] is not entry["UnavailableHandler"], "verified runtime refused"
import zlib
from PIL import Image
def trap(*a, **k): raise AssertionError("host compressor used")
zlib.compress = zlib.compressobj = Image.Image.save = trap
from src.media import gist_hazard_media as hazard, gist_temperature_media as temperature
out = {}
for name, family, synthetic, bundle in json.load(sys.stdin):
    started = time.perf_counter()
    prepared = (temperature if family == "temperature" else hazard).prepare_media(bundle, synthetic=synthetic)
    out[name] = [hashlib.sha256(prepared["png"]).hexdigest(), len(prepared["png"]), round(time.perf_counter() - started, 4)]
sources = sorted({str(getattr(m, "__file__", "")) for k, m in sys.modules.items() if k == "src" or k.startswith("src.")})
print(json.dumps({"vectors": out, "sources": sources}))
'''


def test_sealed_runtime_zip_reproduces_every_golden_vector_without_a_host_compressor(tmp_path):
    deploy = tmp_path / "deploy"
    for name in (*DEPLOYMENT_FILES, "graphic-runtime.zip", "lib/graphic-runtime-manifest.json"):
        target = deploy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "dashboard" / name, target)
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    payload = [[name, family, synthetic, build()] for name, (family, build, synthetic) in sorted(CASES.items())]
    result = subprocess.run([sys.executable, "-I", "-c", PACKAGED, str(deploy / "api/graphic_preview.py")],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=120,
                            cwd=elsewhere, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": str(elsewhere)})
    assert result.returncode == 0, result.stderr[-3000:]
    value = json.loads(result.stdout)
    assert value["sources"] and all(s.startswith(str(deploy / "graphic-runtime.zip") + "/") for s in value["sources"])
    assert {name: row[:2] for name, row in value["vectors"].items()} == {
        name: [png_sha256, size] for name, (_, png_sha256, size) in GOLDEN.items()}
