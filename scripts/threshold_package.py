#!/usr/bin/env python3
"""Offline threshold package verification and an explicit (never executed) upload plan.

  verify       manifest, digest/size, schema, station coverage, cutoff, asset
               identity and the actual ghcn_runtime_inputs consumer read
  upload-plan  verify, then print the exact owner steps; no upload happens here

``--release-assets`` takes an operator-saved ``gh api repos/<repo>/releases/tags/
thresholds-latest`` JSON document so the current release state (including an
empty release) is reported as read, never assumed. Exit 0 ready, 1 otherwise,
2 refused input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import acquisition_dependencies as deps  # noqa: E402
from src.data import threshold_rebuild as rebuild  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["verify", "upload-plan"])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset", type=Path)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--release-assets", type=Path)
    parser.add_argument("--installed-manifest", type=Path, default=REPO / "data" / "station_thresholds.version")
    parser.add_argument("--repo", default=rebuild.DEFAULT_REPO)
    args = parser.parse_args(argv)
    try:
        release = None
        if args.release_assets is not None:
            release = json.loads(args.release_assets.read_bytes()[: 4 * 1024**2])
        verification = rebuild.verify_package(args.db, args.manifest, asset=args.asset,
                                              build_manifest=args.build_manifest, release_assets=release)
        if args.command == "verify":
            print(json.dumps(verification, sort_keys=True, indent=2))
            return 0 if verification["status"] == "ready" else 1
        if args.asset is None:
            raise rebuild.RebuildError("threshold_asset_required")
        plan = rebuild.upload_plan(verification, asset=args.asset, manifest_path=args.manifest,
                                   installed_manifest=args.installed_manifest, repo=args.repo)
        print(json.dumps(plan, sort_keys=True, indent=2))
        return 0
    except (deps.AcquisitionError, OSError, ValueError) as error:
        label = str(error) if isinstance(error, deps.AcquisitionError) else "threshold_package_unavailable"
        print(json.dumps({"status": "refused", "error": label}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
