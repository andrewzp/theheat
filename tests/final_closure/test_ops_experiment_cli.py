"""Weekly review -> bounded experiment plan -> acceptance, through the real CLIs (invented inputs).

The weekly review is produced by the actual ``scripts/weekly_review.mjs`` on an invented
saved state, then consumed by ``scripts/theheat_evaluation.py``. Nothing runs an arm,
calls a provider, changes a flag or authorizes publication.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import theheat_evaluation  # noqa: E402
from src.evaluation import experiment_plan as ep  # noqa: E402

NODE = shutil.which("node")
ARMS = [{"arm_id": "incumbent", "code_revision": "a" * 40, "brief_sha256": "b" * 64, "policy_sha256": "c" * 64,
         "model": "invented-writer-model"},
        {"arm_id": "challenger", "code_revision": "d" * 40, "brief_sha256": "b" * 64, "policy_sha256": "e" * 64,
         "model": "invented-writer-model"}]
SPEC = {"question": "Does the shorter lead brief reduce critic rejections without new factual failures?",
        "arms": ARMS, "allowance": {"max_candidates": 10, "max_model_calls": 40}}


def _rejected(index: int) -> dict:
    return {"ts": f"2026-11-0{1 + index % 3}T0{index}:00:00Z", "stage": "critic", "reasons": ["invented critic rejection"],
            "event_id": f"invented_event_{index}"}


def _weekly_review(tmp_path: Path, state: dict) -> dict:
    if NODE is None:
        pytest.skip("node is required for the weekly review CLI")
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    out = tmp_path / "weekly"
    completed = subprocess.run([NODE, str(ROOT / "scripts/weekly_review.mjs"), "--state", str(tmp_path / "state.json"),
                                "--as-of", "2026-11-04T00:00:00Z", "--output", str(out)],
                               capture_output=True, text=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "TZ": "UTC"})
    assert completed.returncode == 0, completed.stderr
    return json.loads(Path(json.loads(completed.stdout)["json"]).read_text(encoding="utf-8"))


def _cli(tmp_path: Path, *argv: str) -> tuple[int, dict]:
    code = theheat_evaluation.main(list(argv))
    output = Path(argv[argv.index("--output") + 1])
    return code, json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}


def test_weekly_review_local_repair_becomes_a_frozen_default_off_plan_and_accept_holds_without_evidence(tmp_path):
    review = _weekly_review(tmp_path, {"drafts": [], "publish_ledger": {}, "suppressions": [_rejected(i) for i in range(4)]})
    assert review["improvement"]["kind"] == "local_repair"
    (tmp_path / "review.json").write_text(json.dumps(review), encoding="utf-8")
    (tmp_path / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
    code, plan = _cli(tmp_path, "experiment-plan", "--weekly-review", str(tmp_path / "review.json"),
                      "--spec", str(tmp_path / "spec.json"), "--output", str(tmp_path / "plan.json"))
    assert code == 0
    assert plan["improvement"]["issue"] == review["improvement"]["issue"]
    assert plan["improvement"]["weekly_review_id"] == review["report_id"]
    assert plan["execution"] == {"status": "default_off", "authorized": False, "publication_authorized": False}
    assert plan["allowance"]["writer_samples"] == 1 and plan["allowance"]["revisions"] == 0

    (tmp_path / "result.json").write_text(json.dumps({"schema": ep.RESULT_SCHEMA, "plan_id": plan["plan_id"],
                                                       "incumbent": "incumbent", "challenger": "challenger", "arms": {}}))
    code, decision = _cli(tmp_path, "experiment-accept", "--plan", str(tmp_path / "plan.json"),
                          "--result", str(tmp_path / "result.json"), "--output", str(tmp_path / "decision.json"))
    assert code == 0
    assert decision["decision"] == "HOLD" and "arm_results_incomplete" in decision["reasons"]
    assert decision["automatic_changes"] is False


def test_owner_action_spec_drift_and_edited_plans_are_refused(tmp_path):
    owner = {"kind": "weekly_retained_outcome_review", "report_id": "f" * 64,
             "improvement": {"kind": "owner_action", "issue": "invented_source: Access expired"}}
    (tmp_path / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
    (tmp_path / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
    code, _ = _cli(tmp_path, "experiment-plan", "--weekly-review", str(tmp_path / "owner.json"),
                   "--spec", str(tmp_path / "spec.json"), "--output", str(tmp_path / "plan.json"))
    assert code == 2 and not (tmp_path / "plan.json").exists()

    # The spec cannot carry its own improvement: it must come from the weekly review.
    drifted = {**SPEC, "improvement": {"kind": "local_repair", "issue": "invented"}}
    local = {**owner, "improvement": {"kind": "local_repair", "issue": "3 candidates were rejected at critic this week."}}
    (tmp_path / "local.json").write_text(json.dumps(local), encoding="utf-8")
    (tmp_path / "drift.json").write_text(json.dumps(drifted), encoding="utf-8")
    code, _ = _cli(tmp_path, "experiment-plan", "--weekly-review", str(tmp_path / "local.json"),
                   "--spec", str(tmp_path / "drift.json"), "--output", str(tmp_path / "plan2.json"))
    assert code == 2

    code, plan = _cli(tmp_path, "experiment-plan", "--weekly-review", str(tmp_path / "local.json"),
                      "--spec", str(tmp_path / "spec.json"), "--output", str(tmp_path / "plan3.json"))
    assert code == 0
    edited = {**plan, "allowance": {**plan["allowance"], "max_model_calls": 200}}
    (tmp_path / "edited.json").write_text(json.dumps(edited), encoding="utf-8")
    (tmp_path / "result.json").write_text(json.dumps({"schema": ep.RESULT_SCHEMA, "plan_id": plan["plan_id"]}))
    code, _ = _cli(tmp_path, "experiment-accept", "--plan", str(tmp_path / "edited.json"),
                   "--result", str(tmp_path / "result.json"), "--output", str(tmp_path / "decision.json"))
    assert code == 2 and not (tmp_path / "decision.json").exists()

    # Existing output is never overwritten.
    code, _ = _cli(tmp_path, "experiment-plan", "--weekly-review", str(tmp_path / "local.json"),
                   "--spec", str(tmp_path / "spec.json"), "--output", str(tmp_path / "plan3.json"))
    assert code == 2
