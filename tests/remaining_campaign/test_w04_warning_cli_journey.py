"""W04 04.6: the ordinary CLI in fresh processes for opt-in NHC advisory text.

``python -m src.main alerts`` (the configured NHC runner under the CLI-installed owner,
the ordinary writer/fact-check/critic, Gist admission with a live re-read) and later
``python -m src.main auto_publish_due`` (delayed approval, fresh NHC check, 200-scalar
cap, final safety, invented X receipt). Every process is started by
tests.remaining_campaign.warning_journey_child; see it for the named fake boundaries.
Invented storm, places and copy only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.state import DEFAULT_STATE
from tests import live_content_harness as lh
from tests import nhc_advisory_helpers as h

ROOT = Path(__file__).resolve().parents[2]
EPOCH = "invented-warning-journey-epoch-0001"
COPY = "Up to 3 inches of rain could trigger flash flooding and mudslides in Example Province tonight, NHC forecasts."
LONG = ("Up to 3 inches of rain could trigger flash flooding and mudslides in Example Province tonight, NHC forecasts, "
        "with rainfall continuing through tonight across the steep terrain of Example Province as the depression weakens.")
CORRECTED = h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4")))


def _iso(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def cli(tmp_path):
    for name in ("gist", "home", "nhc"):
        (tmp_path / name).mkdir()
    (tmp_path / "gist/state.json").write_text(json.dumps(deepcopy(DEFAULT_STATE)))
    (tmp_path / "nhc/index.json").write_bytes(h.index())
    (tmp_path / "nhc/page.html").write_bytes(h.page())
    (tmp_path / "nhc/page-corrected.html").write_bytes(CORRECTED)
    lh.write_catalogue(tmp_path / "cities.csv", ["Riyadh"])
    lh.write_normals(tmp_path / "normals.csv", lh.normal_rows(10, cities=[("Riyadh", "Asia/Riyadh", 1.0)]))
    return {"dir": tmp_path, "runs": 0}


def run_cli(cli, argv, minutes: float, *, env=None, copy=COPY, **options) -> dict:
    cli["runs"] += 1
    work = cli["dir"] / f"run-{cli['runs']}"
    work.mkdir()
    config = {"dir": str(cli["dir"]), "record": str(work / "record.json"), "argv": argv,
              "now": _iso(h.NOW + timedelta(minutes=minutes)), "forecasts": {},
              "cities_csv": str(cli["dir"] / "cities.csv"), "normals_csv": str(cli["dir"] / "normals.csv"),
              "models": {"copy": copy}, **options}
    (work / "config.json").write_text(json.dumps(config))
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cli["dir"] / "home"), "LC_ALL": "C",
            "LANG": "C", "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "GIST_ID": lh.GIST_ID, "GITHUB_TOKEN": lh.INVENTED_TOKEN,
            **lh.MODEL_ENV, **lh.X_ENV,
            "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": EPOCH,
            "THEHEAT_AQ_PM25_ENABLED": "0", "THEHEAT_AQ_DUST_ENABLED": "0", "THEHEAT_WETBULB_ENABLED": "0",
            "THEHEAT_GHCN_THRESHOLD_VERIFICATION": "failure",
            "THEHEAT_NHC_ADVISORY_ACQUISITION": "1",
            "THEHEAT_NHC_ADVISORY_NOMINATION": json.dumps(h.nominated(freshness_minutes=60)),
            "THEHEAT_NHC_ADVISORY_AUTO_TEXT": "1", **(env or {})}
    run = subprocess.run([sys.executable, "-m", "tests.remaining_campaign.warning_journey_child",
                          str(work / "config.json")], cwd=ROOT, env={k: v for k, v in base.items() if v is not None},
                         capture_output=True, text=True, timeout=600)
    (work / "output.txt").write_text(run.stdout + "\n--- stderr ---\n" + run.stderr)  # Invented data only.
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads((work / "record.json").read_text())


def drafts(cli) -> list[dict]:
    state = json.loads((cli["dir"] / "gist/state.json").read_text())
    return [d for d in state["drafts"] if d["type"] == "nhc_advisory"]


def test_alerts_admits_armed_text_then_a_later_process_posts_once(cli):
    produced = run_cli(cli, ["alerts"], 0)
    assert produced["x"] == [] and produced["nhc"], produced
    (draft,) = drafts(cli)
    assert draft["text"] == COPY and draft["approval_mode"] == "policy_auto"
    assert draft["approval_policy"]["key"] == "nhc_advisory_auto_text" and draft["auto_approve_at"]
    early = run_cli(cli, ["auto_publish_due"], 10)
    assert early["x"] == [] and early["nhc"] == []  # Not due: no source read, no send.
    sent = run_cli(cli, ["auto_publish_due"], 35)
    assert sent["x"] == [COPY] and sent["nhc"]  # Fresh fixed-source reads before safety and after intent.
    assert drafts(cli)[0]["status"] == "posted"
    again = run_cli(cli, ["auto_publish_due"], 70)
    assert again["x"] == []


def test_over_200_copy_is_saved_for_manual_review_and_never_auto_sent(cli):
    run_cli(cli, ["alerts"], 0, copy=LONG)
    (draft,) = drafts(cli)
    assert len(draft["text"]) > 200 and draft["automatic_text_hold"] == "automatic_text_over_200_scalars"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft
    assert run_cli(cli, ["auto_publish_due"], 35)["x"] == []


def test_changed_source_before_send_holds_for_manual_review(cli):
    run_cli(cli, ["alerts"], 0)
    (cli["dir"] / "nhc/page.html").write_bytes(CORRECTED)
    held = run_cli(cli, ["auto_publish_due"], 35)
    (draft,) = drafts(cli)
    assert held["x"] == [] and draft["approval_mode"] == "manual"
    assert "nhc_advisory_current_source_changed" in draft["post_error"]


def test_flag_off_in_the_sending_process_holds(cli):
    run_cli(cli, ["alerts"], 0)
    held = run_cli(cli, ["auto_publish_due"], 35, env={"THEHEAT_NHC_ADVISORY_AUTO_TEXT": "0"})
    (draft,) = drafts(cli)
    assert held["x"] == [] and "warning_auto_text_disabled" in draft["post_error"]
