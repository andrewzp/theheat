# PostgreSQL mandatory-check lifecycle

The optional local PostgreSQL authority now retains a candidate's exact evidence,
checker state and mandatory checks. One transaction commits each paid check's
spending reservation, dispatch and execution grant. A crash or lost response cannot
grant a second request for the same stage. This is a local/preview storage boundary;
Gist remains production storage and no provider executor is connected here.

## Installation and interface

The owner calls `initialize_candidate_checks()` after installing the command,
projection, spending, batch registration, worker and result schemas. Migration007
adds `theheat_checks`. The installer uses the core singleton lock, validates all
prerequisites and installs atomically. Repeat installation validates and preserves
data. The runtime role can read and append permitted records but cannot change or
delete them. Schema, role, environment or permission drift blocks reuse.

```python
authority.candidate_checks(
    action, payload, now=utc_timestamp, request=request_bytes, receipt=receipt,
)
```

Actions are `intake`, `status`, `begin` and `complete`. Each call owns one READ
COMMITTED transaction and the same core row lock as spending and commands. A grant
returns only after commit acknowledgment. Helpers never open a second transaction
or reconstruct the draft projection. Caller dictionaries detach before repeated SQL
use; extra fields or arguments on the wrong action are rejected.

## Exact inputs and fresh eligibility

Intake uses the existing result-review fields plus `custom_id`, `bundle`, `memory`
and explicit `checker_state`. The freshly evaluated result must supply that exact
eligible candidate. One immutable set binds the candidate, text hash, retained plan,
four-field context, policy, usefulness deadline, UTC check day, bundle, memory and
checker-state hash. Candidate intake and its required result choice/review commit
together. Exact repeats reuse the set; changed inputs cannot replace it.

Status uses `check_set_id`, `owner`, integer `fence`, `current_context` and
`checker_state_sha256`. It freshly evaluates the selected result, current policy,
lease, context, candidate and calendar day. Stored historical passes remain visible
after context changes but cannot establish current readiness. Reading status neither
advances the clock nor consumes result-review capacity.

Both `postgres_batch_results.py` and `postgres_checks.py` are included in the
editorial policy source identity. Changes invalidate obsolete policy-bound checks
and approvals. The generated dashboard manifest is part of the release.

## Stage grants, terminal evidence and spending

The required order is deterministic, safety, fact check, critic. Safety and critic
must be enabled in the current policy. Begin adds `stage` and `reservation` to the
status fields and supplies exact nonempty request bytes. Every predecessor must
have passed before a new grant. The deterministic stage cannot reserve money.
Paid stages require the exact Google provider, policy model, stage role, job and
request checksum. Reserve, dispatch, request, binding and attempt commit together.

Each set has at most one grant per stage. An identical request/reservation retry
returns that grant with `dispatch_granted=false`, including after an unknown commit
response or a later valid worker taking ownership. A changed request conflicts.
An intent already dispatched elsewhere cannot pay for another check. Spending
allowances, monotonic clocks and recorded overruns remain enforced.

Completion adds `stage` and `grant_id` to the status fields. Its separate receipt
has exactly `grant_id`, `request_sha256`, `execution_status`, `verdict`, `result`
and `usage`. Only the original grant owner and exact integer fence may complete it.
Completed executions require pass/reject; error or unavailable executions have no
verdict. Result is a dictionary and usage is a dictionary or unknown.

Late or otherwise stale completion retains evidence with disposition `stale`.
An exact repeat preserves its original historical disposition; a changed terminal
receipt is refused. Errors, unavailable checks and stale receipts cannot unblock
later stages or trigger another grant. Adapter-reported passes are trusted local
records, not independent provider verification or proof of scientific truth.

Even four current passes return `publication_approved=false`,
`accounting_complete=false` and `cost_usd=None`. These operations never settle or
release a spending hold, create a draft or approve publication.

## Bounds and recovery

Separate tables retain packets up to 7,000,000 bytes, requests up to 2,000,000,
attempt bindings up to 8,192 and receipts up to 1,000,000. Each intake input is
individually bounded to 2,000,000 bytes; ordinary envelopes are bounded to 8,192.
The set limit is 100,000. These limits do not establish a hosted storage or cost cap.

Raw SHA-256 and database byte counts protect exact bytes. Semantic fingerprints
identify sets/grants separately. Readback preflights size before fetching blobs and
validates canonical documents, semantic IDs, normalized columns, original leases,
request/reservation joins, stage chronology and receipt/disposition agreement.
Administrative bypass is outside the authenticated runtime boundary; damaged
retained joins still fail closed on supported readback.

The tests use real PostgreSQL transactions and explicit synthetic check results.
They cover SQLite parity, independent processes, every partial write, lost commit
acknowledgments, killed connections, corrupted records, permission drift, mutable
inputs and seven-schema backup/restore. They prohibit provider HTTP calls.

The next boundary is immutable raw check-execution evidence and conservative
interpretation. Hosted authority, production migration, all-role spending control,
provider integration and measured quality/cost outcomes remain separate work.
