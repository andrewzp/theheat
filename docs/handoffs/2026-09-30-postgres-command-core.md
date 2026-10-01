# Isolated PostgreSQL command core

`PostgresCommandAuthority` provides local/preview initialization, acceptance,
consumption, state reads, result lookup and paginated command history. It reuses
`Command`, `Principal`, `AutomaticPolicy` and the existing pure reducer, including
revision-bound editing, alternate selection, review, approval, scheduling,
cancellation and rejection. It never sends a post or selects a production backend.
Gist remains production. Hosted ingress, authentication, spending, jobs, media
attachment, raw import and the publishing outbox are not implemented by this core.

The optional PostgreSQL 17 driver profile and explicit Unix-socket connection are
the same as the [projection repository](2026-09-30-postgres-projection-repository.md).
No ambient PG configuration, production environment or automatic backend fallback
is accepted. Principal and role resolver are trusted local adapter inputs, not
proof of authentication. The consumer resolves the subject's current role inside
the write transaction. An explicit revoked identity produces a terminal refusal;
a failing resolver leaves the command pending for recovery. The trusted resolver
must bound its own work; SQL timeouts do not bound a Python callback.

## Atomic ordering and recovery

The separate `theheat_commands` schema contains immutable command intents,
terminal results, accepted/completed events and migration metadata. Its sole
mutable state row points to an exact immutable canonical projection version. It
does not hold a second mutable JSON copy. Original wire bytes remain a separate
retention responsibility; initializing from a state object is not a production
migration or evidence qualification.

Acceptance and consumption acquire the same singleton row lock before selecting
queue entries or reading state. Acceptance therefore commits in sequence order;
consumption processes the oldest pending acceptance. Explicitly targeting a later
pending command returns `command_pending`. Rolled-back identity sequences may
leave gaps. Connections explicitly use READ COMMITTED so role defaults cannot
change the intended lock/read behavior. No process-local mutex serializes workers.

Acceptance commits the exact validated command and its accepted event together.
Consumption commits the new projection, pointer/version, terminal result and
completed event in one outer transaction. The projection helper composes into this
existing transaction; it never opens a separately committing write. No-op and
rejected commands preserve the state version. Reads reconstruct and verify the
complete projection and validate retained command/result/event identities.

All successful receipts leave the transaction only after commit acknowledgment.
After `write_outcome_unknown`, retain the original command id and reconcile through
acceptance/result lookup; do not create a new command to replace a lost response.
Same-id, same-body retries reuse existing receipts, even after the original request
expires. Different-body reuse conflicts. Completed results are historical facts,
not renewed current approval. An unresolved platform outcome still blocks edits.

Initialization is explicit and cannot replace existing state. Provisioning the
separate projection schema may commit first, but core schema installation, its
initial projection and current pointer are atomic. A failed core setup cannot
leave a partial current authority. Ordinary reads do not create or migrate schemas.

## Integrity and limits

Migration/catalog checks include table, function, schema, column and sequence
permissions. Initialization removes broad owner defaults for PUBLIC/runtime before
granting the fixed role. Runtime can read, insert journal rows, advance sequences,
and update only the pointer's version and snapshot key. It cannot edit immutable
records, change the namespace, reset sequence values, truncate tables or alter
schema definitions. Triggers also refuse ordinary owner mutations of the journal.
A pointer trigger enforces one-step progression and structural reference
completeness; application checks verify full canonical content before update/read.

A trusted administrator can still disable guards and rewrite stored receipts.
This is not protection against a malicious DBA, and a database role is not an
application Principal. Direct out-of-contract SQL is not the mutation API. Do not
write into the reserved `command-core-v1` projection namespace through the general
archive API. Production service isolation and all-writer migration remain required.

Requests retain the 128 KiB request limit, with 2 KiB reserved for the stored actor
and environment envelope. Result/event bodies are bounded at 1 MiB. History reads
accept an `after_sequence` cursor and a limit of 1–100, with an 8 MiB encoded-body
preflight per page. The full projection retains its 16 MiB admission limit. These
bounds are not a total disk quota or a hosted API latency/memory guarantee; repeated
history verification can reconstruct multiple historical projections. There is no
pruning or garbage collection.

The standalone projection API keeps its transaction ownership and immutable
receipts. Its original migration is unchanged. Catalog ACL inspection now covers
column/sequence grants; schemas without those grants retain their previous
fingerprint material. The private transaction composition helper is internal and
returns only a provisional receipt until its caller commits.

## Verification

The required PR test job enables the real PostgreSQL profile. Run locally from the
repository using the complete optional environment:

```sh
no_proxy='*' THEHEAT_TEST_POSTGRES=1 THEHEAT_POSTGRES_BINDIR=/path/to/postgresql/17/bin \
  python -m pytest tests/test_postgres_command_authority.py \
  tests/test_postgres_projection.py tests/test_command_authority.py -q
```

Tests own fresh temporary Unix-only clusters. Paired cases compare SQLite and
PostgreSQL reducer results; independent processes verify acceptance ordering,
concurrent edits and duplicate requests. Fault tests cover each intermediate write,
initialization rollback, killed connections and lost commit responses. Permission,
corruption, missing-history, read-purity and actual two-schema backup/restore cases
run without providers or publishing calls. Explicit model-review fixtures remain
offline synthetic test setup, never a production fallback pass.

The standard SDK profile can still import the module without psycopg; database tests
explicitly skip when the optional profile is not requested. Required CI does not
skip them. Private original-state parity and previous-release compatibility checks
retain their source data outside the public repository. None of these tests proves
better tweets, lower bills or a completed production cutover.
