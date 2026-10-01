# Durable graphic packages in the local PostgreSQL prototype

A future attachment command cannot embed the complete render files in its bounded
JSON envelope. `PostgresCommandAuthority.stage_media_proposal` now retains those
files and the exact pending proposal as one immutable package for a later command
to reference. This extends the existing local/preview prototype; Gist remains the
production store, and no hosted service or production endpoint is introduced.

The authority detaches and bounds the caller's request/assets, takes its existing
state lock, resolves the operator's current editor/publisher permission, and reads
the actual current draft. It independently obtains current editorial policy and
rebuilds the proposal at the fixed requested UTC time. Changed predecessor, policy,
proposal or bytes are refused. Proposals older than 24 hours or more than five
minutes in the future cannot be staged.

The package holds exact `input.json`, `alt.txt`, SVG, PDF and PNG bytes, the scoped
predecessor evidence, retained policy/inputs and the proposed revision. Existing
per-file limits and the 26 MiB total asset limit remain; package metadata is capped
at 8 MiB. Immutable byte storage checks byte counts and hashes independently in
PostgreSQL. Runtime roles can select and insert, but cannot alter retained rows.
Schema, environment and role drift are refused.

All assets, capture and package receipt commit together. An identical retry checks
current permission and state again, then returns the first receipt without
rewriting its time or provenance. Lost commit acknowledgement is recovered through
readback or that same idempotent request. Staging advances no draft or authority
revision and changes no command, check, reservation or publication outcome.

`read_media_proposal` verifies retained sizes/hashes and reconstructs the historical
proposal from its captured predecessor and five assets. Its receipt is explicitly
staged, with currentness unevaluated and attachment/publication approval false.
The local `Principal` and resolver are trusted adapter inputs, not an implemented
web authentication mechanism. Structural PNG validation is not visual or scientific
verification; tests retain their synthetic labels.

The focused actual-PostgreSQL tests cover permissions, schema/data corruption,
stale identity and unknown sends, concurrent staging, failure after every write,
killed connections, lost acknowledgement and `pg_dump`/restore. The complete
offline suite and exact-head CI remain release requirements. Policy source binding
includes this module, its shared asset contract and migration; a changed generated
dashboard manifest requires the normal manual Vercel deployment.

Next, add the typed attachment/removal command that resolves the staged package,
rechecks current role, draft and policy, records explicit joint review, and commits
the new draft projection and terminal command receipt atomically. Authenticated
review UI and verified media transport remain separate work. Staging is neither
production graphics nor evidence of improved copy, coverage or operating cost.
