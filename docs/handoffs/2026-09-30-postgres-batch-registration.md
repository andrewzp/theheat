# Atomic PostgreSQL batch registration

The optional local PostgreSQL authority can now retain an exact batch request, its
job identity and its spending hold in one transaction. A crash or competing worker
cannot leave a newly committed hold detached from its request. Registration and
status always return `dispatch_granted=false` and `publication_approved=false`.

## Installation and API

The migration owner explicitly calls `initialize_batches()` after initializing the
command core and spending schema. Migration004 installs `theheat_batches` without
choosing spending limits or changing the current draft projection. Repeated
installation validates the same schema and preserves retained records. Runtime
calls before installation refuse; the runtime role cannot install or migrate it.

Trusted local operations are:

```python
authority.prepare_batch(
    plan_bytes,
    expected_plan_sha256=retained_sha,
    reservation=reservation,
    now=utc_timestamp,
)
authority.batch_status(job_id)
```

These match the existing SQLite registration contract. They validate the core,
spending and batch schemas, environment and roles, then acquire the shared command
singleton lock before joined reads or writes. They do not reconstruct the current
draft projection. Spending uses the same connection and outer transaction; there
is no nested public spending call or independent commit.

## Exact bindings and retry behavior

The existing strict batch-plan reader validates the supplied bytes and independently
retained SHA. The original bytes are stored unchanged, with database hash and length
constraints. Plan bytes remain separate from canonical projection artifacts. The
writer contract is loaded only for explicit batch operations.

An immutable registration joins a unique job, plan SHA and spending intent. The
reservation must match the plan job, complete request SHA, writer model, Anthropic
provider and writer role. The amount covers the complete validated plan. The caller
must justify its estimate; registration does not validate prices, account funding
or the scientific truth of evidence. The caller's reservation dictionary is detached
before reuse across SQL operations.

A new registration must be on or after creation and leave strictly more than the
plan's minimum useful window. Equality refuses. A preexisting exact hold may join
only while still reserved. A dispatched, uncertain, settled or released intent
cannot become a new registration. Any failure rolls back new hold/plan/job rows and
preserves preexisting holds.

An exact retry returns the original binding and current reservation disposition,
even after usefulness expires. This is historical readback, not a fresh financial
action: the supplied time must parse, but the readback does not rerun new-job
eligibility, acquire another hold or advance the spending clock. Changed requests,
reservations or identities conflict. No grant escapes a failed commit; an unknown
acknowledgment is recovered by the same identity.

Status verifies stored bytes, hash, plan/job/hold joins and original registration
time before returning bounded identifiers and disposition. It exposes no prompts or
provider bodies. A valid storage hash alone does not make an invalid plan acceptable.

## Bounds and verification

Plans are at most2,000,000 bytes; registration is limited to100,000 jobs through the
supported API. Reads preflight size before fetching one plan and its bounded spending
record. Unique constraints and foreign keys protect joins; immutable triggers and
restricted runtime grants prevent normal updates, deletes, truncation and DDL.
Initialization clears PUBLIC/runtime default privileges. Schema or permission drift
blocks use. Administrative bypass remains a separate trust boundary.

Real PostgreSQL tests cover paired SQLite outputs, conflicts, exact deadline
boundaries, every existing hold disposition, simultaneous identical/near-cap jobs,
each partial-write rollback, killed connections, lost commit acknowledgments,
installation failure, default privileges, changed/missing joins and actual
four-schema backup/restore. Restored uncertain jobs retain their original request
and never receive another dispatch grant from registration. Explicit HTTP traps
verify that registration makes no provider request.

Production still uses Gist. This release adds no lease, batch submission, result
collection, candidate generation or publishing route. Hosted authority, all-role
cost enforcement, conservative estimates, retention/hosting costs and measured
savings remain unfinished. Runtime models, routine samples, prompts and billing
settings are unchanged. The next PostgreSQL slice ports the existing fenced worker
and late-acknowledgment lifecycle.
