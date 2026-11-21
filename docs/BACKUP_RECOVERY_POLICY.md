# Backup, retention and recovery policy

This policy joins the existing storage tools. It adds no backup schedule,
storage provider, deletion job, automatic restore or production cutover.
The release owner maintains the private coverage record and recovery evidence;
an operator must check that record before claiming a recoverable deployment.
Code, credentials and data backups have different lifecycles.

## Coverage is specific to a storage profile

| Profile | What the existing implementation preserves | What it does not establish |
| --- | --- | --- |
| Production Gist state and feedback | The literal configured files at their recorded revisions, when the bounded backup completes | A transaction spanning Gists, external pending jobs, media closure, a current offsite copy or production restore |
| Local/preview PostgreSQL authority | Versioned migrations, repository artifacts, command/job/check/delivery state and retained history within the initialized profile | Adoption by every production writer, hosted credentials/roles, current production recovery or a storage-service availability guarantee |
| Separate PostgreSQL media store | Immutable artifact rows used by the configured reader/writer paths | Draft/approval/receipt authority or an implicit backup of all externally referenced assets |
| Experimental local SQLite authority | Its own explicit backup and verification/restore-plan paths | A PostgreSQL dump, Gist cutover or production authorization |

The accepted local combined PostgreSQL restore is evidence for its exact frozen
source, schema, roles, tools and inputs. Preserve that result; do not rerun it to
answer a documentation question. A later release, changed role, new table or a
different hosted endpoint needs its own compatibility evidence before that
profile can inherit recovery acceptance. A successful PR database test does not
silently update an operator's accepted production profile.

Keep these boundaries with the existing
[projection repository](handoffs/2026-09-30-postgres-projection-repository.md),
[media-store procedure](MEDIA_STORE_SETUP.md),
[Gist backup implementation](../src/storage/gist_backup.py) and
[local restore planner](../src/commands/restore_plan.py).

## Retain the complete recovery closure

A recovery set includes more than a state JSON file. Record which of the
following are present, absent, conflicting or outside the profile:

- Original source/backup bytes, literal encoding, hashes, byte counts, acquisition
  times and source revisions. Canonical reconstructed JSON is an additional
  representation; it cannot replace original bytes or repair a missing payload.
- Draft IDs and revisions, evidence, checks, reviews, approval epochs, due times,
  receipts and delivery attempts. Preserve unknown and conflicting attempts.
- Source snapshots, baselines, code, prompt, model and policy identities required
  to explain the retained decisions. Missing provider usage and costs remain
  unknown.
- Pending commands and jobs, durable grants, attempts, leases and terminal or
  uncertain results. A history row is not a runnable job. Account-wide external
  jobs are not covered merely because a database inventory is complete.
- Every referenced media package and its transitive artifacts, original published
  asset bytes, manifests, source/reuse references and alt/text bindings. Preserve
  unresolved deliveries, current joint reviews and delivered-history references.
- For a PostgreSQL authority: every application relation and artifact, migration
  receipts, constraints, triggers, functions, ownership, grants, role memberships,
  default privileges and semantic sequence state required by that profile.
- Tool/runtime versions and an exact profile inventory. Credentials belong in
  their existing private secret store, not a public manifest or recovery log.
  Recoverable authentication must be verified separately by an authorized owner.

Never relabel generation memory as a publication. Keep receipt-backed history,
posted state without receipts and publication-unverified memory distinct. Do not
resolve conflicting original artifacts by picking the more convenient encoding.

## Existing Gist backup procedure

Use a privately retained descriptor document from the already authorized
configuration path. The downloader does not discover a different account, infer
a missing Gist ID or substitute the public dashboard projection. Configuration
or access failure remains a named coverage gap; do not work around an
action-specific access or approval block.

The current command interface is:

```sh
python scripts/backup_gist.py \
  --descriptors /absolute/private/descriptors.json \
  --output /absolute/private/new-backup-directory
```

These are placeholders for an operator-approved capture, not an instruction to
run one now. The output must be a new private directory. Existing files are never
overwritten. The current fixed limits are 32 files, 8 MiB per file, 64 MiB total
payload, 16 MiB per metadata response, and four metadata requests within one
30-second deadline. The separate downloader has a 180-second bound. The descriptor
input is limited to 1 MiB. These are refusal
bounds, not storage-retention guarantees or permission to split an oversized
backup into untracked pieces.

