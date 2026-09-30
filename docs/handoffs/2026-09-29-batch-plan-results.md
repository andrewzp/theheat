# Immutable batch plans and results

Version 0.9.108.22 adds `src/two_bot/batch_contract.py`. It is pure local code:
no SDK client, credential, provider request, filesystem operation or implicit clock.
Plans are canonical UTF-8 bytes, limited to 2 MB, and contain one event's request
slate. Bundle and memory fingerprints must match independently retained inputs.
The existing structural evidence audit and scope check must pass. Neither is a
semantic truth certificate. Supplied policy must be valid and agree with the loaded
Anthropic writer and requested sample count.

`prepare_batch_plan` takes bundle/memory, their fingerprints, policy, job ID,
publication epoch, creation/usefulness timestamps and an explicit minimum useful
window in seconds. UTC timestamps end in Z. Urgent inputs are refused; the window
must be longer than the supplied minimum and no longer than seven days. These
bounds do not define a new production freshness rule. One sample is the default;
two or three require an experiment ID and matching supplied policy.

Requests use the shared synchronous prompt, cached prefix and strict output
schema. A 63-character `th_`-prefixed custom ID binds the whole plan identity,
request and sample index. `batch_requests` returns detached SDK arguments after
checking the independent plan SHA and canonical structure. Hashes establish
identity, not authentication; the caller must retain the trusted expected SHA.

`collect_batch_results` takes plan bytes, raw JSONL bytes, the independent SHA,
current bundle/memory/policy/epoch identities and explicit time. Results are
bounded at 3 MB total and 1 MB per row. Duplicate keys, nonfinite values, unknown/
duplicate custom IDs and invalid outer protocol are refused. A later durable
collector must save raw bytes before parsing, including protocol failures.

Rows return in manifest order, regardless of provider order. Missing rows remain
explicit and block all candidates in an incomplete slate. Each valid outer result
retains its raw digest, provider status, message ID and reported usage. Unknown or
malformed usage is labeled; dollar cost remains unknown. Non-success, refusal,
truncation, wrong model, unsupported content, malformed writer JSON, overlong text
and writer KILL do not produce a candidate or initiate a repair/fallback call.

Changed context, retired epoch, collection at/after the deadline or a clock before
creation withholds candidates without discarding reported usage. A successful
candidate only becomes eligible for the ordinary required checks. No check pass,
spending authorization, factual certification or publication approval is granted.

Contract validation covers request parity, source/policy/time/route changes,
experimental slates, input bounds, tampering, out-of-order/incomplete responses,
unusable text, usage uncertainty and forbidden external I/O. Results and request
helpers are not integrated into the production pipeline. Before integration,
include the batch execution sources in current editorial-policy identity and
verify all ordinary checks on selected exact text.

Remaining: durable raw artifacts and request intent, leases, shared reservations,
uncertain-submission reconciliation, default-OFF SDK transport and independently
authorized private trials. The production store, model settings and publication
pause remain unchanged. This slice alone has no realized cost savings.
