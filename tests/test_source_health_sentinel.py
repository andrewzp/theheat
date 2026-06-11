"""Tests for the daily source-health sentinel.

Philosophy: every failing source is OUR problem, because every failure is a gap
in the product (a tweet we can't make). The sentinel does NOT decide whether a
failure is "worth" an issue — if a source is failing, it gets an issue. The
upstream/ours classification survives only as a LABEL that tells the operator the
right fix (patch our code vs find an alternate feed because NASA is down). Issues
auto-close when the source recovers, so the open-issues list is a self-maintaining
view of what is currently broken.
"""

from datetime import datetime, timedelta, timezone

from scripts.source_health_sentinel import (
    LABEL,
    build_issue_body,
    classify_error,
    classify_source,
    plan_issue_actions,
    run_sentinel,
)

NOW = datetime(2026, 6, 4, 18, 0, 0, tzinfo=timezone.utc)
EARTHDATA_403_ERROR = (
    "Ice mass fetch failed: 403 Client Error: Forbidden for url: "
    "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/..."
)
GENERIC_GOV_403_ERROR = (
    "403 Client Error: Forbidden for url: https://www.metoc.navy.mil/jtwc/products/..."
)


def _src(*, statuses, last_error="", last_success_ts="2026-06-04T17:00:00Z"):
    runs = [{"status": s} for s in statuses]
    active = [s for s in statuses if s != "skipped"]
    return {
        "success": active.count("success"),
        "failed": active.count("failed"),
        "degraded": active.count("degraded"),
        "skipped": statuses.count("skipped"),
        "runs": runs,
        "last_error": last_error,
        "last_success_ts": last_success_ts,
    }


def _verdict(source, *, cause="external", error_class="upstream", last_error="503"):
    return {
        "source": source,
        "category": "failing",
        "cause": cause,
        "suggested_action": "do the thing",
        "error_class": error_class,
        "last_error": last_error,
        "last_success_ts": "2026-06-04T17:00:00Z",
        "days_since_success": 0.0,
        "recent_success_rate": 0.0,
    }


class TestClassifyError:
    def test_real_upstream_strings_from_production(self):
        for err in (
            "GPM IMERG fetch hit 3 repeated ReadTimeout failures for 2026-06-03",
            "Ice mass fetch failed: 502 Server Error: Bad Gateway for url: "
            "https://archive.podaac.earthdata.nasa.gov/...",
            "coral_dhw fetch failed: 403 Client Error: Forbidden for url: ...",
            "FIRMS fetch failed: HTTPSConnectionPool(host='firms.modaps.eosdis."
            "nasa.gov', port=443): Max retries exceeded",
            "503 Service Unavailable",
            "ConnectionError: [Errno 101] Network is unreachable",
        ):
            assert classify_error(err) == "upstream", err

    def test_our_bug_strings(self):
        for err in (
            "FIRMS fetch failed: 401 Client Error: Unauthorized",
            "EARTHDATA_TOKEN appears to have expired",
            "KeyError: 'temperature'",
            "AttributeError: 'NoneType' object has no attribute 'get'",
            "ValueError: could not convert string to float",
            "open_meteo schema drift: missing required field(s): latitude",
            "404 Client Error: Not Found for url: ...",
        ):
            assert classify_error(err) == "our_bug", err

    def test_no_error_and_unknown(self):
        assert classify_error("") == "none"
        assert classify_error(None) == "none"
        assert classify_error("something never seen before") == "unknown"

    def test_classifies_earthdata_403_as_our_bug(self):
        assert classify_error(EARTHDATA_403_ERROR) == "our_bug"

    def test_classifies_generic_gov_403_as_upstream(self):
        assert classify_error(GENERIC_GOV_403_ERROR) == "upstream"


