# Unique related observations before generation

Optional cross-signal context must not turn two rows carrying one event identity
into two independently identified observations. For example, two synthetic rows
named `related-a` with headline values 10 and 20 previously could occupy both
related slots. They now contribute no related context until the identity conflict
is resolved upstream. The underlying primary candidate rows remain available.

## Assembly contract

`attach_related_signals` clears prior attachments and compares each identity's
complete writer-visible summary before country/date windowing, ranking or the cap.
This catches a conflicting duplicate even when it would otherwise be below the
cutoff or outside the host's window. Matching candidate and bundle IDs are required;
inconsistent aliases and malformed serialized evidence are withheld.

Identical summaries count once at their best candidate score. Ties preserve first
identity occurrence in queue order. Existing regional, country and date restrictions
apply, and at most two distinct related identities are attached. Each attachment
has detached metric data, so later source or other-host mutations cannot change it.
Withholding logs contain counts, not raw evidence. This operation does not merge
source records, create replacement IDs or infer whether detections represent
separate physical events.

## Direct-call boundary and policy

The strict evidence contract also rejects duplicate, self-referential, blank or
malformed related identities supplied directly to generation. Even two identical
supplied entries are rejected: incoming evidence is not silently repaired. The
pipeline performs this audit before buying a writer, safety, fact-check or critic
call. Existing related-context causality and shared-event checks still apply.

`multisignal.py` now participates in the editorial policy source identity alongside
the strict contract. The generated dashboard policy manifest must be deployed
manually after merge. Existing content and delivery identities remain intact;
checks made under the obsolete policy cannot establish current approval.

## Validation and operating limits

Focused regressions cover conflicting summaries, low-ranked/out-of-window aliases,
identical deduplication, maximum-score ordering, detached nested metrics, stale
attachments, identity aliases, malformed evidence and direct-call rejection with
zero model calls. Existing country/date, serialization, cross-signal and policy
regressions remain required. Run:

```sh
python -m pytest tests/test_multisignal.py tests/two_bot/test_multisignal_gate.py tests/two_bot/test_strict_contract.py tests/test_editorial_policy.py -q -m 'not voice_replay'
python scripts/gen_editorial_policy.py --check
```

Complete the full offline suite, lint/types, dashboard tests/build and exact-head
required CI before release. No runtime model, prompt, sample count or billing flag
changes are included. This deterministic prevention adds no model calls. It does
not establish source truth, human copy preference, measured savings or global
coverage, and it does not activate publishing.
