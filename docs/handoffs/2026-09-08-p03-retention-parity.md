# P03: protected retention and SQLite parity

Implemented locally on `codex/p03-retention-parity`, based on P00 `aee8962`.
This record does not claim deployment, a database migration, or transactional
Gist writes. No production state, publishing setting, or public post was changed.

## Result

Both runtimes retain pending, approved and posted drafts above the nominal
200-record cap. P02 publication uncertainty, intent and revision-conflict records
remain protected. The dashboard now follows Python's existing 30-day rejected
expiry and newest-ten empty-queue guardrail. Legacy timestamps without a timezone
are interpreted as UTC in both runtimes.

Python remains the source for durable defaults, SQLite metadata keys and
retention constants. `scripts/gen_state_contract.py` emits
`dashboard/lib/state-contract.js`; an offline contract test fails if it is stale.
This closes all 15 missing dashboard SQLite metadata fields found in current
code, extending the original assessment's eight-field experimental sample.

Unsupported backend names and SQLite without a path fail clearly. Configured
Gist bootstrap failure no longer exposes empty SQLite state: this covers reads,
dashboard writes and Python writes, including incomplete credentials and failed
bootstrap storage. A newer SQLite database containing unknown metadata is refused
by both readers before an ordinary write can erase it.

Suppression metadata is authoritative when present, including an empty list.
Python updates no longer resurrect stale rows from the older dashboard-only
suppression table. Table-only legacy databases remain readable.

## Evidence

- Full offline Python suite: **2,570 passed, 41 paid replay tests deselected**.
- Dashboard suite: **215 passed**.
- Ruff and mypy: passed; production dashboard build: passed.
- Six shared retention cases cover more than 200 protected records, each P02
  attempt/conflict form, a plain old approved record, exact cutoff boundaries,
  unprotected cap behavior and the empty-queue guardrail.
- Mocked Gist mutation preserves every protected record in a **615-draft** queue.
- Real Python/Node temporary SQLite round trips compare populated values for all
  **66 current durable fields**, including scalars, full writes, partial writes,
  a dashboard draft command and nested P02 revision/receipt evidence.
- Fault tests verify failed bootstrap rollback, unknown future metadata refusal,
  incomplete credentials and suppression authority. Retention also passes with
  Node running in `America/New_York`.

## Integration and remaining limits

Regenerate the state contract after integrating new Python fields, including
P00b's proposed `publication_control`. New top-level fields still require
`DEFAULT_STATE`, `MERGE_SPEC`, TypedDict and SQLite coverage; the generated check
complements those contracts.

Gist remains production authority and still has a non-atomic read/PATCH window.
SQLite remains dormant/local: these field and failure tests do not establish a
safe production switchover or solve its multi-writer snapshot concurrency.
Protected records intentionally exceed the cap; actual database archival and
object-store retention remain later plan work. Legacy dashboard-only
`pending_confirmations` is retained for local backward compatibility and is not
reintroduced into the Python durable schema.

The historical tweet corpus and its scientific evidence limits are unchanged.
This storage repair preserves review and receipt evidence; it does not adjudicate
historical claims or authorize corrections or resumed automatic publishing.
