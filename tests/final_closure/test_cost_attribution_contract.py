"""D3 attribution contract — Python and dashboard validators agree on shared vectors.

Older observations (no ``attribution`` key) stay valid; malformed attribution
is refused, never repaired into a join.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from src.two_bot import call_inventory as inv
from src.two_bot import usage_observations as observations

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/final_closure/fixtures/cost_attribution_vectors.json").read_text())


def _with(attribution):
    return {**VECTORS["base_observation"], "attribution": attribution}


def _node(rows):
    script = '''
      import {readFileSync} from "node:fs";
      import {validUsageObservation, mergeUsageObservations} from "./dashboard/lib/usage-observations.js";
      const rows = JSON.parse(readFileSync(0, "utf8"));
      const merged = mergeUsageObservations({schema_version: 1, observations: rows.filter(r => validUsageObservation(r)), truncated: false, invalid: false});
      console.log(JSON.stringify({valid: rows.map(r => validUsageObservation(r)), merged}));
    '''
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, input=json.dumps(rows),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_old_rows_stay_valid_and_new_rows_need_an_exact_attribution():
    assert observations.valid_record(VECTORS["base_observation"])
    assert all(observations.valid_record(_with(v)) for v in VECTORS["valid"])
    assert not any(observations.valid_record(_with(v)) for v in VECTORS["invalid"])


def test_python_and_dashboard_validators_and_merge_agree():
    rows = [VECTORS["base_observation"], *(_with(v) for v in VECTORS["valid"]), *(_with(v) for v in VECTORS["invalid"])]
    for index, row in enumerate(rows):
        row["id"] = f"{index:032x}"
    expected = [observations.valid_record(row) for row in rows]
    result = _node(rows)
    assert result["valid"] == expected == [True] * (1 + len(VECTORS["valid"])) + [False] * len(VECTORS["invalid"])
    python_merged = observations.merge_observations({"schema_version": 1, "observations": [r for r in rows if observations.valid_record(r)],
                                                     "truncated": False, "invalid": False})
    assert result["merged"] == python_merged


def test_an_invalid_supplied_attribution_is_recorded_as_explicitly_unjoined():
    from types import SimpleNamespace
    row = observations.observe_response("critic", SimpleNamespace(usage_metadata=None), "invented", "google",
                                        attribution={"status": "joined_attempt", "operation": "alerts"})
    assert row["attribution"]["status"] == "unjoined" and observations.valid_record(row)
    retained = observations.observe_response("writer", SimpleNamespace(usage=None), None, "anthropic")
    assert "attribution" not in retained  # Retained-artifact readers keep the original 14-key shape.


def test_attribution_operations_and_paths_are_the_declared_inventory():
    assert observations.ATTRIBUTION_OPERATIONS == tuple(inv.OPERATIONS)
    assert observations.ATTRIBUTION_PATHS == inv.PATHS
    assert inv.unjoined_attribution() == VECTORS["valid"][0]
