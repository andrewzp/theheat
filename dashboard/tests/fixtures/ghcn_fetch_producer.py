"""Existing real GHCN source journey with only invented HTTP outcomes."""
import json
import sys
from unittest.mock import patch

import requests

from dashboard.tests.fixtures import ghcn_intake_producer as intake
from tests.ghcn_intake_cases import Replies

CASES = ("payload", "404", "401", "403", "429", "503", "timeout", "connection")


def produce_fetch(case, provider="ghcn"):
    assert case in CASES
    instances = []

    class OutcomeReplies(Replies):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

        def get(self, url, **kwargs):
            response = super().get(url, **kwargs)
            if "/superghcnd/" not in url or case == "payload":
                return response
            if case == "timeout":
                raise requests.ReadTimeout("invented-private-detail https://secret.invalid/?token=invented")
            if case == "connection":
                raise requests.ConnectionError("invented-private-detail https://secret.invalid/?token=invented")
            response.status_code = int(case)
            return response

    with patch.object(intake, "Replies", OutcomeReplies):
        state = intake.produce("mixed" if case == "payload" else "unavailable", provider)
    assert len(instances) == 1
    state["invented_transport_calls"] = instances[0].calls
    return state


if __name__ == "__main__":
    sys.stdout.write(json.dumps({case: produce_fetch(case) for case in CASES}, sort_keys=True) + "\n")
