# PostgreSQL spending reservations

Two local workers now share one spending allowance through the existing PostgreSQL
authority lock. A reservation and its lifecycle events are immutable. Only the
first committed dispatch transition grants one network attempt; retrying after a
lost commit acknowledgment never grants another attempt. This is an optional
local/preview foundation. Production continues to use Gist.

## Explicit installation and use

`PostgresCommandAuthority.initialize_spending()` is an explicit migration-owner
operation on an initialized command database. It installs migration003 in
`theheat_spending` atomically and preserves the current projection, command history
and limits on repeat calls. Existing archive/core migrations are unchanged.
Spending before installation refuses. The owner does not create runtime credentials
or choose any allowances.

The restricted runtime role calls `spending(action, payload, now=...)`. The schemas
and logical outputs match the SQLite rehearsal in `src/commands/spend_journal.py`.
Inputs are trusted local adapter values, not a hosted authentication mechanism.

| Action | Durable behavior |
| --- | --- |
| `configure` | Explicit immutable daily, monthly and lifetime-per-job limits in integer micro-USD, plus a reference SHA; zero disables new spending. |
| `reserve` | Retain the exact intent/job/request/provider/model/role/estimate identity and positive hold. Same request reuses its hold; changed request conflicts. |
| `dispatch` | Grant true only on the first reserved-to-dispatched commit. Every replay or already advanced state returns false. |
| `uncertain` | Keep the entire dispatched hold indefinitely when the outcome is unknown. |
| `release` | Release only a never-dispatched reservation. |
| `settle` | Retain an evidenced integer charge for dispatched/uncertain work. Exact settlement replay succeeds; a changed charge/evidence conflicts. |
| `status` | Return aggregate totals and optionally one bounded intent, with accounting/enforcement incompleteness explicit. |

No provider client, price table, default allowance, automatic expiry, billing
purchase or invoice integration is added. The authorization SHA is a supplied
reference, not verified authorization. Unknown costs must stay held; a caller must
not manufacture a zero settlement.

## Transaction and accounting contract

Every operation owns one connection and a READ COMMITTED transaction. It validates
the archive/core/spending schema, environment and role, then locks the same command
singleton before reading or changing spending. Spending locks only the pointer;
it does not reconstruct the potentially large draft projection. It never advances
the pointer or changes drafts, command results or projection artifacts.

Private spending helpers compose inside an already validated and locked outer
transaction. They neither connect nor commit independently. Their results are
provisional until that outer commit is acknowledged. Future job registration must
preserve this boundary. A disconnect at commit is unknown; use the retained same
intent to reconcile, never a new identity to obtain another payment grant.

All supported roles and providers share the same limits. Unresolved reservations
count in every new UTC day and month. Settlements count once in either the
reservation or settlement window when that window matches, deliberately
conservatively. Per-job totals span the retained lifetime. Released holds do not
count. An actual charge above its reservation is retained and blocks new holds and
first dispatches; an explicit overrun-resolution design remains future work.

The explicit UTC clock has fixed six-digit microseconds. Calls older than the most
recent retained configuration/reservation/event are refused, including retries.
Read-only status does not advance the clock or append events.

## Integrity, permissions and bounds

Limits/intents/events retain bounded canonical bytes and SHA identities. Normalized
intent/event columns used in accounting are constrained to match their bodies.
Requested records verify canonical bytes, digest, typed values and event order.
An immutable event cannot skip the supported lifecycle or go backward in time.
The runtime role has only necessary reads/inserts and sequence usage; default
PUBLIC/runtime grants are cleared before fixed permissions are installed. Update,
delete and truncate are refused, including ordinary owner SQL. Catalog drift,
column/sequence permissions and migration/role/environment mismatches block use.

An amount is at most10^12 integer micro-USD, an input at most4096 bytes, and the
journal at most100,000 intents through the supported API. SQL aggregates the latest
immutable event per intent using an index; it returns five exact totals rather than
loading all request JSON into Python. Status returns at most one intent and three
events. Aggregation remains bounded O(N); no hosted latency, disk quota or universal
memory bound is claimed. SQL accounting relies on database integrity and the
validated constraints. Deliberate direct SQL or administrative bypass is outside
this trusted local API boundary.

## Validation and remaining work

Tests reuse existing SQLite policy assertions on the real PostgreSQL fixture and
compare complete logical outputs and aggregate reference histories. Independent
processes compete for one remaining allowance and one dispatch grant. Command and
spending consumers visibly wait on the same database row lock. Other cases cover
every inserted-row/commit rollback, killed connection, lost dispatch acknowledgment,
explicit/idempotent install, default privileges, strict values/time, schema drift,
immutable records, body/column identity, corrupt history and actual three-schema
backup/restore. Restored uncertain holds keep their spent dispatch permission.

The required CI PostgreSQL profile runs these tests without provider calls. The
standard profile retains lazy optional-driver import. Production authentication,
all-writer integration, conservative reservation estimates, hosted recovery and
invoice reconciliation remain open. `accounting_complete` and
`production_enforcement` remain false. Shipping this code establishes no account-wide
hard cap, lower monthly bill or improvement in tweet quality.
