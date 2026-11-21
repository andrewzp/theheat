"""Invented NOAA diff bytes and HTTP replies; no real source or model access."""
from collections import Counter
from datetime import date
from unittest.mock import patch

from freezegun import freeze_time
import requests

from src.data import ghcn
from tests.test_ghcn_format import _make_diff_tar

SID, INACTIVE = "BRX00000001", "BRX00000002"
TODAY = date(2026, 11, 21)
NOW = "2026-11-21T12:00:00Z"
DATES = (date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20))


def csv(day, element="TMAX", value=250, *, station=SID, qflag=""):
    return f"{station},{day},{element},{value},,{qflag},T,0700\n"


def payloads(case="mixed"):
    first = {"insert.csv": (
        csv("20261117") + csv("20261118", "TMIN", 120)
        + csv("20261118", station=INACTIVE) + csv("20261110")
        + csv("20261122") + csv("20261118", "PRCP", 10000)
    )}
    second = {"update.csv": csv("20261118", "TMIN", 120, qflag="S"),
              "insert.csv": csv("20261118", value=310)}
    third = {"delete.csv": csv("20261117"), "insert.csv": csv("20261118", value=330)}
    if case == "empty":
        third = {"delete.csv": csv("20261117") + csv("20261118", value=310)}
    elif case == "inactive":
        first = second = third = {"insert.csv": csv("20261118", station=INACTIVE)}
    elif case == "no_temperature":
        first = second = third = {"insert.csv": csv("20261118", "PRCP", 10000)}
    elif case == "malformed":
        second = {"insert.csv": SID + ",20261118,TMAX\n"}
    with freeze_time(NOW):
        result = {day: _make_diff_tar(members) for day, members in zip(DATES, (first, second, third))}
    if case == "missing":
        return {DATES[0]: result[DATES[0]]}
    if case == "unavailable":
        return {}
    return result


class Replies:
    def __init__(self, data, extra=None):
        self.data = data
        self.calls = []
        self.by_url = {url: raw for day, raw in data.items() for url in ghcn._diff_urls_for_end_date(day)}
        self.allowed = {url for day in DATES for url in ghcn._diff_urls_for_end_date(day)}
        self.by_url.update(extra or {})
        self.allowed.update(extra or {})

    def get(self, url, **kwargs):
        assert url in self.allowed, "Uninvented HTTP request refused"
        self.calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = 200 if url in self.by_url else 404
        response._content = self.by_url.get(url, b"invented missing snapshot")
        setattr(response, "_content_consumed", True)
        response.url = url
        return response

    def counts(self):
        return Counter(url for url, _kwargs in self.calls)


def invoke(case="mixed", *, tracked_keys=None):
    data = payloads(case)
    replies = Replies(data)
    metrics: dict = {}
    revisions: list = []
    with patch.object(ghcn.requests, "get", replies.get), freeze_time(NOW):
        observations = ghcn._fetch_recent_obs(
            frozenset({SID}), today=TODAY, lookback_days=3, max_obs_age_days=4,
            metrics_out=metrics, revisions_out=revisions, tracked_keys=tracked_keys,
        )
    return observations, metrics, revisions, replies, data
