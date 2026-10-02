# Atomic media commands in the local PostgreSQL authority

`attach_media_revision` now applies a staged graphic only when the command's
exact predecessor, packet and policy match independently rebuilt current inputs.
The authenticated local adapter supplies the actor; the consumer resolves current
permission after locking the authority state. Five explicit joint confirmations
and a reason are required. Neither retained staging provenance nor a historical
review role grants current permission.

The five immutable assets remain in the separately staged package. The command
contains only bounded identities and review input. Its new pending draft revision,
compact media-review reference, immutable review bytes, projection, terminal result
and completion event commit in one transaction. A failed write rolls back all new
writes. A lost acknowledgement can be recovered from the same command ID without
a second revision. Missing packages receive an explicit refusal; corruption,
migration drift or unavailable storage leave no terminal result.

Removal rebuilds its exact proposal and invalidates old checks and approval.
Removing an absent graphic is an unchanged result; attaching an already attached
identical graphic is refused. Text edits obsolete the current media-review link.
Prior assets, decisions and draft history remain immutable. Historical readback
reconstructs the decision from separately retained command, package and before/after
projections; it reports currentness as unevaluated.

Owner installation is explicit: `initialize_media_staging()` followed by
`initialize_media_commands()`. Migration 010 has separate environment, role,
catalog and immutable-row guards; it does not change migration 009. Runtime uses
SELECT/INSERT privileges for reviews. Unsupported pure/SQLite reducers produce
terminal media refusals so an accepted command does not block later FIFO work.

This is a local/preview implementation. Gist remains the production backend;
there is no new web endpoint, hosted cutover, media upload, provider request or
posting authorization. Existing text-only approval and sender paths still refuse
attached media. Synthetic test acceptance remains explicitly synthetic. No visual
or scientific qualification follows merely from retained bytes or a passing test.

Validation uses disposable actual PostgreSQL databases, synthetic evidence and
structural PNG fixtures. It covers attachment/replacement/removal, current-role and
identity conflicts, atomic write failures, killed connections, lost acknowledgements,
concurrency, tampering, unsupported backends and backup/restore. Run the full
required offline/CI checks before release; a generated dashboard-policy change
also requires the usual manual deployment. No new UI flow is introduced here.

The next integration boundary is authenticated review UI and durable media
transport through the eventual production authority, with hosting, migration and
recovery settled before cutover. This slice does not complete production graphics.

The initial serial CI run timed out while database cases were still passing.
Offline CI now partitions collected files into core, PostgreSQL and media groups;
normal local runs still select every test. The existing required `test` gate joins
all three and fails for unsuccessful or skipped partitions. Database tests retain
real PostgreSQL, all assertions and module fixture grouping; dashboard/SQLite/lint
checks run once in core. Production schedules, queue and timeout are unchanged.
