# Immediate bot output on interrupted runs

Python stdout redirected to a runner can remain buffered until normal exit. The
existing `Run bot` step now sets `PYTHONUNBUFFERED="1"`, allowing already-written
output to reach GitHub immediately. No additional application output is emitted.

The change is confined to that step's environment. Production serialization,
schedules, timeouts, invocation, model settings and publication controls retain
their existing behavior. No dashboard or generated policy change is needed.

Offline workflow tests launch only a synthetic Python child: it writes stdout
without flushing, signals readiness separately, and is killed before normal exit.
The workflow setting makes its stdout readable before termination; the buffered
control loses that output. Both cases use bounded waits and clean up the child.
The existing queue, partition and required-check tests remain in place.

This is local failure-mode evidence, not proof that GitHub retains output through
every infrastructure failure. It neither identifies a shutdown's cause nor
recovers prior logs, unpersisted usage or uncertain operations. Runtime observation
must come from an existing scheduled run, without dispatching a paid trial.
