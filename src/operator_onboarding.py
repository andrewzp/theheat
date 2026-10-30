"""Offline onboarding preflight and supplied-draft inspection (W16.4).

Reads the checkout and the running interpreter only. It never installs or
upgrades packages, reads environment values or credential files, opens a
network connection, or mutates state. Generator checks run the repository's own
``--check`` modes, which never write. Missing optional features are reported as
unavailable with the exact pinned input they need; nothing is repaired here.
"""
from __future__ import annotations

from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = {"core": "requirements.txt", "graphics": "requirements-graphics.txt",
                     "postgres": "requirements-postgres.txt"}
GENERATOR_CHECKS = ("gen_source_registry", "gen_editorial_policy", "gen_dashboard_graphic_runtime",
                    "gen_state_contract", "gen_usage_cost_contract", "gen_runtime_report_workflow")
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|>=)\s*([A-Za-z0-9.+_-]+)\s*$")
MAX_STATE_BYTES = 8 * 1024 * 1024


def _sha(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def pinned_requirements(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        match = _PIN.match(line)
        if match:
            rows.append({"name": match[1], "operator": match[2], "version": match[3]})
    return rows


def _installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def dependency_report(root: Path = ROOT) -> dict:
    groups: dict[str, dict[str, Any]] = {}
    for group, filename in REQUIREMENT_FILES.items():
        path = root / filename
        if not path.is_file():
            groups[group] = {"status": "requirements_missing", "file": filename, "packages": []}
            continue
        packages = []
        for pin in pinned_requirements(path):
            installed = _installed(pin["name"])
            if installed is None:
                state = "missing"
            elif pin["operator"] == "==":
                state = "match" if installed == pin["version"] else "mismatch"
            else:
                state = "present_unverified_minimum"
            packages.append({**pin, "installed": installed, "state": state})
        status = ("available" if all(p["state"] in ("match", "present_unverified_minimum") for p in packages)
                  else "unavailable")
        groups[group] = {"status": status, "file": filename, "packages": packages}
    return {"interpreter": sys.executable, "python": ".".join(map(str, sys.version_info[:3])), "groups": groups}


def repository_report(root: Path = ROOT) -> dict:
    from src.data.open_meteo import load_normals

    normals_path = root / "data/normals.csv"
    header = normals_path.read_text(encoding="utf-8").splitlines()[0] if normals_path.is_file() else ""
    qualified = load_normals(str(normals_path)) if normals_path.is_file() else {}
    thresholds: dict[str, Any] = {"manifest": "data/station_thresholds.version", "status": "missing"}
    manifest_path = root / "data/station_thresholds.version"
    if manifest_path.is_file():
        try:
            sys.path.insert(0, str(root))
            from scripts.threshold_artifacts import ArtifactError, read_manifest
            try:
                fields = read_manifest(manifest_path)
                local = root / "data/station_thresholds.sqlite"
                thresholds = {"manifest": "data/station_thresholds.version", "status": "manifest_valid",
                              "release": fields["release"], "bytes": int(fields["bytes"]),
                              "local_database": "present_unverified" if local.exists() else "absent",
                              "note": "A pinned manifest is not an available release asset; ensure verifies before use."}
            except ArtifactError as exc:
                thresholds = {"manifest": "data/station_thresholds.version", "status": "invalid", "error": str(exc)}
        except ImportError:
            thresholds["status"] = "verifier_unavailable"
    return {
        "inputs": {name: (root / name).exists() for name in (
            "requirements.txt", "dashboard/package.json", "dashboard/package-lock.json", "data/cities.csv",
            "data/normals.csv", "src/data/registry/place_registry.json")},
        "normals": {"header": header, "qualified_points": len(qualified),
                    "status": "qualified" if qualified else ("legacy_unqualified" if header.startswith("city,month,")
                                                            else "unqualified"),
                    "note": ("Legacy name-only rows cannot identify a sampling point or period; Hot10 holds until "
                             "qualified point normals are installed.") if not qualified else None},
        "station_thresholds": thresholds,
    }


def node_report(root: Path = ROOT) -> dict:
    lock = _sha(root / "dashboard/package-lock.json")
    modules = root / "dashboard/node_modules"
    resolved = modules.resolve() if modules.exists() else None
    cache_lock = _sha(resolved.parent / "package-lock.json") if resolved is not None else None
    return {"package_lock_sha256": lock, "node_modules": "absent" if resolved is None else "present",
            "node_modules_lock_sha256": cache_lock,
            "cache_matches_checkout": None if resolved is None or cache_lock is None else cache_lock == lock,
            "note": "Reuse an installed dependency cache only when its package-lock bytes equal the checkout's."}


def generator_report(root: Path = ROOT, *, timeout: float = 300.0, run: bool = True) -> dict:
    results: dict[str, dict[str, Any]] = {}
    for name in GENERATOR_CHECKS:
        script = root / "scripts" / f"{name}.py"
        if not script.is_file():
            results[name] = {"status": "missing"}
            continue
        if not run:
            results[name] = {"status": "not_run"}
            continue
        env = {"PATH": os.defpath, "LC_ALL": "C", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": str(root / ".gstack" / "onboarding-home")}
        try:
            done = subprocess.run([sys.executable, str(script), "--check"], cwd=root, env=env, capture_output=True,
                                  text=True, timeout=timeout, check=False)
            results[name] = {"status": "current" if done.returncode == 0 else "stale_or_failed",
                             "returncode": done.returncode}
        except subprocess.TimeoutExpired:
            results[name] = {"status": "timed_out"}
    return results


def preflight(root: Path = ROOT, *, run_generators: bool = True) -> dict:
    report = {"schema": "theheat.onboarding-preflight/v1", "root": str(root),
              "repository": repository_report(root), "dependencies": dependency_report(root),
              "node": node_report(root), "generated": generator_report(root, run=run_generators),
              "not_inspected": ["environment values and credentials (owner-supplied; never read)",
                                "network reachability of any source, model, Gist or X service"]}
    report["features"] = _features(report)
    report["next_commands"] = [
        "pytest tests/remaining_campaign/ (credential-free env -i, offline fixtures)",
        "python scripts/theheat_onboard.py inspect-draft --state <saved-state.json> --draft-id <id>",
        "node scripts/weekly_review.mjs --state <saved-state.json> --output <new private dir>",
    ]
    return report


def _features(report: dict) -> dict:
    deps = report["dependencies"]["groups"]
    stale = sorted(name for name, row in report["generated"].items() if row["status"] not in ("current", "not_run"))
    return {
        "offline_fixtures": "available" if deps["core"]["status"] == "available" else "unavailable: core pins differ",
        "native_graphics": "available" if deps["graphics"]["status"] == "available"
        else "unavailable: install requirements-graphics.txt pins in an isolated environment (owner action)",
        "postgres_media_store": "available_offline_code_only" if deps["postgres"]["status"] == "available"
        else "unavailable: requirements-postgres.txt pins absent; Gist remains production authority",
        "dashboard_build": "available" if report["node"]["cache_matches_checkout"] else "unavailable: no matching cache",
        "hot10": "holds: qualified normals not installed" if report["repository"]["normals"]["status"] != "qualified"
        else "inputs present",
        "generated_artifacts": ("not_checked" if all(row["status"] == "not_run" for row in report["generated"].values())
                                else "current" if not stale else "stale: " + ", ".join(stale)),
    }


def inspect_draft(state_path: Path, draft_id: str) -> dict:
    """A supplied saved state's draft, projected offline; no text beyond the draft itself is emitted."""
    from src.editorial.automatic_text import automatic_text_hold
    from src.editorial.revisions import approval_is_current, project_draft

    raw = Path(state_path).read_bytes()
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("state_too_large")
    state = json.loads(raw)
    drafts = [d for d in state.get("drafts", []) if isinstance(d, dict) and d.get("id") == draft_id]
    if len(drafts) != 1:
        raise ValueError("draft_not_found" if not drafts else "draft_id_ambiguous")
    draft = drafts[0]
    projected = project_draft(draft)
    ledger = (state.get("publish_ledger") or {}).get(draft.get("event_id") or draft_id)
    return {"draft_id": draft_id, "type": draft.get("type"), "status": draft.get("status"),
            "review_status": projected.get("review_status"), "review_kind": projected.get("review_kind"),
            "approval_current": {mode: approval_is_current(draft, mode) for mode in ("manual", "auto")},
            "automatic_text_hold": automatic_text_hold(draft.get("text")),
            "automatic_source_hold": draft.get("automatic_source_hold"),
            "media_attached": "media_attachment" in draft,
            "publication": None if not isinstance(ledger, dict) else {
                "phase": ledger.get("phase"), "receipt": bool(ledger.get("tweet_id")),
                "unknown_delivery": not ledger.get("tweet_id") and ledger.get("phase") not in ("not_sent", None)},
            "post_error": draft.get("post_error")}


__all__ = ["GENERATOR_CHECKS", "dependency_report", "generator_report", "inspect_draft", "node_report",
           "pinned_requirements", "preflight", "repository_report"]