class TestClassifySource:
    def test_healthy_not_failing(self):
        v = classify_source("co2", _src(statuses=["success"] * 5), now=NOW)
        assert v["category"] == "healthy"

    def test_cadence_skips_only_is_idle(self):
        v = classify_source(
            "ice_mass_antarctica",
            _src(statuses=["skipped"] * 6, last_success_ts=None),
            now=NOW,
        )
        assert v["category"] == "idle"

    def test_failing_upstream_is_failing_labeled_external(self):
        v = classify_source(
            "ice_mass_greenland",
            _src(
                statuses=["failed", "failed", "failed"],
                last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
            ),
            now=NOW,
        )
        assert v["category"] == "failing"
        assert v["cause"] == "external"

    def test_failing_our_bug_is_failing_labeled_ours(self):
        v = classify_source(
            "open_meteo_extreme_signals",
            _src(
                statuses=["success", "failed", "failed", "failed"],
                last_error="KeyError: 'temperature'",
            ),
            now=NOW,
        )
        assert v["category"] == "failing"
        assert v["cause"] == "ours"

    def test_failing_regardless_of_outage_duration(self):
        # No grace period: a source that is currently failing is an issue whether
        # it broke an hour ago or five days ago. Duration is context, not a gate.
        for ts in ("2026-06-04T17:00:00Z", "2026-05-30T00:00:00Z", None):
            v = classify_source(
                "gpm_imerg",
                _src(
                    statuses=["failed"] * 4,
                    last_error="GPM IMERG fetch hit 3 repeated HTTP 503 failures",
                    last_success_ts=ts,
                ),
                now=NOW,
            )
            assert v["category"] == "failing", ts

    def test_idle_source_with_stale_failures_is_idle_not_failing(self):
        # A low-cadence source (ice_mass: Mondays only) whose recent runs are all
        # cadence skips is IDLE — not "failing" — even if its last actual attempt,
        # days ago and outside the recent window, failed. It is not attempting now,
        # so it is not currently failing. (Regression: the live reconciler flagged
        # ice_mass as failing on 5-day-stale 502s while it sat idle — issues #180/#181.)
        s = _src(
            statuses=["success", "failed", "failed"] + ["skipped"] * 6,
            last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
        )
        assert classify_source("ice_mass_antarctica", s, now=NOW)["category"] == "idle"

    def test_recent_failed_attempt_among_skips_is_failing(self):
        # But if there IS a recent active attempt in the window and it failed, the
        # source is actively failing — a low-cadence source that just attempted
        # and failed still gets an issue.
        s = _src(
            statuses=["skipped", "skipped", "failed", "skipped"],
            last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
        )
        assert classify_source("ice_mass_antarctica", s, now=NOW)["category"] == "failing"

    def test_degraded_mostly_working_is_not_failing(self):
        # A source succeeding the majority of recent attempts is degraded, not
        # failing — it's still producing data, so no issue.
        v = classify_source(
            "nhc",
            _src(
                statuses=["success", "success", "failed", "success", "success"],
                last_error="503 Service Unavailable",
            ),
            now=NOW,
        )
        assert v["category"] == "degraded"

    def test_consistently_degraded_source_is_not_failing(self):
        # A source that runs `degraded` EVERY cycle — no hard failures, just
        # partial data each time (e.g. air_quality losing a rate-limited tail
        # chunk) — is still producing data. It must be `degraded`, not `failing`,
        # even though its clean-success rate is 0%. `failing` requires a hard
        # failure (a run that produced nothing). This mirrors the dashboard's
        # classifyHealth, which already gates `unhealthy` on hard failures.
        # Regression: the sentinel filed a false `failing` issue for air_quality
        # (#201) while the dashboard correctly showed it `degraded`.
        v = classify_source(
            "air_quality",
            _src(
                statuses=["degraded"] * 5,
                last_error="50 air-quality city fetches failed",
                last_success_ts=None,
            ),
            now=NOW,
        )
        assert v["category"] == "degraded"


