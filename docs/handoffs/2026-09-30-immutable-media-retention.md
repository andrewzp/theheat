# Atomic local graphic and review retention

The experimental local command authority can now retain a complete graphic review
package in one SQLite transaction: the five exact render assets, current draft
snapshot, requested identity, policy, specification, renderer manifest and supplied
joint-review decision. It reuses the existing immutable artifact store. Gist
remains the production store; this is not a production migration or attachment.

`retain_media_review` acquires the write lock before reading the authoritative
draft and resolving the reviewer's current role. The target draft must exist
exactly once. It independently validates the requested draft and preview identities;
request JSON cannot supply its own authoritative draft or reviewer. The trusted
caller must authenticate ingress and provide the role resolver. This local contract
does not implement authentication itself.

Every supplied asset must have the exact expected name, bounded byte size and
manifest hash. The source and alt-text files must agree with the qualified graphic
specification. PNG checks remain structural; SVG and PDF are stored as opaque
bytes and never executed. Retention does not certify scientific or visual quality.

Blobs, source capture and review row commit together. An identical retry returns
the original historical receipt without duplicate rows. Failure or process death
before commit leaves no partial package. A repeat after changed draft inputs or
revoked reviewer access can refuse; `read_media_review` recovers a committed
historical receipt without requiring another write.

Readback verifies immutable schema guards, all asset bytes and artifact hashes,
then reconstructs the historical packet and decision to verify their bindings.
It reports `currentness=not_evaluated`. Determining current acceptance still
requires independently current inputs and the original reviewer's current role
through the joint-review helper. Retained snapshots must not stand in for current
production state. Hashes do not prove identity, attention or source truth.

The migration is additive within this separate local authority. Initialize it
with its exact current state to install the new schema; reads never migrate.
Updated, deleted, replaced or altered journal structures are refused. Backup and
restore preserve the exact retained bytes. Synthetic tests cover process races,
crash and lost-acknowledgement recovery, access revocation, asset substitution,
schema tampering, migration and backup, while preserving complete draft state.

No provider calls, production writes, draft approval changes, revision increments,
posting intents or public assets are created. Both publication approval and
production attachment authorization remain false; synthetic examples stay marked.
Next: define attachment revisions and invalidation across every Python and
JavaScript state path before enabling attachment mutations, then connect the
authenticated interface and chosen production authority.
