"""Tests for the scheduled-workflow health observer.

Philosophy mirrors the source-health sentinel: a red scheduled workflow is OUR
problem and must surface without a human watching. This observer reads the GitHub
Actions API for the four scheduled workflows and turns any that are red on `main`
into a tracked, auto-closing `workflow-health` issue — the durable, de-duped
signal the daily self-heal routine consumes. It also flags the self-heal routine
itself if its heartbeat goes stale, so the watcher cannot silently die (the exact
failure that hid voice-regression's five red days and the daily-plan routine's
death).
"""

from datetime import datetime, timezone
import os

import scripts.workflow_health as wh
from scripts.workflow_health import (
    BEACON_VARIABLE,
    FAILING_CONCLUSIONS,
    LABEL,
    SELFHEAL_MAX_AGE_H,
    SELFHEAL_SOURCE,
    TITLE_PREFIX,
    build_workflow_issue_body,
    classify_workflow_run,
    count_leading_failures,
    fetch_runs_by_workflow,
    fetch_selfheal_beacon,
    plan_workflow_issue_actions,
    run_workflow_health,
    selfheal_liveness_verdict,
    select_latest_decisive_run,
)

NOW = datetime(2026, 6, 17, 16, 0, 0, tzinfo=timezone.utc)
REPO = "andrewzp/theheat"


def _run(run_id, conclusion, created_at, status="completed"):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "created_at": created_at,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
    }


# Real voice-regression runs (06-13 -> 06-17). The four reds are the five-day
# regression that nobody noticed; the two successes are the post-fix recovery.
VR_RED_RUNS = [
    _run(27624430282, "failure", "2026-06-16T14:22:03Z"),
    _run(27556694852, "failure", "2026-06-15T15:20:27Z"),
    _run(27497526866, "failure", "2026-06-14T11:33:47Z"),
    _run(27465295748, "failure", "2026-06-13T11:20:11Z"),
]
VR_RECOVERED_RUNS = [
    _run(27690444550, "success", "2026-06-17T12:54:39Z"),
    _run(27663411635, "success", "2026-06-17T03:17:24Z"),
    *VR_RED_RUNS,
]


class TestSelectLatestDecisiveRun:
    def test_picks_newest_decisive_run(self):
        run = select_latest_decisive_run(VR_RECOVERED_RUNS)
        assert run["id"] == 27690444550

    def test_skips_cancelled_and_in_progress(self):
        runs = [
            _run(3, None, "2026-06-17T15:00:00Z", status="in_progress"),
            _run(2, "cancelled", "2026-06-17T14:00:00Z"),
            _run(1, "success", "2026-06-17T13:00:00Z"),
        ]
        assert select_latest_decisive_run(runs)["id"] == 1

    def test_returns_none_when_no_decisive_run(self):
        runs = [
            _run(2, None, "2026-06-17T15:00:00Z", status="queued"),
            _run(1, "cancelled", "2026-06-17T14:00:00Z"),
        ]
        assert select_latest_decisive_run(runs) is None

    def test_unsorted_input_picks_newest_by_created_at(self):
        runs = [
            _run(1, "failure", "2026-06-13T11:20:11Z"),
            _run(3, "success", "2026-06-17T12:54:39Z"),
            _run(2, "failure", "2026-06-15T15:20:27Z"),
        ]
        assert select_latest_decisive_run(runs)["id"] == 3


class TestCountLeadingFailures:
    def test_counts_consecutive_reds_from_newest(self):
        assert count_leading_failures(VR_RED_RUNS) == 4

    def test_zero_when_newest_is_success(self):
        assert count_leading_failures(VR_RECOVERED_RUNS) == 0

    def test_stops_at_first_success(self):
        runs = [
            _run(3, "failure", "2026-06-17T15:00:00Z"),
            _run(2, "success", "2026-06-17T14:00:00Z"),
            _run(1, "failure", "2026-06-17T13:00:00Z"),
        ]
        assert count_leading_failures(runs) == 1


class TestClassifyWorkflowRun:
    def test_success_is_healthy(self):
        v = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RECOVERED_RUNS, now=NOW)
        assert v["category"] == "healthy"
        assert v["last_success_url"].endswith("/27690444550")

    def test_known_red_streak_is_failing(self):
        # The exact scenario as of 2026-06-16: four reds, no recent green.
        v = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RED_RUNS, now=NOW)
        assert v["category"] == "failing"
        assert v["conclusion"] == "failure"
        assert v["run_url"].endswith("/27624430282")
        assert v["consecutive_failures"] == 4
        assert v["last_success_url"] is None

    def test_timed_out_is_failing(self):
        runs = [_run(1, "timed_out", "2026-06-17T13:00:00Z")]
        assert classify_workflow_run("bot", "bot.yml", runs, now=NOW)["category"] == "failing"

    def test_startup_failure_is_failing(self):
        runs = [_run(1, "startup_failure", "2026-06-17T13:00:00Z")]
        assert classify_workflow_run("bot", "bot.yml", runs, now=NOW)["category"] == "failing"

    def test_no_runs_is_unknown_not_failing(self):
        v = classify_workflow_run("refresh-thresholds", "refresh-thresholds.yml", [], now=NOW)
        assert v["category"] == "unknown"

    def test_only_cancelled_is_unknown_not_failing(self):
        runs = [_run(1, "cancelled", "2026-06-17T13:00:00Z")]
        assert classify_workflow_run("bot", "bot.yml", runs, now=NOW)["category"] == "unknown"

    def test_recovered_after_reds_carries_last_success(self):
        v = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RECOVERED_RUNS, now=NOW)
        assert v["category"] == "healthy"
        assert v["consecutive_failures"] == 0


