"""Calendar shifts preserve elapsed-time deadlines shared with real children."""
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import time


def test_calendar_shift_keeps_real_elapsed_clocks_across_processes():
    names = ("monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns")
    before = {name: getattr(time, name)() for name in names}
    child = subprocess.run(
        [sys.executable, "-c", "import datetime,json,time; print(json.dumps({"
         "'wall':time.time(),'utc':datetime.datetime.now(datetime.timezone.utc).timestamp(),"
         "'clocks':{n:getattr(time,n)() for n in " + repr(names) + "}}))"],
        env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        capture_output=True, text=True, timeout=10, check=True,
    )
    after = {name: getattr(time, name)() for name in names}
    assert len(child.stdout) < 1024
    actual = json.loads(child.stdout)
    for name in names:
        assert before[name] <= actual["clocks"][name] <= after[name], name
    # The calendar must still move: restoring an elapsed clock cannot silently
    # disable the source-age/fixture-date canary.
    expected = int(os.environ.get("THEHEAT_TIME_TRAVEL_DAYS", "0")) * 86400
    tolerance = after["monotonic"] - before["monotonic"] + 1
    assert abs(time.time() - actual["wall"] - expected) <= tolerance
    assert abs(datetime.now(timezone.utc).timestamp() - actual["utc"] - expected) <= tolerance
