# Fenced PostgreSQL batch ownership

The optional local PostgreSQL authority now coordinates ownership of a registered
batch, grants its first submission once, and retains late acknowledgment evidence.
The job and spending transition share one locked transaction. No provider client
or production worker is introduced.

## Explicit installation and API

After initializing the command, spending and batch-registration schemas, the
migration owner calls `initialize_batch_workers()`. Migration005 installs the
separate `theheat_batch_work` schema. Reinstallation validates existing records;
runtime calls before installation refuse. Installation chooses no allowances and
creates no jobs or grants. Existing migrations remain unchanged.

The trusted local interface matches the SQLite worker contract:

```python
authority.batch_work(action, payload, now=utc_timestamp, raw=None)
```

All operations validate the prerequisite schemas, environment and roles and hold
the same command singleton row lock. They use one READ COMMITTED transaction;
spending helpers neither open another connection nor commit independently. The
wrapper returns a dispatch grant only after the outer commit is acknowledged.
Status never reconstructs the current draft projection.

| Action | Required payload beyond `job_id` | Result |
| --- | --- | --- |
| `status` | None | Bounded identity, disposition, lease and receipt counts |
| `acquire` | `owner`, `ttl_seconds` | Current lease or next fence after expiry |
| `begin` | `owner`, `fence`, `current_context` | At most one committed submission grant |
| `uncertain` | `owner`, `fence` | Durable uncertainty and retained spending hold |
| `observe_ack` | `grant_id`, `receipt_sha256` | Exact response evidence, without adoption |
| `adopt` | `owner`, `fence`, `receipt_sha256` | Current-owner adoption of one valid provider ID |

Fields are exact; canonical payloads are bounded to4096bytes and detached from
mutable caller input. All timestamps are explicit UTC, normalized to six decimal
places. Time cannot precede registration or any retained worker event. Status does
not advance that clock. Spending transitions additionally obey the shared spending
clock. Caller-supplied context and time are trusted adapter inputs, not independent
authentication or proof of current source truth.

## Ownership, uncertainty and evidence

Leases last1–300seconds and carry a monotonically increasing fence. Reusing the
same active owner does not renew its expiry. Another active owner is refused;
expiry equality permits the next owner. A job retains at most1000leases, and
readback validates their contiguous fences, durations and nonoverlapping intervals.
Reconciliation remains possible after the job's useful deadline.

Before the first submission, the current owner/fence must be active; exact bundle,
memory, policy and publication-epoch context must match the plan; strictly more
than the minimum useful window must remain. The grant binds the original job,
plan, spending intent, owner, fence and grant time. Its insert and the spending
dispatch commit together. An externally dispatched hold cannot become a batch
grant. Retrying a committed begin returns no new dispatch permission, including
after an unknown commit acknowledgment or a later owner taking over.

Reacquiring an unadopted submission records uncertainty and preserves its full
hold. Neither lease expiry, acknowledgment nor calendar rollover releases money.
Cancellation and settlement remain separate evidence-driven operations.

Acknowledgments use a separate typed artifact table. It retains exact0–65536byte
responses before protocol parsing, including empty or malformed responses. A job
may retain at most16distinct receipts. Repeated exact evidence is idempotent. SHA,
byte count and database constraints protect storage identity; readback reparses
all bounded receipts and verifies the retained provider identity. URLs are never
followed. The local adapter correlates responses to grants; this is not a
cryptographic provider attestation.

Only a current owner can adopt a valid `message_batch` receipt with a valid ID,
status and complete request counts matching the plan. Late responses alone cannot
adopt themselves. Different IDs within one job or a shared ID across jobs block
adoption. Later conflicting evidence also hides a previously adopted ID in derived
status. Malformed evidence never becomes an accepted response. No report grants
publication or collection, and `accounting_complete` remains false.

## Integrity and recovery evidence

Immutable tables retain leases, submissions, uncertainties, raw acknowledgment
artifacts, observations and adoptions. Foreign keys bind their relationships;
restricted grants and triggers refuse ordinary updates, deletes, truncation and
runtime DDL. Installation clears inherited PUBLIC/runtime privileges. Schema,
permission or metadata drift blocks operation. Administrative bypass is a separate
trust boundary; supported reads also reject damaged identities and missing joins.

Tests pair complete reports with SQLite, exercise independent PostgreSQL workers
competing for a lease and grant, inject failures after every write and before
commit, terminate actual database connections, and lose a committed response.
A real five-schema dump/restore preserves both adopted identities and unresolved
submissions, raw evidence, fences and indefinite holds without another grant.
Original command/projection data remain unchanged. HTTP traps prohibit transport.

This is an optional local/preview foundation. Gist remains production storage.
Hosted authority, every paid route's integration, provider-result retention,
required checks, complete invoice reconciliation and measured product improvements
remain open. No batch lane, publication, paid trial or new service is activated;
runtime models, prompts and routine sample count remain unchanged. The next bounded
PostgreSQL port is durable result retention and review.
