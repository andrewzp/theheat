# Durable local batch result evidence

The experimental SQLite authority now offers `record_batch_results` and
`review_batch_results`. It remains separate from production Gist and never submits,
creates a draft, calls a checker, releases an uncertain charge or publishes.

## Contract

A result receipt binds a known job and committed grant, exact metadata/results
SHA256 values and an explicit download-complete boolean. Raw metadata is limited
to 65,536 bytes and results to 3,000,000 bytes. Both artifacts are retained before
provider parsing. Late workers may append evidence; only current unexpired fenced
ownership may review it. Each job permits 16 distinct receipts, with exact reuse.

Review revalidates stored artifacts and submission identity, terminal metadata and
counts, custom IDs, current evidence/memory/policy/epoch and usefulness deadline.
Partial or invalid output preserves raw evidence and reported usage where parsing
permits it. Unknown cost remains unknown and the spending hold stays intact.

At most one canonical complete result identity is selected per job. Whitespace and
row-order differences normalize by custom ID; exact original bytes remain retained.
A contradictory complete result blocks every candidate, including a later review
of the earlier good receipt. Changed context or expiry may preserve the accounting
identity but cannot preserve text eligibility.

Fresh immutable review reports bind the receipt-set revision, all submission
acknowledgment evidence, context, owner/fence and review time. Stable candidate IDs
bind exact plan and result item. Review reports are not permanent approval: a
consumer must freshly recheck revisions, context, ownership and deadline before
using them. The journal permits 64 distinct reviews per job; exact reuse is safe.
Every report retains required-check and publication approval as false.

## Validation and limits

40 new cases; 178 focused and 4,410 full offline Python tests passed, with 41 paid
tests excluded. Ruff, mypy (149 source files), both generated contract checks and
diff whitespace checks passed. Real process death, rollback, backup/restore,
schema protection, late receipts, stale owners and contradictory responses were
exercised. One existing Google SDK deprecation warning remains.

No dashboard or scientific rule changed. This is local validation on Python 3.14;
required remote CI on Python 3.12 has not run for this local change. Provider result
retrieval, mandatory-check execution, production authority and all-role pricing
remain separate gates. There was no network provider call or measured saving.
