"""W16.5 owned local recovery rehearsal over invented state.

Six situations, each handled by the real command, CLI or reader it would meet in
use, then rendered as one readable Operations board. Every source, draft, job,
receipt and export here is invented; passing proves the local recovery paths,
not production recovery.
"""
from __future__ import annotations

from copy import deepcopy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
from typing import Any

from src import recovery_rehearsal as rehearsal
from src.commands import local_cli
from src.data import source_incidents
from src.state import DEFAULT_STATE
from tests.two_bot import test_batch_transport as transport_tests

inputs, store, prepared = transport_tests.inputs, transport_tests.store, transport_tests.prepared
ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-30T12:00:00Z"


def _cli(script: str, *args: str, env: dict[str, str] | None = None) -> tuple[int, Any]:
    done = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=180, check=False,
                          env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC", "PYTHONDONTWRITEBYTECODE": "1",
                               **(env or {})})
    for stream in (done.stdout, done.stderr):
        lines = [line for line in stream.splitlines() if line.strip()]
        try:
            return done.returncode, json.loads(stream)
        except json.JSONDecodeError:
            if lines and lines[-1].startswith("{"):
                return done.returncode, json.loads(lines[-1])
    raise AssertionError(f"{script} printed no JSON (exit {done.returncode})")


def _local(*argv: str) -> tuple[int, Any]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


def _state_file(tmp_path: Path, name: str, **fields: Any) -> Path:
    state: dict[str, Any] = {**deepcopy(DEFAULT_STATE), **fields}
    path = tmp_path / name
    path.write_text(json.dumps(state))
    return path


def unavailable_source(tmp_path: Path) -> dict:
    attempt = source_incidents.attempt("firms.viirs_noaa21_nrt", "endpoint_missing", window="nrt_24h", region="world",
                                       parser_contract="firms.csv_v1", http_status=404, at="2026-10-30T06:00:00Z")
    run = {"id": "invented-run", "started_at": "2026-10-30T06:00:00Z",
           "sources": [{"source": "firms", "status": "failed",
                        "details": {"incident": source_incidents.run_incident("firms", [attempt])}}]}
    code, plan = _cli("scripts/source_incident_plan.py", "plan", "--state",
                      str(_state_file(tmp_path, "source-state.json", run_history=[run])))
    assert code in (0, 1), plan
    assert plan["network"] == "not_used" and plan["credential_enumeration"] == "not_performed"
    action = next(a for a in plan["actions"] if a["product_id"] == "firms.viirs_noaa21_nrt")
    incident = next(i for i in plan["incidents"] if i["product_id"] == "firms.viirs_noaa21_nrt")
    assert incident["state"] not in {"qualified", "recovered"}
    return rehearsal.status_row("unavailable_source", consumer="scripts/source_incident_plan.py plan",
                                observed=f"{incident['state']}:{incident['last_outcome']}",
                                operator_sees="NOAA-21 VIIRS fire product endpoint missing (HTTP 404); not 'no fires'",
                                safe_action=action["text"])


def missing_baseline(tmp_path: Path) -> dict:
    code, report = _cli("scripts/theheat_onboard.py", "preflight", "--skip-generators")
    assert code == 1 and report["repository"]["normals"]["status"] == "legacy_unqualified"
    assert report["features"]["hot10"].startswith("holds")
    plan_code, _ = _cli("scripts/build_normals.py", "plan", "--cities", "data/cities.csv", "--installed",
                        "data/normals.csv", "--output", str(tmp_path / "normals-plan.json"),
                        "--result", str(tmp_path / "normals-result.json"))
    result = json.loads((tmp_path / "normals-result.json").read_text())
    assert plan_code in (0, 1) and json.dumps(result).count("missing") >= 1
    return rehearsal.status_row("missing_baseline", consumer="scripts/theheat_onboard.py preflight; scripts/build_normals.py plan",
                                observed=report["repository"]["normals"]["status"],
                                operator_sees="Hot 10 holds: installed normals are legacy name-only rows",
                                safe_action="Owner runs build_normals.py acquire from the written plan in an isolated "
                                            "environment, then admit and install; nothing is fetched here.")


def stale_review(tmp_path: Path) -> dict:
    from src.editorial.revisions import initialize_revision, record_human_review, review_is_current

    draft = {"id": "invented-draft", "event_id": "invented-event", "type": "co2_milestone",
             "text": "Invented: CO2 passed a fixture milestone.", "status": "pending",
             "review_context": {"two_bot": {"bundle": {"event_id": "invented-event"}}}}
    initialize_revision(draft)
    record_human_review(draft, at="2026-10-30T10:00:00Z")
    assert review_is_current(draft)
    draft["text"] = "Invented: CO2 passed a fixture milestone this week."  # saved text drifted after review
    assert not review_is_current(draft)
    code, view = _cli("scripts/theheat_onboard.py", "inspect-draft", "--state",
                      str(_state_file(tmp_path, "review-state.json", drafts=[draft])), "--draft-id", "invented-draft")
    assert code == 0 and view["approval_current"] == {"manual": False, "auto": False}
    return rehearsal.status_row("stale_review", consumer="scripts/theheat_onboard.py inspect-draft",
                                observed=str(view["review_status"]),
                                operator_sees="The saved review does not match the current text; it cannot approve",
                                safe_action="Read the current text and record a new review; approval stays unavailable until then.")


