# Retained scientific supply through the actual GHCN runner

This local/preview slice connects the existing qualified GHCN return to immutable
PostgreSQL storage before geographic routing and publication caps. The normal
runner uses the committed read-back bundles for its existing cluster prepass and
individual selections. An absent explicit context preserves normal behavior.
There is no new production backend, source activation or publishing authority.

The fixed `scientific-supply-ghcn-v1` namespace stores one complete source return
under a caller-fixed run UUID, including every returned typed signal bundle,
country record, source outcome, missingness and evidence. Dates, numeric types,
source/QC revisions, archive coverage/cutoff and unknown reporting intervals
survive reconstruction. The explicit codec rejects changed schema, omitted fields,
wrong tags, duplicate identities, unsupported values and oversized input without
truncating scientific supply. It reuses existing immutable PG transactions and
runtime-role checks; no migration or mutable latest pointer is added.

Same identity and exact content is idempotent; changed content conflicts. A lost
commit acknowledgment gets one read reconciliation using that identity, never a
source refetch or hidden retry loop. A failed capture/read withholds the configured
GHCN lane and reports retention unavailable. Failed/degraded/empty acquisition
outcomes stay distinct from successful persistence.

`replay_retained_ghcn_supply` retrieves an explicit UUID and uses the same extracted
partition/prepass/cap logic in a detached JSON state. It returns a bounded preview
result and never enters enqueueing, streak/coverage updates, source-health
finalization, callbacks, draft saving or publishing. It refuses production and
ambient credentials using the existing preview guard; it also requires the main
thread in an otherwise single-threaded process and refuses reentrant replay.
Caller state and suppression context are preserved on both success and error.

Replay is archival, not fresh source acquisition. Original failed/degraded/empty
qualifiers and source times remain visible. Combined-provider replay applies the
existing US/world partition to retained GHCN only and explicitly identifies the
world half as not replayed; it does not fetch a world source. The existing aggregate
scientific hold stays in force. Hashes establish identity, not independent truth,
certified records, source completeness or publication-time QC.

Acceptance uses the existing engineered six-station source archives, actual local
PostgreSQL and the actual runner. It checks cap changes, a fresh reader process,
restore, transaction/identity failures, scientific counterexamples, credential
refusal and operational-state preservation. No real historical text, primary
source reacquisition or model call is needed for these fixtures. Production run
coordination, retention policy, hosted cutover, broader event membership and
independent real-event recall remain separate work.
