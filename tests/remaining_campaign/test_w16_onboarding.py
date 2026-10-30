"""W16.4: offline onboarding preflight and supplied-draft inspection (invented inputs only)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src import operator_onboarding as onboarding
from src.state import DEFAULT_STATE

ROOT = Path(__file__).resolve().parents[2]


def test_checkout_preflight_names_legacy_normals_and_lock_match_without_running_anything():
    report = onboarding.preflight(ROOT, run_generators=False)
    assert report["repository"]["normals"]["status"] == "legacy_unqualified"
    assert report["repository"]["normals"]["qualified_points"] == 0
    assert report["repository"]["station_thresholds"]["status"] == "manifest_valid"
    assert report["features"]["hot10"] == "holds: qualified normals not installed"
    assert report["features"]["generated_artifacts"] == "not_checked"
    assert all(row["status"] == "not_run" for row in report["generated"].values())
    assert "environment values and credentials (owner-supplied; never read)" in report["not_inspected"]


def test_pins_are_classified_against_this_interpreter(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest==0.0.0-invented\nrequests>=1.0\nnot-a-real-package-xyz==1.0\n")
    report = onboarding.dependency_report(tmp_path)
    states = {row["name"]: row["state"] for row in report["groups"]["core"]["packages"]}
    assert states == {"pytest": "mismatch", "requests": "present_unverified_minimum", "not-a-real-package-xyz": "missing"}
    assert report["groups"]["core"]["status"] == "unavailable"
    assert report["groups"]["graphics"]["status"] == "requirements_missing"


def test_generator_checks_report_stale_and_missing_scripts_from_their_own_check_mode(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/gen_source_registry.py").write_text("import sys\nsys.exit(1 if '--check' in sys.argv else 0)\n")
    (tmp_path / "scripts/gen_editorial_policy.py").write_text("import sys\nsys.exit(0)\n")
    report = onboarding.generator_report(tmp_path)
    assert report["gen_source_registry"] == {"status": "stale_or_failed", "returncode": 1}
    assert report["gen_editorial_policy"] == {"status": "current", "returncode": 0}
    assert report["gen_dashboard_graphic_runtime"] == {"status": "missing"}


def _state(tmp_path, *, text, ledger=None):
    from src.editorial.revisions import initialize_revision

    draft = {"id": "invented-draft", "event_id": "invented-event", "type": "co2_milestone", "text": text,
             "status": "pending", "review_context": {"two_bot": {"bundle": {"event_id": "invented-event"}}}}
    initialize_revision(draft)
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    if ledger:
        state["publish_ledger"] = {"invented-event": ledger}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    return path


def test_inspect_draft_projects_holds_and_unknown_delivery(tmp_path):
    path = _state(tmp_path, text="x" * 201, ledger={"phase": "unknown", "tweet_id": None})
    view = onboarding.inspect_draft(path, "invented-draft")
    assert view["automatic_text_hold"] == "automatic_text_over_200_scalars"
    assert view["publication"] == {"phase": "unknown", "receipt": False, "unknown_delivery": True}
    assert view["approval_current"] == {"manual": False, "auto": False}
    with pytest.raises(ValueError, match="draft_not_found"):
        onboarding.inspect_draft(path, "another")


def test_cli_exit_codes(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("theheat_onboard", ROOT / "scripts/theheat_onboard.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = _state(tmp_path, text="Invented short text.")
    assert module.main(["inspect-draft", "--state", str(path), "--draft-id", "invented-draft"]) == 0
    assert json.loads(capsys.readouterr().out)["draft_id"] == "invented-draft"
    assert module.main(["inspect-draft", "--state", str(tmp_path / "absent.json"), "--draft-id", "x"]) == 2
    assert module.main(["unknown-command"]) == 64
