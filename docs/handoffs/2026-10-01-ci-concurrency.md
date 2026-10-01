# Isolate PR checks from the bot queue

The test and production jobs were separate, but their workflow-level concurrency
group was shared. A long PR suite could occupy the same group as scheduled bot
work. GitHub also replaces an older pending run when another run enters the same
group under its default queue policy.

PR checks now use `theheat-ci-<PR number>`. A newer head may cancel obsolete checks
only within that PR. Every scheduled or manually dispatched bot mode keeps the
literal `theheat-bot` group with cancellation disabled. Keeping that literal also
preserves coordination with producer runs using the preceding workflow version.
Unknown non-PR events fall back to the production group.

The existing job exclusions, schedule expressions, input modes, permissions,
production timeout and smoke gate are unchanged. The full test job exceeded its
former 25-minute allowance, so it now has a bounded 35-minute allowance. Pytest
reports its 20 slowest tests and prints thread stacks after a test stalls for two
minutes; this diagnostic does not skip, terminate or pass a test. The entire suite,
real PostgreSQL checks and dashboard tests/build remain required. The cancelled
run's logs were unavailable. The subsequent run also timed out; its retained log
stops immediately before a media case with a 1,000,087-byte generated test ID.
The oversized input itself passes locally. Short explicit IDs now cover that
case and the large prompt fixtures, preserving every input and assertion. A
collection hook rejects IDs over 1,024 UTF-8 bytes before they can enter the
execution log or `PYTEST_CURRENT_TEST`, with a bounded error that omits the value.
This also protects subprocess environments from oversized test names. The runner
log does not establish the internal cause of its stall; new exact-head CI must
verify that this repair clears the observed boundary. The timeout is not raised again.
No manual workflow run or paid trial is needed. The display-only
branch remains excluded from testing and cannot occupy the production group.

`tests/test_bot_workflow_concurrency.py` verifies the narrow expression contract,
PR partitioning, production fallback and required job separation. These are local
policy checks, not a general expression interpreter or simulated GitHub scheduler.
Required CI at the reviewed head must verify actual syntax and all existing tests.
This scheduler slice changes no dashboard or policy manifest. When bundled with
the prospective-media revision, deploy that dashboard change once after CI passes.

This change does not serialize unrelated workflows, make Gist transactional or
guarantee execution of every pending production run. The existing production queue
policy remains unchanged. Measure natural workflow delays and recovery separately;
a passing PR is not proof of fewer incidents, lower total cost or better coverage.

Reference: [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
