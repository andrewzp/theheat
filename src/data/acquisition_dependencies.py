"""Isolated acquisition dependency contract and machine-readable tool results.

Owner-run acquisition tools (qualified normals, GHCN threshold rebuild) declare
their third-party needs in ``requirements-acquisition.txt``. That file is never
installed into the runtime: Root creates an isolated environment for it. This
module only *reads* the manifest and the current interpreter's installed
distributions; it never installs, upgrades or imports a provider network path.

Every tool reports one ``theheat.acquisition-result/v1`` document whose status
separates the failure kinds that file presence would otherwise blur:

- ``dependency_unavailable`` — a required distribution is not installed here;
- ``dependency_incompatible`` — installed, but outside the declared range or
  missing the adapter's interface;
- ``source_absent`` — the dependency works but the source supplied no product
  (no data for a point, absent archive, empty release);
- ``product_invalid`` — a product exists but fails schema/provenance/loader
  admission;
- ``incomplete`` — bounded limits or transport failures stopped the run; it can
  resume and nothing partial was promoted;
- ``planned`` / ``ready`` — a deterministic plan, or an admitted/verified
  candidate. ``ready`` is integrity and loader acceptance, never scientific
  qualification.

The ``source_health`` projection has exactly the arguments of
``src.state.record_source_health`` so Sources/Operations show the same run
history shape as other sources.
"""

from __future__ import annotations

from importlib import import_module, metadata
from pathlib import Path
import re
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "requirements-acquisition.txt"
RESULT_SCHEMA = "theheat.acquisition-result/v1"
STATUSES = ("planned", "ready", "incomplete", "dependency_unavailable", "dependency_incompatible",
            "source_absent", "product_invalid")
_HEALTH_STATUS = {"planned": "skipped", "ready": "success", "incomplete": "degraded"}
_ERROR_CLASS = {"dependency_unavailable": "dependency", "dependency_incompatible": "dependency",
                "source_absent": "source_absent", "product_invalid": "product_invalid", "incomplete": "incomplete"}
_LINE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<spec>(?:\s*(?:==|>=|<=|<|>|!=)\s*[0-9][0-9A-Za-z.]*\s*,?)*)"
    r"\s*#\s*tool=(?P<tool>[a-z_]+)(?:\s+api=(?P<api>[A-Za-z0-9_,]+))?\s*\Z")
_CLAUSE = re.compile(r"(==|>=|<=|<|>|!=)\s*([0-9][0-9A-Za-z.]*)")
MAX_MANIFEST_BYTES = 16 * 1024
# Tools whose live path needs no third-party distribution. ``normals`` reaches
# Meteostat through the owned ``bounded_http`` transport (meteostat_normals);
# the unbounded meteostat SDK wrapper stays refused.
STDLIB_TOOLS = {"normals": "standard library only: src/data/bounded_http.py + src/data/meteostat_normals.py"}


class AcquisitionError(ValueError):
    """Fixed public labels; never provider bodies, paths or credentials."""


def _release(version: str) -> tuple[int, ...]:
    """Numeric release segments; pre/post/local parts stop the comparison."""
    parts = []
    for piece in str(version).split("."):
        match = re.match(r"\d+", piece)
        if not match:
            break
        parts.append(int(match.group()))
        if match.group() != piece:
            break
    return tuple(parts) or (0,)


def _cmp(left: str, right: str) -> int:
    a, b = _release(left), _release(right)
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def satisfies(version: str, spec: str) -> bool:
    for op, bound in _CLAUSE.findall(spec):
        order = _cmp(version, bound)
        if not {"==": order == 0, "!=": order != 0, ">=": order >= 0, "<=": order <= 0,
                ">": order > 0, "<": order < 0}[op]:
            return False
    return True


