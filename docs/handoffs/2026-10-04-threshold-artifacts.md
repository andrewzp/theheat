# Threshold artifact preservation and recovery

The threshold reader now validates the committed manifest, database SHA256, byte
count, row counts and checkpoint before using a cache. Both workflows use only the
exact manifest cache key. A downloaded replacement is staged and verified before
replacing a local file; active journals and symlinks stop replacement.

Scheduled maintenance can restore a missing legacy asset from an exact verified
cache. It never replaces an existing release asset. New database versions use
compressed, content-addressed filenames. The manifest advances only after GitHub
reports a completed upload with the expected digest and size. An ambiguous upload
gets one receipt check, never a second upload or deletion. An unchanged compressed
version reuses its existing encoded receipt without assuming another encoder would
produce identical bytes.

The existing six-field manifest remains readable. The compressed format adds
`format=sqlite-gzip`, `asset`, `asset_sha256` and `asset_bytes`, alongside the raw
database identity and counts. Bounds are below 2 GiB for the database, 512 MiB for
the compressed asset, 4 KiB for the manifest and 900 retained release assets.
Capacity exhaustion blocks rather than deleting history. Transfers have a
five-minute timeout; the update stage has a fifteen-minute limit within a
thirty-minute maintenance job. The workflow saves the new cache only after a
normal Git push succeeds. A concurrent main update or failed push remains a
failure; an unreferenced uploaded asset can remain, while the old pointer survives.

Artifact integrity does not establish scientific lineage. Incremental maintenance
now stops before source mutation when the baseline checkpoint is missing, ahead
of the allowed lag, or older than the requested update window can cover. It does
not invent a checkpoint, rebuild history, or qualify threshold and record claims.
The existing updater's internal handling of missing daily intervals needs separate
review; this preflight alone does not certify every subsequent source interval.

Offline tests use invented SQLite data and a fake GitHub transport. They cover
cache identity, corrupt/compressed downloads, journal and path conflicts, unknown
lineage, interrupted/ambiguous upload, server receipt conflicts, unchanged retries,
concurrent local changes, capacity bounds and a failing workflow push. The focused
artifact, updater and workflow suite passes 120 tests. No real release asset is
uploaded by these tests.

This is a backend workflow change. No dashboard or generated editorial policy
changes, provider calls, publication activation or database backend migration are
included. A successful code release is not evidence that a scheduled recovery has
run or that the source baseline is scientifically qualified.