class TestRunWorkflowHealth:
    def test_mixed_reports_failures(self):
        runs_by_workflow = {
            "theheat-bot": {"file": "bot.yml", "runs": [_run(1, "success", "2026-06-17T14:00:00Z")]},
            "voice-regression": {"file": "voice-regression.yml", "runs": VR_RED_RUNS},
        }
        report = run_workflow_health(runs_by_workflow, now=NOW)
        assert report["has_failures"] is True
        assert [v["workflow"] for v in report["failing"]] == ["voice-regression"]
        assert report["summary"]["failing"] == 1
        assert report["summary"]["healthy"] == 1

    def test_all_healthy_has_no_failures(self):
        runs_by_workflow = {
            "theheat-bot": {"file": "bot.yml", "runs": [_run(1, "success", "2026-06-17T14:00:00Z")]},
            "voice-regression": {"file": "voice-regression.yml", "runs": VR_RECOVERED_RUNS},
        }
        report = run_workflow_health(runs_by_workflow, now=NOW)
        assert report["has_failures"] is False
        assert report["failing"] == []

    def test_stale_selfheal_beacon_surfaces_as_failure(self):
        runs_by_workflow = {
            "theheat-bot": {"file": "bot.yml", "runs": [_run(1, "success", "2026-06-17T14:00:00Z")]},
        }
        beacon = {"run_at": "2026-06-15T00:00:00Z", "outcome": "ok"}  # ~64h stale
        report = run_workflow_health(runs_by_workflow, beacon=beacon, now=NOW)
        assert report["has_failures"] is True
        assert any(v["workflow"] == SELFHEAL_SOURCE for v in report["failing"])

    def test_fresh_selfheal_beacon_is_quiet(self):
        runs_by_workflow = {
            "theheat-bot": {"file": "bot.yml", "runs": [_run(1, "success", "2026-06-17T14:00:00Z")]},
        }
        beacon = {"run_at": "2026-06-17T12:00:00Z", "outcome": "ok"}  # 4h fresh
        report = run_workflow_health(runs_by_workflow, beacon=beacon, now=NOW)
        assert report["has_failures"] is False


class TestSelfHealLiveness:
    def test_stale_beacon_flags(self):
        beacon = {"run_at": "2026-06-15T00:00:00Z", "outcome": "ok"}
        v = selfheal_liveness_verdict(beacon, now=NOW)
        assert v is not None
        assert v["workflow"] == SELFHEAL_SOURCE
        assert v["category"] == "failing"

    def test_fresh_beacon_quiet(self):
        beacon = {"run_at": "2026-06-17T12:00:00Z", "outcome": "ok"}
        assert selfheal_liveness_verdict(beacon, now=NOW) is None

    def test_missing_beacon_is_quiet_no_rollout_noise(self):
        # A never-set beacon (routine not configured yet) must NOT file an issue.
        assert selfheal_liveness_verdict(None, now=NOW) is None

    def test_exactly_at_threshold_is_quiet(self):
        run_at = NOW.timestamp() - SELFHEAL_MAX_AGE_H * 3600
        beacon = {"run_at": datetime.fromtimestamp(run_at, tz=timezone.utc).isoformat()}
        assert selfheal_liveness_verdict(beacon, now=NOW) is None

    def test_unparseable_beacon_is_quiet(self):
        assert selfheal_liveness_verdict({"run_at": "not-a-date"}, now=NOW) is None


