"""OFFLINE FIXTURE: a file-backed model of the GitHub Actions REST surfaces the run-scoped inbox uses.

* ``<root>/runs.json`` — workflow runs of gist-commands.yml (the workflow-runs listing; listed in a
  configurable, optionally shuffled order, 100 per page, filtered by event/branch/created as GitHub's
  query parameters promise);
* ``<root>/artifacts/*.json`` — artifacts, each naming its producing run (``workflow_run.id``); the
  consumer CLI's acknowledgement DELETE (route-fixture-fetch.mjs) removes these files;
* zips are built from the admitted directories the test registered.

The repository-wide artifact listing is deliberately REFUSED: the inbox must never need it.
No network, credentials or GitHub.
"""
from __future__ import annotations

from datetime import UTC, datetime
import io
import json
from pathlib import Path
import random
from urllib import parse
import zipfile

GENUINE = {"path": ".github/workflows/gist-commands.yml", "event": "workflow_dispatch", "head_branch": "main",
           "repository": {"id": 7}, "head_repository": {"id": 7}}


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeActions:
    def __init__(self, root: Path, *, seed: int | None = None):
        self.root = root
        (root / "artifacts").mkdir(parents=True, exist_ok=True)
        self.seed = seed
        self.calls: list[str] = []
        self.zips: dict[int, Path] = {}
        self.next_id = 1
        if not (root / "runs.json").exists():
            (root / "runs.json").write_text("[]")

    def runs(self) -> list[dict]:
        return json.loads((self.root / "runs.json").read_text())

    def add_run(self, created: datetime, *, status: str = "completed", **fields) -> int:
        runs = self.runs()
        run_id = 10_000 + len(runs)
        runs.append({"id": run_id, "status": status, "created_at": stamp(created), **GENUINE, **fields})
        (self.root / "runs.json").write_text(json.dumps(runs))
        return run_id

    def add_artifact(self, run_id: int | None, name: str, *, admitted_dir: Path | None = None, created: datetime | None = None) -> int:
        artifact_id = self.next_id
        self.next_id += 1
        row = {"id": artifact_id, "name": name, "expired": False, "created_at": stamp(created or datetime.now(UTC)),
               "workflow_run": {"id": run_id} if run_id is not None else None}
        (self.root / "artifacts" / f"a{artifact_id:07d}.json").write_text(json.dumps(row))
        if admitted_dir is not None:
            self.zips[artifact_id] = admitted_dir
        return artifact_id

    def artifacts(self) -> list[dict]:
        return [json.loads(path.read_text()) for path in sorted((self.root / "artifacts").iterdir()) if path.suffix == ".json"]

    def __call__(self, args: list[str]) -> bytes:
        url = args[0]
        self.calls.append(url)
        path, _, query = url.partition("?")
        params = dict(parse.parse_qsl(query))
        if path.endswith("/actions/workflows/gist-commands.yml/runs"):
            since = params["created"].removeprefix(">=")
            rows = [row for row in self.runs() if row["event"] == params["event"] and row["head_branch"] == params["branch"]
                    and row["created_at"] >= since]
            if self.seed is not None:
                random.Random(self.seed + int(params["page"])).shuffle(rows)  # page movement between requests
            page, size = int(params["page"]), int(params["per_page"])
            return json.dumps({"total_count": len(rows), "workflow_runs": rows[(page - 1) * size: page * size]}).encode()
        if "/actions/runs/" in path and path.endswith("/artifacts"):
            run_id = int(path.split("/")[-2])
            rows = [row for row in self.artifacts() if (row.get("workflow_run") or {}).get("id") == run_id]
            return json.dumps({"total_count": len(rows), "artifacts": rows}).encode()
        if path.endswith("/zip"):
            folder = self.zips[int(path.split("/")[-2])]
            blob = io.BytesIO()
            with zipfile.ZipFile(blob, "w") as archive:
                for name in ("command.json", "admission.json"):
                    archive.writestr(name, (folder / name).read_bytes())
            return blob.getvalue()
        raise AssertionError(f"the run-scoped inbox must not call {url}")