def interrupted_job(prepared_store) -> dict:
    raw, pair = prepared_store
    code, jobs = _local("--database", raw.path, "jobs")
    assert code == 0 and jobs["inspection"]["automatic_retry"] is False
    row = next(job for job in jobs["inspection"]["jobs"] if job["job_id"] == pair[1]["job_id"])
    assert row["start_state"] == "unstarted"
    code, released = _local("--database", raw.path, "recover", "--job-id", pair[1]["job_id"],
                            "--operation", "release_unstarted")
    assert code == 0 and released["sent"] is False
    code, again = _local("--database", raw.path, "jobs")
    return rehearsal.status_row("interrupted_unstarted_job", consumer="local_cli jobs; local_cli recover release_unstarted",
                                observed=f"{row['start_state']}->released",
                                operator_sees="A writer job was granted nothing before it stopped; it was released, not resent",
                                safe_action="Nothing to resend. A released job can be queued again by the normal producer only.")


def unknown_delivery(tmp_path: Path) -> dict:
    from src.editorial.revisions import initialize_revision

    draft = {"id": "invented-sent", "event_id": "invented-sent-event", "type": "co2_milestone",
             "text": "Invented: delivery acknowledgement lost.", "status": "approved",
             "review_context": {"two_bot": {"bundle": {"event_id": "invented-sent-event"}}}}
    initialize_revision(draft)
    ledger = {"invented-sent-event": {"phase": "submitted", "intent_id": "00000000-0000-4000-8000-000000000001"}}
    code, view = _cli("scripts/theheat_onboard.py", "inspect-draft", "--state",
                      str(_state_file(tmp_path, "delivery-state.json", drafts=[draft], publish_ledger=ledger)),
                      "--draft-id", "invented-sent")
    assert code == 0 and view["publication"]["unknown_delivery"] is True and view["publication"]["receipt"] is False
    # The W14.4 reconciliation reader over the same invented state: inspect only, no receipt, no change.
    from src.commands.sqlite_authority import SQLiteAuthority

    database = tmp_path / "delivery.sqlite3"
    SQLiteAuthority(database).initialize({**deepcopy(DEFAULT_STATE), "drafts": [draft], "publish_ledger": ledger})
    code, inspected = _local("--database", str(database), "delivery", "inspect")
    row = next(r for r in inspected["rows"] if r["event_id"] == "invented-sent-event")
    assert code == 0 and inspected["mutation"] == "none" and row["hold"] == "receipt_required_unknown_stays_unknown"
    return rehearsal.status_row("unknown_delivery", consumer="inspect-draft; local_cli delivery inspect",
                                observed=f"{view['publication']['phase']}:{row['hold']}",
                                operator_sees="A send started and its acknowledgement was lost; delivery is unknown",
                                safe_action="Reconcile against the platform receipt for this exact intent; never resend.")


def restore_refusal(tmp_path: Path) -> dict:
    tmp_path = tmp_path.resolve()  # the store refuses any symlinked path component
    export = tmp_path / "media-export"
    export.mkdir(mode=0o700)
    (export / "unexpected.json").write_text("{}")
    store_path = tmp_path / "restore-target.sqlite3"
    code, refused = _cli("scripts/retain_gist_media.py", "restore", "--source", str(export),
                         env={"THEHEAT_MEDIA_WRITER_STORE": f"sqlite:{store_path}", "THEHEAT_MEDIA_STORE": f"sqlite:{store_path}"})
    assert code == 2 and refused["held"] == "export_missing" and not store_path.exists()
    # The W14.5 restore plan for state refuses a backup whose bytes differ from the recorded hash.
    from src.commands.sqlite_authority import SQLiteAuthority

    target = SQLiteAuthority(tmp_path / "restore-state.sqlite3")
    target.initialize(dict(deepcopy(DEFAULT_STATE)))
    before = target.read()
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps(DEFAULT_STATE))
    code, plan = _local("--database", str(tmp_path / "restore-state.sqlite3"), "restore-plan", "--backup", str(backup),
                        "--expected-sha256", "0" * 64, "--restore-id", "rehearsal-restore", "--media-export", str(export))
    codes = {row["code"] for row in plan.get("refusals", [])} if isinstance(plan, dict) else set()
    assert not plan.get("executable") and plan.get("mutation") == "none" and "backup_artifact_changed" in codes
    assert target.read() == before
    return rehearsal.status_row("restore_plan_refusal", consumer="retain_gist_media.py restore; local_cli restore-plan",
                                observed=refused["held"] + "+" + ",".join(sorted(codes)),
                                operator_sees="The export is missing or incomplete; nothing was restored",
                                safe_action="Export again from the source store and verify it; the target was not touched.")


def test_owned_recovery_rehearsal_reaches_a_readable_operations_board(tmp_path, prepared):
    rows = [unavailable_source(tmp_path), missing_baseline(tmp_path), stale_review(tmp_path), interrupted_job(prepared),
            unknown_delivery(tmp_path), restore_refusal(tmp_path)]
    document = rehearsal.board(rows, as_of=NOW)
    text = rehearsal.render_markdown(document)
    assert [row["step"] for row in document["rows"]] == list(rehearsal.STEPS)
    assert document["sent"] == 0 and document["production_mutated"] == 0
    for title in rehearsal.TITLES.values():
        assert title in text
    assert "not production recovery evidence" in text and "never resend" in text
    (tmp_path / "rehearsal.md").write_text(text)


def test_board_refuses_side_effects_and_incomplete_rehearsals():
    import pytest

    with pytest.raises(rehearsal.RehearsalError, match="rehearsal_side_effect"):
        rehearsal.status_row("unknown_delivery", consumer="x", observed="y", operator_sees="z", safe_action="w", sent=True)
    with pytest.raises(rehearsal.RehearsalError, match="incomplete_rehearsal"):
        rehearsal.board([rehearsal.status_row("stale_review", consumer="x", observed="y", operator_sees="z",
                                              safe_action="w")], as_of=NOW)
