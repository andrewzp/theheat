"""Milestone F1: the real `python -m src.main leaderboard|alerts|auto_publish_due` CLI in
fresh processes, with every external transport replaced before import (see
tests/live_content_child.py and tests/live_content_harness.py). Gist is an invented
HTTP store, X an invented create endpoint, models SDK-shaped offline answers.

Hot10 base journeys (post once, paused policy, changed source, ended day, edited
text, unknown receipt) are in tests/test_hot10_live_content.py; these add the
over-200, unavailable-check and opt-in PM2.5 `alerts` journeys.
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

from src.data import places
from src.state import DEFAULT_STATE
from tests import live_content_harness as h

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
EPOCH = "invented-journey-epoch-0001"
HOT10_OVER = ("Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure among "
              "15 sampled cities, ahead of Baghdad at 8.1°C and Cairo at 7.4°C above their own monthly normals, today.")
PM25_COPY = "Lahore's PM2.5 is forecast to average 250 µg/m³ today, about 17 times the WHO 24-hour guideline, per CAMS model data."
NAMES = [name for name, _zone, _kind in h.CITIES] + ["Lahore"]


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def lahore_key() -> str:
    row = h.catalogue_rows(["Lahore"])[0]
    place = places.place_for_row(row)
    return h.coordinate_key(place["lat"], place["lon"])


@pytest.fixture
def cli(tmp_path):
    for name in ("gist", "home"):
        (tmp_path / name).mkdir()
    (tmp_path / "gist/state.json").write_text(json.dumps(deepcopy(DEFAULT_STATE)))
    h.write_catalogue(tmp_path / "cities.csv", NAMES)
    h.write_normals(tmp_path / "normals.csv", h.normal_rows(10))
    return {"dir": tmp_path, "runs": 0}


def run_cli(cli, argv, now: datetime, *, env=None, **options) -> dict:
    cli["runs"] += 1
    work = cli["dir"] / f"run-{cli['runs']}"
    work.mkdir()
    config = {"dir": str(cli["dir"]), "record": str(work / "record.json"), "argv": argv, "now": _iso(now),
              "forecasts": h.forecast_table(), "cities_csv": str(cli["dir"] / "cities.csv"),
              "normals_csv": str(cli["dir"] / "normals.csv"), **options}
    (work / "config.json").write_text(json.dumps(config))
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cli["dir"] / "home"), "LC_ALL": "C", "LANG": "C",
            "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "GIST_ID": h.GIST_ID, "GITHUB_TOKEN": h.INVENTED_TOKEN, **h.MODEL_ENV, **h.X_ENV,
            "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": EPOCH,
            "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1", "THEHEAT_AQ_DUST_ENABLED": "0",
            "THEHEAT_GHCN_THRESHOLD_VERIFICATION": "failure", **(env or {})}
    run = subprocess.run([sys.executable, "-m", "tests.live_content_child", str(work / "config.json")], cwd=ROOT,
                         env={k: v for k, v in base.items() if v is not None}, capture_output=True, text=True, timeout=600)
    (work / "output.txt").write_text(run.stdout + "\n--- stderr ---\n" + run.stderr)  # Invented data only.
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads((work / "record.json").read_text())


def state(cli) -> dict:
    return json.loads((cli["dir"] / "gist/state.json").read_text())


def drafts(cli, kind: str) -> list[dict]:
    return [d for d in state(cli)["drafts"] if d["type"] == kind]


# ---------------------------------------------------------------- Hot10 extra journeys


def test_over_200_hot10_copy_is_saved_for_manual_review_and_never_auto_sent(cli):
    record = run_cli(cli, ["leaderboard"], T0, models={"copy": HOT10_OVER})
    assert record["models"] == ["writer", "safety", "fact_check", "critic"]
    draft = drafts(cli, "hot10")[0]
    assert draft["text"] == HOT10_OVER and draft["automatic_text_hold"] == "automatic_text_over_200_scalars"
    assert draft["approval_mode"] == "manual" and "auto_approve_at" not in draft
    sent = run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=45))
    assert sent["x"] == [] and drafts(cli, "hot10")[0]["status"] == "pending"


def test_unavailable_or_failed_check_saves_nothing(cli):
    copy = "Riyadh's forecast high of 39.2°C runs 9.2°C above its October normal, the largest departure among 15 sampled cities."
    record = run_cli(cli, ["leaderboard"], T0, models={"copy": copy, "fact_passed": False})
    assert record["models"] == ["writer", "safety", "fact_check"] and drafts(cli, "hot10") == []
    kill = next(row for row in state(cli)["suppressions"] if row.get("event_id") == "hot10_2026-10-29")
    assert kill["stage"] == "fact_check"
    assert run_cli(cli, ["auto_publish_due"], T0 + timedelta(minutes=45))["x"] == []


# ---------------------------------------------------------------- opt-in PM2.5 through `alerts`

PM25_ENV = {"THEHEAT_PM25_FORECAST_AUTO_TEXT": "1"}
T_AQ = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)


def alerts(cli, **options) -> dict:
    hazard = {"pm25": 250.0, "dust": 100.0, "pm10": 90.0}
    return run_cli(cli, ["alerts"], T_AQ, env=PM25_ENV, models={"copies": {"air_quality_hazard": PM25_COPY}},
                   air_quality={lahore_key(): hazard}, **options)


def test_opt_in_pm25_alerts_journey_posts_once_and_isolates_other_sources(cli):
    record = alerts(cli)
    assert record["models"] == ["writer", "safety", "fact_check", "critic"]
    draft = drafts(cli, "air_quality_hazard")[0]
    assert draft["approval_policy"]["key"] == "pm25_forecast_auto_text" and draft["approval_mode"] == "policy_auto"
    report = state(cli)["run_history"][0]
    aq = next(row for row in report["sources"] if row["source"] == "air_quality")
    failed = [row["source"] for row in report["sources"] if row["status"] == "failed"]
    assert aq["status"] == "success" and failed and report["status"] == "partial_failure"  # Others fail alone.
    sent = run_cli(cli, ["auto_publish_due"], T_AQ + timedelta(minutes=40), env=PM25_ENV,
                   air_quality={lahore_key(): {"pm25": 250.0, "dust": 100.0, "pm10": 90.0}})
    assert sent["x"] == [PM25_COPY] and sent["models"] == ["safety"] and [c["points"] for c in sent["aq_calls"]] == [1]
    assert drafts(cli, "air_quality_hazard")[0]["status"] == "posted"
    again = run_cli(cli, ["auto_publish_due"], T_AQ + timedelta(minutes=80), env=PM25_ENV)
    assert again["x"] == [] and again["aq_calls"] == []


def test_new_local_day_holds_the_automatic_send(cli):
    alerts(cli)
    held = run_cli(cli, ["auto_publish_due"], datetime(2026, 10, 30, 0, 10, tzinfo=UTC), env=PM25_ENV)
    draft = drafts(cli, "air_quality_hazard")[0]
    assert held["x"] == [] and held["models"] == [] and "air_quality_window_ended" in draft["post_error"]


def test_source_change_after_the_writer_is_never_saved(cli):
    record = alerts(cli, aq_switch_after=2, air_quality_after={lahore_key(): {"pm25": 240.0, "dust": 100.0, "pm10": 90.0}})
    assert record["models"] == ["writer", "safety", "fact_check", "critic"] and drafts(cli, "air_quality_hazard") == []


def test_policy_disabled_before_send_holds(cli):
    alerts(cli)
    held = run_cli(cli, ["auto_publish_due"], T_AQ + timedelta(minutes=40),
                   env={**PM25_ENV, "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "0"})
    assert held["x"] == [] and drafts(cli, "air_quality_hazard")[0]["approval_mode"] == "manual"


def test_unknown_delivery_is_never_resent(cli):
    alerts(cli)
    hazard = {lahore_key(): {"pm25": 250.0, "dust": 100.0, "pm10": 90.0}}
    lost = run_cli(cli, ["auto_publish_due"], T_AQ + timedelta(minutes=40), env=PM25_ENV, air_quality=hazard,
                   x_failure="create_lost")
    assert len(lost["x"]) == 1
    again = run_cli(cli, ["auto_publish_due"], T_AQ + timedelta(minutes=80), env=PM25_ENV, air_quality=hazard)
    assert again["x"] == [] and drafts(cli, "air_quality_hazard")[0].get("tweet_id") is None
