# P00c local command authority foundation

Status: locally implemented and independently reviewed; **P00c production acceptance remains open**. This adds a separate offline transactional authority. No dashboard route, bot workflow, Gist adapter, credential or publisher is connected to it. Production mode is refused. It does not repair the existing Gist GET/PATCH race.

Continue the [one-authority design](../plans/2026-09-09-p00c-single-mutation-authority.md), the [upgrade handoff](2026-09-08-codex-upgrade-handoff.md) and their assessments. Preserve the original reports and retained-tweet corpus. This foundation does not change their scientific or historical conclusions: a fingerprint proves which stored evidence was reviewed, not that the evidence or claim is correct. Synthetic command fixtures are not additional evidence about actual published tweets, geographic coverage, model quality or engagement.

## Implemented boundary

`authenticated adapter -> immutable command -> durable acceptance -> serialized transaction -> revision reducer -> state + terminal result`

The local CLI supplies an explicitly trusted operator fixture in place of the first component. It is a developer harness, not hosted authentication.

| Component | Implemented contract |
| --- | --- |
| `src/commands/schema.py` | Strict, bounded request and immutable envelope; canonical UUID and SHA-256 digest; UTC request/deadline; explicit environment; ingress-derived actor; exact target text/evidence/content/decision identities. |
| `src/commands/reducer.py` | Deterministic transitions from supplied state, command, current principal, clock and effective release policy. Copies input before mutation and validates all bulk targets first. |
| `src/commands/sqlite_authority.py` | Separate local/preview database with immutable environment, accepted intents, terminal results and append-only acceptance/completion journal. A real `BEGIN IMMEDIATE` precedes every transactional state read. |
| `src/commands/local_cli.py` | Offline `init`, `submit`, `drain` and `status`; bounded drain; current roles reloaded from a trusted local file. Automatic scheduling defaults paused and there is no send operation. |
| `src/editorial/revisions.py` | Shared revision helpers accept an explicit timestamp. `bind_reviewed_revision` records a deterministic binding after authority checks. Runtime `authorize_draft` retains P00b's policy checks. |

Supported commands are edit revision, select candidate, record human review, approve revision, schedule revision, cancel approval, reject revision and fixed-target bulk rejection. Approval/scheduling requires a current publisher role; editors may review and edit. Viewer commands are denied. Execution rechecks the subject's current role or disabled account before applying an accepted command.

Request JSON cannot set actor, role, environment or authentication context. Those come from the adapter. Each target contains `draft_id`, `content_revision`, `decision_revision`, `text_sha256` and `evidence_sha256`. Selection additionally requires `candidate_rank` and the fingerprint of the complete selected candidate, `candidate_sha256`; a mutable rank cannot silently select replacement text. Bulk rejection names at most 500 unique targets and never expands when retried.

An accepted receipt means the intent is durable; it does not mean the change succeeded. Execution records applied, unchanged or rejected with a stable code, resulting identities, state version and any publication intent ID. Reusing a command ID with any different immutable envelope is rejected. Repeating an identical acceptance returns its original receipt, including after the command deadline. Repeating a completed command returns its original result without touching state. A new expired command is refused; an already accepted command that expires becomes a durable terminal rejection.

The consumer processes accepted sequence order. An explicit command ID can retrieve a completed result or process the oldest pending command, but cannot skip earlier work. Revision, candidate, authorization and domain conflicts are terminal and leave state unchanged. Malformed revision history becomes a terminal rejection so one poisoned draft cannot stall every subsequent command. Storage failures roll back and remain retryable; arbitrary runtime exceptions are not disguised as validation results.

## Crash and publication semantics

Acceptance is committed before consumption. One transaction commits the updated state snapshot, its version, terminal command result and completion journal event together. A process exit before commit rolls all four back while retaining the prior acceptance. A lost reply after commit returns the durable result on retry. Independent processes contend through SQLite, not an in-process mutex.

Journal database triggers reject updates, deletes, duplicate-key replacement and upserts for immutable tables. They protect against accidental SQL writes, including SQLite `INSERT OR REPLACE`; they do not resist a database owner who can drop triggers or alter the file. State and results use the same database, so no two-store pseudo-transaction is claimed.

Edits and alternate selection invalidate obsolete review and approval. Human review and approval retain the actual subject and reason. Automatic scheduling requires current model review, explicit trusted enabled policy, matching release epoch, valid nonretired persisted control and story-level eligibility. Ambient environment variables and wall clock do not influence the pure reducer. The CLI does not enable automatic policy. Runtime publication independently retains all P00b final-send and epoch checks.

Drafts with submitted/unknown outcomes, unresolved attempts or receipts for different content cannot be edited, rejected, canceled or reauthorized through this reducer. Their original drafts and ledger entries are preserved. An approval only records a deterministic publication intent; this adapter never contacts a platform or considers an intent a successful post. Platform-outbox execution and reconciliation remain separate open work. No external exactly-once guarantee is claimed.

## Local use

Use a separate database file and offline fixtures; never point this at the bot's existing SQLite file or export its snapshot into a live Gist writer.

