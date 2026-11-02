"""ROUTE repair B.2 through REAL processes: the dashboard drafts handler (one client process),
the REAL Python admission, the REAL inbox scan (``scripts/gist_command_inbox.fetch``) over a
paginated, SHUFFLED artifact listing with unrelated artifacts interleaved, and the REAL Node consumer
CLI inside the ``fcntl`` group stand-in, which acknowledges (deletes) artifacts only after their
results are durable.

OFFLINE FIXTURES, explicitly: file-backed whole-file Gist (``route-fixture-fetch.mjs``), an injected
``gh api`` runner serving the fixture's artifact directory, invented data and an invented test key.
Red baselines: receipts/red-b2-drain-starvation.txt and red-b2-inbox-page-cap-v2.txt.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import random
import subprocess
import zipfile

from scripts import gist_command_inbox as inbox
from src.commands import gist_commands
from tests.real_closure import route_harness as h

REPO = "invented/theheat"


def _seed(root: Path, count: int) -> dict:
    seed = h.fixture_state(count)
    h.seed_gist(root, h.STATE_GIST, {"state.json": json.dumps(seed["state"]), "gist-write-route.json": h.route_record()})
    h.seed_gist(root, h.FEEDBACK_GIST, {})
    return seed


def _submit(root: Path, bodies: list[dict]) -> list[dict]:
    done = subprocess.run([h.NODE, "--import", h.SHIM, "tests/helpers/route-bulk-client.mjs", "app/api/drafts/route.js", json.dumps(bodies)],
                          cwd=h.DASHBOARD, env=h.client_env(root, route="serialized"), capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _admit(root: Path, responses: list[dict], *, unrelated_per_command: int = 0, start_id: int = 1) -> dict[int, Path]:
    """REAL admission of each dispatched envelope; the fixture artifact store gets one entry per
    admitted command and ``unrelated_per_command`` unrelated artifacts beside each."""
    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    dirs: dict[int, Path] = {}
    artifact_id = start_id
    for index, response in enumerate(responses):
        raw = response["body"]["command"]
        out = root / "admitted" / f"cmd{start_id}-{index:04d}"
        result = gist_commands.admit(raw, out, now=now, seal_kid="k-test", control_kid="k-ctl-test")
        assert result["admitted"], result
        for extra in range(unrelated_per_command):
            (root / "artifacts" / f"u{artifact_id:06d}.json").write_text(json.dumps(
                {"id": artifact_id, "name": f"bot-run-report-{index}-{extra}", "expired": False, "created_at": stamp}))
            artifact_id += 1
        (root / "artifacts" / f"c{artifact_id:06d}.json").write_text(json.dumps(
            {"id": artifact_id, "name": f"theheat-command-{result['command_id']}", "expired": False, "created_at": stamp,
             "workflow_run": {"id": 5000 + index, "repository_id": 7, "head_repository_id": 7, "head_branch": "main"}}))
        dirs[artifact_id] = out
        artifact_id += 1
    return dirs


def _runner(root: Path, dirs: dict[int, Path], seed: int):
    """``gh api`` stand-in: the fixture artifact store, listed in a SHUFFLED order, 100 per page."""
    calls: list[str] = []

    def run(args: list[str]) -> bytes:
        calls.append(args[0])
        if args[0].endswith("/zip"):
            folder = dirs[int(args[0].split("/")[-2])]
            blob = io.BytesIO()
            with zipfile.ZipFile(blob, "w") as archive:
                for name in ("command.json", "admission.json"):
                    archive.writestr(name, (folder / name).read_bytes())
            return blob.getvalue()
        if "/actions/runs/" in args[0]:
            # Every admitted command came from a gist-commands.yml workflow_dispatch run on main.
            return json.dumps({"id": int(args[0].split("/")[-1]), "path": ".github/workflows/gist-commands.yml",
                               "event": "workflow_dispatch", "head_branch": "main"}).encode()
        rows = [json.loads(path.read_text()) for path in sorted((root / "artifacts").iterdir())]
        random.Random(seed).shuffle(rows)
        page = int(args[0].split("&page=")[1])
        return json.dumps({"total_count": len(rows), "artifacts": rows[(page - 1) * 100: page * 100]}).encode()
    return run, calls


def _drain(root: Path, dirs: dict[int, Path], *, seed: int, name: str, expect: int = 0, **env: str) -> tuple[dict, dict | None]:
    out = root / f"inbox-{name}"
    fetched = inbox.fetch(REPO, out, _runner(root, dirs, seed)[0])
    report = h.run_consumer(root, h.consumer_env(root, run_id=str(3000 + seed), **env), root / f"report-{name}.json", expect=expect, inbox=out)
    return fetched, report


def _commands_left(root: Path) -> int:
    return sum(json.loads(p.read_text())["name"].startswith("theheat-command-") for p in (root / "artifacts").iterdir())


def test_101_commands_with_interleaved_unrelated_artifacts_in_any_order_make_progress_and_are_retired(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root, 101)
    responses = _submit(root, [{"action": "reject", "draftId": f"draft_route_{i}", "expectedRevision": seed["identities"][f"draft_route_{i}"]}
                               for i in range(1, 102)])
    assert {r["status"] for r in responses} == {202}
    dirs = _admit(root, responses, unrelated_per_command=3)  # 404 artifacts: 5 listing pages
    first_scan, first = _drain(root, dirs, seed=11, name="1")
    assert first_scan["scan_complete"] is True and first_scan["pages"] == 5 and first_scan["candidates"] == 101
    assert first_scan["fetched"] == 101
    assert first is not None
    assert (len(first["applied"]), len(first["duplicates"]), first["deferred"]) == (100, 0, 1)
    assert len(first["acknowledged"]["deleted"]) == 100 and _commands_left(root) == 1
    assert len(list((root / "artifacts").iterdir())) == 1 + 303, "unrelated artifacts are never touched"
    second_scan, second = _drain(root, dirs, seed=12, name="2")
    assert second_scan["candidates"] == 1
    assert second is not None and len(second["applied"]) == 1 and second["deferred"] == 0
    assert _commands_left(root) == 0
    assert {d["status"] for d in h.gist_state(root)["drafts"]} == {"rejected"}
    assert len(h.results(root)) == 101


def test_restart_between_patch_and_acknowledgement_resettles_as_duplicates(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root, 3)
    responses = _submit(root, [{"action": "reject", "draftId": f"draft_route_{i}", "expectedRevision": seed["identities"][f"draft_route_{i}"]}
                               for i in range(1, 4)])
    dirs = _admit(root, responses, unrelated_per_command=40)
    _, crashed = _drain(root, dirs, seed=21, name="crash", expect=97, ROUTE_FIXTURE_EXIT_AFTER_PATCH="1")
    assert crashed is None and _commands_left(root) == 3, "crashed after the PATCH: nothing acknowledged"
    assert {row["status"] for row in h.results(root).values()} == {"applied"}
    _, report = _drain(root, dirs, seed=22, name="again")
    assert report is not None
    assert (report["applied"], len(report["duplicates"]), report["state_patches"]) == ([], 3, 0)
    assert len(report["acknowledged"]["deleted"]) == 3 and _commands_left(root) == 0


def test_crash_before_patch_acknowledges_nothing_and_the_next_drain_applies(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root, 2)
    responses = _submit(root, [{"action": "reject", "draftId": "draft_route_1", "expectedRevision": seed["identities"]["draft_route_1"]}])
    dirs = _admit(root, responses)
    _, crashed = _drain(root, dirs, seed=31, name="crash", expect=96, ROUTE_FIXTURE_EXIT_BEFORE_PATCH="1")
    assert crashed is None and _commands_left(root) == 1 and h.results(root) == {}
    _, report = _drain(root, dirs, seed=32, name="again")
    assert report is not None and len(report["applied"]) == 1 and _commands_left(root) == 0


def _listing(rows: list[dict], seed: int):
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)

    def run(args: list[str]) -> bytes:
        if args[0].endswith("/zip"):
            raise AssertionError("scan only")
        page = int(args[0].split("&page=")[1])
        return json.dumps({"artifacts": shuffled[(page - 1) * 100: page * 100]}).encode()
    return run


def test_scan_does_not_rely_on_order_horizon_filters_without_stopping_and_the_cap_is_reported():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = [f"{i:08d}-2222-4333-8444-555555555555" for i in range(5)]
    unrelated = [{"id": 100 + i, "name": f"bot-report-{i}", "expired": False, "created_at": stale if i % 2 else fresh} for i in range(450)]
    commands = [{"id": 10 + i, "name": f"theheat-command-{cid}", "expired": False, "created_at": fresh} for i, cid in enumerate(ids)]
    old_command = {"id": 9, "name": f"theheat-command-{'9' * 8}-2222-4333-8444-555555555555", "expired": False, "created_at": stale}
    for seed in range(8):
        scan = inbox.scan_admitted(REPO, _listing(unrelated + commands + [old_command], seed), now=now)
        assert scan["scan_complete"] is True and scan["pages"] == 5
        assert sorted(row["id"] for row in scan["artifacts"]) == [10, 11, 12, 13, 14], f"order seed {seed}"
        assert scan["beyond_horizon"] == 1, "old commands are filtered, never a stop condition"
    # Old artifacts FIRST in the listing must not stop the scan before newer commands on later pages.
    ordered = [{**row, "created_at": stale} for row in unrelated] + [old_command] + commands
    scan = inbox.scan_admitted(REPO, lambda args: json.dumps({"artifacts": ordered[(int(args[0].split("&page=")[1]) - 1) * 100:
                                                                                     int(args[0].split("&page=")[1]) * 100]}).encode(), now=now)
    assert len(scan["artifacts"]) == 5
    # Cap: more than 30 full pages -> scan_complete false (visible), only what was seen is offered.
    many = [{"id": 1000 + i, "name": f"bot-report-{i}", "expired": False, "created_at": fresh} for i in range(inbox.MAX_PAGES * 100 + 50)]
    capped = inbox.scan_admitted(REPO, _listing(many + commands, 3), now=now)
    assert capped["scan_complete"] is False and capped["pages"] == inbox.MAX_PAGES


def test_fetch_is_bounded_oldest_first_and_writes_the_scan_report(tmp_path):
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    origin = {"id": 77, "repository_id": 7, "head_repository_id": 7, "head_branch": "main"}
    rows = [{"id": i + 1, "name": f"theheat-command-{i:08d}-2222-4333-8444-555555555555", "expired": False, "workflow_run": origin,
             "created_at": (now - timedelta(minutes=400 - i)).strftime("%Y-%m-%dT%H:%M:%SZ")} for i in range(inbox.MAX_ARTIFACTS + 20)]
    scan = inbox.scan_admitted(REPO, _listing(rows, 5), now=now)
    assert len(scan["artifacts"]) == inbox.MAX_ARTIFACTS and scan["candidates"] == inbox.MAX_ARTIFACTS + 20
    assert [row["id"] for row in scan["artifacts"]] == list(range(1, inbox.MAX_ARTIFACTS + 1)), "oldest first"

    def run(args: list[str]) -> bytes:
        if args[0].endswith("/zip"):
            return b"not a zip"
        if "/actions/runs/" in args[0]:
            return json.dumps({"path": ".github/workflows/gist-commands.yml", "event": "workflow_dispatch", "head_branch": "main"}).encode()
        return _listing(rows[:2], 1)(args)
    result = inbox.fetch(REPO, tmp_path, run, now=now)
    assert json.loads((tmp_path / "scan.json").read_text()) == {"beyond_horizon": 0, "candidates": 2, "deferred": 0,
                                                                "pages": 1, "provenance_refused": {}, "scan_complete": True,
                                                                "unverified": 0}
    assert result["fetched"] == 0 and len(result["skipped"]) == 2