class TestRunSentinel:
    def test_every_failing_source_is_surfaced(self):
        # The real snapshot: gpm + both ice_mass are failing → ALL get issued,
        # because every failure is a product gap. co2 is healthy → not.
        source_health = {
            "gpm_imerg": _src(
                statuses=["failed"] * 6,
                last_error="GPM IMERG fetch hit 3 repeated HTTP 503 failures",
            ),
            "ice_mass_antarctica": _src(
                statuses=["failed", "failed"],
                last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
            ),
            "ice_mass_greenland": _src(
                statuses=["failed", "failed"],
                last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
            ),
            "co2": _src(statuses=["success"] * 5),
        }
        report = run_sentinel(source_health, now=NOW)
        assert report["has_failures"] is True
        assert {v["source"] for v in report["failing"]} == {
            "gpm_imerg", "ice_mass_antarctica", "ice_mass_greenland"
        }

    def test_all_healthy_is_no_failures(self):
        report = run_sentinel({"co2": _src(statuses=["success"] * 5)}, now=NOW)
        assert report["has_failures"] is False
        assert report["failing"] == []

    def test_sentinel_liveness_flags_stale_alerts_lane(self):
        stale_alerts = (NOW - timedelta(hours=7)).isoformat().replace("+00:00", "Z")
        fresh_auto_publish = (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")

        report = run_sentinel(
            {},
            now=NOW,
            run_history=[
                {"mode": "auto_publish_due", "started_at": fresh_auto_publish},
                {"mode": "alerts", "started_at": stale_alerts},
            ],
        )

        liveness = [v for v in report["failing"] if v["source"] == "_pipeline_liveness"]
        assert len(liveness) == 1
        assert liveness[0]["cause"] == "ours"
        assert "Actions" in build_issue_body(liveness[0])

    def test_sentinel_liveness_quiet_when_fresh(self):
        fresh_alerts = (NOW - timedelta(hours=5, minutes=59)).isoformat().replace("+00:00", "Z")
        fresh_auto_publish = (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")

        report = run_sentinel(
            {},
            now=NOW,
            run_history=[
                {"mode": "auto_publish_due", "started_at": fresh_auto_publish},
                {"mode": "alerts", "started_at": fresh_alerts},
            ],
        )

        assert "_pipeline_liveness" not in {v["source"] for v in report["failing"]}
        assert report["has_failures"] is False


class TestPlanIssueActions:
    def test_creates_issues_for_new_failures(self):
        actions = plan_issue_actions({"a", "b"}, {})
        assert sorted(a["source"] for a in actions if a["action"] == "create") == ["a", "b"]

    def test_closes_issues_for_recovered_sources(self):
        actions = plan_issue_actions({"a"}, {"a": 1, "b": 2})
        closes = [a for a in actions if a["action"] == "close"]
        assert closes == [{"action": "close", "source": "b", "number": 2}]

    def test_create_and_close_together_leaves_still_failing_alone(self):
        actions = plan_issue_actions({"a", "c"}, {"b": 5, "c": 7})
        creates = sorted(a["source"] for a in actions if a["action"] == "create")
        closes = sorted(a["source"] for a in actions if a["action"] == "close")
        assert creates == ["a"]
        assert closes == ["b"]

    def test_nothing_to_do_when_aligned(self):
        assert plan_issue_actions({"a"}, {"a": 1}) == []

    def test_create_action_carries_current_cause_label_and_body(self):
        failing = {"gpm_imerg": _verdict("gpm_imerg", cause="external")}

        actions = plan_issue_actions(failing, {})

        assert actions == [{
            "action": "create",
            "source": "gpm_imerg",
            "labels": [LABEL, "external"],
            "body": build_issue_body(failing["gpm_imerg"]),
        }]

    def test_existing_issue_updates_when_cause_or_body_changes(self):
        current = _verdict(
            "gpm_imerg",
            cause="ours",
            error_class="our_bug",
            last_error="KeyError: 'precipitation'",
        )
        stale = _verdict("gpm_imerg", cause="external", last_error="503")

        actions = plan_issue_actions(
            {"gpm_imerg": current},
            {
                "gpm_imerg": {
                    "number": 42,
                    "labels": [LABEL, "external"],
                    "body": build_issue_body(stale),
                }
            },
        )

        assert actions == [{
            "action": "update",
            "source": "gpm_imerg",
            "number": 42,
            "labels": [LABEL, "ours"],
            "remove_labels": ["external"],
            "body": build_issue_body(current),
        }]
