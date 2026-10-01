# PostgreSQL batch-result retention and review

The optional local PostgreSQL authority can now retain returned batch metadata and
result files, then produce a fresh review under current worker ownership. Exact
raw evidence and review documents survive crashes and retries. No provider client,
paid check, database draft or publication is created by these operations.

## Installation and interfaces

The owner explicitly calls `initialize_batch_results()` after initializing the
command, spending, registration and worker schemas. Migration006 creates the
separate `theheat_batch_results` schema. Installation and reinstallation validate
all prerequisite schemas, environment and roles and hold the same command singleton
lock. No limits, jobs or provider settings are chosen by installation.

```python
authority.record_batch_results(
    payload, metadata=metadata_bytes, results=result_bytes, now=utc_timestamp,
)
authority.batch_results_status(job_id, now=utc_timestamp)
authority.review_batch_results(review_payload, now=utc_timestamp)
```

Intake requires exactly `job_id`, `grant_id`, `metadata_sha256`, `results_sha256`
and a strict Boolean `complete`. Review requires exactly `job_id`, `owner`, `fence`,
`receipt_id` and the four-field `current_context`. Canonical payloads are bounded to
4,096 bytes and detached from caller dictionaries. Time is explicit UTC, normalized
to six fractional digits. These are trusted local adapter inputs, not authenticated
hosted ingress or independent proof of source truth.

Every wrapper owns one READ COMMITTED transaction and the shared core lock. Helpers
reuse that connection; no inner commit or independent spending operation occurs.
Receipts return only after acknowledged commit. Status and private fresh evaluation
are read-only, never append a time, and do not reconstruct the draft projection.
The retained result clock and worker clock both apply where relevant.

## Exact evidence and distinct identities

Separate typed tables retain metadata up to 65,536 bytes, result files up to
3,000,000 bytes, and canonical review documents up to 4,000,000 bytes. Raw metadata
and results may be empty or malformed. Intake verifies the exact committed grant,
independently supplied hashes and sizes, then retains bytes before interpreting
result content. Intake does not require the original worker's lease to remain
active; a late worker may preserve evidence without gaining authority to review it.

The receipt ID is the existing typed semantic fingerprint of its complete binding.
A separate SHA verifies the stored canonical binding bytes. These are different
identities and are both checked. The `complete` flag belongs to the receipt binding;
a truncated download remains distinct even when its visible rows happen to look
complete. Exact repeated intake remains idempotent at capacity.

A job may retain 16 distinct receipts and 64 distinct reviews. Reads preflight row
counts and artifact sizes before loading data. The bounds apply per job, not to
hosted total disk or operating cost. Database hash/length constraints, foreign keys,
uniqueness, immutable triggers and restricted grants protect the stored joins.
Schema, permission or metadata drift blocks operations. Administrative bypass is a
separate trust boundary; supported readback also checks damaged retained joins.

## Fresh interpretation and conservative disposition

A current, unexpired worker must review results. The existing strict parser verifies
planned result IDs, terminal status, message identity and writer structure. Metadata
must identify the adopted provider batch, be ended with zero processing, and have
request/outcome counts matching the complete result set. Unknown identity, incomplete
downloads, malformed protocol and conflicting complete content block candidates.

Reported token usage survives unusable writer text when present in a valid
response. Non-success outcomes remain recorded. Cost remains unknown; neither an acknowledgment
nor a review settles or releases a spending hold. Missing usage is not zero usage.
`required_checks_completed` and `publication_approved` remain false, with
`cost_usd=None` and `accounting_complete=false`.

Whitespace and row order may differ between equivalent complete files. Their exact
raw bytes remain distinct, while canonical provider-result identity and individual
candidate IDs remain stable. At most one unambiguous complete semantic choice is
retained. Later contradictory complete evidence invalidates candidate eligibility
for every competing receipt, including a previously usable one.

A later provider-ID conflict also changes the submission revision and withholds
candidates, while preserving the earlier accounting choice and all evidence.
Changed bundle, memory, policy or publication epoch, and useful-deadline equality,
withhold stale text. No cached review is treated as current eligibility.

Review identity binds the selected receipt, plan, full ordered receipt inventory,
current submission revision including ordered acknowledgments, current context,
owner, fence and exact review time. Persisting a choice, review artifact and review
row is atomic. A capacity, size, write or commit failure rolls back all new review
records while preserving previously retained raw evidence and spending holds.

## Verification and remaining boundary

Tests compare complete reports, candidate/review IDs and exact review bytes with
SQLite; exercise partial-to-complete recovery, mixed terminal outcomes, every
context change, stale owners, deadline equality, malformed and conflicting results;
and verify real independent PostgreSQL worker contention. They inject failure after
every write and before commit, terminate connections, lose committed responses and
retry through a fresh authority. Actual capacity boundaries, corrupted joins,
permissions and six-schema dump/restore are covered. HTTP calls are prohibited.

Existing command, projection, registration, spending and worker schemas remain
compatible. The optional driver and writer contract remain lazily loaded. Gist is
still production storage. No batch lane, paid trial, publication or account change
is activated, and no measured quality or savings result is inferred. The next
bounded PostgreSQL port is exact mandatory-check intake and durable check state.
