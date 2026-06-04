"""Tests for the daily source-health sentinel.

Philosophy: every failing source is OUR problem, because every failure is a gap
in the product (a tweet we can't make). The sentinel does NOT decide whether a
failure is "worth" an issue — if a source is failing, it gets an issue. The
upstream/ours classification survives only as a LABEL that tells the operator the
right fix (patch our code vs find an alternate feed because NASA is down). Issues
auto-close when the source recovers, so the open-issues list is a self-maintaining
view of what is currently broken.
"""

from datetime import datetime, timezone

from scripts.source_health_sentinel import (
    classify_error,
    classify_source,
    plan_issue_actions,
    run_sentinel,
)

NOW = datetime(2026, 6, 4, 18, 0, 0, tzinfo=timezone.utc)


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
