"""Real SVG rendering, packaging and failure boundaries over invented source inputs."""

import builtins
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

from src.editorial.revisions import fingerprint
from src.media import evidence_graphic_render as renderer
from src.media.evidence_graphic import build_alt_text
from tests.air_quality_graphic_helpers import graphic_bundle as aq_bundle
from tests.crw_graphic_helpers import graphic_inputs
from tests.fire_graphic_helpers import graphic_bundle as fire_bundle
from tests.ghcn_graphic_helpers import graphic_bundles
from tests.test_air_quality_graphic_adapter import adapt as aq_spec
from tests.test_crw_graphic_adapter import adapt as crw_spec
from tests.test_fire_graphic_adapter import adapt as fire_spec
from tests.test_fire_map_graphic_adapter import adapt as map_spec
from tests.test_temperature_graphic_adapter import adapt as temperature_spec
from tests.test_viirs_map_graphic_adapter import adapt as viirs_spec
from tests.viirs_graphic_helpers import viirs_bundle

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def specs():
    temperatures = graphic_bundles()
    return [temperature_spec(temperatures[-1:]),
            temperature_spec(temperatures, template="temperature_trajectory"),
            crw_spec(*graphic_inputs()), aq_spec(aq_bundle()), fire_spec(fire_bundle()), map_spec(fire_bundle()),
            viirs_spec(viirs_bundle())]


@pytest.mark.parametrize("index", range(7))
def test_real_svg_preserves_full_qualifications_and_is_deterministic(specs, index):
    spec = specs[index]
    original = deepcopy(spec)
    result = renderer.render_svg(**spec)
    assert result == renderer.render_svg(**spec)
    assert spec == original
    assert 0 < len(result["svg"]) <= renderer.MAX_SVG_BYTES
    assert result["width"] == 1200 and result["height"] == 1500
    assert result["svg_sha256"] == hashlib.sha256(result["svg"]).hexdigest()
    assert result["cache_key"] == fingerprint(result["binding"])
    assert result["binding"]["source_evidence_sha256"] == spec["expected_evidence_sha256"]
    assert result["publication_approved"] is False
    assert b"<!DOCTYPE" not in result["svg"] and b"<!ENTITY" not in result["svg"]
    tree = ET.fromstring(result["svg"])
    assert tree.find(NS + "title").text == result["title"]
    assert tree.find(NS + "desc").text == result["alt_text"] == build_alt_text(spec["template"], spec["evidence"])
    assert "SYNTHETIC" in result["alt_text"]
    tags = {node.tag.removeprefix(NS) for node in tree.iter()}
    assert not tags & {"script", "foreignObject", "image", "a", "use"}
    assert all(not key.lower().startswith("on") and not key.endswith("href")
               for node in tree.iter() for key in node.attrib)
    style = tree.find(NS + "style").text
    assert style.count("url(") == 1 and "data:font/ttf;base64," in style


