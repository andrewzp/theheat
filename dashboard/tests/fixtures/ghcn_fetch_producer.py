"""Existing real GHCN source journey with only invented HTTP outcomes."""
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import patch

import requests

from dashboard.tests.fixtures import ghcn_intake_producer as intake
from tests.ghcn_intake_cases import Replies

CASES = ("payload", "404", "401", "403", "429", "503", "timeout", "connection")


def produce_fetch(case, provider="ghcn", *, capture_time="2026-11-21T12:00:00Z", tracked=True):
    assert case in CASES or case == "invalid_payload"
    instances = []

    class OutcomeReplies(Replies):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

        def get(self, url, **kwargs):
            response = super().get(url, **kwargs)
            if "/superghcnd/" not in url or case == "payload":
                return response
            if case == "invalid_payload":
                response._content = b"invented invalid NOAA archive bytes"
                return response
            if case == "timeout":
                raise requests.ReadTimeout("invented-private-detail https://secret.invalid/?token=invented")
            if case == "connection":
                raise requests.ConnectionError("invented-private-detail https://secret.invalid/?token=invented")
            response.status_code = int(case)
            return response

    history = nullcontext() if tracked else patch.object(intake, "record_observation_revision", lambda *a, **k: None)
    with patch.object(intake, "Replies", OutcomeReplies), patch.object(intake, "NOW", capture_time), history:
        state = intake.produce("mixed" if case in {"payload", "invalid_payload"} else "unavailable", provider)
    instant = datetime.fromisoformat(capture_time.replace("Z", "+00:00"))
    state["run_history"][0].update(
        started_at=(instant - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ended_at=(instant + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert len(instances) == 1
    state["invented_transport_calls"] = instances[0].calls
    return state


if __name__ == "__main__":
    sys.stdout.write(json.dumps({**{case: produce_fetch(case) for case in CASES},
                                "untracked_404": produce_fetch("404", tracked=False),
                                "invalid_payload": produce_fetch("invalid_payload", tracked=False),
                                "later_401": produce_fetch("401", capture_time="2026-11-21T12:10:00Z")}, sort_keys=True) + "\n")