def read_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, Any]]:
    """Strict parse: one requirement per line with its declared tool; unknown syntax is refused."""
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise AcquisitionError("acquisition_manifest_too_large")
    rows = []
    for line in raw.decode("utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = _LINE.fullmatch(text)
        if not match:
            raise AcquisitionError("acquisition_manifest_invalid")
        spec = re.sub(r"\s+", "", match["spec"]).rstrip(",")
        rows.append({"name": match["name"].lower(), "spec": spec, "tool": match["tool"],
                     "api": [name for name in (match["api"] or "").split(",") if name]})
    if not rows or len({(row["name"], row["tool"]) for row in rows}) != len(rows):
        raise AcquisitionError("acquisition_manifest_invalid")
    return rows


def _installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def check(tool: str, *, manifest: Path = MANIFEST_PATH, installed=_installed, importer=import_module) -> dict[str, Any]:
    """Report the declared dependency state for one tool without installing anything.

    ``installed``/``importer`` are injectable so tests exercise absent, wrong-version
    and wrong-interface cases without touching the shared environment.
    """
    rows = [row for row in read_manifest(manifest) if row["tool"] == tool]
    if not rows and tool in STDLIB_TOOLS:
        return {"tool": tool, "status": "available", "manifest": manifest.name, "requirements": [],
                "installation": "none_required", "runtime": STDLIB_TOOLS[tool]}
    if not rows:
        raise AcquisitionError("acquisition_tool_unknown")
    results, status = [], "available"
    for row in rows:
        version = installed(row["name"])
        entry: dict[str, Any] = {"name": row["name"], "required": row["spec"], "installed": version,
                                 "api": row["api"], "state": "available"}
        if version is None:
            entry["state"] = "unavailable"
        elif not satisfies(version, row["spec"]):
            entry["state"] = "incompatible_version"
        elif row["api"]:
            try:
                module = importer(row["name"])
            except Exception:  # noqa: BLE001 - any import failure is an unusable dependency
                entry["state"] = "import_failed"
            else:
                missing = [name for name in row["api"] if not callable(getattr(module, name, None))]
                if missing:
                    entry["state"], entry["missing_api"] = "incompatible_api", missing
        results.append(entry)
        if entry["state"] == "unavailable" and status == "available":
            status = "unavailable"
        elif entry["state"] not in {"available", "unavailable"}:
            status = "incompatible"
    return {"tool": tool, "status": status, "manifest": manifest.name, "requirements": results,
            "installation": "owner_isolated_environment_only"}


def dependency_status(check_result: dict[str, Any]) -> str | None:
    """The result status a dependency check forces, or None when usable."""
    return {"unavailable": "dependency_unavailable", "incompatible": "dependency_incompatible"}.get(
        check_result["status"])


def result(tool: str, status: str, *, reasons: list[str] | None = None, dependency: dict | None = None,
           source: dict | None = None, product: dict | None = None, counters: dict | None = None,
           observed: int = 0, promoted: int = 0) -> dict[str, Any]:
    if status not in STATUSES:
        raise AcquisitionError("acquisition_status_unknown")
    reasons = sorted(set(reasons or []))
    health: dict[str, Any] = {"source": f"acquisition:{tool}", "status": _HEALTH_STATUS.get(status, "failed"),
                              "error": None, "error_class": None,
                              "metrics": {"observed": max(int(observed), 0), "promoted": max(int(promoted), 0)}}
    if status.startswith("dependency_") and dependency:
        failing = [f"{row['name']} {row['state']}" for row in dependency.get("requirements", [])
                   if row.get("state") != "available"]
        health["error"] = status + (": " + ", ".join(failing) if failing else "")
        health["error_class"] = _ERROR_CLASS[status]
    elif status not in _HEALTH_STATUS:
        health["error"] = status + (": " + reasons[0] if reasons else "")
        health["error_class"] = _ERROR_CLASS[status]
    elif status == "incomplete":
        health["error"] = "incomplete" + (": " + reasons[0] if reasons else "")
        health["error_class"] = _ERROR_CLASS[status]
    return {"schema": RESULT_SCHEMA, "tool": tool, "status": status, "reasons": reasons,
            "dependency": dependency, "source": source or {}, "product": product or {},
            "counters": counters or {}, "scientific_qualification": "not_established_by_tool_result",
            "source_health": health}


def record_acquisition_health(state: Any, tool_result: dict[str, Any], *, timestamp: Any = None) -> None:
    """Write one tool result into the existing per-source health/run-history shape."""
    from src import state as state_mod

    if not isinstance(tool_result, dict) or tool_result.get("schema") != RESULT_SCHEMA:
        raise AcquisitionError("acquisition_result_invalid")
    health = tool_result["source_health"]
    state_mod.record_source_health(state, health["source"], health["status"], health["error"],
                                   timestamp=timestamp, metrics=health["metrics"],
                                   error_class=health["error_class"])


__all__ = ["AcquisitionError", "MANIFEST_PATH", "RESULT_SCHEMA", "STATUSES", "check", "dependency_status",
           "read_manifest", "record_acquisition_health", "result", "satisfies"]
