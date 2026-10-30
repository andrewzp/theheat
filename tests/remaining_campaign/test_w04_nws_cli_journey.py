"""W04 04.6: the ordinary CLI in fresh processes for opt-in NWS (severe_weather) warning text.

``python -m src.main alerts`` (the NWS runner over the fixed active-alerts feed, the
ordinary writer/fact-check/critic, Gist admission) and later
``python -m src.main auto_publish_due`` (delayed approval, the active feed re-read at the
publication boundary, final safety, invented X receipt). Every process is started by
tests.remaining_campaign.warning_journey_child with the same fake boundaries as the NHC
journey. Invented office, area and copy only.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.state import DEFAULT_STATE
from tests import live_content_harness as lh

ROOT = Path(__file__).resolve().parents[2]
EPOCH = "invented-nws-journey-epoch-0001"
NOW = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
AREA = "Ficta Coast"
COPY = f"The NWS warns hurricane conditions are expected along the {AREA} tonight."


def _iso(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def feed(description: str = "Hurricane conditions are expected within the next 12 hours.") -> bytes:
    issued = (NOW - timedelta(minutes=20)).isoformat()
    props: dict[str, object] = {"id": "urn:oid:2.49.0.1.840.0.invented-nws-journey.001.1", "event": "Hurricane Warning",
             "category": "Met", "status": "Actual", "messageType": "Alert", "references": [], "areaDesc": AREA,
             "severity": "Extreme", "headline": "Hurricane Warning issued by NWS Invented Office",
             "description": description, "senderName": "NWS Invented Office", "sent": issued, "effective": issued,
             "onset": issued, "expires": (NOW + timedelta(hours=4)).isoformat(), "ends": None, "parameters": {}}
    return json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None,
                                                                   "properties": props}]}).encode()


@pytest.fixture
def cli(tmp_path):
    for name in ("gist", "home", "nws"):
        (tmp_path / name).mkdir()
    (tmp_path / "gist/state.json").write_text(json.dumps(deepcopy(DEFAULT_STATE)))
    (tmp_path / "nws/feed.json").write_bytes(feed())
    lh.write_catalogue(tmp_path / "cities.csv", ["Riyadh"])
    lh.write_normals(tmp_path / "normals.csv", lh.normal_rows(10, cities=[("Riyadh", "Asia/Riyadh", 1.0)]))
    return {"dir": tmp_path, "runs": 0}


def run_cli(cli, argv, minutes: float, *, env=None, copy=COPY) -> dict:
    cli["runs"] += 1
    work = cli["dir"] / f"run-{cli['runs']}"
    work.mkdir()
    config = {"dir": str(cli["dir"]), "record": str(work / "record.json"), "argv": argv,
              "now": _iso(NOW + timedelta(minutes=minutes)), "forecasts": {},
              "cities_csv": str(cli["dir"] / "cities.csv"), "normals_csv": str(cli["dir"] / "normals.csv"),
              "models": {"copy": copy}}
    (work / "config.json").write_text(json.dumps(config))
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cli["dir"] / "home"), "LC_ALL": "C",
            "LANG": "C", "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "GIST_ID": lh.GIST_ID, "GITHUB_TOKEN": lh.INVENTED_TOKEN,
            **lh.MODEL_ENV, **lh.X_ENV,
            "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": EPOCH,
            "THEHEAT_AQ_PM25_ENABLED": "0", "THEHEAT_AQ_DUST_ENABLED": "0", "THEHEAT_WETBULB_ENABLED": "0",
            "THEHEAT_GHCN_THRESHOLD_VERIFICATION": "failure",
            "THEHEAT_NWS_WARNING_AUTO_TEXT": "1", **(env or {})}
    run = subprocess.run([sys.executable, "-m", "tests.remaining_campaign.warning_journey_child",
                          str(work / "config.json")], cwd=ROOT, env={k: v for k, v in base.items() if v is not None},
                         capture_output=True, text=True, timeout=600)
    (work / "output.txt").write_text(run.stdout + "\n--- stderr ---\n" + run.stderr)  # Invented data only.
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads((work / "record.json").read_text())


def drafts(cli) -> list[dict]:
    state = json.loads((cli["dir"] / "gist/state.json").read_text())
    return [d for d in state["drafts"] if d["type"] == "severe_weather"]


def test_alerts_admits_armed_nws_text_then_a_later_process_posts_once(cli):
    produced = run_cli(cli, ["alerts"], 0)
    assert produced["x"] == [] and produced["nws"], produced
    (draft,) = drafts(cli)
    assert draft["text"] == COPY and draft["approval_mode"] == "policy_auto", draft.get("post_error")
    assert draft["approval_policy"]["key"] == "nws_warning_auto_text" and draft["auto_approve_at"]
    early = run_cli(cli, ["auto_publish_due"], 10)
    assert early["x"] == [] and early["nws"] == []  # Not due: no source read, no send.
    sent = run_cli(cli, ["auto_publish_due"], 35)
    assert sent["x"] == [COPY] and sent["nws"]  # The active feed is re-read at the publication boundary.
    assert drafts(cli)[0]["status"] == "posted"
    again = run_cli(cli, ["auto_publish_due"], 70)
    assert again["x"] == []


def test_changed_nws_source_before_send_holds_for_manual_review(cli):
    run_cli(cli, ["alerts"], 0)
    (cli["dir"] / "nws/feed.json").write_bytes(feed("Hurricane conditions are now expected within 6 hours."))
    held = run_cli(cli, ["auto_publish_due"], 35)
    (draft,) = drafts(cli)
    assert held["x"] == [] and draft["approval_mode"] == "manual"
    assert draft["post_error"].startswith("NWS warning needs fresh source review: nws_source"), draft["post_error"]


def test_nws_flag_off_in_the_sending_process_holds(cli):
    run_cli(cli, ["alerts"], 0)
    held = run_cli(cli, ["auto_publish_due"], 35, env={"THEHEAT_NWS_WARNING_AUTO_TEXT": "0"})
    (draft,) = drafts(cli)
    assert held["x"] == [] and "warning_auto_text_disabled" in draft["post_error"]
