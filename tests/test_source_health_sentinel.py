"""Tests for the daily source-health sentinel classifier.

The sentinel reads the gist source_health and decides, per source, whether a
failure is UPSTREAM (NASA/gov/network — self-heals, stay silent) or OUR_BUG
(code error, auth/token, moved endpoint, or an abnormally long outage — open an
issue and ping the operator). The whole point is to stop crying wolf on NASA
flakiness while never missing a failure that is actually ours to fix.
"""

from scripts.source_health_sentinel import (
    classify_error,
    classify_source,
    run_sentinel,
)


def _src(*, statuses, last_error="", success=None, failed=None):
    """Build a gist-shaped source_health entry from a list of run statuses."""
    runs = [{"status": s} for s in statuses]
    active = [s for s in statuses if s != "skipped"]
    return {
        "success": success if success is not None else active.count("success"),
        "failed": failed if failed is not None else active.count("failed"),
        "degraded": active.count("degraded"),
        "skipped": statuses.count("skipped"),
        "runs": runs,
        "last_error": last_error,
    }


class TestClassifyError:
    def test_real_upstream_strings_from_production(self):
        upstream = [
            "GPM IMERG fetch hit 3 repeated ReadTimeout failures for 2026-06-03; "
            "first error: ReadTimeout: HTTPSConnectionPool(host='gpm1.gesdisc...",
            "Ice mass fetch failed for antarctica: 502 Server Error: Bad Gateway "
            "for url: https://archive.podaac.earthdata.nasa.gov/...",
            "coral_dhw fetch failed: 403 Client Error: Forbidden for url: "
            "https://coralreefwatch.noaa.gov/...",
            "FIRMS fetch failed: HTTPSConnectionPool(host='firms.modaps.eosdis."
            "nasa.gov', port=443): Max retries exceeded",
            "Ocean SST fetch failed: HTTPSConnectionPool(host='climatereanalyzer."
            "org', port=443): Max retries",
            "503 Service Unavailable",
            "ConnectionError: [Errno 101] Network is unreachable",
            "429 Too Many Requests",
        ]
        for err in upstream:
            assert classify_error(err) == "upstream", err

    def test_our_bug_strings(self):
        our_bug = [
            "FIRMS fetch failed: 401 Client Error: Unauthorized for url: ...",
            "EARTHDATA_TOKEN appears to have expired",
            "KeyError: 'temperature'",
            "AttributeError: 'NoneType' object has no attribute 'get'",
            "ValueError: could not convert string to float: 'n/a'",
            "TypeError: unsupported operand type(s)",
            "open_meteo schema drift: missing required field(s): latitude",
            "json.decoder.JSONDecodeError: Expecting value: line 1 column 1",
        ]
        for err in our_bug:
            assert classify_error(err) == "our_bug", err

    def test_sustained_404_or_410_is_our_bug_moved_endpoint(self):
        assert classify_error("404 Client Error: Not Found for url: ...") == "our_bug"
        assert classify_error("410 Client Error: Gone for url: ...") == "our_bug"

    def test_no_error_is_none(self):
        assert classify_error("") == "none"
        assert classify_error("-") == "none"
        assert classify_error(None) == "none"

    def test_unrecognized_nonempty_error_is_unknown(self):
        # An unmatched, non-empty error is suspicious — the sentinel escalates
        # unknowns rather than silently filing them as upstream.
        assert classify_error("something nobody has ever seen before") == "unknown"


