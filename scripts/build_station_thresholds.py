#!/usr/bin/env python3
"""Owner-run GHCN-Daily threshold rebuild from explicit local inputs.

Replaces the old one-shot bootstrap that silently downloaded the whole archive.
Every step is explicit, bounded and restartable; nothing uploads.

  resolve-inputs bounded read of the primary NOAA GHCN-Daily index and
                 ghcnd-version.txt -> a byte-pinned, versioned fetch plan
                 (2 GETs; no data asset is read)
  fetch-inputs   fetch exactly the planned stations/inventory/countries/version
                 files (owned bounded transport) and ghcnd_all.tar.gz (range-
                 resumable with If-Range, exact planned size) into a new inputs
                 directory bound by inputs-manifest.json; resumable
  package        offline: verified inputs -> plan -> all partitions -> package
                 -> verification -> upload plan + exact install command
  install-manifest  replace data/station_thresholds.version only when the new
                 asset is verified on the release; the old manifest is kept
  fetch-archive  bounded resumable download of ghcnd_all.tar.gz with a receipt
                 (--max-bytes/--deadline-seconds/--max-retries are required)
  plan           exact inputs (stations/inventory/countries files + archive),
                 snapshot cutoff, QC policy, active universe and partitions
  build          one archive pass over the selected pending partitions; each
                 partition is published only when complete
  assemble       SQLite artifact + gzip asset + V2 manifest + build manifest

Station/inventory/country text files are the NOAA ghcnd-stations.txt,
ghcnd-inventory.txt and ghcnd-countries.txt files, saved by the owner.
Then verify and plan the upload with ``scripts/threshold_package.py``.
Each command prints JSON. Exit 0 ready/planned, 1 other status, 2 refused input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import acquisition_dependencies as deps  # noqa: E402
from src.data import bounded_http  # noqa: E402
from src.data import threshold_rebuild as rebuild  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
INSTALLED_MANIFEST = REPO / "data" / "station_thresholds.version"


def _transport(base_url: str, *, requests: int, transfer: int, deadline: float, retries: int,
               cancel: threading.Event, options: dict | None = None) -> bounded_http.BoundedTransport:
    limits = bounded_http.Limits(max_requests=requests, max_transfer_bytes=transfer, max_decoded_bytes=transfer,
                                 deadline_seconds=deadline, max_retries=retries,
                                 max_response_bytes=rebuild.MAX_TEXT_BYTES)
    return bounded_http.BoundedTransport(limits, allowed_origins=[base_url], cancel=cancel, **(options or {}))


def _cancel_on_sigterm(cancel: threading.Event):
    if threading.current_thread() is not threading.main_thread():
        return None
    return signal.signal(signal.SIGTERM, lambda _signum, _frame: cancel.set())


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise bounded_http.TransportStop("cancelled")


def _read_json(path: Path, limit: int = 4 * 1024**2):
    return json.loads(path.read_bytes()[:limit])


def _paths(args) -> dict[str, Path]:
    return {"stations": args.stations, "inventory": args.inventory, "countries": args.countries,
            "archive": args.archive}


def _emit(document: dict) -> int:
    print(json.dumps(document, sort_keys=True, indent=2))
    return 0 if document.get("status") in {"planned", "ready"} else 1


def main(argv: list[str] | None = None, *, session_factory=None, base_url: str = rebuild.BASE_URL,
         transport_options: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve-inputs")
    resolve.add_argument("--output", type=Path, required=True)
    resolve.add_argument("--deadline-seconds", type=float, default=60.0)
    resolve.add_argument("--max-retries", type=int, default=2)
    fetch_inputs = sub.add_parser("fetch-inputs")
    fetch_inputs.add_argument("--fetch-plan", type=Path, required=True)
    fetch_inputs.add_argument("--dest", type=Path, required=True)
    fetch_inputs.add_argument("--deadline-seconds", type=float, required=True)
    fetch_inputs.add_argument("--max-retries", type=int, required=True)
    pack = sub.add_parser("package")
    pack.add_argument("--inputs", type=Path, required=True)
    pack.add_argument("--work-dir", type=Path, required=True)
    pack.add_argument("--out-dir", type=Path, required=True)
    pack.add_argument("--partitions", type=int, required=True)
    pack.add_argument("--deadline-seconds", type=float, required=True)
    pack.add_argument("--snapshot-date")
    pack.add_argument("--release-assets", type=Path, help="saved `gh api repos/<repo>/releases/tags/thresholds-latest`")
    pack.add_argument("--installed-manifest", type=Path, default=INSTALLED_MANIFEST)
    pack.add_argument("--repo", default=rebuild.DEFAULT_REPO)
    install = sub.add_parser("install-manifest")
    install.add_argument("--manifest", type=Path, required=True)
    install.add_argument("--build-manifest", type=Path, required=True)
    install.add_argument("--release-assets", type=Path, required=True)
    install.add_argument("--installed", type=Path, default=INSTALLED_MANIFEST)
    fetch = sub.add_parser("fetch-archive")
    fetch.add_argument("--dest", type=Path, required=True)
    fetch.add_argument("--max-bytes", type=int, required=True)
    fetch.add_argument("--deadline-seconds", type=float, required=True)
    fetch.add_argument("--max-retries", type=int, required=True)
    for name in ("plan", "build", "assemble"):
        command = sub.add_parser(name)
        for flag in ("--stations", "--inventory", "--countries", "--archive"):
            command.add_argument(flag, type=Path, required=True)
        if name == "plan":
            command.add_argument("--snapshot-date", required=True)
            command.add_argument("--partitions", type=int, required=True)
            command.add_argument("--active-year-cutoff", type=int)
            command.add_argument("--archive-receipt", type=Path)
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--work-dir", type=Path, required=True)
        if name == "build":
            command.add_argument("--partition", type=int, action="append", help="repeat; default all pending")
            command.add_argument("--deadline-seconds", type=float, required=True)
        if name == "assemble":
            command.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    cancel = threading.Event()
    previous = _cancel_on_sigterm(cancel) if args.command in {"resolve-inputs", "fetch-inputs"} else None
    try:
        if args.command == "resolve-inputs":
            retries = args.max_retries
            transport = _transport(base_url, requests=2 * (1 + retries), transfer=2 * 1024**2,
                                   deadline=args.deadline_seconds, retries=retries, cancel=cancel,
                                   options=transport_options)
            plan = rebuild.resolve_inputs(transport, base_url=base_url)
            if args.output.exists() and _read_json(args.output).get("plan_sha256") != plan["plan_sha256"]:
                raise rebuild.RebuildError("threshold_fetch_plan_output_exists")
            rebuild._atomic_bytes(args.output, json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")
            return _emit(deps.result("thresholds", "planned", source={
                "fetch_plan_sha256": plan["plan_sha256"], "source_version": plan["source_version"]["version"]},
                product={"assets": {role: {"name": a["name"], "bytes": a["bytes"]} for role, a in plan["assets"].items()},
                         "suggested_snapshot_date": plan["suggested_snapshot_date"]},
                counters={"transport": transport.snapshot()}))
        if args.command == "fetch-inputs":
            plan = rebuild._check_fetch_plan(_read_json(args.fetch_plan))
            retries = args.max_retries
            if not 0 <= retries <= 5 or not 1 <= args.deadline_seconds <= 24 * 3600:
                raise rebuild.RebuildError("threshold_fetch_limit_invalid")
            transport = _transport(plan["base_url"], requests=5 * (1 + retries),
                                   transfer=plan["limits"]["text_transfer_bytes"] * (1 + retries),
                                   deadline=args.deadline_seconds, retries=retries, cancel=cancel,
                                   options=transport_options)
            if session_factory is None:
                import requests

                session_factory = requests.Session
            remaining = max(transport.remaining(), 1.0)
            return _emit(rebuild.fetch_inputs(plan, args.dest, transport=transport, archive_session=session_factory(),
                                              archive_deadline_seconds=remaining, max_retries=retries))
        if args.command == "package":
            release = _read_json(args.release_assets) if args.release_assets else None
            return _emit(rebuild.package(args.inputs, work_dir=args.work_dir, out_dir=args.out_dir,
                                         partitions=args.partitions, deadline_seconds=args.deadline_seconds,
                                         snapshot_date=args.snapshot_date, release_assets=release,
                                         installed_manifest=args.installed_manifest, repo=args.repo))
        if args.command == "install-manifest":
            outcome = rebuild.install_manifest(args.manifest, args.installed, build_manifest=args.build_manifest,
                                               release_assets=_read_json(args.release_assets))
            print(json.dumps(outcome, sort_keys=True, indent=2))
            return 0
        if args.command == "fetch-archive":
            if session_factory is None:
                import requests

                session_factory = requests.Session
            return _emit(rebuild.fetch_archive(args.dest, session=session_factory(), max_bytes=args.max_bytes,
                                               deadline_seconds=args.deadline_seconds, max_retries=args.max_retries,
                                               check=lambda: _check_cancel(cancel)))
        if args.command == "plan":
            plan = rebuild.build_plan(stations=args.stations, inventory=args.inventory, countries=args.countries,
                                      archive=args.archive, snapshot_date=args.snapshot_date,
                                      partitions=args.partitions, active_year_cutoff=args.active_year_cutoff,
                                      archive_receipt=args.archive_receipt)
            if args.output.exists() and json.loads(args.output.read_text()).get("plan_sha256") != plan["plan_sha256"]:
                raise rebuild.RebuildError("threshold_plan_output_exists")
            rebuild._atomic_bytes(args.output, json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")
            status = "source_absent" if plan["missing_inputs"] else "planned"
            return _emit(deps.result("thresholds", status, reasons=[f"{name}_missing" for name in plan["missing_inputs"]],
                                     source={"plan_sha256": plan["plan_sha256"], "inputs": plan["inputs"]},
                                     product={"active_stations": plan["active_stations"],
                                              "partitions": len(plan["partitions"])},
                                     observed=plan["active_stations"]))
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if args.command == "build":
            return _emit(rebuild.build_partitions(plan, paths=_paths(args), work_dir=args.work_dir,
                                                  select=args.partition, deadline_seconds=args.deadline_seconds))
        build = rebuild.assemble(plan, paths=_paths(args), work_dir=args.work_dir, out_dir=args.out_dir)
        return _emit(deps.result("thresholds", "ready", source={"plan_sha256": plan["plan_sha256"]},
                                 product={"database": build["database"], "asset": build["asset"],
                                          "coverage": build["coverage"]},
                                 observed=build["coverage"]["active_stations"],
                                 promoted=build["coverage"]["active_with_thresholds"]))
    except bounded_http.TransportStop as stop:
        print(json.dumps({"status": "incomplete", "reasons": [stop.reason]}))
        return 1
    except bounded_http.TransportOutcome as outcome:
        print(json.dumps({"status": "incomplete", "reasons": [f"provider_{outcome.outcome}"]}))
        return 1
    except (deps.AcquisitionError, OSError, ValueError, KeyError) as error:
        label = str(error) if isinstance(error, deps.AcquisitionError) else "threshold_input_unavailable"
        print(json.dumps({"status": "refused", "error": label}))
        return 2
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
