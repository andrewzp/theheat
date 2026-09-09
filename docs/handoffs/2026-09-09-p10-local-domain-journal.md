# P10 first local evidence journal

This extends the experimental local command authority with immutable evidence packets and draft revisions. An applied edit, its retained state/evidence and its terminal command result now commit in one SQLite transaction. A disk/projection failure or process crash rolls them all back while preserving the accepted command for retry. This is a partial P10 implementation, not a production storage migration or P11 acceptance.

## Retained data and identity

Six versioned tables retain schema metadata, content-addressed bytes, draft entities, draft revisions, snapshot origins and packet occurrences. Snapshot artifacts preserve the exact original UTF-8 bytes, including fields this first projection does not interpret. Current draft text and the existing editorial evidence payload have separate byte artifacts; the editorial evidence fingerprint is deliberately distinct from the artifact's SHA256.

A declared source namespace and a unique legacy draft ID establish the provisional entity alias across snapshots. A repeated alias within a snapshot, missing/invalid alias, or a conflicting known legacy event ID is quarantined and retained without an entity/revision join. Missing event IDs do not prove historical continuity. Text, ordinal position and import occurrence IDs never establish cross-snapshot identity. Reused legacy revision counters with different text/evidence remain distinct retained revisions.

Historical revision branches and decisions remain exact packets. The importer does not fill missing historical context from the latest draft, certify a check as completed from an `allowed` boolean, approve old bindings, reconcile platform receipts, or turn generation memory into publication evidence. A retained tweet ID is an assertion present in the source packet. Packet/disposition counts are not unique historical tweet counts or the 63-text audit reconciliation.

The earlier audit still distinguishes 31 receipt-backed texts, 7 posted-state texts without a receipt ID and 25 generation-memory texts with unverified publication. Its selected live checks do not recover the entire account history or establish causal engagement results. This journal retains those evidence limits; it does not correct or republish historical tweets.

## Local use

Use a separate private SQLite path, never the bot's legacy SQLite/threshold database. New authority files use mode0600. Initialization refuses databases containing unrelated tables; status/read/consume do not create missing files. Only local and preview environments exist.

```sh
python -m src.commands.local_cli --database /private/tmp/theheat-local.sqlite init \
  --state /private/tmp/private-initial-state.json --source-namespace private-source-name
python -m src.commands.local_cli --database /private/tmp/theheat-local.sqlite import \
  --state /private/tmp/private-archived-state.json --import-id stable-archive-identity
python -m src.commands.local_cli --database /private/tmp/theheat-local.sqlite domain-status --verify
```

The source namespace must remain stable for the same legacy source/account. Use a different database/namespace for an unrelated source. An import ID replays only its original exact bytes; different evidence under that ID is rejected. Passive import leaves the current authority state, approvals, state version and command queue unchanged. This CLI does not authenticate a hosted operator or publish.

Existing experimental authorities explicitly migrate by initializing with their current state and the intended source namespace. The migration transaction retains a bootstrap snapshot at the existing state version and does not invent pre-migration history. Unsupported schema versions, changed DDL or missing immutability guards fail closed. UPDATE/DELETE/REPLACE/UPSERT protection covers every immutable table. Initialization installs authority/domain schema and bootstrap state atomically.

Each snapshot/artifact is limited to16MiB; selected packet indexing is limited to10,000 occurrences per snapshot. Exceeding a bound fails the entire transaction. There is no silent truncation. No lifetime database quota, remote artifact store, pruning policy or production disk-capacity guarantee is implemented.

## Validation and acceptance limits

29 new offline tests cover exact bytes, passive/idempotent imports, alias collisions, reused counters, preserved uncertainty, invalid/duplicate-key/nonfinite JSON, explicit bounds, transactional bootstrap, real process death, parallel consumers, immutable-table overwrite forms, changed schema, damaged artifact hashes, backup restoration, migration and production/foreign-database refusal. Existing51 authority tests still pass. Full local suite:3,690 passed,41 paid tests excluded; Ruff/mypy pass (139 files).

The private rehearsal initializes from a saved current snapshot, imports the frozen incumbent snapshot twice, verifies idempotency and unchanged authority state, then backs up and restores every artifact. It retains326 distinct artifacts,40 provisional entities,40 revisions,2 snapshots and482 indexed occurrences; these are storage counts, not independent post/receipt counts. All186 frozen manifest files verify before and after. Report SHA256: `5e1582f2b05f17f912c7cb383bf865a47d33ca7f5042449da02d0e5c1aa3de62`. Exact private state/text and databases remain ignored local artifacts, never public fixtures. No provider calls or production writes were made by the rehearsal.

Still open: typed source runs, observations, baseline versions, events and explicit check execution/verdict records; history/receipt reconciliation; a complete migration validation report; production authority, authenticated ingress and jobs/outbox; production backup drills and cutover/rollback. The dashboard and bot still use their existing backend. This module has no production importer, provider adapter, media upload or publisher.
