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
    YIELD_WATCH_MARKER,
    build_issue_body,
    build_yield_watch_body,
    classify_error,
    classify_source,
    parse_served_via,
    plan_issue_actions,
    plan_yield_watch_action,
    run_sentinel,
    yield_watch_sources,
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


def _yield_src(statuses, *, observed=0):
    return {
        "success": statuses.count("success"),
        "failed": statuses.count("failed"),
        "degraded": statuses.count("degraded"),
        "skipped": statuses.count("skipped"),
        "total_observed": observed,
        "last_success_ts": "2026-06-04T17:00:00Z",
        "runs": [{"status": status} for status in statuses],
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


class TestYieldWatch:
    def test_yield_watch_flags_zero_observed_success_source(self):
        watched = yield_watch_sources({
            "gdacs": _yield_src(["success"] * 10, observed=0),
            "co2": _yield_src(["success"] * 10, observed=42),
        })

        assert [row["source"] for row in watched] == ["gdacs"]

    def test_yield_watch_ignores_allowlisted(self):
        watched = yield_watch_sources({
            "synthesis_fire_drought_heat": _yield_src(["success"] * 10, observed=0),
        })

        assert watched == []

    def test_yield_watch_ignores_copernicus_ems_quiet_window(self):
        watched = yield_watch_sources({
            "copernicus_ems": _yield_src(["success"] * 10, observed=0),
        })

        assert watched == []

    def test_yield_watch_requires_full_window(self):
        watched = yield_watch_sources({
            "gdacs": _yield_src(["success"] * 9, observed=0),
        })

        assert watched == []

    def test_yield_watch_digest_action_lifecycle(self):
        watched = yield_watch_sources({
            "gdacs": _yield_src(["success"] * 10, observed=0),
        })
        body = build_yield_watch_body(watched)

        assert YIELD_WATCH_MARKER in body
        assert plan_yield_watch_action(watched, None)["action"] == "create_yield_watch"
        assert plan_yield_watch_action(watched, {"number": 9, "body": body, "labels": [LABEL, "unknown"]}) is None
        stale = plan_yield_watch_action(watched, {"number": 9, "body": body, "labels": [LABEL, "external"]})
        assert stale["action"] == "update_yield_watch"
        assert stale["remove_labels"] == ["external"]
        assert plan_yield_watch_action([], {"number": 9, "body": body, "labels": [LABEL, "unknown"]}) == {
            "action": "close_yield_watch",
            "number": 9,
        }


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


class TestServedViaBackupLeg:
    """R-01: a primary served by a redundancy witness records `served via <leg>`.

    Parity contract: dashboard/lib/source-health.js parseServedVia +
    classifyHealth must agree with these outcomes on the same fixture (see
    dashboard/tests/source-health.test.js `served via backup leg`).
    """

    def test_parse_served_via_extracts_leg(self):
        assert parse_served_via("served via noaa_hms") == "noaa_hms"
        assert parse_served_via("served via open_meteo_flood") == "open_meteo_flood"

    def test_parse_served_via_none_for_real_errors(self):
        assert parse_served_via(None) is None
        assert parse_served_via("") is None
        assert parse_served_via("503 Server Error") is None

    def test_degraded_when_served_via_backup_leg(self):
        # Primary down, witness served every recent cycle: status="degraded",
        # diagnostic "served via noaa_hms", NO hard failures. Must be degraded
        # (not healthy, not failing) and surface the leg.
        v = classify_source(
            "firms",
            _src(statuses=["degraded"] * 5, last_error="served via noaa_hms"),
            now=NOW,
        )
        assert v["category"] == "degraded"
        assert v["served_via"] == "noaa_hms"

    def test_healthy_when_primary_serves(self):
        # Primary healthy every recent cycle: no served_via, classified healthy.
        v = classify_source("firms", _src(statuses=["success"] * 5), now=NOW)
        assert v["category"] == "healthy"
        assert v["served_via"] is None

    def test_served_via_cleared_when_recovered_to_healthy(self):
        # A stale "served via" diagnostic must NOT show once the primary recovered
        # (all recent success -> healthy -> served_via cleared).
        v = classify_source(
            "firms",
            _src(statuses=["success"] * 5, last_error="served via noaa_hms"),
            now=NOW,
        )
        assert v["category"] == "healthy"
        assert v["served_via"] is None

    def test_backup_served_does_not_open_issue(self):
        report = run_sentinel({"firms": _src(statuses=["degraded"] * 5, last_error="served via noaa_hms")})
        assert report["has_failures"] is False
        assert [v["source"] for v in report["degraded"]] == ["firms"]


# ---------------------------------------------------------------------------
# Task 5 — coverage_watch classifier
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import coverage_watch  # noqa: E402


def _log(country: str, continent: str, n: int, cls: str = "heat") -> list[dict]:
    return [
        {"cls": cls, "event_id": f"{country}-{i}", "country": country,
         "continent": continent, "date": "2026-06-25"}
        for i in range(n)
    ]


def _alerts() -> list[dict]:
    return [{"id": "r", "mode": "alerts", "started_at": "2026-06-25T00:00:00Z"}]


class TestCoverageWatch:
    NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)

    def test_us_only_flags_mono_regional(self):
        out = coverage_watch(_log("United States", "North America", 22), _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "mono_regional"
        assert out[0]["dominant"] in ("United States", "North America") and out[0]["share"] >= 0.85

    def test_diversified_does_not_flag(self):
        log = (
            _log("United States", "North America", 8)
            + _log("Spain", "Europe", 6)
            + _log("India", "Asia", 4)
            + _log("Brazil", "South America", 4)
        )
        assert coverage_watch(log, _alerts(), now=self.NOW) == []

    def test_thin_window_is_insufficient_not_silent(self):
        out = coverage_watch(_log("United States", "North America", 10), _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "insufficient_data"

    def test_no_data_while_drafting_flags(self):
        out = coverage_watch([], _alerts(), now=self.NOW)
        assert len(out) == 1 and out[0]["kind"] == "no_data"

    def test_no_data_quiet_bot_does_not_flag(self):
        assert coverage_watch([], [], now=self.NOW) == []


# ---------------------------------------------------------------------------
# Task 6 — coverage-watch issue reconciliation
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import (  # noqa: E402
    build_coverage_watch_body,
    plan_coverage_watch_action,
    COVERAGE_WATCH_MARKER,
)


class TestCoverageWatchIssue:
    MONO = [{"cls": "heat", "kind": "mono_regional", "dominant": "United States",
             "share": 0.95, "events": 22, "distribution": {"United States": 21, "Spain": 1}}]
    INSUF = [{"cls": "heat", "kind": "insufficient_data", "dominant": "—",
              "share": 0.0, "events": 10, "distribution": {}}]

    def test_body_has_marker_and_share(self):
        body = build_coverage_watch_body(self.MONO)
        assert COVERAGE_WATCH_MARKER in body and "United States" in body and "95" in body

    def test_create_when_mono_and_no_issue(self):
        assert plan_coverage_watch_action(self.MONO, None)["action"] == "create_coverage_watch"

    def test_insufficient_data_does_not_open_issue(self):
        assert plan_coverage_watch_action(self.INSUF, None) is None

    def test_close_when_clear_and_issue_open(self):
        assert plan_coverage_watch_action([], {"number": 7, "body": COVERAGE_WATCH_MARKER}) == {
            "action": "close_coverage_watch", "number": 7}

    def test_noop_when_clear_no_issue(self):
        assert plan_coverage_watch_action([], None) is None


# ---------------------------------------------------------------------------
# Writer watch — budget_exhausted kills while runs stay green (2026-07-03 class)
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import (  # noqa: E402
    WRITER_WATCH_MARKER,
    build_writer_watch_body,
    plan_writer_watch_action,
    writer_watch,
)


def _budget_supp(ts: str, stage: str = "budget_exhausted") -> dict:
    return {"id": f"supp_{ts}", "ts": ts, "stage": stage}


class TestWriterWatch:
    NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    ALERTS = [{"mode": "alerts"}]

    def test_flags_recent_budget_exhausted(self):
        supps = [
            _budget_supp("2026-07-04T10:00:00Z"),
            _budget_supp("2026-07-04T11:00:00Z"),
        ]
        assert writer_watch(supps, self.ALERTS, now=self.NOW) == [{
            "kind": "budget_exhausted",
            "count": 2,
            "last_ts": "2026-07-04T11:00:00Z",
        }]

    def test_ignores_old_rows_and_other_stages(self):
        supps = [
            _budget_supp("2026-07-02T10:00:00Z"),  # outside the 24h window
            _budget_supp("2026-07-04T10:00:00Z", stage="critic"),
        ]
        assert writer_watch(supps, self.ALERTS, now=self.NOW) == []

    def test_silent_when_not_drafting(self):
        # a paused bot must not false-alarm on stale rows
        supps = [_budget_supp("2026-07-04T10:00:00Z")]
        assert writer_watch(supps, [], now=self.NOW) == []

    def test_empty_and_malformed_inputs(self):
        assert writer_watch(None, self.ALERTS, now=self.NOW) == []
        assert writer_watch(["junk", {"ts": None}], self.ALERTS, now=self.NOW) == []

    def test_malformed_budget_row_ts_is_skipped_not_recent(self):
        # Lexically, "not-a-date" > "2026-..." — a string compare would count it
        # as recent and false-open (or pin) the issue. It must be SKIPPED.
        supps = [
            _budget_supp("not-a-date"),
            _budget_supp(""),
            _budget_supp("2026-13-99T99:99:99Z"),
            _budget_supp("2026-02-31T00:00:00Z"),  # invalid calendar date
        ]
        assert writer_watch(supps, self.ALERTS, now=self.NOW) == []
        # ...and a valid recent row still fires alongside junk.
        supps.append(_budget_supp("2026-07-04T11:00:00Z"))
        out = writer_watch(supps, self.ALERTS, now=self.NOW)
        assert out[0]["count"] == 1

    def test_incident_replay_2026_07_03(self):
        # The real incident shape: a morning of budget_exhausted kills across
        # green alerts runs -> exactly one loud finding.
        supps = [
            _budget_supp(f"2026-07-04T0{h}:15:00.123456Z") for h in range(6, 10)
        ]
        out = writer_watch(supps, self.ALERTS, now=self.NOW)
        assert len(out) == 1
        assert out[0]["count"] == 4
        assert out[0]["last_ts"].startswith("2026-07-04T09:15")


class TestWriterWatchIssue:
    FINDING = [{"kind": "budget_exhausted", "count": 3, "last_ts": "2026-07-04T11:00:00Z"}]

    def test_body_names_the_failure_and_the_fix(self):
        body = build_writer_watch_body(self.FINDING)
        assert WRITER_WATCH_MARKER in body
        assert "Anthropic" in body
        assert "credit" in body.lower()
        assert "3 draft(s)" in body

    def test_create_when_finding_and_no_issue(self):
        action = plan_writer_watch_action(self.FINDING, None)
        assert action["action"] == "create_writer_watch"
        assert "ours" in action["labels"]

    def test_update_when_body_changed(self):
        stale = {"number": 9, "body": WRITER_WATCH_MARKER + "\nold"}
        action = plan_writer_watch_action(self.FINDING, stale)
        assert action["action"] == "update_writer_watch"
        assert action["number"] == 9

    def test_close_when_clear_and_issue_open(self):
        assert plan_writer_watch_action([], {"number": 4, "body": WRITER_WATCH_MARKER}) == {
            "action": "close_writer_watch", "number": 4}

    def test_noop_when_clear_no_issue(self):
        assert plan_writer_watch_action([], None) is None


# ---------------------------------------------------------------------------
# Queue watch — human-gated drafts aging unreviewed (2026-06-29→07-03 class)
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import (  # noqa: E402
    QUEUE_WATCH_MARKER,
    build_queue_watch_body,
    plan_queue_watch_action,
    queue_watch,
)


def _draft(created_at, *, mode="manual_only", status="pending", dtype="regional_anomaly"):
    return {
        "id": f"draft_{created_at}",
        "status": status,
        "type": dtype,
        "created_at": created_at,
        "approval_policy": {"mode": mode},
    }


class TestQueueWatch:
    NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_flags_aged_manual_draft(self):
        drafts = [_draft("2026-07-03T06:00:00Z", dtype="all_time_high")]
        out = queue_watch(drafts, now=self.NOW)
        assert out == [{
            "kind": "stale_reviews",
            "count": 1,
            "oldest_age_h": 30,
            "types": {"all_time_high": 1},
        }]

    def test_fresh_posted_and_auto_owned_do_not_count(self):
        auto_owned = _draft("2026-07-01T06:00:00Z", mode="armed_auto")
        auto_owned["approval_mode"] = "auto"
        auto_owned["auto_approve_at"] = "2026-07-04T13:00:00Z"
        drafts = [
            _draft("2026-07-04T06:00:00Z"),                      # fresh (6h)
            _draft("2026-07-01T06:00:00Z", status="posted"),     # not pending
            auto_owned,                                          # auto path owns it
        ]
        assert queue_watch(drafts, now=self.NOW) == []

    def test_live_policy_auto_draft_is_auto_owned(self):
        # The legacy armed_auto path sets approval_mode="policy_auto" +
        # auto_approve_at (draft_save.py); posting still owns it (codex r2 P2).
        d = _draft("2026-07-01T06:00:00Z", mode="armed_auto")
        d["approval_mode"] = "policy_auto"
        d["auto_approve_at"] = "2026-07-04T13:00:00Z"
        assert queue_watch([d], now=self.NOW) == []

    def test_failed_closed_armed_auto_policy_counts_as_human_gated(self):
        # approval_policy.mode is only the RECOMMENDATION. A draft whose policy
        # says armed_auto but that failed closed to manual (no critic PASS, or
        # demoted: approval_mode="manual", no auto_approve_at) is human-gated —
        # excluding it would recreate the silent-aging blind spot (codex P1).
        d = _draft("2026-07-01T06:00:00Z", mode="armed_auto")
        assert d.get("approval_mode") is None  # fixture models the demoted shape
        out = queue_watch([d], now=self.NOW)
        assert out[0]["count"] == 1

    def test_suggested_auto_and_missing_mode_count_as_human_gated(self):
        drafts = [
            _draft("2026-07-02T06:00:00Z", mode="suggested_auto"),
            {"status": "pending", "type": "fire", "created_at": "2026-07-02T06:00:00Z"},
        ]
        out = queue_watch(drafts, now=self.NOW)
        assert out[0]["count"] == 2
        assert out[0]["types"] == {"regional_anomaly": 1, "fire": 1}

    def test_malformed_created_at_skipped(self):
        drafts = [
            _draft("not-a-date"),
            _draft(""),
            _draft("2026-02-31T00:00:00Z"),  # invalid calendar date
        ]
        assert queue_watch(drafts, now=self.NOW) == []
        assert queue_watch(None, now=self.NOW) == []

    def test_incident_replay_prudhoe_class(self):
        # The real shape: a strong record + a marine heatwave sitting for days
        # while an old France reganom rots — one loud finding, typed.
        drafts = [
            _draft("2026-07-02T04:00:00Z", dtype="all_time_high"),
            _draft("2026-07-02T10:00:00Z", dtype="marine_heatwave"),
            _draft("2026-06-28T18:00:00Z", dtype="regional_anomaly"),
        ]
        out = queue_watch(drafts, now=self.NOW)
        assert out[0]["count"] == 3
        assert out[0]["oldest_age_h"] == 138
        assert out[0]["types"]["all_time_high"] == 1


class TestQueueWatchIssue:
    FINDING = [{"kind": "stale_reviews", "count": 2, "oldest_age_h": 30,
                "types": {"all_time_high": 1, "marine_heatwave": 1}}]

    def test_body_names_counts_types_and_ttl(self):
        body = build_queue_watch_body(self.FINDING)
        assert QUEUE_WATCH_MARKER in body
        assert "2 pending draft(s)" in body
        assert "all_time_high:1" in body
        assert "TTL" in body

    def test_create_update_close_noop(self):
        assert plan_queue_watch_action(self.FINDING, None)["action"] == "create_queue_watch"
        stale = {"number": 3, "body": QUEUE_WATCH_MARKER + "\nold"}
        assert plan_queue_watch_action(self.FINDING, stale)["action"] == "update_queue_watch"
        assert plan_queue_watch_action([], {"number": 3, "body": QUEUE_WATCH_MARKER}) == {
            "action": "close_queue_watch", "number": 3}
        assert plan_queue_watch_action([], None) is None


# ---------------------------------------------------------------------------
# Editor brief — ranked needs-you-now view of the pending queue
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import (  # noqa: E402
    EDITOR_BRIEF_MARKER,
    EDITOR_BRIEF_MAX_ROWS,
    build_editor_brief_body,
    editor_brief,
    plan_editor_brief_action,
)


class TestEditorBrief:
    def _draft(self, *, hours_old=2.0, dtype="fire", score=70, status="pending",
               tweet_date=None, auto=False, text="draft text"):
        now = datetime.now(timezone.utc)
        d = {
            "id": f"d_{dtype}_{hours_old}",
            "status": status,
            "type": dtype,
            "created_at": (now - timedelta(hours=hours_old)).isoformat().replace("+00:00", "Z"),
            "score": {"total": score},
            "text": text,
        }
        if tweet_date:
            d["tweet_date"] = tweet_date
        if auto:
            d["approval_mode"] = "auto"
            d["auto_approve_at"] = now.isoformat().replace("+00:00", "Z")
        return d

    def test_ranks_closing_forecast_first_then_aging_then_score(self):
        today = datetime.now(timezone.utc).date().isoformat()
        drafts = [
            self._draft(dtype="all_time_high", score=90),
            self._draft(dtype="fire", hours_old=30.0, score=60),
            self._draft(dtype="absolute_extreme", score=50, tweet_date=today),
        ]
        findings = editor_brief(drafts, now=datetime.now(timezone.utc))
        assert [f["type"] for f in findings] == ["absolute_extreme", "fire", "all_time_high"]
        assert findings[0]["closing"] and findings[1]["urgent"]

    def test_excludes_auto_owned_and_non_pending(self):
        drafts = [self._draft(auto=True), self._draft(status="posted")]
        assert editor_brief(drafts, now=datetime.now(timezone.utc)) == []

    def test_empty_queue_returns_empty(self):
        assert editor_brief([], now=datetime.now(timezone.utc)) == []

    def test_body_sections_and_cap(self):
        drafts = [self._draft(dtype=f"t{i}", score=50 + i) for i in range(12)]
        findings = editor_brief(drafts, now=datetime.now(timezone.utc))
        body = build_editor_brief_body(findings)
        assert EDITOR_BRIEF_MARKER in body
        assert "more on the dashboard" in body
        assert body.count("score ") == EDITOR_BRIEF_MAX_ROWS

    def test_body_stable_across_successive_hours(self):
        """codex P2: the body must render identically hour-to-hour for an
        unchanged pending queue. Rendering an hourly-recomputed age counter
        (e.g. '12h old' -> '13h old') made plan_editor_brief_action's
        body-diff update check fire every hour — exactly the flap the no-flap
        Global Constraint forbids. ``t`` is pinned to real now() so neither
        draft (2h/30h old) crosses the 24h urgency boundary between the two
        renders (2->3h and 30->31h)."""
        t = datetime.now(timezone.utc)
        drafts = [
            {
                "id": "d_fire_2h",
                "status": "pending",
                "type": "fire",
                "created_at": (t - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                "score": {"total": 70},
                "text": "draft text",
            },
            {
                "id": "d_heat_30h",
                "status": "pending",
                "type": "all_time_high",
                "created_at": (t - timedelta(hours=30)).isoformat().replace("+00:00", "Z"),
                "score": {"total": 60},
                "text": "draft text",
            },
        ]
        body_now = build_editor_brief_body(editor_brief(drafts, now=t))
        body_later = build_editor_brief_body(editor_brief(drafts, now=t + timedelta(hours=1)))
        assert body_now == body_later


class TestEditorBriefIssue:
    FINDING = [{"id": "d_fire_2.0", "type": "fire", "age_h": 30, "score": 60,
                "tweet_date": None, "urgent": True, "closing": False,
                "preview": "draft text"}]

    def test_create_update_close_noop(self):
        assert plan_editor_brief_action(self.FINDING, None)["action"] == "create_editor_brief"
        stale = {"number": 5, "body": EDITOR_BRIEF_MARKER + "\nold"}
        assert plan_editor_brief_action(self.FINDING, stale)["action"] == "update_editor_brief"
        assert plan_editor_brief_action([], {"number": 5, "body": EDITOR_BRIEF_MARKER}) == {
            "action": "close_editor_brief", "number": 5}
        assert plan_editor_brief_action([], None) is None

    def test_noop_when_body_unchanged(self):
        body = build_editor_brief_body(self.FINDING)
        current = {"number": 5, "body": body}
        assert plan_editor_brief_action(self.FINDING, current) is None


# ---------------------------------------------------------------------------
# News-gap watch — the Bet A phase 0 miss-detector
# ---------------------------------------------------------------------------
from scripts.source_health_sentinel import (  # noqa: E402
    NEWS_GAP_MARKER,
    build_news_gap_body,
    news_gap_watch,
    plan_news_gap_action,
)


def _news_ev(kind, country, name=None, admin1=None, *, confidence="verified",
             window_end=None, headline="ev", sources=("WHO",)):
    from datetime import date as _date
    return {
        "kind": kind,
        "headline": headline,
        "place": {"country": country, "admin1": admin1, "name": name},
        "window_start": (window_end or _date.today().isoformat()),
        "window_end": (window_end or _date.today().isoformat()),
        "impact": [{"claim": "c", "value": 1, "source_name": s,
                    "url": "https://x", "as_of": "d"} for s in sources],
        "confidence": confidence,
    }


class TestNewsGapWatch:
    NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

    def test_europe_heat_deaths_with_no_candidate_flags(self):
        # The incident that motivated Bet A: WHO-verified mortality, nothing
        # detected anywhere -> exactly one finding naming the source.
        ev = _news_ev("heat_mortality", "France", headline="Europe heat deaths",
                      window_end="2026-07-03")
        out = news_gap_watch([ev], [], [], now=self.NOW)
        assert len(out) == 1
        assert out[0]["headline"] == "Europe heat deaths"
        assert out[0]["sources"] == ["WHO"]

    def test_matching_heat_candidate_suppresses_the_flag(self):
        ev = _news_ev("heat_mortality", "France", window_end="2026-07-03")
        cand = {"event_id": "reganom_France", "category": "regional_anomaly",
                "type": "regional_anomaly", "city": "", "where": "France (6 sampled cities)",
                "date": "2026-07-03"}
        assert news_gap_watch([ev], [cand], [], now=self.NOW) == []

    def test_colorado_fire_matches_by_state_name(self):
        ev = _news_ev("fire", "United States", name="Knowles", admin1="CO",
                      window_end="2026-07-03")
        cand = {"event_id": "fire_x", "category": "fire", "type": "fire",
                "city": "Grand Junction", "where": "near Grand Junction, Colorado",
                "date": "2026-07-03"}
        assert news_gap_watch([ev], [cand], [], now=self.NOW) == []

    def test_wrong_family_candidate_does_not_suppress(self):
        # A France PRECIP candidate must not swallow a heat-mortality gap.
        ev = _news_ev("heat_mortality", "France", window_end="2026-07-03")
        cand = {"event_id": "precip_x", "category": "precipitation", "type": "precip",
                "city": "Paris", "where": "Paris, France", "date": "2026-07-03"}
        out = news_gap_watch([ev], [cand], [], now=self.NOW)
        assert len(out) == 1

    def test_pending_or_posted_draft_text_suppresses(self):
        ev = _news_ev("heat_mortality", "France", window_end="2026-07-03")
        draft = {"status": "posted", "type": "regional_anomaly",
                 "text": "Six French cities ran ~12C above their normal... France"}
        assert news_gap_watch([ev], [], [draft], now=self.NOW) == []

    def test_fort_de_france_candidate_does_not_hide_a_france_gap(self):
        # codex P1 regression: substring matching read 'Fort-de-France,
        # Martinique' as covering a France heat-mortality event.
        ev = _news_ev("heat_mortality", "France", window_end="2026-07-03")
        cand = {"event_id": "heat_mq", "category": "heat", "type": "anomaly_hot",
                "city": "Fort-de-France", "where": "Fort-de-France, Martinique",
                "date": "2026-07-03"}
        out = news_gap_watch([ev], [cand], [], now=self.NOW)
        assert len(out) == 1

    def test_unverified_old_and_unmatchable_events_never_flag(self):
        unverified = _news_ev("heat_mortality", "France", confidence="unverified",
                              window_end="2026-07-03")
        old = _news_ev("heat_mortality", "France", window_end="2026-06-20")
        no_tokens = _news_ev("fire", "United States", window_end="2026-07-03")
        assert news_gap_watch([unverified, old, no_tokens], [], [], now=self.NOW) == []

    def test_duplicate_impact_publishers_dedupe_before_the_cap(self):
        # #396: two NIFC impact rows rendered '(per NIFC, NIFC)'. Dedupe is
        # order-preserving and applied before the 3-source cap, so a repeated
        # publisher can't crowd a distinct one out of the cap.
        ev = _news_ev("fire", "United States", name="Pocket", admin1="AZ",
                      window_end="2026-07-03", headline="Pocket fire (AZ)",
                      sources=("NIFC", "NIFC", "InciWeb", "AZ Forestry"))
        out = news_gap_watch([ev], [], [], now=self.NOW)
        assert len(out) == 1
        assert out[0]["sources"] == ["NIFC", "InciWeb", "AZ Forestry"]


class TestNewsGapIssue:
    FINDING = [{"kind": "heat_mortality", "headline": "Europe heat deaths",
                "sources": ["WHO"]}]

    def test_body_names_event_and_source(self):
        body = build_news_gap_body(self.FINDING)
        assert NEWS_GAP_MARKER in body
        assert "Europe heat deaths" in body and "WHO" in body

    def test_body_dedupes_repeated_source_names(self):
        # #396 guard at the render layer too: a finding that arrives with
        # duplicate names must still name each publisher once.
        body = build_news_gap_body([{"kind": "fire", "headline": "Pocket fire (AZ)",
                                     "sources": ["NIFC", "NIFC"]}])
        assert "(per NIFC)" in body
        assert "NIFC, NIFC" not in body

    def test_lifecycle_create_update_close_noop(self):
        assert plan_news_gap_action(self.FINDING, None)["action"] == "create_news_gap"
        stale = {"number": 5, "body": NEWS_GAP_MARKER + "\nold"}
        assert plan_news_gap_action(self.FINDING, stale)["action"] == "update_news_gap"
        assert plan_news_gap_action([], {"number": 5, "body": NEWS_GAP_MARKER}) == {
            "action": "close_news_gap", "number": 5}
        assert plan_news_gap_action([], None) is None