class TestClassifySource:
    def test_healthy_source_not_flagged(self):
        s = _src(statuses=["success"] * 5, last_error="")
        assert classify_source("co2", s)["category"] == "healthy"

    def test_cadence_skips_only_is_idle_not_flagged(self):
        # ice_mass on a non-Monday: recent rows are all skips. Must NOT alarm.
        s = _src(statuses=["skipped"] * 6, last_error="")
        assert classify_source("ice_mass_antarctica", s)["category"] == "idle"

    def test_recently_failing_upstream_is_upstream(self):
        s = _src(
            statuses=["success", "failed", "failed", "failed"],
            last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
        )
        assert classify_source("ice_mass_greenland", s)["category"] == "upstream"

    def test_recently_failing_our_bug_is_flagged(self):
        s = _src(
            statuses=["success", "failed", "failed", "failed"],
            last_error="KeyError: 'temperature'",
        )
        v = classify_source("open_meteo_extreme_signals", s)
        assert v["category"] == "our_bug"

    def test_intermittent_upstream_stays_silent_not_escalated(self):
        # gpm-style: fails a lot but still succeeds sometimes (not a dead source).
        s = _src(
            statuses=["success", "failed", "failed", "success", "failed", "failed"],
            last_error="GPM IMERG fetch hit 3 repeated ReadTimeout failures",
        )
        assert classify_source("gpm_imerg", s)["category"] == "upstream"

    def test_upstream_but_dead_too_long_escalates(self):
        # Even an upstream error, if the source is fully dark for many consecutive
        # active attempts, likely means a moved endpoint / expired credential.
        s = _src(
            statuses=["failed"] * 14,
            last_error="403 Client Error: Forbidden for url: ...",
        )
        v = classify_source("jtwc", s, long_failure_threshold=10)
        assert v["category"] == "our_bug"
        assert "long" in v["reason"].lower() or "consecutive" in v["reason"].lower()

    def test_sustained_hard_upstream_never_escalates(self):
        # NASA can 503 / ReadTimeout for days. No duration turns a server outage
        # into our bug. Regression: the sentinel's first live run escalated a
        # 10-deep run of HTTP 503 from GES DISC as a "moved endpoint" (issue #174).
        for err in (
            "GPM IMERG fetch hit 3 repeated HTTP 503 failures; first error: "
            "HTTP 503 from https://gpm1.gesdisc.eosdis.nasa.gov/...",
            "Ice mass fetch failed: 502 Server Error: Bad Gateway",
            "ReadTimeout: HTTPSConnectionPool(host='gpm1.gesdisc...', port=443)",
        ):
            s = _src(statuses=["failed"] * 14, last_error=err)
            v = classify_source("gpm_imerg", s, long_failure_threshold=10)
            assert v["category"] == "upstream", err

    def test_intermittent_flaky_above_half_not_escalated(self):
        # Mostly-succeeding source with the odd failure is not "failing".
        s = _src(
            statuses=["success", "success", "failed", "success", "success"],
            last_error="503 Service Unavailable",
        )
        assert classify_source("nhc", s)["category"] in ("healthy", "degraded")


class TestRunSentinel:
    def test_todays_real_failures_are_a_silent_day(self):
        # The exact production snapshot: gpm ReadTimeout + ice_mass 502 + gov 403s.
        # Every one is upstream → has_our_bugs must be False (no ping).
        source_health = {
            "gpm_imerg": _src(
                statuses=["success", "failed", "failed", "failed", "failed", "failed"],
                last_error="GPM IMERG fetch hit 3 repeated ReadTimeout failures",
            ),
            "ice_mass_antarctica": _src(
                statuses=["success", "failed", "failed", "skipped", "skipped"],
                last_error="Ice mass fetch failed for antarctica: 502 Server Error: Bad Gateway",
            ),
            "coral_dhw": _src(
                statuses=["success"] * 4 + ["failed"],
                last_error="coral_dhw fetch failed: 403 Client Error: Forbidden",
            ),
            "co2": _src(statuses=["success"] * 5, last_error=""),
        }
        report = run_sentinel(source_health)
        assert report["has_our_bugs"] is False
        flagged = {v["source"] for v in report["our_bug"]}
        assert flagged == set()

    def test_a_real_bug_is_escalated_and_pings(self):
        source_health = {
            "co2": _src(statuses=["success"] * 5, last_error=""),
            "open_meteo_extreme_signals": _src(
                statuses=["success", "failed", "failed", "failed"],
                last_error="AttributeError: 'NoneType' object has no attribute 'get'",
            ),
        }
        report = run_sentinel(source_health)
        assert report["has_our_bugs"] is True
        flagged = {v["source"] for v in report["our_bug"]}
        assert flagged == {"open_meteo_extreme_signals"}
