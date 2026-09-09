# P00c: one mutation authority

Status: design, not implemented. P00b pauses automatic publication and closes raw-text posting, but does not make Gist writes atomic. `_state_rev`, a second GET, a process marker or a Gist lock file is not a lock.

## Current writers and cutover

- Dashboard draft actions and dispatch rollback directly PATCH `state.json` through `dashboard/lib/state-store.js`.
- Bot CLI and the publication intent writer PATCH the same file. `bot.yml` uses workflow concurrency `theheat-bot`; PR tests unnecessarily share it.
- `reject-all-drafts.yml` has a different concurrency group and runs an independent state writer. Its script must be replaced by the common rejection reducer, including decision revisions and unresolved-outcome checks.
- `world_cache.write_cache` PATCHes `world_threshold_cache.json`; currently called inside the bot, but must carry the same authority boundary.
- Source sentinel only reads Gist but currently receives its write-capable PAT. Current self-heal/beacons and threshold maintenance write other GitHub resources. Historical external grading routines once rejected drafts through Gist; their current remote permissions and prompt need verification.

## Intended boundary

Authenticated request -> immutable command -> durable acceptance -> one serialized consumer -> Python domain reducer -> state and command outcome.

Only the consumer holds production Gist and platform credentials. Vercel reads projections and submits commands. Local tools, old deployments, all other workflows and external routines lose direct Gist/platform authority. Code guards supplement this credential boundary, never substitute for it. Preview and production use isolated credentials and queues.

Commands include edit revision, candidate selection, review, approve, schedule, cancel, reject, bulk reject, collection mode, threshold-cache update and publication reconciliation. Each contains a unique ID, schema/environment, payload hash, exact target/expected content and decision revisions, actor derived from authenticated ingress, requested time/deadline and necessary review confirmation. Same ID with changed payload is rejected. Bulk targets are explicit; a retry never silently expands to newly generated drafts.

Move all domain decisions to Python. Dashboard exposes queued, running, conflict, failed, confirmed and unknown states, retains unsaved text until acknowledgment, and never writes a whole state snapshot. Publication uses current exact approval, records intent before side effects and records each platform outcome independently. Unknown outcomes require reconciliation.

## Inbox and scheduling

Preferred enduring inbox: private transactional storage with conditional command creation. A private command repository/object store is another interim option if its permissions and atomic creation are verified. Never publish unpublished command text in issues or public source branches.

An Actions-only interim can avoid new hosting: a no-secret acceptance job uploads an immutable command artifact before the consumer job waits for serialization. A scheduled sweeper finds accepted commands without terminal outcomes; canceled wakeups do not erase intent. The dashboard distinguishes dispatch received from durably accepted. The consumer archives accepted intent and terminal outcome into its durable journal. Monitor artifact retention, deletion and overdue unarchived commands; ordinary build artifacts are not indefinite storage.

Use one fixed production consumer job concurrency group, `cancel-in-progress: false`, `queue: max`. GitHub now permits 100 pending runs; overflow and cancellation still need inbox recovery. Dispatch can return a workflow run ID. Neither API feature provides exact-once delivery or unlimited queue durability. Sources: [concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency), [queue expansion](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/), [dispatch run IDs](https://github.blog/changelog/2026-02-19-workflow-dispatch-api-now-returns-run-ids/), [artifact immutability/retention](https://github.com/actions/upload-artifact).

## Open acceptance criteria

- [ ] Every writer above routes through the same consumer; inventory includes remote routines and old deployments.
- [ ] Production secrets are available only to its protected production job; nonconsumer attempts fail independently of code markers.
- [ ] Accepted commands survive consumer cancellation, queue overflow, restart and lost acknowledgment; age/retention alarm before loss.
- [ ] One state write includes a completed nonpublishing command and result, so crash after commit returns its existing result on retry.
- [ ] Interleaved two-session edits conflict usefully; duplicate approvals create one intent; source/cache writes cannot remove operator changes.
- [ ] Reject-all versus collection and edit versus publication regressions preserve unrelated updates and every unresolved attempt.
- [ ] Fault injection before send, after platform success and before receipt save cannot cause a blind retry. Platform outcomes remain independent.
- [ ] Origin/content-type/body limits, authenticated operator roles and preview isolation protect ingress; actor is never trusted from JSON.
- [ ] Staging concurrency proves the actual hosted boundary; local sequential mocks alone are insufficient.
- [ ] P11/P13/P14/P16 migration remains tracked: Gist serialization is interim, not a replacement for transactional storage, durable publication outbox and bounded workers.
