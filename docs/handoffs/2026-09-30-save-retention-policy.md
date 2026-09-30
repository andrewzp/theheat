# Protected retention on the draft-save path

The shared state policy protects pending, approved and posted drafts, unresolved
publication attempts and revision conflicts. The orchestrator still had an older
pruning rule: when its queue reached 200 rows, saving a new draft retained only the
last 200 pending rows. That could drop protected history before persistence, even
though a later Gist merge might restore some rows from a prior snapshot.

The save path now appends and initializes the new draft without pruning history.
The existing persistence policy then protects active/history/uncertain rows and
expires or caps ordinary rejected rows after cycle selection. This ordering matters:
cycle selection uses the starting queue length to identify this cycle's additions.
Trimming during a save would shift that boundary and miss candidates. Supersession,
approval, publishing and backend selection are unchanged.

Synthetic regressions exercise the actual save function at 199, 200 and 201 rows,
all protected statuses and attempt/conflict cases, nested evidence, rejected expiry,
cap allocation, duplicate refusal and a mocked Gist write/read whose empty remote
state cannot rescue deleted rows. The old pending-only rule failed the protected-history regressions. An initial
local attempt to trim immediately after append also failed a new cycle-boundary
regression; the final change leaves retention at persistence. This establishes a code-path defect, not demonstrated production data loss.

This correction preserves the established policy; it does not cap total state
size or finish durable-storage migration. No dashboard source or generated policy
changes are required for this backend-only slice.