Keep descriptors, the complete manifest, objects and the final completion
receipt together. Only the parent process verifies every file's recorded size,
SHA-256 and private regular-file properties before writing `COMPLETE.json`.
A directory, some downloaded bytes, an earlier completion receipt or exit code
alone is insufficient evidence of a complete new capture. On failure retain the
actual refusal and any original partial evidence, including `INCOMPLETE.json`
when emitted. Descriptor preflight, output creation or the initial descriptor
write can fail before that marker exists; the upstream descriptor request can
also fail before the downloader starts. A missing marker proves neither success
nor permission to retry. Never rename an incomplete
capture to complete or fill missing bytes from a newer revision.

This route is bounded and does not retry automatically. Its implementation
refuses unsupported path/file types and symlink traversal; use an actual canonical
private directory, not an OS shortcut path. A repeat after a failed or uncertain
operation requires its existing action-specific authorization, a new output
location and a clear account of the earlier attempt. Never silently repeat a
consumed one-attempt operation.

## Media and database recovery

For store-backed images, use the existing
[media plan/export/readback procedure](MEDIA_STORE_SETUP.md#6-provider-migration-or-recovery-old-store-stays-untouched).
The plan starts from a specific state snapshot. Preserve that snapshot and its
hash alongside the resulting export inventory; changes to current references
must be reconciled before switching a reader. A Gist backup alone does not
include separate media-store bytes. Conversely, a media-only database backup
cannot restore approvals or publishing state. Keep the old store untouched.

For the PostgreSQL authority, prepare against the accepted migration and role
inventory. A complete database dump and required immutable media must be restored
into a separately owned, empty target under an explicit reviewed execution plan.
Do not reuse a production database as a test target, omit ownership/ACL checks,
drop existing objects, bypass catalog validation or run automatic initialization
over an unexpected schema. This policy supplies no destructive restore command.

Before declaring a restore usable, compare all recorded application rows and
artifact bytes, catalog/role/ACL commitments and semantic sequence state. Verify
repository reads against the restored receipts and source bindings. An artifact
hash match does not prove a weather claim or that an old approval remains current.
The separate [SQLite restore planner](../src/commands/restore_plan.py) preserves
its local/preview and append-only contract; it is not a PostgreSQL restore tool.

Keep restored work quarantined from paid clients and platform credentials.
Review expired leases, pending operations and uncertain results before resuming
anything. Never resend a publication because its acknowledgement is missing.
Use only the existing explicitly supported read-only reconciliation path and
original operation identity; unresolved sends stay held. Restoring data confers
no source freshness, model check, editorial approval or publication permission.

A production cutover requires a separately accepted owner/identity/epoch plan,
every old writer fenced, final delta reconciled and rollback verified. Retaining
Gist as authority and restoring a separate fixture is not a dual-write cutover.

## Retention and operating responsibilities

Until a specific retention/deletion policy is separately authorized, preserve
protected receipts, unknown deliveries, original historical evidence, accepted
recovery sets and their failed predecessor evidence. Current limits on rolling
diagnostics, save rows or individual artifacts do not authorize pruning those
recovery sets. Do not add unbounded automatic captures as an alternative to a
retention decision.

Keep private backups in access-restricted locations separate from public source
control, PRs, build artifacts and browser-download areas. Verify a retained set's
hashes before relying on it. An independently retained copy needs its own custody,
complete-byte and readback evidence; two paths to the same local file are not an
independent recovery copy. This policy creates no new cloud upload or credential
grant. Retention is an operator obligation, not a promise of permanent storage.

The release owner records, per profile:

| Required record | Meaning |
| --- | --- |
| Last complete capture and integrity check | Exact time, identities, artifact inventory and verified bytes; otherwise unavailable |
| Last accepted restore | Exact source/profile and result, with compatibility limits |
| Coverage gaps | Missing media/jobs/credentials, conflicts, access refusals and incomplete captures |
| Operating ownership | Who may capture, verify, reconcile and approve a recovery; publisher authority stays separate |
| Capture cadence and retention | Actually configured behavior and separately approved targets; never infer a schedule from this document |
| Recovery point/time | Measured results where available; otherwise unknown, with targets clearly labeled as targets |
| Next action | A concrete existing-tool action or named block, with any action-specific authorization preserved |

On schema, role, media-backend or writer-authority changes, the release owner
reconciles the affected profile before claiming compatible recovery. Required PR
checks and deployment preservation still run normally; a documentation change
does not authorize another hosted trial. Escalate an incomplete capture, absent
copy, unresolved send or incompatible profile by its specific diagnostic and keep
unaffected operation within its accepted boundaries. Do not claim an RPO, RTO,
offsite protection or production disaster recovery from a passing test suite.
