# Dashboard Gist evidence preservation

A dashboard edit rewrites the Gist state document. Ordinary JavaScript JSON
serialization changes Python-produced numbers such as `500.0` to `500`. That can
invalidate a selected-source digest or a source projection in an untouched draft.

Both dashboard Gist write paths retain a bounded raw JSON token tree alongside
ordinary values used by the existing merge and revision logic. Unchanged subtrees
are emitted from the latest raw document. Draft correspondence uses unique saved
IDs; copied history uses the same draft's retained revision and text. Ambiguous
numeric representations are refused. The observed second-read check also binds
numeric spelling, which editorial revision fingerprints deliberately normalize.
The first full raw tree and defensive state clone leave scope before the second
read; the mutable updater never receives the raw baseline. Native preview also
rechecks the exact retained bundle, with type-sensitive JSON and sorted object
keys, after rendering and before returning an image.

Source-bearing fields cannot be changed, added or removed by these dashboard
mutation paths. A text edit retains the exact evidence while revoking checks and
approval. Existing invalid evidence stays invalid; no source hash is recomputed,
no historical record is repaired and preservation is not scientific qualification.

Editing refuses before PATCH for duplicate JSON keys (including escaped aliases),
duplicate or missing draft IDs, nonfinite numbers, integral numeric values outside
JavaScript's safe range (including decimal/exponent forms), ambiguous source
history, or unauthorized source changes. It also refuses documents above 8 MiB,
one million value nodes or depth 64. Copied raw subtrees count toward output bounds.
Limit failures return `state_evidence_limit`; other preservation failures return
`state_evidence_preservation`. Both are bounded 409 errors without source values.
Ordinary optional object fields with `undefined` retain their existing omission
behavior; unsupported array values never silently become null.

Read-only projections retain their existing behavior. The Gist GET-to-PATCH race
also remains: raw preservation does not make Gist transactional. SQLite and local
command backends are not selected or changed by this boundary.

Regression coverage runs the actual authenticated draft edit route with mocked
Gist transport and blocked sockets, saves two edits plus an unrelated write, then
passes the retained AQ and untouched MODIS evidence through the actual Python
preview. Additional tests cover invalid evidence, source tampering, numeric edge
cases, stale second reads, history ambiguity, reordering and rejection retention.
