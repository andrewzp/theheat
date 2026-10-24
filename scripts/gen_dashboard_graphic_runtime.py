#!/usr/bin/env python3
"""Build the explicit public Python preview package; --check never writes files."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Deliberately explicit: lazy scientific guards must stay in the package.
SOURCES = (
    'src/__init__.py',
    'src/dashboard_preview/__init__.py',
    'src/dashboard_preview/auth.py',
    'src/dashboard_preview/errors.py',
    'src/dashboard_preview/http.py',
    'src/dashboard_preview/preview.py',
    'src/dashboard_preview/reader.py',
    'src/dashboard_preview/reader_status.py',
    'src/data/__init__.py',
    'src/data/_freshness.py',
    'src/data/_http.py',
    'src/data/air_quality.py',
    'src/data/air_quality_contract.py',
    'src/data/air_quality_evidence.py',
    'src/data/coral_evidence.py',
    'src/data/coral_regional_contract.py',
    'src/data/coral_source_contract.py',
    'src/data/crw_contract.py',
    'src/data/fire_evidence.py',
    'src/data/fire_identity.py',
    'src/data/fire_source_contract.py',
    'src/data/ghcn.py',
    'src/data/ghcn_db.py',
    'src/data/ghcn_format.py',
    'src/data/open_meteo.py',
    'src/data/openmeteo_budget.py',
    'src/data/places.py',
    'src/data/source_status.py',
    'src/data/temperature_evidence.py',
    'src/data/temperature_history.py',
    'src/editorial/__init__.py',
    'src/editorial/_util.py',
    'src/editorial/approval.py',
    'src/editorial/candidates.py',
    'src/editorial/marine_evidence.py',
    'src/editorial/publication.py',
    'src/editorial/revisions.py',
    'src/editorial/scoring/__init__.py',
    'src/editorial/scoring/_shared.py',
    'src/editorial/scoring/air_quality.py',
    'src/editorial/scoring/atmospheric.py',
    'src/editorial/scoring/disasters.py',
    'src/editorial/scoring/drought.py',
    'src/editorial/scoring/fire.py',
    'src/editorial/scoring/hot10.py',
    'src/editorial/scoring/marine.py',
    'src/editorial/scoring/precipitation.py',
    'src/editorial/scoring/synthesis.py',
    'src/editorial/scoring/temperature.py',
    'src/editorial/scoring/wetbulb.py',
    'src/editorial/thresholds.py',
    'src/media/__init__.py',
    'src/media/air_quality_graphic_adapter.py',
    'src/media/evidence_graphic.py',
    'src/media/evidence_graphic_render.py',
    'src/media/fire_graphic_adapter.py',
    'src/media/fire_map_graphic_adapter.py',
    'src/media/maps/ne_110m_land_v4_1_0.json',
    'src/media/maps/manifest.json',
    'src/media/maps/NOTICE.md',
    'src/media/fonts/DejaVuSansMono.ttf',
    'src/media/fonts/DejaVu-LICENSE.txt',
    'src/media/temperature_graphic_adapter.py',
    'src/media/viirs_map_graphic_adapter.py',
    'src/state_schema.py',
    'src/two_bot/__init__.py',
    'src/two_bot/evidence_contract.py',
    'src/two_bot/ghcn_claim_contract.py',
    'src/two_bot/intern/__init__.py',
    'src/two_bot/intern/air_quality.py',
    'src/two_bot/json_utils.py',
    'src/two_bot/strict_contract.py',
    'src/two_bot/types.py',
)
RESOURCES = (
    ("src/data/registry/place_registry.json", "data/place_registry.json"),
    ("src/data/registry/country_codes.json", "data/country_codes.json"),
)
DEPLOYMENT_FILES = ("api/graphic_preview.py", "api/graphic_reader_status.py", "pyproject.toml", "uv.lock")


BASEMAP_PINS = {
    "ne_110m_land_v4_1_0.zip": "1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de",
    "ne_110m_land_v4_1_0.json": "a37b057aca4fc9714a0c24b5d6bc9778bb5845894646e4052383ea63fa3cd50d",
    "manifest.json": "1af072edc46ae3252bf6cf0edb43993986de262a2840b2cd4907eb4866f970e9",
}


def validate_basemap(root):
    """Package only the reviewed local map resources; never fetch or rewrite pins."""
    for name, expected in BASEMAP_PINS.items():
        with (root / "src/media/maps" / name).open("rb") as stream:
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024 or sha256(content).hexdigest() != expected:
            raise ValueError("Unqualified basemap resource: " + name)


def generate(root=ROOT):
    validate_basemap(root)
    output = BytesIO()
    files = {}
    entries = [(name, name) for name in SOURCES] + list(RESOURCES)
    seen = set()
    for destination, source in entries:
        for name in (destination, source):
            path = PurePosixPath(name)
            if (not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)
                    or str(path) != name):
                raise ValueError("Unsafe graphic runtime path")
        if destination in seen:
            raise ValueError("Duplicate graphic runtime destination")
        seen.add(destination)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, source in entries:
            data = (root / source).read_bytes()
            files[name] = sha256(data).hexdigest()
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    packaged = output.getvalue()
    policy = (root / "dashboard/lib/editorial-policy-manifest.js").read_text()
    source_policy = json.loads(policy.split("export const EDITORIAL_POLICY_MANIFEST = ", 1)[1])
    identity = {
        "schema_version": 1, "format": "saved-source-svg-preview-v2",
        "archive_sha256": sha256(packaged).hexdigest(), "files": files,
        "resource_sources": dict(RESOURCES),
        "policy_source_sha256": source_policy["source_sha256"],
        "deployment_files": {name: sha256((root / "dashboard" / name).read_bytes()).hexdigest()
                             for name in DEPLOYMENT_FILES},
    }
    manifest = {"identity": identity, "runtime_sha256": sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    return packaged, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, content in zip(("graphic-runtime.zip", "lib/graphic-runtime-manifest.json"), generate()):
        target = ROOT / "dashboard" / name
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                raise SystemExit("Graphic runtime is stale. Run python scripts/gen_dashboard_graphic_runtime.py")
        else:
            target.write_bytes(content)


if __name__ == "__main__":
    main()
