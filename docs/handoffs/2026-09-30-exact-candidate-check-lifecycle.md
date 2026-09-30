# Exact candidate checks after batch result collection

This is a local transactional extension, not a production batch activation or
backend migration. Gist remains production state and publication stays paused.

Previously, retained batch results had a current eligibility review but no durable
required-check lifecycle. `SQLiteAuthority.candidate_checks` now offers `intake`,
`begin`, `complete` and `status` operations in an additive, immutable journal.

## Contract

Intake re-evaluates the retained result under the current fenced owner, loaded
policy, exact evidence/memory hashes, publication epoch and useful-until deadline.
It retains the supplied bundle/memory, checker state and exact writer result.
Checker state includes the pending-draft comparison and reuse history provided to
the actual check functions; its hash must match on every later operation. UTC day
rollover also invalidates readiness because the critic selects today's drafts. A unique batch
job/item key prevents a second candidate identity from replacing the first.
Equivalent reordered/whitespace result receipts reuse the same candidate.

Required stages are deterministic, safety, fact_check and critic. This adapter
refuses policies with safety or critic disabled. The order avoids buying a later
check before its prerequisites pass. A model stage atomically reserves spending,
claims one dispatch and records the exact request artifact. Duplicate begin calls
return the original grant with `dispatch_granted=false`; a crash or lost grant
acknowledgment cannot buy another request. No retry or automatic settlement exists.

Completion retains a bounded structured adapter receipt with independent execution
status and verdict, exact request/grant binding, result and usage. These records
are assertions by the trusted local check adapter, not self-certification by an
LLM. Missing/error/unavailable/stale results never pass. Late outcomes remain
available for accounting but cannot advance checking. Unknown costs remain held.
Conflicting terminal receipts are refused, and SQL guards prevent replacing prior
sets, attempts and receipts.

Every status or next-stage call freshly rechecks context and retained provider
results. A late conflicting result, evidence/policy/epoch change, usefulness expiry
or invalid lease blocks readiness even when historical stages show passes. A
historical idempotent completion response is not a current readiness decision.
`required_checks_completed` is descriptive; `publication_approved` remains false
on every operation. No authority draft, review/approval binding or posting intent
is created. Repeated reads do not consume the result-review journal's capacity.

## Validation and remaining integration

Synthetic offline tests exercise actual transactions, separate-process concurrent
grants and process death, lost acknowledgment/restart, exact and conflicting
receipts, policy/context/lease/deadline changes, rejected/unavailable checks,
budget exhaustion, bounds, SQL immutability, additive migration and backup/restore.
Model outcomes in these fixtures are explicit test data, not measured quality.

The next slice must bind actual existing check functions to these grants, account
for every transport attempt, preserve exact text and reject hidden retry/fallback
multiplication. That executor is not implemented here. Hosted authority, all-route
production budget enforcement, reconciliation and a specifically authorized paid
trial remain separate gates. No savings, quality improvement or production
recovery is inferred from the local lifecycle.
