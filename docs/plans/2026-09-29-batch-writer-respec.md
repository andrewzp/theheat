# Batch writer revision against the September pipeline

Status: request/result contracts and local spending reservations are implemented;
durable batch jobs and transport remain unbuilt. The lane is OFF until its
acceptance gates pass.
This supersedes the July proposal to store pending batch work directly in Gist.
It does not activate publishing, increase writer samples, authorize a paid trial,
buy credits, or establish a monthly savings forecast.

## Verified provider facts and economic interpretation

Anthropic documents a 50% batch discount, possible stacking with prompt caching,
best-effort cache hits, up to 24-hour processing/expiry and results retained for
29 days. Results can be succeeded, errored, canceled or expired; result order is
not request order. Cancellation is not immediate. Concurrent batches can slightly
exceed a workspace spend limit. These are provider behavior, not our deadlines or
budget policy. [Batch API documentation](https://platform.claude.com/docs/en/build-with-claude/batch-processing).

Auto-reload buys credits when a balance drops below its threshold; it does not
repair software, source access or authorization. A disconnected/timed-out request
can still be charged. [API billing documentation](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage).

Three equal-size requests at half price cost 1.5 times one standard-price request
before differences in cache behavior, checks, selection, retries and wasted
results. Therefore batch is a useful writer-cost lever, not proof of lower total
cost after a three-sample increase. Keep one routine sample until a bounded private
comparison supports spending more. No model or price-table migration is incidental.

The saved July economics plan revised peak-season projections to $15–22/month.
Those were forecasts based on a different prompt/volume/retry mix, not today's
verified bill. The new $8–15/month proposal likewise needs a complete ledger,
provider reconciliation, actual batch cache-hit rates and useful-output counts.
Do not sum overlapping assumed savings or price Gemini calls as free.

## Current contract to preserve

- Use the current writer's actual system/user prompt, dynamic impact/multi-signal
  guidance, selected model, cached prefix and strict `WRITER_OUTPUT_SCHEMA`.
  Qualification occurs before creating a paid intent. Unsupported/out-of-scope
  evidence does not enter a batch.
- Preserve exact bundle, memory, policy, request and candidate identities. The
  current writer has explicit JSON/length-retry fallbacks; structured outputs
  reduce malformed output but have not deleted every retry route.
- Returned text still requires deterministic honesty/scientific checks, completed
  safety and fact checks, and the configured critic before it becomes a draft.
  A transport success, model KILL, empty response or parsed JSON is not approval.
- Editing/alternates/media/policy changes invalidate obsolete checks and approval.
  No batch completion may directly mutate a posted draft or send a tweet.
- Gist is not a transactional job queue. The local SQLite authority is a prototype;
  neither is silently promoted to a new production backend by the batch feature.

## Implementation slices

### B1: immutable request planning and result contract

Implemented locally in `78e3d5b` (shared synchronous requests) and `8e45214`
(immutable plans/results). See the September 29 request-parity and plan-results
handoffs. These are pure contracts with no network submission or draft approval.


Build a no-provider-call planner and result parser first. Extract shared writer
request construction with synchronous argument-parity tests; do not fork a stale
prompt. Inputs: qualified bundle and its independently retained hash, memory and
hash, current policy, exact model/provider, explicit creation/deadline timestamps,
job identity and one sample by default. Permit 1–3 only as an explicit experiment
parameter, never by changing the production default. Bound all serialized inputs.

Use a namespaced hash-derived `custom_id` within the provider's character/length
constraint, including job/request/sample identity. Event ID alone is insufficient:
the event can acquire new evidence or a different policy. Produce immutable
request bytes, per-item binding and a manifest SHA. The output remains unapproved.

Caller supplies an independently justified usefulness deadline. Urgent or
near-deadline inputs stay out of batching; the planner does not decide that a
forecast remains useful for the provider's entire processing window. Define and
test equality at the deadline as expired. Unknown time/epoch or malformed policy
is a refusal, not an invented deadline.

Parse provider items by exact `custom_id` with duplicate/unknown/missing-result
handling. Bound result size before parsing; reject ambiguous JSON and unsupported
content types. Retain all terminal statuses, raw-response hash and usage even when
text cannot be used. Parse successful writer text with the same strict contract;
refuse over-length output without an unbudgeted repair request. No generated text
enters production from this slice.

Acceptance: synchronous request parity; prompt/memory/evidence/policy/model changes
alter binding; reordered results match correctly; duplicate/unknown IDs fail;
expiry, refusal, malformed/oversized content and unsupported routes are explicit;
one sample remains default; zero provider calls. New parser tests use synthetic
evidence and do not turn old high prose grades into factual qualification.

### B2: durable lifecycle and spending reservations

The spending reservation subset is implemented locally in `8629037`; see
`docs/handoffs/2026-09-29-local-spend-reservations.md`. It serializes reservations,
grants dispatch once, retains uncertain charges and blocks on reconciliation
overruns. Batch-specific artifact/job/lease integration remains unbuilt. The
experimental authority is not the production store or a complete cost ceiling.


Use an explicit local authority extension for rehearsal. Atomically persist the
request intent, immutable artifacts, expected source/policy/deadline, reservation
and state transition. The store interface must make transaction ownership clear;
production hosting/migration is a separate decision and acceptance gate.

States: prepared, reserved, submitting, submitted, submission_uncertain, collecting,
completed, expired, cancellation_requested, canceled, failed. Persist an attempt
before network submission. A lost create response is submission_uncertain: retain
the reservation and prohibit automatic resubmission or synchronous fallback until
reconciled. Do not invent provider idempotency guarantees. A cancellation request
does not prove cancellation or release all possible charges.

Reserve conservatively before dispatch under shared project daily/monthly/job
allowances; all relevant provider paths must share that authority before claiming
an all-in cap. Unknown pricing/usage needs an explicit bounded policy, never a
zero-dollar assumption. Record billed/estimated/unpriced dimensions separately;
retain cached-read/write duration and batch mode rather than applying a blanket
discount to the existing synchronous ledger. Reservations must survive restarts,
late results, lease loss and cancellation races.

Lease/fence every transition. Only the current owner can advance a job. Duplicate
collection must be idempotent, retain exact response/usage identity and create at
most one candidate per item. Evidence revision, policy, publication epoch,
deadline or job ownership changes make text ineligible without discarding usage.
Stopping new submissions must still permit authorized reconciliation/accounting
of existing work. Expired output is retained for diagnosis and never auto-posted.

Acceptance: two concurrent reservers cannot exceed allowance; process death before
and after each commit/network boundary is recoverable; lost submit acknowledgments
do not cause duplicate spend; duplicate/out-of-order/late responses do not double
charge or create drafts; all backups restore jobs, artifacts and reservations.

### B3: bounded transport and collection, default OFF

Add an explicit feature flag defaulting OFF. Use the existing Anthropic SDK's batch
endpoints with one transport-attempt owner, timeouts and bounded polling. Do not
hold a workflow alive in a polling loop. A single scheduler owner resumes durable
work; no new schedule is activated as part of this local implementation.

Inject transport for tests. A submission verifies its reservation, current lease,
current inputs and remaining usefulness window immediately before dispatch. A
collector verifies result IDs, complete terminal state, exact request and current
authority before passing usable text into ordinary mandatory checks. Any optional
repair or synchronous fallback requires a separate budgeted intent. Retain provider
errors without secret bodies, raw payload logging or automatic provider switching.

Acceptance: OFF performs no submit; mocked submit/retrieve/cancel/results paths
preserve lifecycle and charge uncertainty; all required checks still execute on
the exact selected text; no production state, upload, send or feature flip during
offline verification. SDK/CI dependency compatibility must be verified explicitly.

### B4: private measured trial, then production decision

After funded access, explicit trial allowance and a reviewed backend exist, compare
one synchronous sample, one batch sample and (only within allowance) three batch
samples on the same qualified evidence. Keep condition labels out of human rating
screens. Include latency, expirations, retries, usage/unknown charges, factual
eligibility, human edits and preference in cost per usable draft.

Publishing need not be resumed to inspect privately generated candidates. The
experiment is not authorized merely because local tests passed. Promote a setting
only with a declared useful-quality benefit inside the operating allowance.
Production resumption uses current containment/epoch/approval controls; it is not
a revert of the safety work. Complete a private end-to-end rehearsal first.

## Remaining limits

The request/result contract and local spending journal are tested foundations,
not a working batch lane. Durable batch jobs, leases, transport, required-check
integration and an authorized measured trial remain. No $10–15/month or quality uplift is claimed. Dollar ceilings, provider
workspace/account scope and the production durable authority remain explicit
decisions. Global source recall, source recovery, joint graphic approval/attachment and
publication reconciliation still have independent work; batch pricing does not solve them.
