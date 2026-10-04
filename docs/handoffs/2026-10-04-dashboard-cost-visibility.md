# Dashboard cost visibility

The dashboard now shows two separate pieces of cost evidence from its existing
state read: the current UTC month's recorded priced subtotal and the explicitly
named `google-standard-paid-2026-10-02` token scenario. The view labels the actual
bill unavailable and exposes coverage counts, missing usage, conflicts, truncation,
observation dates, and separate answer/thinking tokens in keyboard-accessible details.
Empty data stays unavailable. Failed refreshes retain and label the last loaded view.

The two amounts must not be added. Neither represents complete account charges,
a monthly forecast, an enforced allowance, or measured savings. Recorded estimates
retain their original prices. The Google scenario still excludes unsupported
modalities, tool input, grounding, storage, other pricing tiers and unknown models;
it uses exact provider-resolved model identities. Runtime models and billing flags
are unchanged, and this projection makes no provider calls or state writes.

## Versioned numeric identity

The pure Python and JavaScript scenario projections produce report schema 2.
`identity_semantics=validated_integer_fields_v2` means integral schema/count/modality
numbers use integer semantics before the byte bound and duplicate comparison.
For example, otherwise identical records containing `1` and `1.0` count once;
boolean, fractional, nonfinite and out-of-range counts remain invalid. Actual
quantity, timestamp, label or identity differences still fence every competing
record, including valid counterparts of malformed observations. The existing
`exact_duplicates` counter now counts identical semantic records under this version.

This deliberately changes report identity from schema 1's Python JSON number
spelling. It does not migrate observation schema 1, rewrite stored evidence, or
replace previously generated reports. Observation dates cover validated retained
records, including excluded/conflicting records; they do not establish continuous
capture or freshness. Missing cache quantities produce a token-only interval.

`dashboard/lib/usage-cost-contract.js` is generated from the Python snapshot by
`scripts/gen_usage_cost_contract.py`; the tests check freshness. JavaScript uses
BigInt nano-USD for arithmetic and decimal strings for transport. A shared synthetic
matrix compares full Python/JavaScript reports, including every eligibility branch,
identity conflicts, malformed/prototype inputs, model thresholds and maximum counts.

## API and UI boundaries

Authenticated `/api/dashboard?cost_scenario=google-standard-paid-2026-10-02` adds
an allowlisted `costEvidence` object. Omitting the parameter leaves the scenario
unrequested; unknown names cannot supply rates. Authorization precedes I/O. Both
cost projections fail independently and never hide otherwise readable dashboard
state. Observation IDs, response IDs, raw model/stage labels and raw usage records
are omitted. Existing `/api/usage` compatibility fields remain unchanged and are
not used by the cost panel.

Synthetic local Basic-auth browser checks cover desktop and 390px layouts,
keyboard expansion/collapse, a stopped-server refresh followed by recovery, and
empty usage. Outbound fetch is blocked in that fixture. This does not establish
signed-in production behavior, account bills, lower costs or editorial improvement.
Publishing remains paused; historical tweet evidence limits are unchanged.
