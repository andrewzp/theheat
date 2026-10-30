#!/usr/bin/env python3
"""P17a current-GHCN pilot qualification from primary NOAA metadata; fetches nothing.

  ghcn-pilots --inputs DIR            the byte-pinned inputs from
                                      build_station_thresholds.py fetch-inputs
                                      (stations/inventory/countries re-hashed)
  ghcn-pilots --stations F --inventory F --countries F
                                      explicit metadata files

Prints one theheat.regional-ghcn-coverage/v1 JSON document (also written with
--output). Exit 0 when every pilot's GHCN coverage was qualified (present or
absent), 1 when a pilot's country code could not be verified, 2 refused input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import places, regional_coverage, threshold_rebuild  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    threshold_rebuild._sha_file(path, threshold_rebuild.MAX_TEXT_BYTES)
    return path.read_text(encoding="ascii", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    pilots = sub.add_parser("ghcn-pilots")
    pilots.add_argument("--inputs", type=Path)
    for name in ("--stations", "--inventory", "--countries"):
        pilots.add_argument(name, type=Path)
    pilots.add_argument("--cities", type=Path, default=REPO / "data" / "cities.csv")
    pilots.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        version = identities = None
        if args.inputs is not None:
            document = threshold_rebuild.verify_inputs(args.inputs, roles=("stations", "inventory", "countries"))
            paths = {role: args.inputs / document["inputs"][role]["name"] for role in ("stations", "inventory", "countries")}
            version = document["source_version"]
            identities = {role: {k: document["inputs"][role][k] for k in ("name", "sha256", "bytes")} for role in paths}
        elif args.stations and args.inventory and args.countries:
            paths = {"stations": args.stations, "inventory": args.inventory, "countries": args.countries}
            identities = {role: threshold_rebuild._identity(path, threshold_rebuild.MAX_TEXT_BYTES)
                          for role, path in paths.items()}
        else:
            raise threshold_rebuild.RebuildError("regional_coverage_inputs_required")
        result = regional_coverage.qualify(_read(paths["stations"]), _read(paths["inventory"]), _read(paths["countries"]),
                                           catalogue=places.load_cities(str(args.cities)), source_version=version,
                                           input_identities=identities)
    except (threshold_rebuild.RebuildError, OSError, ValueError, KeyError) as error:
        label = str(error) if isinstance(error, threshold_rebuild.RebuildError) else "regional_coverage_input_unavailable"
        print(json.dumps({"status": "refused", "error": label}))
        return 2
    body = json.dumps(result, sort_keys=True, indent=2)
    if args.output:
        threshold_rebuild._atomic_bytes(args.output, body.encode() + b"\n")
    print(body)
    return 0 if all(p["status"] != "country_code_unverified" for p in result["pilots"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
