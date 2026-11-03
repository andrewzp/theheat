"""ROUTE repair B.2 + root checkpoint R1 through REAL processes: the dashboard drafts handler (one client
process), the REAL Python admission, the REAL run-scoped inbox scan (``scripts/gist_command_inbox.fetch``)
and the REAL Node consumer CLI inside the ``fcntl`` group stand-in, which acknowledges (deletes) artifacts
only after their results are durable and then records their producing runs as SETTLED in the Gist.

OFFLINE FIXTURES, explicitly: file-backed whole-file Gist (``route-fixture-fetch.mjs``), a file-backed
model of the Actions REST listings (``route_inbox_fixture.FakeActions``; the repository-wide artifact
listing is refused), invented data and an invented test key. 3,000 unrelated artifacts are retained in
every scenario. Red baselines: receipts/red-b2-*.txt, receipts/red-review3-r1-scan-restart.txt.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess

from scripts import gist_command_inbox as inbox
from src.commands import gist_commands
from tests.real_closure import route_harness as h
from tests.real_closure.route_inbox_fixture import FakeActions

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


def _rejects(seed: dict, count: int) -> list[dict]:
    return [{"action": "reject", "draftId": f"draft_route_{i}", "expectedRevision": seed["identities"][f"draft_route_{i}"]}
            for i in range(1, count + 1)]


def _unrelated(gh: FakeActions, count: int = 3000) -> None:
    for index in range(count):
        gh.add_artifact(None if index % 2 else 900_000 + index, f"bot-run-report-{index}")


def _admit(root: Path, gh: FakeActions, responses: list[dict]) -> None:
    """REAL admission of each dispatched envelope inside its own gist-commands workflow_dispatch run."""
    now = datetime.now(UTC)
    for index, response in enumerate(responses):
        out = root / "admitted" / f"cmd{len(gh.runs()):05d}"
        result = gist_commands.admit(response["body"]["command"], out, now=now, seal_kid="k-test", control_kid="k-ctl-test")
        assert result["admitted"], result
        run_id = gh.add_run(now - timedelta(seconds=len(responses) - index))
        gh.add_artifact(run_id, f"theheat-command-{result['command_id']}", admitted_dir=out)


def _settled(root: Path) -> set[int]:
    files = {name: {"content": content} for name, content in h.gist_files(root).items()}
    return inbox.settled_runs_from_files(files)


def _drain(root: Path, gh: FakeActions, *, name: str, expect: int | None = 0, **env: str) -> tuple[dict, dict | None]:
    """``expect=None``: exit 0, or 3 exactly when the scan reported itself partial (visible, not silent)."""
    out = root / f"inbox-{name}"
    scan = inbox.fetch(REPO, out, gh, settled=_settled(root))
    report_path = root / f"report-{name}.json"
    if expect is not None:
        return scan, h.run_consumer(root, h.consumer_env(root, run_id="3001", **env), report_path, expect=expect, inbox=out)
    process = h.start_consumer(root, h.consumer_env(root, run_id="3001", **env), report_path, inbox=out)
    stdout, stderr = process.communicate(timeout=300)
    assert process.returncode == (0 if scan["scan_complete"] else 3), (stdout, stderr)
    return scan, json.loads(report_path.read_text())


def _commands_left(gh: FakeActions) -> int:
    return sum(row["name"].startswith("theheat-command-") for row in gh.artifacts())


def test_101_commands_beside_3000_unrelated_artifacts_progress_and_their_runs_are_settled(tmp_path):
    root = h.make_root(tmp_path)
    gh = FakeActions(root)
    seed = _seed(root, 101)
    _unrelated(gh)
    responses = _submit(root, _rejects(seed, 101))
    assert {r["status"] for r in responses} == {202}
    _admit(root, gh, responses)
    scan, first = _drain(root, gh, name="1")
    assert (scan["runs_listed"], scan["runs_examined"], scan["fetched"], scan["scan_complete"]) == (101, 101, 101, True)
    assert first is not None
    assert (len(first["applied"]), len(first["duplicates"]), first["deferred"]) == (100, 0, 1)
    assert len(first["acknowledged"]["deleted"]) == 100 and _commands_left(gh) == 1
    assert first["settled"] == {"recorded": 100} and len(_settled(root)) == 100
    assert sum(1 for row in gh.artifacts() if row["name"].startswith("bot-run-report-")) == 3000, "unrelated artifacts untouched"
    scan2, second = _drain(root, gh, name="2")
    assert (scan2["runs_settled_skipped"], scan2["runs_examined"]) == (100, 1), "settled runs cost no request"
    assert second is not None and len(second["applied"]) == 1 and _commands_left(gh) == 0
    assert {d["status"] for d in h.gist_state(root)["drafts"]} == {"rejected"}
    assert not any("/actions/artifacts?" in call for call in gh.calls), "the repository-wide listing is never used"


def test_beyond_the_old_cap_every_live_command_is_discovered_across_drains_with_page_movement(tmp_path):
    """260 live commands in 260 runs (> 150 examined per drain), 3,000 unrelated artifacts, a listing
    re-shuffled for every page request, and new runs created between drains: all are applied."""
    root = h.make_root(tmp_path)
    gh = FakeActions(root, seed=5)
    seed = _seed(root, 260)
    _unrelated(gh)
    _admit(root, gh, _submit(root, _rejects(seed, 260)))
    applied, drains, per_drain = 0, 0, []
    while _commands_left(gh) and drains < 12:
        drains += 1
        for _ in range(25):  # page movement: admission-refused runs (no command artifact) keep arriving
            gh.add_run(datetime.now(UTC))
        scan, report = _drain(root, gh, name=f"m{drains}", expect=None)
        assert report is not None
        applied += len(report["applied"])
        per_drain.append(len(report["applied"]))
        assert scan["runs_examined"] <= inbox.MAX_RUNS_EXAMINED
        if scan["deferred_runs"] or not scan["scan_complete"]:
            assert report["scan"]["scan_complete"] is False, "a partial scan is reported, never silent"
    assert _commands_left(gh) == 0 and applied == 260, (drains, applied, per_drain)
    assert {d["status"] for d in h.gist_state(root)["drafts"]} == {"rejected"}
    # Eventual discovery under page movement (the old cap restarted at page 1 and never progressed);
    # a drain whose moving pages happened to hide every remaining command may apply none, never lose one.
    assert sum(per_drain) == 260 and per_drain[0] == 100, per_drain


def test_restart_between_patch_and_acknowledgement_resettles_as_duplicates(tmp_path):
    root = h.make_root(tmp_path)
    gh = FakeActions(root)
    seed = _seed(root, 3)
    _unrelated(gh, 300)
    _admit(root, gh, _submit(root, _rejects(seed, 3)))
    _, crashed = _drain(root, gh, name="crash", expect=97, ROUTE_FIXTURE_EXIT_AFTER_PATCH="1")
    assert crashed is None and _commands_left(gh) == 3 and _settled(root) == set(), "nothing acknowledged or settled"
    assert {row["status"] for row in h.results(root).values()} == {"applied"}
    _, report = _drain(root, gh, name="again")
    assert report is not None
    assert (report["applied"], len(report["duplicates"]), report["state_patches"]) == ([], 3, 0)
    assert len(report["acknowledged"]["deleted"]) == 3 and _commands_left(gh) == 0 and len(_settled(root)) == 3


def test_crash_before_patch_acknowledges_nothing_and_the_next_drain_applies(tmp_path):
    root = h.make_root(tmp_path)
    gh = FakeActions(root)
    seed = _seed(root, 2)
    _admit(root, gh, _submit(root, _rejects(seed, 1)))
    _, crashed = _drain(root, gh, name="crash", expect=96, ROUTE_FIXTURE_EXIT_BEFORE_PATCH="1")
    assert crashed is None and _commands_left(gh) == 1 and h.results(root) == {}
    _, report = _drain(root, gh, name="again")
    assert report is not None and len(report["applied"]) == 1 and _commands_left(gh) == 0


def test_settled_runs_are_skipped_unsettled_running_runs_are_retried_and_old_runs_are_out_of_scope(tmp_path):
    gh = FakeActions(tmp_path / "gh")
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    old = gh.add_run(now - timedelta(hours=30))
    settled = gh.add_run(now - timedelta(hours=2))
    running = gh.add_run(now - timedelta(minutes=1), status="in_progress")
    refused = gh.add_run(now - timedelta(minutes=3))
    scan = inbox.fetch(REPO, tmp_path / "out", gh, now=now, settled={settled})
    assert (scan["runs_listed"], scan["runs_settled_skipped"], scan["runs_examined"]) == (3, 1, 2), "the horizon filter excludes the old run"
    assert scan["empty_completed_runs"] == [{"run_id": refused, "created_at": gh.runs()[3]["created_at"]}], "only a COMPLETED empty run settles"
    assert all(f"/runs/{old}/" not in c and f"/runs/{settled}/" not in c for c in gh.calls)
    assert any(f"/runs/{running}/" in c for c in gh.calls)
    unavailable = inbox.fetch(REPO, tmp_path / "out2", gh, now=now, settled=None)
    assert unavailable["settled_cursor"] == "unavailable" and unavailable["runs_examined"] == 3, "no cursor: more requests, never fewer runs"


def test_more_unsettled_runs_than_the_drain_examines_are_reported_as_deferred(tmp_path):
    gh = FakeActions(tmp_path / "gh")
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    for index in range(inbox.MAX_RUNS_EXAMINED + 7):
        gh.add_run(now - timedelta(minutes=500 - index))
    scan = inbox.fetch(REPO, tmp_path / "out", gh, now=now, settled=set())
    assert (scan["runs_examined"], scan["deferred_runs"], scan["scan_complete"]) == (inbox.MAX_RUNS_EXAMINED, 7, False)
    examined = [int(c.split("/runs/")[1].split("/")[0]) for c in gh.calls if c.endswith("/artifacts?per_page=100")]
    assert examined == sorted(examined), "oldest runs first"
