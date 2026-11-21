"""Invented NIFC HTTP -> real parser/runner/durable serialization -> Sources.

No model or platform call. Source qualification and zero-metric omission are
the production implementations, not manually assembled health rows.
"""
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess

from freezegun import freeze_time
import pytest

from src import state as storage
from src.orchestrator.sources import nifc
from tests.test_awc_observed import NOW
from tests.test_nifc_reported_area_consumer import capture as capture, record  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("truncated", [False, True])
def test_actual_report_census_survives_durable_zero_omission_and_node_reader(
    monkeypatch, fresh_state, capture, truncated,
):
    capture["payload"] = {"features": [record(), record(IncidentSize=True),
                                          record(IncidentSize=1), record(IsCpxChild=1)],
                          "exceededTransferLimit": truncated}
    monkeypatch.setattr(nifc, "_should_draft", lambda *_args, **_kwargs: False)
    run = {"id": "invented-fire-census", "mode": "alerts", "started_at": NOW.isoformat(), "sources": []}
    with freeze_time(NOW, tick=True):
        nifc.run_fire_footprint(fresh_state, run)
        storage.finalize_run(fresh_state, run)
    row, = run["sources"]
    assert row["status"] == "degraded" and row["observed"] == 1 and row["promoted"] == 0
    assert row["details"] == {"raw_rows": 4, "qualified_rows": 1, "held_rows": 1,
                               "row_holds": {"invalid_size": 1, "below_floor": 1, "child": 1},
                               "coverage_truncated": truncated}
    assert "promoted" not in fresh_state["source_health"]["fire_footprint"]["runs"][-1]
    assert len(capture["calls"]) == 1 and fresh_state.get("_triage_queue", []) == []
    # VALIDATION supplies the explicit Node24 directory on PATH locally; CI
    # installs Node24. This must run on both macOS and Linux, with no skip.
    node = "node"
    script = f"""
      import fs from 'node:fs';
      import {{ buildSourceHealthPayload }} from {json.dumps((ROOT / 'dashboard/lib/source-health.js').as_uri())};
      const state = JSON.parse(fs.readFileSync(0, 'utf8'));
      const source = buildSourceHealthPayload(state, {{ asOf: {json.dumps((NOW + timedelta(hours=1)).isoformat())} }})
        .sources.find(row => row.source === 'fire_footprint');
      process.stdout.write(JSON.stringify(source));
    """
    result = subprocess.run([node, "--input-type=module", "--eval", script],
                            input=json.dumps(fresh_state), text=True, capture_output=True,
                            timeout=30, check=True, cwd=ROOT,
                            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
    actual = json.loads(result.stdout)
    assert actual["outcome"]["state"] == "fire_reports_held"
    assert "1 qualified; 1 held; 0 admission holds; 0 queued" in actual["outcome"]["detail"]
    assert ("coverage was truncated" in actual["outcome"]["detail"]) is truncated
    assert actual["coverage_row"]["observed"] == 1 and actual["coverage_row"]["promoted"] == 0
    assert actual["degraded"] == 1
