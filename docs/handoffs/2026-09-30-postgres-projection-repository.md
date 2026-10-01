# Local PostgreSQL projection archive

This optional repository stores immutable canonical JSON projections for local or
preview experiments. It has no current-state pointer, production backend selector,
command handler, authorization principal, publishing outbox or paid model client.
Gist remains the production store. A successful archive receipt is not evidence
qualification, editorial approval or permission to spend or publish.

`src/storage/postgres_projection.py` exposes `PostgresProjectionRepository`,
`ProjectionReceipt` and bounded `ProjectionError` codes. Construction requires an
explicit absolute Unix-socket directory, database and user. It rejects ambient
`PG*` configuration and supports PostgreSQL 17. Initialization uses a separately
provisioned migration owner and runtime role. Runtime calls must use the recorded
non-owner role; they reject privileged roles and all role memberships.
Initialization revokes broad owner default privileges before granting access. There is no hosted authentication or secret configuration.

## Representation and limits

Version keys are `(namespace, snapshot_id)`, with bounded ASCII labels. A version
contains a canonical SHA-256, byte count, field count and database creation time.
Each top-level field refers to the SHA-256 of its complete canonical JSON value.
Unchanged fields reuse artifacts across versions. This simple decomposition does
not normalize operational entities or avoid growth when a large field changes.

Canonical encoding is this Python implementation's sorted-key UTF-8 JSON with
compact separators, not a cross-language canonicalization standard. It preserves
unknown fields, empty collections, valid Unicode/NUL strings, integer versus float
representation, and negative floating zero. It does not normalize Unicode. It
rejects non-finite floats, integers outside ±(2^53−1), non-JSON types, invalid
Unicode, and duplicate keys during byte decoding. Exact original wire bytes and
provider responses must be retained separately: this API accepts Python objects,
so it cannot recover whitespace, original key order or duplicate keys already lost
before admission.

Admission is bounded to 16 MiB, 512 top-level fields, 1,024 encoded bytes per field
name, depth 32 and 1,000,000 JSON value/container nodes. Names and values use `bytea`,
including strings that PostgreSQL text/JSONB cannot represent. Bounds are per
projection, not a total disk quota or a complete process-memory ceiling. There is
no retention, pruning, garbage collection or hosted cost estimate.

## Transactions, privilege and integrity

Every call owns its connection and transaction. Writes explicitly request
synchronous commit. Artifacts, references and version metadata commit atomically;
a receipt is returned only after the transaction context acknowledges commit.
Same-key, same-content retries return the original receipt. Different content
conflicts, including simultaneous callers. A database error during a write returns
`write_outcome_unknown`: reconcile/retry the same identity, never invent a new key
because an acknowledgment was lost. This conservative code does not prove that a
failed call committed, and contains no automatic retry loop.

Shared artifact inserts use sorted hashes to keep lock order consistent. Reads
check the catalog fingerprint and migration version, bound aggregate referenced
bytes before payload transfer, verify every artifact's byte count/hash/canonical
encoding, and reconstruct the complete version identity. Invalid, missing or
oversized references fail closed. Reconstructed objects are detached from inputs.

The runtime role gets schema usage, table reads and inserts into artifacts,
versions and references. It cannot edit metadata, update/delete/truncate existing
rows or change schema definitions. Statement triggers also refuse ordinary owner
updates/deletes/truncation. Initialization checks the migration and catalog rather
than overwriting an existing unexpected schema; later schema, trigger and grant
changes are detected. Direct out-of-contract SQL inserts may create incomplete
packets, but reads will not accept them as valid projections. They never confer
editorial or publication rights.

The database owner remains an administrative trust boundary. An administrator can
disable triggers and rewrite schema receipts; catalog fingerprinting is not a
security boundary against a malicious DBA. Hosting security, authenticated ingress,
complete privilege provisioning, production migrations and operational recovery
remain separate work. Restore must preserve owners, grants and the runtime role;
its migration/catalog receipts and canonical contents are checked again on read.

## Required verification

Install the normal requirements plus `requirements-postgres.txt` in a separate
environment. Provide PostgreSQL 17 binaries, then run:

```sh
THEHEAT_TEST_POSTGRES=1 THEHEAT_POSTGRES_BINDIR=/path/to/postgresql/17/bin \
  python -m pytest tests/test_postgres_projection.py -q
```

Tests create a fresh mode-0700 temporary cluster with Unix sockets, TCP disabled
and host authentication rejected. They stop/remove only that owned cluster. No
existing database, provider call, paid replay or production state is used. When the
profile is requested, missing driver/binaries fail rather than skip. Default
installations transparently skip database-dependent tests; pure admission/lazy
import tests still run. The required PR `test` job installs PostgreSQL 17 and the
pinned optional driver and enables this profile in the full offline suite.

The real-database suite covers canonical identity, initialization, schema tamper,
non-owner permissions, concurrency, mid-write rollback, connection termination,
lost commit response, partial/corrupt packets, and actual `pg_dump`/`pg_restore`.
On macOS, use `no_proxy='*'` for the full offline suite's forked-process tests.
Python documents that system proxy discovery is unsafe after fork; this local
setting avoids that OS API without weakening the network gate or assertions.
See the [Python urllib warning](https://docs.python.org/3.12/library/urllib.request.html).

Synthetic fixtures are public. Original state/corpus, parity snapshots and raw
source packets remain private. Local tests establish this repository contract;
they do not establish a production migration, lower bills or better tweets.

API/transaction reference: [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
CI packages: [official PostgreSQL Ubuntu repository](https://www.postgresql.org/download/linux/ubuntu/).
