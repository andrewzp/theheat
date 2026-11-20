"""Real local source refusals remain held; only fixed diagnostics are retained."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from dashboard.tests.fixtures.rainfall_grid_hold_producer import CASES, produce, original_frame
from src.data import gpm_imerg as gpm, rainfall_grid as grid
from tests.test_rainfall_grid_pipeline import NOW


@pytest.mark.parametrize("name,code", CASES.items())
def test_actual_http_collector_and_durable_health_retain_exact_hold_without_grid_nomination(name, code):
    state = produce(name)
    row, = state["run_history"][0]["sources"]
    discovery = row["details"]["rainfall_grid_discovery"]
    assert discovery == {"schema": "theheat.imerg-grid-discovery/v1", "status": "held",
                         "reason": "rainfall_grid_frame_unqualified", "hold_code": code}
    assert row["observed"] == 1 and (row["promoted"] > 0) is (name == "city")
    health = state["source_health"]["gpm_imerg"]["runs"][-1]
    assert ("promoted" in health) is (name == "city")
    assert state["drafts"] == []


def test_valid_frame_remains_qualified_without_a_new_diagnostic_or_extra_request():
    state = produce("qualified")
    row, = state["run_history"][0]["sources"]
    assert row["details"]["rainfall_grid_discovery"]["status"] == "qualified"
    assert "hold_code" not in row["details"]["rainfall_grid_discovery"]
    assert row["promoted"] == 1


class ForeignHold(grid.GridHeld):
    pass


@pytest.mark.parametrize("exception", [
    grid.GridHeld("private-token /secret/path <script>"), grid.GridHeld("constructor"),
    grid.GridHeld("rainfall_grid_time_invalid", "private-token"),
    ForeignHold("rainfall_grid_time_invalid"), ValueError("private-token"),
    OSError("private-token"), KeyError("private-token"), TypeError("private-token"),
])
def test_unknown_or_nonexact_exception_stays_generic_without_exporting_prose(exception):
    from src.data import rainfall_grid_scan
    raw = original_frame()
    before = deepcopy(raw)
    result: dict = {}
    with freeze_time(NOW), patch.object(rainfall_grid_scan, "scan", side_effect=exception):
        rows = gpm._subset_grid(raw, [], resolved_date=(NOW - timedelta(days=1)).date(), product="late", discovery_out=result)
    assert rows == [] and raw == before
    assert result == {"schema": "theheat.imerg-grid-discovery/v1", "status": "held",
                      "reason": "rainfall_grid_frame_unqualified", "rows": []}
