"""The SUPPLY review's exact production chain over a builder-made GHCND candidate (test-only).

``admit(candidate)`` -> ``install_plan(candidate, <tmp>/data/normals_ghcnd_mean_tmax.csv)`` ->
``load_normals(candidate/normals.csv)`` -> ``hot10_contract.qualify(h.city_temps(HOT10_CAPTURE), ...,
sampled=14, now=HOT10_CAPTURE, product=PRODUCT)`` -> ``build_hot10_bundle()`` -> ``validate_bundle()`` ->
``hot10_graphic_spec(..., expected_bundle_sha256=gist_hazard_media.fingerprint(bundle), synthetic=True)``.

Every stage runs on its own, as the review ran them, so a refusal upstream never hides what a
later stage does with the same bytes. Each case starts from a fresh candidate produced by the real
``build_candidate`` over ``tests.real_closure.test_supply_ghcnd_normals._world`` (12 registered
fixture cities, 144 monthly rows). A CSV mutation updates only the manifest's ``csv_sha256`` and
``csv_bytes``; the missing-manifest case removes the review's nine provenance fields. Bundle
mutations change a valid control bulletin's retained baselines and re-fingerprint every row (the
graphic stage is then given the mutated bundle's own fingerprint). Invented inputs; no network,
no renderer, no PNG.

``python -m tests.real_closure.supply_repair_chain`` prints both tables (receipt driver).
"""
from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

from src.data import ghcnd_monthly_normals as gn
from src.editorial import hot10_contract as contract
from src.media import gist_hazard_media as media, hot10_graphic_adapter as adapter
from src.two_bot.intern import build_hot10_bundle
from tests import gist_hazard_helpers as gh, live_content_harness as h

NOW = gh.HOT10_CAPTURE
REMOVED_PROVENANCE = ("inputs", "source_version", "input_product", "cities", "stations", "attribution", "dataset",
                      "units", "assembled_at")


def build(root: Path) -> Path:
    """A fresh synthetic candidate from the real builder (the review's ``_world``)."""
    from tests.real_closure.test_supply_ghcnd_normals import _world

    world = _world(root)
    out = root / "out"
    result = gn.build_candidate(world.cities, world.write(), world.dir, out)
    assert result["status"] == "ready", result
    return out / "candidate"


def read_rows(candidate: Path) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO((candidate / "normals.csv").read_text(encoding="utf-8")))
    return list(reader.fieldnames or ()), list(reader)


def _write_manifest(candidate: Path, manifest: dict[str, Any]) -> None:
    (candidate / "manifest.json").write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                                         ensure_ascii=False).encode())


def rewrite_rows(candidate: Path, change: Callable[[dict[str, str]], None]) -> None:
    """Apply ``change`` to every CSV row, then update only csv_sha256/csv_bytes in the manifest."""
    fields, rows = read_rows(candidate)
    for row in rows:
        change(row)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = buffer.getvalue().encode("utf-8")
    (candidate / "normals.csv").write_bytes(body)
    manifest = json.loads((candidate / "manifest.json").read_bytes())
    manifest.update(csv_sha256=hashlib.sha256(body).hexdigest(), csv_bytes=len(body))
    _write_manifest(candidate, manifest)


def strip_manifest(candidate: Path, keys: tuple[str, ...] = REMOVED_PROVENANCE) -> None:
    manifest = json.loads((candidate / "manifest.json").read_bytes())
    for key in keys:
        manifest.pop(key, None)
    _write_manifest(candidate, manifest)


def _rows_change(**values: str) -> Callable[[Path], None]:
    return lambda candidate: rewrite_rows(candidate, lambda row: row.update(values))


# The review's table, same rows in the same order.
CASES: dict[str, Callable[[Path], None]] = {
    "Valid control": lambda candidate: None,
    "valid_days=0": _rows_change(valid_days="0"),
    "station_lat=0, station_lon=0, distance_km=0": _rows_change(station_lat="0.0", station_lon="0.0",
                                                                distance_km="0.0"),
    "place_elevation_m=nan": _rows_change(place_elevation_m="nan"),
    "Manifest provenance removed": strip_manifest,
    "Row source_version=made-up-version": _rows_change(source_version="made-up-version"),
}


def graphic(bundle: dict) -> str:
    try:
        adapter.hot10_graphic_spec(bundle, expected_bundle_sha256=media.fingerprint(bundle), synthetic=True)
    except adapter.Hot10GraphicRefused as refused:
        return "refused:" + refused.code
    return "accepted"


def min_monthly_places(normals: dict[str, dict]) -> int:
    """Distinct loaded places per calendar month (the loader's view), minimum over the 12 months."""
    return min(sum(1 for entry in normals.values() if month in entry) for month in range(1, 13))


def qualify(normals: dict[str, dict], cities: tuple = h.CITIES) -> dict[str, Any]:
    """The review's call (``sampled=14`` for the harness's fourteen cities)."""
    return contract.qualify(h.city_temps(NOW, cities), normals, sampled=len(cities), now=NOW, product=gn.PRODUCT)


def bulletin(result: dict[str, Any]) -> dict:
    return build_hot10_bundle(result["rows"], changes=[], event_id=f"hot10_{NOW.date().isoformat()}",
                              universe=result["universe"]).to_dict()


