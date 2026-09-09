# P02 follow-up: preserve malformed publication evidence

This bounded fix addresses a live manual-publication gate. It does not enable
automatic publication, change credentials, publish anything, or make Gist writes
transactional. The original assessment and incumbent tweet corpus remain the
baseline; no historical text or public receipt was changed.

## Defect and resulting behavior

Python skipped non-object members of `attempt_conflicts`. JavaScript also treated
an explicit null conflict collection as absent. A `not_sent` parent containing
unreadable evidence could therefore permit editing, approval and another send.
Both ledger merge implementations discarded malformed children, so an unrelated
state update could remove the remaining evidence of uncertainty.

Both runtimes now distinguish missing fields from retained null/scalar/array
attempts. Every malformed conflict collection or member blocks mutation and
publication, even below a matching receipt or a draft marked `confirmed` or
`not_sent`. Receipt reconciliation cannot clear an unknown outcome when such
evidence remains.

Ledger merges separate readable attempts from malformed subtrees. Readable
attempts retain the existing receipt/phase precedence. Malformed subtrees are
preserved verbatim inside `attempt_conflicts`, outside that precedence, so a new
receipt cannot overwrite them. Scalar per-event payloads receive an unknown
wrapper while retaining the original value. Repeated merges remain stable and
unrelated dashboard edits continue to work.

Different phase observations without a nonempty string intent ID no longer count
as proof of one platform call. Distinct unidentified legacy observations remain
available for reconciliation. Normal identified submitted-to-confirmed and
known-rate-limit progression remains covered and unchanged.

## Validation

- 24 shared adversarial JSON fixtures, including 18 malformed shapes, are read by
  both runtimes. They cover absent fields, null/scalar/array collections and
  members, nested uncertainty and valid known-not-sent controls.
- Actual Node/Python merge output agrees for every retained fixture. Merge order,
  repeated merges, exact malformed-subtree preservation and newer matching
  receipts are checked.
- Python direct manual, direct automatic, queued manual and due send paths never
  reach a platform or intent write for malformed evidence. Matching receipts do
  not clear unknown status.
- Every dashboard draft action refuses the affected draft without a write or
  dispatch. Its read projection is blocked, and an unrelated edit preserves the
  malformed evidence.
- Full offline Python: **2,848 passed**, **41 paid replay tests excluded**.
- Dashboard: **284 passed**. Ruff, mypy (123 source files), dashboard build and
  whitespace checks passed.

## Integration

Base: `f5e7e126666220f4044f1109a58d4655425cfc7c`.
Branch: `codex/p02-malformed-outcomes`.

Runtime changes are confined to the Python/JavaScript outcome helpers and ledger
merge helpers. There are no new top-level durable state fields or generated
contract changes. P00c's separate reducer validation should remain in place;
this fix protects existing dashboard and sender paths. If integrating with its
`revisions.py` helper extraction, retain both changes. No version bump, push,
merge, deployment, production call or corpus modification was performed here.

Unreadable evidence remains blocked until an explicit, source-backed
reconciliation is implemented or performed through an authorized process. This
change does not invent a receipt, infer that an attempt never happened, or prove
the historical tweets scientifically correct.
