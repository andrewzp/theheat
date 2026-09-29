# Transactional local spending reservations

Version 0.9.108.23 extends the experimental `SQLiteAuthority`, not the production
Gist path. `initialize` explicitly installs immutable spending tables in the same
transaction as the existing local authority/domain schema. It preserves existing
limits. Old local databases need that migration with their current state and source
namespace. Status calls never silently create a database or configure an allowance.

`SQLiteAuthority.spending(action, payload, now=...)` executes one trusted local
operation inside `BEGIN IMMEDIATE`, before reading the budget. This API is not a
hosted authentication/authorization endpoint. Its tables and immutability guards
are validated on every call. The optional `before_commit` seam exercises rollback
and process death; it is not accepted from a remote request.

Actions:

- `configure`: explicit integer micro-USD daily/monthly/per-job limits and a
  caller-supplied authorization-reference SHA. Zero disables spending. Configuration
  replays exactly or refuses conflicting replacement. No production amount is set.
- `reserve`: immutable intent/job/request/estimate identities, model/provider/role
  and a positive conservative allowance. Writer, safety, fact-check, critic, news
  and repair share these limits. Duplicate identical requests reuse one hold;
  conflicting intent IDs are refused.
- `dispatch`: the first atomic transition returns `dispatch_granted: true`.
  Every later call returns false. The caller must not initiate its one network
  attempt without that true result. A lost acknowledgment cannot justify another.
- `uncertain`: retain the entire dispatched hold, including after a restart or
  day/month change. There is no timeout that silently releases unknown charges.
- `release`: only a never-dispatched reservation can release without cost evidence.
- `settle`: supplied nonnegative cost and reconciliation-evidence SHA finalize a
  dispatched/uncertain attempt. Exact replay is idempotent; conflicts are refused.
  Missing cost cannot be supplied as null or invented as zero. A documented zero
  is a trusted caller assertion, not an account verification by this module.
- `status`: current conservative totals and an optional intent. It explicitly
  disclaims complete accounting and production enforcement.

All outstanding holds count against every new UTC day and month. Settled charges
count in both the reservation and settlement windows, deliberately conservatively.
Per-job allowance spans the job's lifetime. Released holds do not count. Timestamps
use fixed-width microseconds internally, preventing fractional-second ordering
errors; requests cannot move behind the latest journal event. Amounts are bounded
at 10^12 micro-USD per field and the journal at 100,000 intents.

If an actual reconciled charge exceeds its reservation, retain that charge and
block further reservations and unstarted dispatches. Never discard a charge to
make a cap appear satisfied. An explicit future reconciliation/policy-migration
flow is needed to resolve overruns or change configured limits; this prototype
does not reset its journal or invent such approval automatically.

Tests exercise independent processes contesting one allowance, one dispatch grant,
idempotency, role aggregation, day/month carryover, overrun recording, strict amounts,
subsecond time, immutable tables, changed schemas, rollback/process death and an
actual SQLite backup/restore. Spending operations preserve draft state and domain
evidence. No provider, network, billing setting or production mutation is used.

Remaining requirements before a production cap claim: one hosted authority used by
every producer, independently justified conservative pricing/reservation estimates,
complete response and invoice reconciliation, deployment/rollback and recovery.
The caller's estimate/reference hashes are provenance, not proof that a price or
authorization is correct. Multiple unrelated databases do not share a cap.

Batch integration must persist its request artifact and job ownership alongside
these holds, fence stale workers, keep raw late results and reconcile uncertain
submissions. No batch scheduler or transport is activated by this local slice.