def chain(candidate: Path, scratch: Path, cities: tuple = h.CITIES) -> dict[str, Any]:
    """Each production stage on the same candidate bytes; codes only."""
    out: dict[str, Any] = {}
    admission = gn.admit(candidate)
    out["admission"] = admission["status"]
    out["admission_reasons"] = sorted(set(admission["reasons"]))
    try:
        plan = gn.install_plan(candidate, scratch / "data" / gn.INSTALLED_NAME)
    except gn.GhcndNormalsError as error:
        out["install_plan"] = "refused:" + str(error)
    else:
        out["install_plan"] = plan["admission"]
    report: dict[str, Any] = {}
    normals = gn.load_normals(candidate / "normals.csv", report)
    out["loader"] = {"status": report.get("status"), "accepted": report.get("accepted"),
                     "refused": report.get("refused")}
    out["min_monthly_places"] = min_monthly_places(normals)
    result = qualify(normals, cities)
    out["qualified"] = result["universe"]["qualified_cities"]
    if not result["complete"]:
        out["bundle_errors"] = "held (fewer than 10 qualified)"
        out["graphic_spec"] = "not reached (held)"
        return out
    bundle = bulletin(result)
    out["bundle_errors"] = contract.validate_bundle(bundle)
    out["graphic_spec"] = graphic(bundle)
    return out


def control_bundle(root: Path) -> dict:
    """The valid control's bulletin, through the real chain."""
    candidate = build(root)
    result = qualify(gn.load_normals(candidate / "normals.csv"))
    assert result["complete"], result["universe"]
    return bulletin(result)


def refingerprint(bundle: dict) -> dict:
    for row in bundle["raw_signal_dump"]["cities"]:
        row["row_fingerprint"] = contract.row_fingerprint(row)
    return bundle


def _baseline(**values: Any) -> Callable[[dict], None]:
    return lambda baseline: baseline.update(values)


def _elevation_pair(baseline: dict) -> None:
    # Station and place agree with each other, but not with the registered catalogue point.
    baseline.update(place_elevation_m=3000.0, station_elevation_m=3000.0)


# Retained-bulletin mutations: every ranked row's baseline changed, then re-fingerprinted.
BUNDLE_CASES: dict[str, Callable[[dict], None]] = {
    "valid_days=0": _baseline(valid_days=0),
    "valid_days=931 (> 30 x 31 days)": _baseline(valid_days=931),
    "flagged_values=-1": _baseline(flagged_values=-1),
    "station_lat=0, station_lon=0, distance_km=0": _baseline(station_lat=0.0, station_lon=0.0, distance_km=0.0),
    "place/station elevation 3000 m (not the registered point)": _elevation_pair,
    "place_elevation_m=nan": _baseline(place_elevation_m=float("nan")),
    "source_version=made-up-version": _baseline(source_version="made-up-version"),
}


def bundle_case(bundle: dict, change: Callable[[dict], None]) -> dict[str, Any]:
    mutated = deepcopy(bundle)
    for row in mutated["raw_signal_dump"]["cities"]:
        change(row["baseline"])
    try:
        refingerprint(mutated)
    except ValueError as error:  # a non-finite value cannot be fingerprinted at all
        return {"refingerprint": "impossible:" + type(error).__name__, "bundle_errors": "n/a",
                "graphic_spec": "n/a"}
    return {"refingerprint": "ok", "bundle_errors": contract.validate_bundle(mutated), "graphic_spec": graphic(mutated)}


def run_all(root: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    table = {}
    for index, (name, mutate) in enumerate(CASES.items()):
        base = root / f"case{index}"
        candidate = build(base)
        mutate(candidate)
        table[name] = chain(candidate, base / "scratch")
    bundle = control_bundle(root / "bundle-control")
    bundles = {name: bundle_case(bundle, change) for name, change in BUNDLE_CASES.items()}
    return table, bundles


def _short(value: Any) -> str:
    return "`" + json.dumps(value) + "`" if isinstance(value, list) else str(value)


def render(table: dict[str, dict], bundles: dict[str, dict]) -> str:
    lines = ["| Independent mutation | Admission | Install plan | Minimum monthly places | Qualified | Bundle errors "
             "| Graphic spec |", "|---|---|---|---:|---:|---|---|"]
    for name, row in table.items():
        lines.append(f"| {name} | {row['admission']} | {row['install_plan']} | {row['min_monthly_places']} | "
                     f"{row['qualified']} | {_short(row['bundle_errors'])} | {row['graphic_spec']} |")
    lines += ["", "Admission reasons and loader report per case:"]
    for name, row in table.items():
        lines.append(f"- {name}: reasons={row['admission_reasons']} loader={json.dumps(row['loader'], sort_keys=True)}")
    lines += ["", "Retained bulletin (valid control) with every ranked baseline changed and re-fingerprinted:", "",
              "| Bundle mutation | Re-fingerprint | validate_bundle | Graphic spec |", "|---|---|---|---|"]
    for name, row in bundles.items():
        lines.append(f"| {name} | {row['refingerprint']} | {_short(row['bundle_errors'])} | {row['graphic_spec']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="theheat-supply-chain-") as directory:
        table, bundles = run_all(Path(directory))
    sys.stdout.write(render(table, bundles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
