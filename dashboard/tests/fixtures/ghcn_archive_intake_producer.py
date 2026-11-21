"""Already-requested invented .dly bytes, real collector and source projection.

All diff responses are missing. No live source, SDK, sender or operator data.
"""
from copy import deepcopy
from datetime import date
import json
import sys
from unittest.mock import patch

from dashboard.tests.fixtures import ghcn_intake_producer as intake
from tests.ghcn_intake_cases import SID

NOW = "2026-11-21T12:00:00Z"
DAY = date(2026, 11, 18)
_base_archive = intake.archive


def archive_bytes(*, target=DAY, high=330, low=-150, qflag="", station=SID):
    """Complete invented calendar, two elements; missing cells remain explicit."""
    lines = []
    for line in _base_archive("unavailable").decode().splitlines():
        year, month = int(line[11:15]), int(line[15:17])
        for element, ordinary, candidate in (("TMAX", 250, high), ("TMIN", 150, low)):
            cells = []
            for i in range(31):
                old = line[21 + i * 8:29 + i * 8]
                value = -9999 if int(old[:5]) == -9999 else ordinary
                flag = ""
                try:
                    day = date(year, month, i + 1)
                except ValueError:
                    day = None
                if day is not None and day >= date(2026, 11, 17):
                    value = -9999
                if day is not None and day == target:
                    value = candidate if candidate is not None else -9999
                    flag = qflag
                cells.append(f"{value:5d} {flag or ' '}T")
            lines.append(f"{station}{year:04d}{month:02d}{element}" + "".join(cells))
    return ("\n".join(lines) + "\n").encode()


def produce_archive(case="fresh", provider="ghcn"):
    cases = {"fresh": {}, "empty": {"target": None}, "stale": {"target": date(2026, 11, 16)},
             "future": {"target": date(2026, 11, 22)}, "qc": {"qflag": "S"}, "invalid_archive": {}}
    assert case in cases
    payload = b"invented invalid station archive" if case == "invalid_archive" else archive_bytes(**cases[case])

    def archive(_case, *, baseline=False):
        return archive_bytes(target=None) if baseline else payload

    with patch.object(intake, "archive", archive):
        return deepcopy(intake.produce("unavailable", provider))


if __name__ == "__main__":
    sys.stdout.write(json.dumps({name: produce_archive(name) for name in ("fresh", "empty", "stale", "future", "qc", "invalid_archive")}
                               | {"combined": produce_archive(provider="both_global")}, sort_keys=True) + "\n")
