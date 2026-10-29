"""Invented positive clock wiring through the actual Node fixture launcher.

No authority, PostgreSQL, native renderer or provider operation is constructed.
"""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from freezegun import freeze_time
import pytest

from src.commands.schema import utc_text
from src.two_bot.check_executor import _window_available
from tests.test_postgres_preview_important_variants import CHILD
from tests.workflow_clock import ELAPSED_CLOCKS, midday_metadata, ticking_workflow_clock

ROOT = Path(__file__).resolve().parents[1]
NODE_PROBE = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installWorkflowClock} from './dashboard/test-support/workflow-clock.js';
import {runFixtureWorker} from './dashboard/test-support/fixture-worker.js';
const [configFile,python,child,root]=process.argv.slice(1);
const config=JSON.parse(readFileSync(configFile,'utf8'));
const RealDate=Date;
const restoreClock=installWorkflowClock(config.test_clock);
let proof;
try {
  const nodeUTC=Date.now();
  const run=await runFixtureWorker(python,[child,configFile,'fixture_clock',''],{
    cwd:root,env:{PATH:process.env.PATH,PYTHONPATH:root,no_proxy:'*',LC_ALL:'C'},
    encoding:'utf8',timeout:30000,
  });
  assert.equal(run.status,0,run.stdout+run.stderr);
  const childClock=JSON.parse(run.stdout);
  // The existing positive journey's producer-wait expression and bound.
  const availability=new Date(Date.now()+50).toISOString();
  const wait=Date.parse(availability)-Date.now()+250;
  assert.ok(wait>0 && wait<=60500);
  const started=process.hrtime.bigint();
  await new Promise(resolve=>setTimeout(resolve,wait));
  const elapsed=Number(process.hrtime.bigint()-started)/1e6;
  assert.ok(elapsed>=wait-10 && elapsed<2000);
  proof={node_utc:nodeUTC,child:childClock,wait_ms:wait,timer_elapsed_ms:elapsed};
} finally { restoreClock(); }
proof.restored=Date===RealDate;
console.log(JSON.stringify(proof));
"""


@pytest.mark.parametrize("wall,before_available", [
    ("2026-10-22T23:58:30Z", False),
    ("2033-07-04T23:59:58Z", False),
    ("2033-07-05T00:00:02Z", True),
], ids=["actual_late_day", "time_travel_late_day", "time_travel_after_midnight"])
def test_positive_parent_child_and_node_share_midday_without_changing_elapsed_time(
    tmp_path, wall, before_available
):
    clocks = {name: getattr(time, name) for name in ELAPSED_CLOCKS}
    try:
        with freeze_time(wall, tick=True):
            for name, clock in clocks.items():
                setattr(time, name, clock)
            setattr(subprocess, "_time", clocks["monotonic"])
            late = datetime.now(UTC)
            # Real production guard: the original late-day positive fixture is
            # ineligible even though its 300-second lease and source are fresh.
            packet = dict(check_date=late.date().isoformat(), useful_until=utc_text(late + timedelta(hours=8)))
            lease = dict(expires_at=utc_text(late + timedelta(seconds=300)))
            assert _window_available(packet, lease, utc_text(late)) is before_available
            metadata = midday_metadata()
            assert metadata["fixed_at"][:10] == wall[:10]
            with ticking_workflow_clock(metadata):
                parent_before = datetime.now(UTC)
                before_monotonic = time.monotonic()
                assert parent_before.hour == 12
                child = tmp_path / "important-worker.py"
                child.write_text(CHILD)
                config_file = tmp_path / "clock-config.json"
                config_file.write_text(json.dumps(dict(test_clock=metadata)))
                # This executes the actual CHILD bootstrap via the actual
                # asynchronous fixture subprocess launcher, stopping before PG.
                run = subprocess.run(
                    ["node", "--input-type=module", "-e", NODE_PROBE,
                     str(config_file), sys.executable, str(child), str(ROOT)],
                    cwd=ROOT, env={"PATH": os.environ["PATH"], "LC_ALL": "C"},
                    capture_output=True, text=True, timeout=15, check=True,
                )
                proof = json.loads(run.stdout)
                parent_after = datetime.now(UTC)
                assert not run.stderr and proof["restored"] is True
                assert before_monotonic <= proof["child"]["monotonic"] <= time.monotonic()
                assert parent_before.timestamp() <= proof["child"]["utc"] <= parent_after.timestamp()
                assert parent_before.timestamp() * 1000 <= proof["node_utc"] <= parent_after.timestamp() * 1000
                now = utc_text(parent_after)
                for stamp in (utc_text(parent_before), now):
                    current = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    assert _window_available(
                        dict(check_date=current.date().isoformat(), useful_until=utc_text(current + timedelta(hours=8))),
                        dict(expires_at=utc_text(current + timedelta(seconds=300))), stamp,
                    )
                assert getattr(subprocess, "_time") is clocks["monotonic"]
                (tmp_path / "clock-tuple.json").write_text(json.dumps(dict(
                    original_wall=wall, original_window_available=before_available,
                    metadata=metadata, parent_before=parent_before.isoformat(),
                    parent_after=parent_after.isoformat(), **proof,
                ), indent=2) + "\n")
            assert datetime.now(UTC).hour == late.hour
            assert all(getattr(time, name) is clock for name, clock in clocks.items())
    finally:
        for name, clock in clocks.items():
            setattr(time, name, clock)
        setattr(subprocess, "_time", clocks["monotonic"])
