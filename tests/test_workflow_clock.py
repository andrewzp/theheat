"""A midnight wall clock cannot age invented positive fixtures mid-workflow."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from freezegun import freeze_time
import pytest

from tests.workflow_clock import ELAPSED_CLOCKS, midday_metadata, ticking_workflow_clock

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("wall", ["2026-10-20T23:59:58Z", "2026-10-21T00:00:02Z"])
def test_invented_positive_clock_aligns_real_children_and_keeps_elapsed_clocks(wall):
    real_clocks = {name: getattr(time, name) for name in ELAPSED_CLOCKS}
    with freeze_time(wall, tick=True):
        for name, clock in real_clocks.items():
            setattr(time, name, clock)
        metadata = midday_metadata()
        assert metadata["fixed_at"][:10] == wall[:10]
        with ticking_workflow_clock(metadata):
            assert datetime.now(UTC).hour == 12
            before = {name: getattr(time, name)() for name in ELAPSED_CLOCKS}
            child = subprocess.run([sys.executable, "-c",
                "import json,sys,time; from datetime import UTC,datetime; "
                "from tests.workflow_clock import start_child_clock; "
                "clock=start_child_clock(json.loads(sys.argv[1])); "
                "print(json.dumps({'utc':datetime.now(UTC).timestamp(),"
                "'clocks':{n:getattr(time,n)() for n in " + repr(ELAPSED_CLOCKS) + "}}))",
                json.dumps(metadata)], cwd=ROOT,
                env={"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT)},
                capture_output=True, text=True, timeout=15, check=True)
            actual = json.loads(child.stdout)
            assert not child.stderr
            after = {name: getattr(time, name)() for name in ELAPSED_CLOCKS}
            for name in ELAPSED_CLOCKS:
                assert before[name] <= actual["clocks"][name] <= after[name], name
            assert abs(datetime.now(UTC).timestamp() - actual["utc"]) < 2
            node = subprocess.run(["node", "--input-type=module", "-e",
                "import {installWorkflowClock} from './dashboard/test-support/workflow-clock.js';"
                "const RealDate=Date; const start=process.hrtime.bigint();"
                "const restore=installWorkflowClock(JSON.parse(process.argv[1]));"
                "const utc=Date.now(); const text=new Date().toISOString();"
                "restore(); console.log(JSON.stringify({utc,text,restored:Date===RealDate,"
                "elapsed:Number(process.hrtime.bigint()-start)}));", json.dumps(metadata)],
                cwd=ROOT, env={"PATH": os.environ["PATH"]},
                capture_output=True, text=True, timeout=15, check=True)
            actual_node = json.loads(node.stdout)
            assert actual_node["restored"] is True and actual_node["elapsed"] > 0
            assert abs(datetime.now(UTC).timestamp() * 1000 - actual_node["utc"]) < 2000
            assert actual_node["text"][11:13] == "12"
            assert actual_node["text"][:10] == wall[:10]
        assert datetime.now(UTC).hour == datetime.fromisoformat(wall.replace("Z", "+00:00")).hour
        assert all(getattr(time, name) is clock for name, clock in real_clocks.items())
