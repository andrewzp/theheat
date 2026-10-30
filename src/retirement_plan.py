"""Bounded local retirement planner (W16.6): an unapplied plan, never a removal.

A candidate path, flag or branch is eligible only with documented replacement
evidence and proven local non-use: no remaining reference in source, dashboard,
scripts, workflows or tests outside itself. Production Gist and legacy
publication paths, anything blocked by unresolved receipts or active jobs, and
every branch stay refused or plan-only. Nothing is deleted, renamed, pushed or
cleaned up here; Root applies a reviewed plan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA = "theheat.retirement-plan/v1"
SCAN_ROOTS = ("src", "dashboard/lib", "dashboard/app", "scripts", ".github/workflows", "tests", "dashboard/tests")
SCAN_SUFFIXES = (".py", ".js", ".mjs", ".jsx", ".ts", ".tsx", ".yml", ".yaml", ".json", ".toml", ".cfg", ".sh")
PROTECTED = ("src/state.py", "src/orchestrator/posting.py", "src/orchestrator/draft_save.py",
             "src/editorial/revisions.py", "src/posting/", "dashboard/lib/state-store.js",
             "dashboard/lib/lossless-gist.js", "dashboard/app/api/drafts/route.js", "src/orchestrator/world_cache.py")
PUBLICATION_PATHS = ("src/orchestrator/posting.py", "src/posting/", "src/commands/delivery")
MAX_FILES = 20_000
MAX_CANDIDATES = 200


class RetirementPlanError(ValueError):
    pass


def _scan(root: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for base in SCAN_ROOTS:
        directory = root / base
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if "node_modules" in path.parts or not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if len(files) >= MAX_FILES:
                raise RetirementPlanError("repository_scan_bound")
            try:
                files.append((str(path.relative_to(root)), path.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return files


def _needles(kind: str, target: str) -> list[str]:
    if kind == "flag":
        return [target]
    if target.endswith(".py"):
        module = target[:-3].replace("/", ".")
        return [module, Path(target).name]
    return [Path(target).name]


def _unresolved(state: dict | None) -> list[str]:
    if not isinstance(state, dict):
        return []
    supplied = state.get("publish_ledger")
    ledger: dict[str, Any] = supplied if isinstance(supplied, dict) else {}
    unknown = [event for event, row in ledger.items()
               if isinstance(row, dict) and not row.get("tweet_id") and row.get("phase") not in ("not_sent", None)]
    jobs = [str(job.get("id")) for job in state.get("jobs", []) if isinstance(job, dict)
            and job.get("status") not in ("completed", "cancelled", "expired")]
    return [f"unresolved_publication:{event}" for event in sorted(unknown)] + [f"active_job:{job}" for job in jobs]


def plan(root: Path, candidates: Any, *, state: dict | None = None) -> dict:
    if not isinstance(candidates, list) or not 0 < len(candidates) <= MAX_CANDIDATES:
        raise RetirementPlanError("candidate_count")
    files = _scan(Path(root))
    blockers = _unresolved(state)
    eligible, refused = [], []
    for row in candidates:
        if not isinstance(row, dict) or row.get("kind") not in ("path", "flag", "branch") \
                or not isinstance(row.get("target"), str) or not row["target"].strip():
            refused.append({"candidate": row, "reason": "invalid_candidate"})
            continue
        kind, target = row["kind"], row["target"].strip()
        evidence = row.get("replacement_evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            refused.append({"kind": kind, "target": target, "reason": "no_documented_replacement"})
            continue
        if kind == "branch":
            eligible.append({"kind": kind, "target": target, "action": "plan_only",
                             "note": "Branch deletion is never performed here; Root decides after review."})
            continue
        if kind == "path" and any(target == p or target.startswith(p) for p in PROTECTED):
            refused.append({"kind": kind, "target": target, "reason": "still_needed_production_path"})
            continue
        if kind == "path" and blockers and any(target.startswith(p) for p in PUBLICATION_PATHS):
            refused.append({"kind": kind, "target": target, "reason": "unresolved_state", "blockers": blockers})
            continue
        if kind == "path" and not (Path(root) / target).exists():
            refused.append({"kind": kind, "target": target, "reason": "target_absent"})
            continue
        references = sorted({name for name, text in files if name != target
                             and any(needle in text for needle in _needles(kind, target))})
        if references:
            refused.append({"kind": kind, "target": target,
                            "reason": "flag_still_read" if kind == "flag" else "still_referenced",
                            "reference_count": len(references), "references": references[:10]})
            continue
        eligible.append({"kind": kind, "target": target, "replacement_evidence": evidence.strip(),
                         "action": "remove_after_review"})
    return {"schema": SCHEMA, "applied": False, "eligible": eligible, "refused": refused, "state_blockers": blockers,
            "note": "Unapplied plan. No file, flag, branch, job, database or production resource was changed."}


__all__ = ["PROTECTED", "RetirementPlanError", "SCHEMA", "plan"]
