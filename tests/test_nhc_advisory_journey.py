"""The actual NHC publication workflow across fresh processes, with invented transports only.

trial prepare → trial execute (four reserved offline stage calls) → import check →
import apply (one PATCH through an invented ``gh``) → the actual dashboard handlers
list/review/approve (Node) → ``python -m src.main manual_tweet`` (owner re-reads NHC at
entry, final safety and after the durable intent; invented X receipt; history) → a
second fresh sender never resends. Text-only: no media store or media hosting is
configured. Every Python step is a new process started by tests.nhc_advisory_child;
see that module for the named fake boundaries. No network, model, Gist or X access.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.state import DEFAULT_STATE
from tests import nhc_advisory_helpers as h
from tests.nhc_advisory_import_helpers import FLAGS, TRIAL_ID, production_policy, report
from tests.test_gist_store_journey import node_binary

ROOT = Path(__file__).resolve().parents[1]
GIST_ID = "0123456789abcdef0123"
T0 = h.NOW
CORRECTED = h.page(h.bulletin(hazard=h.HAZARD.replace("1 to 3", "2 to 4")))


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def base_env(home: Path) -> dict:
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LC_ALL": "C", "LANG": "C",
            "NETRC": "/dev/null", "NO_PROXY": "*", "no_proxy": "*", "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1"}


@pytest.fixture
def journey(tmp_path):
    from scripts.fresh_sample_trial import MODELS
    policy = production_policy()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for name in ("nhc", "gist", "bin", "claims-common/.git", "home"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "nhc/index.json").write_bytes(h.index())
    (tmp_path / "nhc/page.html").write_bytes(h.page())
    (tmp_path / "nhc/page-corrected.html").write_bytes(CORRECTED)
    state = deepcopy(DEFAULT_STATE)
    state["run_history"] = [{"started_at": at(-1), "runtime_inventory": {
        "schema_version": 1, "captured_at": at(-1), "editorial_policy": policy}}]
    (tmp_path / "gist/state.json").write_text(json.dumps(state))
    (tmp_path / "gist/runtime-inventory.json").write_bytes(
        report(captured=T0 - timedelta(minutes=1), code=head, policy=policy))
    (tmp_path / "variables.json").write_text(json.dumps({"variables": [{"name": k, "value": v}
                                                                       for k, v in FLAGS.items()]}))
    gh = tmp_path / "bin/gh"
    gh.write_text(f"#!{sys.executable}\n" + FAKE_GH)
    gh.chmod(0o700)
    env = {**base_env(tmp_path / "home"), "PATH": f"{tmp_path / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
           "INVENTED_GH_DIR": str(tmp_path), "INVENTED_GIST_ID": GIST_ID,
           "ANTHROPIC_API_KEY": "invented-no-provider-access", "GEMINI_API_KEY": "invented-no-provider-access",
           "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0", "THEHEAT_CRITIC_ENABLED": "1"}
    # The trial's own pinned profile (configure() applies the same values); never the sender's.
    trial = {"THEHEAT_WRITER_MODEL": MODELS["writer"][1], "THEHEAT_FACT_CHECK_MODEL": MODELS["fact_check"][1],
             "THEHEAT_CRITIC_MODEL": MODELS["critic"][1], "GEMINI_SAFETY_MODEL": MODELS["safety"][1]}
    return {"dir": tmp_path, "env": env, "trial_env": trial, "policy": policy, "runs": 0}


FAKE_GH = r'''"""Invented GitHub CLI: serves the journey's local Gist and variables; never the network."""
import json, os, sys
from pathlib import Path
root = Path(os.environ["INVENTED_GH_DIR"])
args = sys.argv[1:]
with (root / "gh-calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
assert args[0] == "api", args
gist, route = root / "gist", f"gists/{os.environ['INVENTED_GIST_ID']}"
if args[1:3] == ["--method", "PATCH"]:
    assert args[3:] == [route, "--input", "-"], args
    body = json.load(sys.stdin)
    assert list(body) == ["files"] and list(body["files"]) == ["state.json"], "one state.json mutation only"
    mode = (root / "gh-patch-mode").read_text().strip() if (root / "gh-patch-mode").exists() else "apply"
    if mode in ("apply", "apply_then_lose"):
        (gist / "state.json").write_text(body["files"]["state.json"]["content"])
    if mode in ("lose", "apply_then_lose"):
        sys.exit(1)
    print("{}")
    sys.exit(0)
if args[1] == route:
    files = {p.name: {"content": p.read_text(), "truncated": False} for p in sorted(gist.iterdir())}
    print(json.dumps({"files": files}))
elif args[1] == "repos/invented-owner/invented-repo/actions/variables?per_page=100":
    print((root / "variables.json").read_text())
else:
    sys.exit(3)
'''


def child(journey, kind, target, argv, now, *, extra_env=None, **options):
    """One fresh process running one actual entrypoint; returns (record, stdout JSON)."""
    journey["runs"] += 1
    work = journey["dir"] / f"run-{journey['runs']}"
    work.mkdir()
    config = {"dir": str(journey["dir"]), "record": str(work / "record.json"), "kind": kind, "target": target,
              "argv": argv, "now": now, **options}
    (work / "config.json").write_text(json.dumps(config))
    env = {**journey["env"], "GIST_ID": GIST_ID, **(extra_env or {})}
    run = subprocess.run([sys.executable, "-m", "tests.nhc_advisory_child", str(work / "config.json")], cwd=ROOT,
                         env=env, capture_output=True, text=True, timeout=300)
    (work / "output.txt").write_text(run.stdout + "\n--- stderr ---\n" + run.stderr)  # Invented data only.
    assert run.returncode == 0, run.stderr[-4000:]
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    return json.loads((work / "record.json").read_text()), (json.loads(lines[-1]) if lines else None)


def produce(journey, *, switch_after=None):
    out = journey["dir"] / "packet"
    snapshot = journey["dir"] / "state-snapshot.json"
    snapshot.write_bytes((journey["dir"] / "gist/state.json").read_bytes())
    nomination = {"NHC_ADVISORY_NOMINATION": json.dumps(h.nominated()), **journey["trial_env"]}
    record, prepared = child(journey, "script", "scripts/nhc_advisory_trial.py",
                             ["prepare", "--state", str(snapshot), "--output", str(out), "--trial-id", TRIAL_ID],
                             at(0), extra_env=nomination)
    assert record["exit"] == 0 and prepared["candidate_count"] == 1 and len(record["nhc"]) == 2
    record, executed = child(journey, "script", "scripts/nhc_advisory_trial.py",
                             ["execute", "--output", str(out), "--approved-plan-sha256", prepared["plan_sha256"]],
                             at(1), extra_env=journey["trial_env"], stages=True, nhc_switch_after_pages=switch_after)
    assert record["exit"] == 0, executed
    return out, record, executed


def importer(journey, action, proposal, *extra):
    sha = hashlib.sha256(proposal.read_bytes()).hexdigest()
    return child(journey, "script", "scripts/nhc_advisory_import.py",
                 [action, "--proposal", str(proposal), "--proposal-sha256", sha, "--gist-id", GIST_ID,
                  "--repository", "invented-owner/invented-repo", *extra], at(3 if action == "check" else 4))


def review(journey, now):
    raw = (journey["dir"] / "gist/state.json").read_text()
    done = subprocess.run([node_binary(), "tests/helpers/nhc-review-driver.mjs"], cwd=ROOT / "dashboard",
                          input=json.dumps({"raw_state": raw, "policy": journey["policy"], "now": now}),
                          text=True, capture_output=True, timeout=60, env=base_env(journey["dir"] / "home"))
    assert done.returncode == 0, done.stderr[-3500:]
    result = json.loads(done.stdout)
    (journey["dir"] / "gist/state.json").write_text(result["raw_state"])  # The dashboard's Gist write.
    return result


def sender(journey, inputs, now, *, extra_env_override=None, **options):
    env = {"THEHEAT_STATE_BACKEND": "gist", "GITHUB_TOKEN": "invented-not-a-real-token",
           "TWITTER_API_KEY": "invented", "TWITTER_API_SECRET": "invented", "TWITTER_ACCESS_TOKEN": "invented",
           "TWITTER_ACCESS_SECRET": "invented", "TWEET_TEXT": inputs["tweet_text"], "DRAFT_ID": inputs["draft_id"],
           "PUBLISH_INTENT_ID": inputs["publish_intent_id"], **(extra_env_override or {})}
    record, _ = child(journey, "module", "src.main", ["manual_tweet"], now, extra_env=env, **options)
    return record, json.loads((journey["dir"] / "gist/state.json").read_text())


def pending_draft(journey):
    out, record, executed = produce(journey)
    assert executed["pending_proposal"] is True and executed["paid_dispatch_reservations"] == 4
    assert record["stages"] == ["writer", "fact_check", "critic"] and record["models"][0][0] == "google"
    proposal = out / "pending-proposal.json"
    record, checked = importer(journey, "check", proposal)
    assert record["exit"] == 0 and checked["writes"] == 0 and len(record["nhc"]) == 2, checked
    journal = journey["dir"] / "journal"
    record, applied = importer(journey, "apply", proposal, "--journal", str(journal),
                               "--expected-state-sha256", checked["state_sha256"])
    assert applied["outcome"] == "confirmed_pending" and applied["patch_attempts"] == 1, applied
    assert len(record["nhc"]) == 2 and record["http"] == [["GET", u] for u in record["nhc"]]
    calls = [json.loads(line) for line in (journey["dir"] / "gh-calls.jsonl").read_text().splitlines()]
    assert sum(1 for c in calls if "PATCH" in c) == 1
    return json.loads((journey["dir"] / "gist/state.json").read_text())


def test_trial_import_review_send_receipt_and_no_resend_in_fresh_processes(journey):
    state = pending_draft(journey)
    (draft,) = state["drafts"]
    assert (draft["status"], draft["approval_policy"]["mode"]) == ("pending", "manual_only")
    assert "review_binding" not in draft and "approval_binding" not in draft and "publish_intent_id" not in draft
    reviewed = review(journey, f"{at(6)[:-1]}.000Z")
    assert reviewed["patches"] == 2 and reviewed["dispatches"][0]["inputs"]["mode"] == "manual_tweet"
    inputs = reviewed["dispatches"][0]["inputs"]
    record, state = sender(journey, inputs, at(8))
    (draft,) = state["drafts"]
    assert record["exit"] == 0 and record["x"] == [["create", draft["text"]]]
    # The sender's own owner re-read NHC at entry, at the final-safety attempt and after the durable intent.
    assert len(record["nhc"]) == 6 and [provider for provider, _ in record["models"]] == ["google"]
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-receipt"
    assert state["publish_ledger"][draft["event_id"]]["tweet_id"] == "invented-x-receipt"
    assert draft["event_id"] in state["posted_events"]
    # Text-only: no media store configured, no media-hosting module loaded, no upload call.
    assert record["media_modules"] == [] and "THEHEAT_MEDIA_STORE" not in journey["env"]
    again, after = sender(journey, inputs, at(9))
    assert again["x"] == [] and after["publish_ledger"] == state["publish_ledger"]
    assert after["drafts"][0]["status"] == "posted"


def test_a_source_change_after_the_writer_response_retains_it_and_promotes_nothing(journey):
    # Page reads: pre-claim guard, writer pre-reservation and pre-dispatch guards; then corrected.
    out, record, executed = produce(journey, switch_after=3)
    assert executed["pending_proposal"] is False and executed["drafts_returned"] == 0
    assert record["stages"] == ["writer"] and executed["paid_dispatch_reservations"] == 1
    rows = [json.loads(line) for line in (out / "purchases.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in rows if r.get("stage") == "writer"] == ["reserved_before_dispatch", "response_returned"]
    assert not (out / "pending-proposal.json").exists()
    assert json.loads((journey["dir"] / "gist/state.json").read_text())["drafts"] == []


def test_a_correction_after_approval_holds_the_sender_before_safety_or_intent(journey):
    pending_draft(journey)
    inputs = review(journey, f"{at(6)[:-1]}.000Z")["dispatches"][0]["inputs"]
    (journey["dir"] / "nhc/page.html").write_bytes(CORRECTED)
    record, state = sender(journey, inputs, at(8))
    (draft,) = state["drafts"]
    assert record["x"] == [] and record["models"] == [] and draft["status"] == "pending"
    assert "nhc_advisory_current_source_changed" in draft["post_error"]
    assert draft["event_id"] not in state["publish_ledger"]


def test_a_lost_create_response_stays_unknown_and_a_fresh_sender_never_resends(journey):
    pending_draft(journey)
    inputs = review(journey, f"{at(6)[:-1]}.000Z")["dispatches"][0]["inputs"]
    record, state = sender(journey, inputs, at(8), x_failure="create_lost")
    (draft,) = state["drafts"]
    assert len(record["x"]) == 1 and draft["publish_outcome"] == "unknown"
    again, after = sender(journey, inputs, at(9))
    assert again["x"] == [] and after["drafts"][0]["publish_outcome"] == "unknown"


def test_the_operator_deadline_passing_before_send_holds(journey):
    pending_draft(journey)
    inputs = review(journey, f"{at(6)[:-1]}.000Z")["dispatches"][0]["inputs"]
    record, state = sender(journey, inputs, at(31))  # Capture at T0 + 30 minutes freshness.
    assert record["x"] == [] and record["nhc"] == [] and state["drafts"][0]["status"] == "pending"
    assert "nhc_advisory_operator_deadline_passed" in state["drafts"][0]["post_error"]


def test_a_changed_runtime_policy_after_approval_sends_and_reads_nothing(journey):
    pending_draft(journey)
    inputs = review(journey, f"{at(6)[:-1]}.000Z")["dispatches"][0]["inputs"]
    # A different deployed safety model is a different editorial policy than the one approved.
    record, state = sender(journey, inputs, at(8), extra_env_override={"GEMINI_SAFETY_MODEL": "invented-changed-model"})
    assert record["x"] == [] and record["nhc"] == [] and record["models"] == []
    assert state["drafts"][0]["status"] == "approved" and state["publish_ledger"] == {}
