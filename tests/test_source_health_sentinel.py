"""Tests for the daily source-health sentinel classifier.

The sentinel reads the gist source_health and decides, per source, whether a
failure is UPSTREAM (NASA/gov/network — transient, self-heals, stay silent) or
OUR_BUG (code error, auth/token, moved endpoint, OR an outage that has lasted a
significant length of time — open an issue and ping). "Significant length" is
measured in wall-clock days since the last success (cadence-independent), not a
raw consecutive-failure count.
"""

from datetime import datetime, timezone

from scripts.source_health_sentinel import (
    classify_error,
    classify_source,
    run_sentinel,
)

NOW = datetime(2026, 6, 4, 18, 0, 0, tzinfo=timezone.utc)
RECENT = "2026-06-04T17:00:00Z"        # ~1h ago — a transient blip
ONE_DAY_AGO = "2026-06-03T18:00:00Z"   # transient outage (< OUTAGE_DAYS)
FIVE_DAYS_AGO = "2026-05-30T18:00:00Z"  # sustained outage (>= OUTAGE_DAYS)


def _src(*, statuses, last_error="", last_success_ts=RECENT, success=None, failed=None):
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
        "last_success_ts": last_success_ts,
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
        assert classify_error("something nobody has ever seen before") == "unknown"


class TestClassifySource:
    def test_healthy_source_not_flagged(self):
        s = _src(statuses=["success"] * 5)
        assert classify_source("co2", s, now=NOW)["category"] == "healthy"

    def test_cadence_skips_only_is_idle(self):
        # ice_mass on a non-Monday: recent rows are all skips. Must NOT alarm.
        s = _src(statuses=["skipped"] * 6, last_success_ts=None)
        assert classify_source("ice_mass_antarctica", s, now=NOW)["category"] == "idle"

    def test_transient_upstream_stays_silent(self):
        # Failing now, but succeeded a day ago — a transient blip, self-heals.
        s = _src(
            statuses=["success", "failed", "failed", "failed"],
            last_error="Ice mass fetch failed: 502 Server Error: Bad Gateway",
            last_success_ts=ONE_DAY_AGO,
        )
        assert classify_source("ice_mass_greenland", s, now=NOW)["category"] == "upstream"

    def test_transient_hard_upstream_503_stays_silent(self):
        # The original false positive (#174): a SHORT 503 stretch must NOT escalate.
        s = _src(
            statuses=["failed"] * 6,
            last_error="GPM IMERG fetch hit 3 repeated HTTP 503 failures",
            last_success_ts=ONE_DAY_AGO,
        )
        assert classify_source("gpm_imerg", s, now=NOW)["category"] == "upstream"

    def test_recently_failing_our_bug_escalates(self):
        s = _src(
            statuses=["success", "failed", "failed", "failed"],
            last_error="KeyError: 'temperature'",
        )
        assert classify_source("open_meteo_extreme_signals", s, now=NOW)["category"] == "our_bug"

    def test_sustained_hard_upstream_escalates(self):
        # The gap: a hard-upstream outage (503 / 502 / ReadTimeout) that persists
        # for a significant length of time IS ours to investigate — a moved or
        # decommissioned endpoint, or a persistently rejected request — not
        # silent forever. (Reverses the wrong assertion shipped in 0.9.12.1.)
        for err in (
            "GPM IMERG fetch hit 3 repeated HTTP 503 failures; first error: "
            "HTTP 503 from https://gpm1.gesdisc.eosdis.nasa.gov/...",
            "Ice mass fetch failed: 502 Server Error: Bad Gateway",
            "ReadTimeout: HTTPSConnectionPool(host='gpm1.gesdisc...', port=443)",
        ):
            s = _src(statuses=["failed"] * 8, last_error=err, last_success_ts=FIVE_DAYS_AGO)
            v = classify_source("gpm_imerg", s, now=NOW, outage_days=3)
            assert v["category"] == "our_bug", err
            assert "day" in v["reason"].lower()

    def test_sustained_soft_upstream_403_escalates(self):
        s = _src(
            statuses=["failed"] * 8,
            last_error="403 Client Error: Forbidden for url: ...",
            last_success_ts=FIVE_DAYS_AGO,
        )
        assert classify_source("jtwc", s, now=NOW, outage_days=3)["category"] == "our_bug"

    def test_never_succeeded_and_failing_escalates(self):
        # A source that has never once succeeded and is failing is worth a look
        # regardless of error class — it has never worked.
        s = _src(statuses=["failed"] * 4, last_error="503 Service Unavailable", last_success_ts=None)
        assert classify_source("new_source", s, now=NOW)["category"] == "our_bug"

    def test_intermittent_flaky_above_half_not_escalated(self):
        s = _src(
            statuses=["success", "success", "failed", "success", "success"],
            last_error="503 Service Unavailable",
        )
        assert classify_source("nhc", s, now=NOW)["category"] in ("healthy", "degraded")


class TestRunSentinel:
    def test_todays_real_failures_are_a_silent_day(self):
        # Real production snapshot. gpm last succeeded ~2 days ago (< 3-day
        # threshold), so its sustained 503 stretch is still transient → silent.
        source_health = {
            "gpm_imerg": _src(
                statuses=["failed"] * 6,
                last_error="GPM IMERG fetch hit 3 repeated HTTP 503 failures",
                last_success_ts="2026-06-02T19:50:09Z",
            ),
            "ice_mass_antarctica": _src(
                statuses=["success", "failed", "failed", "skipped", "skipped"],
                last_error="Ice mass fetch failed for antarctica: 502 Server Error: Bad Gateway",
                last_success_ts="2026-06-02T12:00:00Z",
            ),
            "coral_dhw": _src(
                statuses=["success"] * 4 + ["failed"],
                last_error="coral_dhw fetch failed: 403 Client Error: Forbidden",
            ),
            "co2": _src(statuses=["success"] * 5),
        }
        report = run_sentinel(source_health, now=NOW, outage_days=3)
        assert report["has_our_bugs"] is False
        assert {v["source"] for v in report["our_bug"]} == set()

    def test_a_real_bug_is_escalated(self):
        source_health = {
            "co2": _src(statuses=["success"] * 5),
            "open_meteo_extreme_signals": _src(
                statuses=["success", "failed", "failed", "failed"],
                last_error="AttributeError: 'NoneType' object has no attribute 'get'",
            ),
        }
        report = run_sentinel(source_health, now=NOW, outage_days=3)
        assert report["has_our_bugs"] is True
        assert {v["source"] for v in report["our_bug"]} == {"open_meteo_extreme_signals"}

    def test_sustained_outage_is_escalated(self):
        # gpm dark for 5 days on 503s → escalate even though the error is upstream.
        source_health = {
            "gpm_imerg": _src(
                statuses=["failed"] * 12,
                last_error="GPM IMERG fetch hit 3 repeated HTTP 503 failures",
                last_success_ts=FIVE_DAYS_AGO,
            ),
        }
        report = run_sentinel(source_health, now=NOW, outage_days=3)
        assert report["has_our_bugs"] is True
        assert {v["source"] for v in report["our_bug"]} == {"gpm_imerg"}
