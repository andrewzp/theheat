# Batch worker ownership and uncertain submissions

The experimental local authority now fences worker ownership before granting a
batch submission attempt. A lease has a caller-selected duration of 1–300 seconds
and a monotonically increasing per-job fence. An active lease cannot be silently
extended by retry. Equality at expiry ends ownership. Reacquisition permits
reconciliation, never another submission after a committed grant.

`SQLiteAuthority.batch_work` owns one actual database write transaction for the
lease, grant, acknowledgment or adoption transition. `begin` compares current
bundle, memory, policy and publication-epoch bindings, checks the minimum useful
window and atomically dispatches the existing spending reservation. Only the
first committed grant returns `dispatch_granted=true`. No provider is called by
this journal. Jobs remain local; Gist is still the production state store.

A lost response retains its full spending hold. A replacement worker records
uncertainty instead of resubmitting. Late acknowledgment bytes can be retained
without active ownership, but only the current lease can adopt a provider ID.
Receipts are bounded to 64KiB and 16 distinct entries per job; even malformed
bounded bytes remain evidence. Duplicate receipts are idempotent. Conflicting
provider IDs within or across jobs block acceptance. Provider URLs are untrusted
retained data and are never followed. The future trusted transport must correlate
its response to the exact grant; a locally supplied hash is not provider-signed
proof of that attribution. Timestamp proximity cannot resolve an unknown batch.

The receipt parser checks identifying/count fields against the documented
[Message Batch response](https://platform.claude.com/docs/en/api/messages/batches/create).
Independent lease, attempt, acknowledgment and spending records keep submission
uncertainty distinct from billed-cost uncertainty and publication approval. All
status results withhold collection/publication grants. No completion or receipt
performs factual checks or creates a candidate.

Validation: 62 new worker cases; 237 focused cases; all 4,335 offline Python tests
pass, with 41 paid tests excluded. Ruff, mypy over 147 source files, generated
contracts and diff checks pass. Tests exercise real competing processes, death
before and after commit, stale fences and late receipts, conflicting IDs,
reservation overruns, stored-grant tampering and actual backup/restore. One existing
Google SDK deprecation warning remains. No dashboard source changed.

Next: bounded default-OFF transport, raw-result retention and collection, then
mandatory checks on the exact chosen text. Production hosting/migration, all-role
budget integration, funded trial authorization and actual measured cost/quality
remain separate gates. No model setting, budget amount or publishing flag changed.