def test_svg_does_not_write_assets_or_invoke_pdf_or_subprocess(specs, monkeypatch, tmp_path):
    from reportlab.graphics import renderPDF

    def forbidden(*args, **kwargs):
        raise AssertionError("SVG tried an output/subprocess/PDF operation")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(renderer.subprocess, "run", forbidden)
    monkeypatch.setattr(renderPDF, "drawToFile", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    result = renderer.render_svg(**specs[5])
    assert result["svg"].startswith(b"<?xml") and not list(tmp_path.iterdir())


def test_invalid_evidence_fails_before_optional_dependency_import(specs, monkeypatch):
    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith("reportlab"), "optional renderer loaded before qualification"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    spec = deepcopy(specs[5])
    spec["evidence"]["points"][0]["frp_source"] += 20
    with pytest.raises(ValueError):
        renderer.render_svg(**spec)
    spec["expected_evidence_sha256"] = fingerprint(spec["evidence"])
    with pytest.raises(ValueError):
        renderer.render_svg(**spec)


def test_oversize_svg_is_refused_not_truncated(specs, monkeypatch):
    normal = renderer.render_svg(**specs[5])
    monkeypatch.setattr(renderer, "MAX_SVG_BYTES", len(normal["svg"]) - 1)
    with pytest.raises(ValueError, match="SVG byte limit"):
        renderer.render_svg(**specs[5])
    monkeypatch.setattr(renderer, "MAX_SVG_BYTES", len(normal["svg"]))
    assert renderer.render_svg(**specs[5]) == normal


def test_source_like_markup_is_text_not_executable_xml():
    evidence = json.loads((ROOT / "tests/fixtures/evidence_graphics_synthetic.json").read_text())["temperature_comparator"]
    evidence["location"] = "<svg/onload=x>&'\""
    result = renderer.render_svg("temperature_comparator", evidence, expected_evidence_sha256=fingerprint(evidence))
    tree = ET.fromstring(result["svg"])
    text = " ".join(tree.itertext())
    assert evidence["location"] in text
    assert len(tree.findall(".//" + NS + "svg")) == 0
    assert not any("onload" in node.attrib for node in tree.iter())


def test_long_word_or_unrenderable_axis_never_silently_clips():
    evidence = json.loads((ROOT / "tests/fixtures/evidence_graphics_synthetic.json").read_text())["temperature_comparator"]
    evidence["scope"] = "x" * 100
    with pytest.raises(ValueError, match="readable"):
        renderer.render_svg("temperature_comparator", evidence, expected_evidence_sha256=fingerprint(evidence))
    with pytest.raises(ValueError, match="unrenderable"):
        renderer.render_svg(**fire_spec(fire_bundle([1.7e308])))


@pytest.mark.parametrize("index,adapter", [(4, "fire_graphic_adapter.py"), (5, "fire_map_graphic_adapter.py"),
                                           (6, "viirs_map_graphic_adapter.py")])
@pytest.mark.parametrize("resource", ["evidence_graphic_render.py", "evidence_graphic.py", "adapter", renderer.FONT_RESOURCE])
def test_packaged_resource_changes_invalidate_render_identity(specs, monkeypatch, index, adapter, resource):
    name = adapter if resource == "adapter" else resource
    original = renderer.render_svg(**specs[index])
    digest = renderer._resource_digest
    monkeypatch.setattr(renderer, "_resource_digest", lambda key: "a" * 64 if key == name else digest(key))
    changed = renderer.render_svg(**specs[index])
    assert changed["cache_key"] != original["cache_key"]


def test_concurrent_rendering_does_not_mix_charts_or_font_state(specs):
    expected = [renderer.render_svg(**s) for s in specs]
    with ThreadPoolExecutor(max_workers=5) as pool:
        actual = list(pool.map(lambda s: renderer.render_svg(**s), specs * 2))
    assert actual == expected * 2


@pytest.mark.parametrize("index", [4, 5, 6])
def test_zip_loaded_renderer_matches_filesystem_without_extraction(specs, tmp_path, index):
    # This is a test-only package of public source, not the production allowlist.
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((ROOT / "src").rglob("*.py")):
            bundle.write(path, path.relative_to(ROOT))
        bundle.write(ROOT / "src/media" / renderer.FONT_RESOURCE, "src/media/" + renderer.FONT_RESOURCE)
        for name in ("ne_110m_land_v4_1_0.json", "manifest.json", "NOTICE.md"):
            bundle.write(ROOT / "src/media/maps" / name, "src/media/maps/" + name)
    fixture = tmp_path / "spec.json"
    fixture.write_text(json.dumps(specs[index]))
    script = '''
import json, socket, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
def deny(*a, **k): raise AssertionError("network is forbidden")
socket.socket.connect = deny
from src.media.evidence_graphic_render import render_svg
with open(sys.argv[2]) as f: spec = json.load(f)
r = render_svg(**spec)
print(json.dumps({k: r[k] for k in ("cache_key", "svg_sha256", "alt_text")}))
'''
    result = subprocess.run([sys.executable, "-I", "-c", script, str(archive), str(fixture)],
                            check=True, capture_output=True, text=True, cwd=tmp_path, timeout=30)
    normal = renderer.render_svg(**specs[index])
    assert json.loads(result.stdout) == {k: normal[k] for k in ("cache_key", "svg_sha256", "alt_text")}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["runtime.zip", "spec.json"]


def test_current_map_uses_shared_measured_layout_and_keeps_current_font_bounds():
    spec = map_spec(fire_bundle(values=[125.75, 500.1234, 750.25, 0],
        coordinates=[(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]))
    layout = renderer.map_text_layout(spec["evidence"])
    root = ET.fromstring(renderer.render_svg(**spec)["svg"])
    rendered = root.findall(".//" + NS + "text")
    assert [row["text"] for row in layout["texts"]] == ["".join(node.itertext()) for node in rendered]
    for row in layout["texts"]:
        left, bottom, right, top = row["box"]
        assert 20 <= left < right <= 1180 and 20 <= bottom < top <= 1480
    assert all(row["size"] == 56 for row in layout["point_labels"])
    for row, retained in zip(layout["point_labels"], spec["evidence"]["map"]["labels"]):
        x0, y0, x1, y1 = row["box"]
        assert retained["box"][0] <= x0 < x1 <= retained["box"][2]
        assert retained["box"][1] <= y0 < y1 <= retained["box"][3]


def test_viirs_map_uses_the_same_measured_layout_for_readiness_and_drawing():
    spec = viirs_spec(viirs_bundle([125.75, 500.1234, 750.25, 0], categories=("high", "nominal", "low", "high"),
                                   coordinates=[(35, -110), (35, -109.989), (35.009, -110), (35.009, -109.989)]))
    layout = renderer.map_text_layout(spec["evidence"])
    root = ET.fromstring(renderer.render_svg(**spec)["svg"])
    assert [row["text"] for row in layout["texts"]] == ["".join(node.itertext()) for node in root.findall(".//" + NS + "text")]
    texts = [row["text"] for row in layout["texts"]]
    assert texts.index("Source detection confidence") + 1 == texts.index("A high · B nominal · C low · D high")
    assert "NASA FIRMS · NOAA-20 VIIRS" in texts and not any("MODIS" in text for text in texts)
    assert all(row["size"] == 56 for row in layout["point_labels"])
