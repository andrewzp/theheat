"""A3: HMS unpublished-day handling, FIRMS failure classification, and GPM/Earthdata access health.

Invented rows, tokens and run history only. The FIRMS contract (api/area/csv/
MAP_KEY/SOURCE/world/DAY_RANGE) was re-confirmed from the primary FIRMS API page;
the HMS change follows the primary HMS Text index (each day's file appears during
that UTC day and is finalised the next morning). No request leaves the process.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
import responses

from src import state as state_mod
from src.data import firms, gpm_imerg, source_access as sa, source_incidents as si
from src.data.source_status import SourceFetchError
from src.orchestrator.sources import gpm_imerg as gpm_runner
from tests.live_content_harness import trap_network

FIXTURE = Path(__file__).parent / "fixtures" / "supply_gpm_access.json"
HMS_HEADER = "        Lon,        Lat, YearDay, Time, Satellite, Method, Ecosystem, FRP\n"
PRIMARY = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/invented_key/VIIRS_NOAA21_NRT/world/1"


def _hms_body(when: datetime) -> str:
    return HMS_HEADER + f" -110.500000, 35.250000, {when:%Y%j}, {when:%H%M}, Synthetic sensor, Synthetic method, , 500.000\n"


@responses.activate
def test_unpublished_current_hms_day_reads_yesterday_once_and_keeps_row_times(monkeypatch):
    monkeypatch.setattr(firms, "FIRMS_API_KEY", "invented_key")
    monkeypatch.setenv(firms.HMS_PREVIOUS_DAY_FLAG, "1")
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    for product in ("VIIRS_NOAA21_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"):
        for _ in range(3):
            responses.add(responses.GET, PRIMARY.replace("VIIRS_NOAA21_NRT", product), status=503)
    responses.add(responses.GET, firms._hms_url(now.date()), status=404)
    responses.add(responses.GET, firms._hms_url(yesterday.date()),
                  body=_hms_body(yesterday.replace(hour=22, minute=10)), status=200)
    attempts: list = []
    fires = firms.fetch_fires(attempts=attempts)
    assert len(fires) == 1 and fires[0].source_leg == "noaa_hms"
    assert fires[0].acquired_at.startswith(yesterday.strftime("%Y-%m-%d"))  # the row's own minute, not "today"
    hms = [(a["window"], a["outcome"]) for a in attempts if a["product_id"] == "firms.noaa_hms"]
    assert hms == [("current_utc_day_file", "granule_missing"), ("previous_utc_day_file", "qualified")]
    hms_calls = [c.request.url for c in responses.calls if "hms_fire" in c.request.url]
    assert len(hms_calls) == 2  # bounded: today, then yesterday once; never a crawl
    incident = si.run_incident("firms", attempts)
    assert incident["product_state"] == "alternate_served" and incident["independent_source_upper_bound"] == 1


@responses.activate
@pytest.mark.parametrize("flag", ["0", "true", None])
def test_flag_off_keeps_the_single_current_day_read(monkeypatch, flag):
    monkeypatch.setattr(firms, "FIRMS_API_KEY", "invented_key")
    if flag is None:
        monkeypatch.delenv(firms.HMS_PREVIOUS_DAY_FLAG, raising=False)
    else:
        monkeypatch.setenv(firms.HMS_PREVIOUS_DAY_FLAG, flag)
    now = datetime.now(UTC)
    responses.add(responses.GET, firms._hms_url(now.date()), status=404)
    attempts: list = []
    with pytest.raises(Exception):
        firms._fetch_fires_hms(250, attempts=attempts, today=now.date())
    assert [(a["window"], a["outcome"]) for a in attempts] == [("current_utc_day_file", "endpoint_missing")]
    assert len(responses.calls) == 1


@responses.activate
def test_a_non_404_hms_failure_never_falls_back_to_another_day(monkeypatch):
    monkeypatch.setattr(firms, "FIRMS_API_KEY", "invented_key")
    monkeypatch.setenv(firms.HMS_PREVIOUS_DAY_FLAG, "1")
    now = datetime.now(UTC)
    for _ in range(3):
        responses.add(responses.GET, firms._hms_url(now.date()), status=503)
    attempts: list = []
    with pytest.raises(Exception):
        firms._fetch_fires_hms(250, attempts=attempts, today=now.date())
    assert [a["window"] for a in attempts] == ["current_utc_day_file"]
    assert not any(firms._hms_url(now.date() - timedelta(days=1)) == c.request.url for c in responses.calls)


# --- GPM / Earthdata ----------------------------------------------------------------

def _jwt(expires: datetime) -> str:
    def part(doc):
        return base64.urlsafe_b64encode(json.dumps(doc).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': int(expires.timestamp())})}.invented"


def _refused_row(at: str, credential_expires_at: str) -> dict:
    record = sa.run_record(credential_expires_at=credential_expires_at, attempts=[{"outcome": "access_refused"}],
                           backoff=None, now=datetime.fromisoformat(at.replace("Z", "+00:00")))
    return {"id": f"run-{at}", "started_at": at, "sources": [
        {"source": "gpm_imerg", "status": "failed", "details": {"earthdata_access": record}}]}


def test_backoff_schedule_is_per_credential_and_bounded():
    exp = "2026-12-30T00:00:00Z"
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    one = [_refused_row("2026-10-30T09:00:00Z", exp)]
    assert sa.refusal_backoff(one, credential_expires_at=exp, now=now)["next_attempt_after"] == "2026-10-30T15:00:00Z"
    assert sa.refusal_backoff(one, credential_expires_at=exp, now=now + timedelta(hours=4)) is None  # 6 h elapsed
    three = one + [_refused_row("2026-10-29T09:00:00Z", exp), _refused_row("2026-10-28T09:00:00Z", exp)]
    backoff = sa.refusal_backoff(three, credential_expires_at=exp, now=now)
    assert backoff["consecutive_refusals"] == 3 and backoff["next_attempt_after"] == "2026-11-02T09:00:00Z"
    # A renewed credential (different expiry claim) is tried at once; older refusals never hold it.
    assert sa.refusal_backoff(three, credential_expires_at="2027-01-15T00:00:00Z", now=now) is None
    # A later qualified primary run ends the refusal streak.
    qualified = {"id": "ok", "started_at": "2026-10-30T10:00:00Z", "sources": [
        {"source": "gpm_imerg", "status": "success", "details": {"incident": {"product_state": "primary_qualified"}}}]}
    assert sa.refusal_backoff([qualified] + three, credential_expires_at=exp, now=now) is None


def test_runner_sends_no_request_inside_backoff_and_records_it(monkeypatch):
    trap_network(monkeypatch.setattr)
    expires = datetime.now(UTC) + timedelta(days=40)
    exp_iso = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    monkeypatch.setenv("EARTHDATA_TOKEN", _jwt(expires))
    monkeypatch.delenv("THEHEAT_RAINFALL_REGIONAL_SCAN", raising=False)
    monkeypatch.setenv(gpm_runner.REFUSAL_BACKOFF_FLAG, "1")
    refused_at = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bot_state = state_mod._fresh_state()
    bot_state["run_history"] = [_refused_row(refused_at, exp_iso)]
    current_run: dict = {"id": "r", "sources": []}
    gpm_runner.run_gpm_imerg(bot_state, current_run, [{"city": "Ficta", "country": "ZZ", "lat": 1.0, "lon": 2.0}])
    entry = current_run["sources"][-1]
    assert entry["status"] == "failed" and "no request sent" in entry["error"]
    access = entry["details"]["earthdata_access"]
    assert access["refused"] is False and access["backoff"]["consecutive_refusals"] == 1
    outcomes = [a["outcome"] for a in entry["details"]["incident"]["attempts"]]
    assert outcomes == ["access_backoff"]
    assert bot_state["source_health"]["gpm_imerg"]["runs"][-1]["error_class"] == "auth"


def test_backoff_flag_off_still_attempts_and_records_the_refusal(monkeypatch):
    trap_network(monkeypatch.setattr)
    expires = datetime.now(UTC) + timedelta(days=40)
    exp_iso = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    monkeypatch.setenv("EARTHDATA_TOKEN", _jwt(expires))
    monkeypatch.delenv("THEHEAT_RAINFALL_REGIONAL_SCAN", raising=False)
    monkeypatch.delenv(gpm_runner.REFUSAL_BACKOFF_FLAG, raising=False)
    seen: list = []
    monkeypatch.setattr(gpm_imerg, "fetch_daily_precip", lambda **kwargs: seen.append(kwargs) or [])
    refused_at = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    bot_state = state_mod._fresh_state()
    bot_state["run_history"] = [_refused_row(refused_at, exp_iso)]
    gpm_runner.run_gpm_imerg(bot_state, {"id": "r", "sources": []}, [])
    assert len(seen) == 1 and "access_backoff" not in seen[0]  # off: today's behaviour, one ordinary attempt


def test_runner_records_a_refusal_once_and_leaves_normal_rows_unchanged(monkeypatch):
    trap_network(monkeypatch.setattr)
    expires = datetime.now(UTC) + timedelta(days=40)
    monkeypatch.setenv("EARTHDATA_TOKEN", _jwt(expires))
    monkeypatch.delenv("THEHEAT_RAINFALL_REGIONAL_SCAN", raising=False)

    def refused(*, trace=None, **_kwargs):
        raise SourceFetchError("GPM IMERG fetch failed: HTTP 401")

    refusal_details = {"rainfall_opportunity": {}, "incident": si.run_incident("gpm_imerg", [si.attempt(
        "gpm_imerg.imerg_late_opendap", "access_refused", window="imerg_late_daily_walkback_late",
        region="rotating_window", parser_contract="gpm_imerg.ascii_subset")])}
    monkeypatch.setattr(gpm_imerg, "fetch_daily_precip", refused)
    monkeypatch.setattr(gpm_runner, "_trace_details", lambda trace: dict(refusal_details))
    bot_state = state_mod._fresh_state()
    current_run = {"id": "r", "sources": []}
    gpm_runner.run_gpm_imerg(bot_state, current_run, [])
    access = current_run["sources"][-1]["details"]["earthdata_access"]
    assert access["refused"] is True and access["backoff"] is None and access["refused_at"]
    # A normal successful run carries no access record (byte-identical rows otherwise).
    monkeypatch.setattr(gpm_imerg, "fetch_daily_precip", lambda **_k: [])
    monkeypatch.setattr(gpm_runner, "_trace_details", lambda trace: {"rainfall_opportunity": {}})
    bot_state2 = state_mod._fresh_state()
    run2 = {"id": "r2", "sources": []}
    gpm_runner.run_gpm_imerg(bot_state2, run2, [])
    assert "earthdata_access" not in run2["sources"][-1]["details"]


def test_access_health_matches_the_shared_fixture_and_names_last_good_age():
    doc = json.loads(FIXTURE.read_text())
    for name, case in doc["cases"].items():
        out = sa.gpm_access_health(case["state"], now=datetime.fromisoformat(case["as_of"].replace("Z", "+00:00")))
        assert {k: out[k] for k in doc["compared_fields"]} == case["expected"], name
        assert out["requests_sent_by_projection"] == 0 and out["empty_feed_is_not_coverage"] is True
    expired = doc["cases"]["expired"]["expected"]
    assert expired["stage"] == "access_expired" and expired["last_good"]["data_date"] == "2026-08-20"
    assert expired["last_good"]["age_days"] == 71 and "71 days old" in expired["public_text"]
