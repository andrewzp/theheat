"""Pinned public-domain shapefile conversion, bounded and offline."""

from io import BytesIO
import hashlib
import struct
import zipfile

from pathlib import Path

import pytest

from scripts import build_fire_basemap as build


def raw():
    return (build.FOLDER / build.ARCHIVE).read_bytes()


def test_exact_archive_offline_rebuild_twice_and_resource_bounds():
    a = build.build(
        raw(),
        converter_sha256=hashlib.sha256(
            __import__("pathlib").Path(build.__file__).read_bytes()
        ).hexdigest(),
    )
    assert a == build.build(
        raw(),
        converter_sha256=hashlib.sha256(
            __import__("pathlib").Path(build.__file__).read_bytes()
        ).hexdigest(),
    )
    assert a[0] == (build.FOLDER / build.DERIVED).read_bytes()
    assert a[1] == (build.FOLDER / "manifest.json").read_bytes()
    assert len(a[0]) <= 512 * 1024


def repack(change):
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(raw())) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            name, data = change(item.filename, src.read(item))
            dst.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize("kind", ["traversal", "version", "crs", "extra", "oversize"])
def test_invalid_archive_members_never_extract(kind, tmp_path, monkeypatch):
    def change(name, data):
        if name.endswith(".VERSION.txt"):
            if kind == "traversal":
                return "../VERSION.txt", data
            if kind == "version":
                return name, b"4.0.0"
            if kind == "extra":
                return "unrelated.txt", data
            if kind == "oversize":
                return name, b"0" * (2 * 1024 * 1024 + 1)
        if name.endswith(".prj") and kind == "crs":
            return name, b"unknown"
        return name, data

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        build.members(repack(change))
    assert not list(tmp_path.iterdir())


def test_changed_original_refuses_before_member_parsing(monkeypatch):
    monkeypatch.setattr(build, "members", lambda *_: pytest.fail("must check pin first"))
    with pytest.raises(ValueError, match="hash"):
        build.build(raw() + b"x", converter_sha256="a" * 64)


@pytest.mark.parametrize("kind", ["type", "length", "nonfinite", "bounds", "ring"])
def test_shapefile_structural_damage_refuses(kind):
    shape = bytearray(build.members(raw())["ne_110m_land.shp"])
    if kind == "type":
        struct.pack_into("<i", shape, 32, 3)
    elif kind == "length":
        shape.pop()
    else:
        rec = 108
        parts, count = struct.unpack_from("<2i", shape, rec + 36)
        start = rec + 44 + 4 * parts
        if kind == "nonfinite":
            struct.pack_into("<d", shape, start, float("nan"))
        elif kind == "bounds":
            struct.pack_into("<d", shape, start, 180 + 1e-9)
        else:
            struct.pack_into("<d", shape, start, 0.01234)
    with pytest.raises(ValueError):
        build.rings_from_shp(shape)


@pytest.mark.parametrize("name", ["ne_110m_land_v4_1_0.zip", "ne_110m_land_v4_1_0.json", "manifest.json"])
def test_runtime_packaging_refuses_changed_map_resources(tmp_path, name):
    from scripts.gen_dashboard_graphic_runtime import BASEMAP_PINS, validate_basemap
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "src/media/maps"
    target.mkdir(parents=True)
    for filename in BASEMAP_PINS:
        (target / filename).write_bytes((root / "src/media/maps" / filename).read_bytes())
    validate_basemap(tmp_path)
    with (target / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="Unqualified basemap"):
        validate_basemap(tmp_path)