class TestPlanWorkflowIssueActions:
    # Signature: plan_workflow_issue_actions(failing, recovered, open_issues).
    # An issue is CLOSED only for a workflow we positively observed RECOVERED —
    # never merely "not in the failing set" (that auto-closed still-failing issues
    # on a transient fetch failure: the false-recovery bug both reviewers caught).
    def test_creates_issue_for_new_failure(self):
        actions = plan_workflow_issue_actions({"voice-regression"}, set(), {})
        assert actions == [{"action": "create", "workflow": "voice-regression"}]

    def test_closes_issue_for_recovered_workflow(self):
        actions = plan_workflow_issue_actions(set(), {"voice-regression"}, {"voice-regression": 5})
        assert actions == [{"action": "close", "workflow": "voice-regression", "number": 5}]

    def test_unknown_or_fetch_failed_workflow_issue_is_NOT_closed(self):
        # The regression test for the false-recovery bug. A workflow with an open
        # issue that is neither confirmed-failing nor confirmed-recovered (e.g. its
        # run fetch failed → unknown) must be LEFT ALONE, never auto-closed.
        assert plan_workflow_issue_actions(set(), set(), {"voice-regression": 5}) == []

    def test_create_and_close_leaves_still_failing_and_unknown_alone(self):
        actions = plan_workflow_issue_actions(
            {"voice-regression", "theheat-bot"},      # failing
            {"refresh-thresholds"},                    # recovered (healthy)
            {"refresh-thresholds": 9, "theheat-bot": 7, "source-health-sentinel": 3},
        )
        kinds = {(a["action"], a["workflow"]) for a in actions}
        assert ("create", "voice-regression") in kinds
        assert ("close", "refresh-thresholds") in kinds
        assert not any(a["workflow"] == "theheat-bot" for a in actions)        # still failing
        assert not any(a["workflow"] == "source-health-sentinel" for a in actions)  # unknown → left alone

    def test_nothing_to_do_when_aligned(self):
        assert plan_workflow_issue_actions({"voice-regression"}, set(), {"voice-regression": 1}) == []

    def test_create_carries_labels_and_body_when_verdict_given(self):
        verdict = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RED_RUNS, now=NOW)
        actions = plan_workflow_issue_actions({"voice-regression": verdict}, set(), {})
        create = actions[0]
        assert create["action"] == "create"
        assert LABEL in create["labels"]
        assert "voice-regression" in create["body"]

    def test_update_when_body_changes(self):
        verdict = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RED_RUNS, now=NOW)
        open_issues = {"voice-regression": {"number": 3, "body": "stale body", "labels": [LABEL]}}
        actions = plan_workflow_issue_actions({"voice-regression": verdict}, set(), open_issues)
        assert actions[0]["action"] == "update"
        assert actions[0]["number"] == 3

    def test_update_skipped_when_body_current(self):
        verdict = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RED_RUNS, now=NOW)
        body = build_workflow_issue_body(verdict)
        open_issues = {"voice-regression": {"number": 3, "body": body, "labels": [LABEL, "ours"]}}
        assert plan_workflow_issue_actions({"voice-regression": verdict}, set(), open_issues) == []


class TestFetchSelfHealBeacon:
    # In CI the SELFHEAL_BEACON repo variable is injected as an env var via
    # `vars.SELFHEAL_BEACON` — the default GITHUB_TOKEN cannot read the variables
    # REST endpoint, so env-first is the only thing that makes the meta-guard fire.
    def teardown_method(self):
        os.environ.pop(BEACON_VARIABLE, None)

    def test_reads_beacon_json_from_env(self):
        os.environ[BEACON_VARIABLE] = '{"run_at": "2026-06-17T12:00:00Z", "outcome": "ok"}'
        beacon = fetch_selfheal_beacon()
        assert beacon == {"run_at": "2026-06-17T12:00:00Z", "outcome": "ok"}

    def test_empty_env_is_none(self):
        os.environ[BEACON_VARIABLE] = ""
        assert fetch_selfheal_beacon() is None

    def test_unparseable_env_is_none(self):
        os.environ[BEACON_VARIABLE] = "not json"
        assert fetch_selfheal_beacon() is None


class TestFetchRunsByWorkflow:
    def test_marks_fetch_failure_distinct_from_empty(self, monkeypatch):
        # A failed gh api call must NOT look like "no runs / recovered" — it must
        # be flagged so downstream never auto-closes a still-failing issue.
        monkeypatch.setattr(wh, "_gh_api", lambda path: None)
        result = fetch_runs_by_workflow()
        assert len(result) == 4
        for info in result.values():
            assert info["fetch_ok"] is False
            assert info["runs"] == []

    def test_marks_fetch_success(self, monkeypatch):
        monkeypatch.setattr(wh, "_gh_api", lambda path: {"workflow_runs": [
            _run(1, "success", "2026-06-17T14:00:00Z"),
        ]})
        result = fetch_runs_by_workflow()
        for info in result.values():
            assert info["fetch_ok"] is True
            assert len(info["runs"]) == 1


class TestBuildWorkflowIssueBody:
    def test_body_has_workflow_run_url_and_autoclose_note(self):
        verdict = classify_workflow_run("voice-regression", "voice-regression.yml", VR_RED_RUNS, now=NOW)
        body = build_workflow_issue_body(verdict)
        assert "voice-regression" in body
        assert "/27624430282" in body
        assert "auto-close" in body.lower()
        assert "self-heal" in body.lower()

    def test_title_prefix_constant(self):
        assert TITLE_PREFIX == "Workflow failing: "

    def test_failing_conclusions_cover_the_three_red_states(self):
        assert FAILING_CONCLUSIONS == frozenset({"failure", "timed_out", "startup_failure"})