```sh
python -m src.commands.local_cli --database /tmp/theheat-authority.sqlite init --state /path/to/offline-state.json
python -m src.commands.local_cli --database /tmp/theheat-authority.sqlite submit --request /path/to/command.json --operators /path/to/local-operators.json --subject reviewer-fixture
python -m src.commands.local_cli --database /tmp/theheat-authority.sqlite drain --operators /path/to/local-operators.json
python -m src.commands.local_cli --database /tmp/theheat-authority.sqlite status
```

The operator file maps a subject to exactly `role` and `authentication_context`; it is trusted local configuration. An actual ingress must verify a session/token and origin, enforce body/rate limits, resolve operator roles server-side, protect status reads and use isolated preview/production identities. Putting this fixture behind HTTP would not implement authentication.

## Validation and review

Validated on the released P00b/P03 base `8fafd750ebcafcd56ebb310efbb3e09e87831a14`: **2,644 offline Python tests passed**, 41 paid replays deselected; **222 dashboard tests passed**; Ruff and mypy passed across 126 source files. The new command suite contains 49 tests; combined command/publication-containment coverage contains 74 tests and also passed independent review. No paid calls, production mutation, post, public correction or deployment was performed for this implementation.

The focused tests include eight independent writer processes preserving unrelated updates; competing edits and distinct approval commands; concurrent duplicate approval replay yielding one intent; a real child `os._exit` inside an uncommitted transaction; lost acknowledgment; expired requests; current-role revocation; fixed bulk sets; source and candidate changes; retained uncertain publication evidence; a poisoned first command followed by valid work; immutable journal SQL enforcement; environment refusal; and a complete local CLI flow. Clock/environment independence is tested across editing, reviewing, approving and scheduling.

Independent review identified and verified fixes for mutable candidate ranks, malformed-history queue poisoning and SQLite replacement bypasses. Directed execution was also tightened to preserve FIFO. These tests prove the local transactional contract, not hosted durability or credential isolation.

## Integrated release checks

The reviewed foundation was integrated with P04 place containment and the P02/P00a uncertainty/metrics release in `codex/p00c-authority-release`. The automatic-policy wrapper and the newer malformed-outcome checks both remain in the shared revision module. Validation on this integration: **3,076 offline Python tests passed**, 41 paid replays excluded; **286 dashboard tests**, build, Ruff and mypy (128 source files) passed. This is still the local-only authority boundary, with no hosted adapter or production cutover. No application version bump is needed for this experimental, unconnected module; deployment is not a completion criterion for its production authority work.

## Next implementation slices and external gates

1. **Choose and provision the private transactional authority.** SQLite is usable for this same-machine, shared-file experiment. Independent ephemeral dashboard/workflow hosts do not share this file. A production adapter needs durable storage, backups, restore evidence and an operational owner. No such service was provisioned or activated here.
2. **Implement a Postgres adapter against this contract.** A feasible first step keeps a single authoritative state row plus the intent/result/event tables. Lock that authority row within the same database transaction before applying the pure reducer, commit state/result together, and reuse the independent concurrency/crash suite against real database connections. Expose a narrow acceptance operation to ingress; give consumers state mutation rights; deny update/delete on immutable journals to application roles. Full relational domain migration remains P11. There is no Postgres adapter or deployment evidence yet.
3. **Connect authenticated private ingress and the dashboard.** Submit immutable commands and expose accepted/pending/conflict/failed/confirmed results. Retain unsaved edits until durable acceptance and clearly distinguish acceptance from completion. Add real two-session browser coverage, origin/content-type/body/rate-limit tests and operator-role revocation tests. Never place unpublished command payloads in public issues, repositories or build logs.
4. **Convert every writer.** Dashboard mutation/rollback routes, bot state updates, approval intents, reject-all, threshold/world-cache updates, source results and external routines must use the authority. Extend commands for those bounded domain operations; no generic caller-supplied whole-state replacement. The current reducer does not yet implement ingestion, collection controls, cache updates or publication reconciliation. A Gist projection can be downstream of the database authority; retaining Gist as an independent writable authority would leave the race open.
5. **Isolate credentials and drain old workers.** Only the protected consumer receives production state/platform write credentials. Remove them from Vercel, old deployments, other workflows, local tools and external routines. Verify nonconsumer writes fail independently of code guards. Use a fixed protected consumer boundary with durable queue recovery; scheduling/concurrency settings alone do not make accepted intent durable. Verify canceled workers, lost wakeups, queue overflow and delayed consumers against the actual hosted inbox, with age alarms.
6. **Build and test the publication outbox.** Persist per-platform intent before any effect, independently record outcomes, and reconcile uncertain sends before retry. Inject failure before send, after platform success and before receipt save. Retain P00b pause/epoch checks at arming and final send. This local approval reducer does not cover that external crash window.
7. **Prove the cutover in staging before calling P00c complete.** Demonstrate overlapping dashboard, collector, bulk and publisher commands preserving unrelated changes; source/candidate/approval conflicts; private durable acceptance and replay across host replacement; backups and restoration; and credential denial outside the consumer. Keep production automatic publication paused until its separate release conditions and authorization are satisfied.

P00c remains open until all production writers and secrets actually obey that boundary. The larger plan's P11/P13/P14/P16 storage, outbox and worker changes remain tracked; local test success is not a substitute for those acceptance criteria.
