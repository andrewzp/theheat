# Atomic local batch registration

The batch plan and spending reservation could previously be retained separately.
A crash between them would leave an unexplained hold or an unreserved request.
`SQLiteAuthority.prepare_batch` now owns one real SQLite write transaction for
all three records: exact immutable plan bytes, immutable job binding and the
existing spending reservation. This is an experimental local authority extension,
not a production backend change. Gist remains the production state store.

## Contract

Call `prepare_batch(plan_bytes, expected_plan_sha256=..., reservation=..., now=...)`.
The hash must be independently retained. The reservation uses the existing
microUSD schema and must bind the complete plan hash, job, Anthropic writer role
and exact planned model. The hold covers the entire batch, not a guessed per-item
cost. Estimate correctness and actual authorization are still caller assertions;
no production allowance or new pricing formula is selected here.

New registrations require creation at or before now and strictly more than the
plan's minimum usefulness window remaining. A passed deadline never creates a
new reservation. Exact retries return the current reservation state without a
second hold, even after expiry or dispatch. Changed plan/reservation identities
conflict. An existing independent hold can be joined only while still reserved
and with every field identical. Used or released attempts cannot become new jobs.

`batch_status(job_id)` revalidates stored plan bytes, schema, reservation and join
identities. Receipts contain bounded identifiers and explicit false dispatch and
publication grants. No prompt, unpublished evidence or provider body is logged.
A registration is not a worker lease, model request or permission to publish.

The new schema is installed by explicit local authority initialization. Existing
state, versions, namespaces and artifacts are preserved. Missing migration or
changed append-only guards fail closed. Schema uniqueness and the write
transaction serialize separate processes; there is no process-local lock standing
in for database guarantees. The prototype refuses more than 100,000 jobs.

## Verification and remaining work

Focused tests exercise real independent-process contention, process death before
commit, rollback after a failed job insert, exact replay after restart/expiry,
reservation conflicts and used attempts, minimum-window equality, malformed and
oversized plans, modified stored bytes and joins, schema migration/guards and
actual backup/restore. No source/model/network call is made. Existing state and
all unrelated evidence remain unchanged. All 4,273 offline Python tests pass, with 41 paid tests excluded. The focused
profile passes 251 cases, including 54 new registration/reader cases. Ruff, mypy
over 146 source files, generated contracts and diff checks pass. One existing
Google SDK deprecation warning remains. No dashboard source changed.

Job leases and fences, uncertain submission reconciliation, default-OFF transport,
raw result retention and mandatory-check integration remain. All paid producers
must share a justified budget authority before this can establish a production
cap. No production deployment, trial, billing setting or publishing activation
is implied by these local tests. Human copy preference, global coverage and
actual cost per usable result remain unmeasured outcomes.
