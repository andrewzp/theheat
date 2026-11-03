"""OFFLINE FIXTURE: stand-in for the GitHub Actions ``theheat-bot`` concurrency group.

Takes an exclusive ``fcntl.flock`` on the given lock file BEFORE starting the wrapped
consumer, holds it until the consumer exits, then releases it. Only consumer processes
take it (dashboard clients and admission never do), exactly like the route contract:
one group job at a time, across independently started processes.
"""
import fcntl
import subprocess
import sys

with open(sys.argv[1], "a+") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        raise SystemExit(subprocess.run(sys.argv[2:]).returncode)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
